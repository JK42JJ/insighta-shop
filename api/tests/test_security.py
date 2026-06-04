"""봉투암호화 단위 테스트 (F6.3) — DB 불필요, EnvelopeCipher 직접 구성."""

import pytest

from app.core.security import (
    _HEADER_LEN,
    _NONCE_LEN,
    EnvelopeCipher,
    KekNotConfiguredError,
    PiiBlobFormatError,
    PiiCryptoError,
    PiiDecryptError,
    UnknownKeyVersionError,
    cipher_from_master_key,
)

KEK = bytes(range(32))
CIPHER = EnvelopeCipher({1: KEK}, active_version=1)
PT = b"P123456789012"


def test_roundtrip() -> None:
    blob, key_version = CIPHER.encrypt(PT, store_id=1, pii_type="pccc")
    assert key_version == 1
    assert CIPHER.decrypt(blob, store_id=1, pii_type="pccc") == PT


def test_nonce_random_per_encryption() -> None:
    """동일 평문 2회 → 암호문 상이 + blob 내 nonce 12B 상이 (재사용 금지)."""
    b1, _ = CIPHER.encrypt(PT, store_id=1, pii_type="pccc")
    b2, _ = CIPHER.encrypt(PT, store_id=1, pii_type="pccc")
    assert b1 != b2
    nonce_k1 = b1[_HEADER_LEN : _HEADER_LEN + _NONCE_LEN]
    nonce_k2 = b2[_HEADER_LEN : _HEADER_LEN + _NONCE_LEN]
    assert nonce_k1 != nonce_k2


def test_aad_binds_store_and_type() -> None:
    """다른 store/type으로 복호화 시도 → 실패 (암호문 이식 차단)."""
    blob, _ = CIPHER.encrypt(PT, store_id=1, pii_type="pccc")
    with pytest.raises(PiiDecryptError):
        CIPHER.decrypt(blob, store_id=2, pii_type="pccc")
    with pytest.raises(PiiDecryptError):
        CIPHER.decrypt(blob, store_id=1, pii_type="phone")


def test_unknown_key_version() -> None:
    other = EnvelopeCipher({2: KEK}, active_version=2)
    blob, _ = other.encrypt(PT, store_id=1, pii_type="pccc")
    with pytest.raises(UnknownKeyVersionError):
        CIPHER.decrypt(blob, store_id=1, pii_type="pccc")


def test_tampered_blob() -> None:
    blob, _ = CIPHER.encrypt(PT, store_id=1, pii_type="pccc")
    tampered = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    with pytest.raises(PiiDecryptError):
        CIPHER.decrypt(tampered, store_id=1, pii_type="pccc")


def test_garbage_blob_format_error() -> None:
    with pytest.raises(PiiBlobFormatError):
        CIPHER.decrypt(b"junk", store_id=1, pii_type="pccc")


def test_error_messages_leak_nothing() -> None:
    """예외 메시지에 평문·키 재료 미포함."""
    blob, _ = CIPHER.encrypt(PT, store_id=1, pii_type="pccc")
    tampered = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    with pytest.raises(PiiDecryptError) as exc_info:
        CIPHER.decrypt(tampered, store_id=1, pii_type="pccc")
    msg = str(exc_info.value)
    assert PT.decode() not in msg
    assert KEK.hex() not in msg


def test_master_key_validation() -> None:
    with pytest.raises(KekNotConfiguredError):
        cipher_from_master_key("")
    with pytest.raises(PiiCryptoError):
        cipher_from_master_key("not-base64!!!")
    with pytest.raises(PiiCryptoError):
        cipher_from_master_key("c2hvcnQ=")  # 5바이트 — 32바이트 아님
