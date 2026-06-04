"""도메인 엔티티 — Design Doc §4. M0 범위: store, audit_log."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.models import Base, PkMixin, StoreScopedMixin, TimestampMixin


class Store(Base, PkMixin, TimestampMixin):
    __tablename__ = "store"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False, default="smartstore")
    credentials_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AuditLog(Base, PkMixin, StoreScopedMixin, TimestampMixin):
    """모든 외부 발송(메일·발주·상품등록)은 여기 기록 (CLAUDE.md §7-4)."""

    __tablename__ = "audit_log"

    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def write_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    payload_ref: str | None = None,
    store_id: int | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload_ref=payload_ref,
        store_id=store_id,
    )
    session.add(entry)
    session.flush()
    return entry
