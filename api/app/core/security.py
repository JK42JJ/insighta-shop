"""PII 봉투암호화 — AES-256-GCM, per-record DEK (Design Doc §8.2, F6.3).

봉투 구조 (진짜 봉투 — V1 KMS 전환 시 wrapped DEK 재포장만, 데이터 재암호화 불필요):

    blob = [1B fmt=0x01][1B key_version][12B nonce_k][48B wrapped DEK(32+tag16)]
           [12B nonce_d][N data_ct+tag16]

    aad  = "insighta-shop:pii:v1:{store_id}:{type}"
           -- 불변 항목만 (order_id 등 가변 항목 금지). 암호문을 다른 store/type으로
           -- 옮겨붙이면 복호화가 실패한다.

nonce 규칙: 매 암호화마다 os.urandom(12) (96-bit 랜덤). blob에 함께 저장.
재사용·레코드 값에서의 결정적 파생 금지.

에러 정책: 복호화 실패/KEK 부재/key_version 미스는 조용한 빈 값 반환 금지 —
타입드 예외를 던진다. 예외 메시지에 평문·키 조각을 절대 포함하지 않는다.
(audit_log 기록은 호출측 app/domain/pii.py 책임.)
"""

import base64
import binascii
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

FMT_V1 = 0x01
_KEY_LEN = 32
_NONCE_LEN = 12
_TAG_LEN = 16
_WRAPPED_DEK_LEN = _KEY_LEN + _TAG_LEN  # 48
_HEADER_LEN = 2
_MIN_BLOB_LEN = _HEADER_LEN + _NONCE_LEN + _WRAPPED_DEK_LEN + _NONCE_LEN + _TAG_LEN


class PiiCryptoError(Exception):
    """베이스 예외. 메시지에 평문·키 재료를 포함하지 않을 것."""


class KekNotConfiguredError(PiiCryptoError):
    pass


class UnknownKeyVersionError(PiiCryptoError):
    pass


class PiiBlobFormatError(PiiCryptoError):
    pass


class PiiDecryptError(PiiCryptoError):
    pass


def _aad(store_id: int, pii_type: str) -> bytes:
    return f"insighta-shop:pii:v1:{store_id}:{pii_type}".encode()


class EnvelopeCipher:
    def __init__(self, kek_ring: Mapping[int, bytes], active_version: int) -> None:
        for version, kek in kek_ring.items():
            if not (1 <= version <= 255):
                raise PiiCryptoError(f"key_version must be 1..255, got {version}")
            if len(kek) != _KEY_LEN:
                raise PiiCryptoError(f"KEK for version {version} must be {_KEY_LEN} bytes")
        if active_version not in kek_ring:
            raise UnknownKeyVersionError(f"active key_version={active_version} not in ring")
        self._ring = dict(kek_ring)
        self._active = active_version

    def encrypt(self, plaintext: bytes, *, store_id: int, pii_type: str) -> tuple[bytes, int]:
        """반환: (blob, key_version)."""
        kek = self._ring[self._active]
        aad = _aad(store_id, pii_type)
        dek = os.urandom(_KEY_LEN)
        nonce_d = os.urandom(_NONCE_LEN)
        data_ct = AESGCM(dek).encrypt(nonce_d, plaintext, aad)
        nonce_k = os.urandom(_NONCE_LEN)
        wrapped = AESGCM(kek).encrypt(nonce_k, dek, aad)
        blob = bytes([FMT_V1, self._active]) + nonce_k + wrapped + nonce_d + data_ct
        return blob, self._active

    def decrypt(self, blob: bytes, *, store_id: int, pii_type: str) -> bytes:
        if len(blob) < _MIN_BLOB_LEN:
            raise PiiBlobFormatError("blob too short")
        if blob[0] != FMT_V1:
            raise PiiBlobFormatError(f"unknown blob format version: {blob[0]}")
        key_version = blob[1]
        kek = self._ring.get(key_version)
        if kek is None:
            raise UnknownKeyVersionError(f"key_version={key_version} not in ring")

        offset = _HEADER_LEN
        nonce_k = blob[offset : offset + _NONCE_LEN]
        offset += _NONCE_LEN
        wrapped = blob[offset : offset + _WRAPPED_DEK_LEN]
        offset += _WRAPPED_DEK_LEN
        nonce_d = blob[offset : offset + _NONCE_LEN]
        offset += _NONCE_LEN
        data_ct = blob[offset:]

        aad = _aad(store_id, pii_type)
        try:
            dek = AESGCM(kek).decrypt(nonce_k, wrapped, aad)
        except InvalidTag as exc:
            raise PiiDecryptError("DEK unwrap failed") from exc
        try:
            return AESGCM(dek).decrypt(nonce_d, data_ct, aad)
        except InvalidTag as exc:
            raise PiiDecryptError("data decrypt failed") from exc


def cipher_from_master_key(master_key_b64: str) -> EnvelopeCipher:
    if not master_key_b64:
        raise KekNotConfiguredError("PII_MASTER_KEY is not set")
    try:
        kek = base64.b64decode(master_key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PiiCryptoError("PII_MASTER_KEY is not valid base64") from exc
    if len(kek) != _KEY_LEN:
        raise PiiCryptoError(f"PII_MASTER_KEY must decode to {_KEY_LEN} bytes")
    # KEK 링: V1 KMS 전환 시 {2: KmsKekProvider} 추가 + re-wrap 잡 (Design Doc §8.2)
    return EnvelopeCipher({1: kek}, active_version=1)


def get_cipher() -> EnvelopeCipher:
    return cipher_from_master_key(get_settings().PII_MASTER_KEY)
