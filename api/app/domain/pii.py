"""customer_pii — 본문 테이블과 분리된 PII 저장 (F6.3).

평문은 어댑터 경계에서만 복호화하고, 도메인 객체는 ciphertext만 보유한다.
복호화 실패는 조용한 빈 값이 아니라 타입드 예외 + audit_log 기록 (M1 에러 경로 정책).
"""

import logging
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, LargeBinary, String, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import get_session_factory
from app.core.models import Base, PkMixin, StoreScopedMixin, TimestampMixin
from app.core.security import PiiBlobFormatError, PiiCryptoError, get_cipher
from app.domain.models import write_audit

logger = logging.getLogger(__name__)

PII_TYPE_PCCC = "pccc"
PII_TYPE_PHONE = "phone"
PII_TYPE_ADDR = "addr"
PII_TYPES = (PII_TYPE_PCCC, PII_TYPE_PHONE, PII_TYPE_ADDR)


class CustomerPii(Base, PkMixin, StoreScopedMixin, TimestampMixin):
    __tablename__ = "customer_pii"

    # FK는 orders 테이블 생성(M3) 후 추가
    order_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    retain_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


def store_pii(
    session: Session,
    *,
    store_id: int,
    pii_type: str,
    plaintext: str,
    retain_until: datetime,
    order_id: int | None = None,
) -> CustomerPii:
    if pii_type not in PII_TYPES:
        raise ValueError(f"unknown pii type: {pii_type}")
    blob, key_version = get_cipher().encrypt(
        plaintext.encode(), store_id=store_id, pii_type=pii_type
    )
    row = CustomerPii(
        store_id=store_id,
        order_id=order_id,
        type=pii_type,
        ciphertext=blob,
        key_version=key_version,
        retain_until=retain_until,
    )
    session.add(row)
    session.flush()
    return row


def read_pii(pii: CustomerPii) -> str:
    """복호화. 실패 시 audit_log 기록 후 예외 재전파 (빈 값 반환 금지)."""
    if pii.store_id is None:
        raise PiiBlobFormatError("customer_pii.store_id missing")
    try:
        plaintext = get_cipher().decrypt(
            bytes(pii.ciphertext), store_id=pii.store_id, pii_type=pii.type
        )
    except PiiCryptoError as exc:
        _audit_decrypt_failure(pii, exc)
        raise
    return plaintext.decode()


def _audit_decrypt_failure(pii: CustomerPii, exc: PiiCryptoError) -> None:
    """호출측 트랜잭션이 롤백돼도 감사 기록이 남도록 별도 세션에서 즉시 커밋.

    payload_ref에는 예외 타입명만 — 평문·키 조각 미포함.
    """
    factory = get_session_factory()
    with factory() as session:
        write_audit(
            session,
            actor="system",
            action="pii_decrypt_failed",
            target_type="customer_pii",
            target_id=str(pii.id),
            payload_ref=type(exc).__name__,
            store_id=pii.store_id,
        )
        session.commit()
    logger.error(
        "pii decrypt failed",
        extra={"ctx": {"customer_pii_id": pii.id, "error": type(exc).__name__}},
    )


def purge_expired(session: Session) -> int:
    """retain_until 경과분 파기 + audit_log. 반환: 삭제 건수."""
    expired_ids = (
        session.execute(select(CustomerPii.id).where(CustomerPii.retain_until <= func.now()))
        .scalars()
        .all()
    )
    if expired_ids:
        session.execute(delete(CustomerPii).where(CustomerPii.id.in_(expired_ids)))
    write_audit(
        session,
        actor="system",
        action="pii_purge",
        target_type="customer_pii",
        payload_ref=f"deleted={len(expired_ids)}",
    )
    return len(expired_ids)
