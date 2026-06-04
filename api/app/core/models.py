"""SQLAlchemy Base + 공통 믹스인 — 모든 엔티티에 store_id/created_at/updated_at (CLAUDE.md §7-6)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PkMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class StoreScopedMixin:
    """멀티 스토어 확장 대비 — 1일차부터 모든 엔티티에 store_id."""

    store_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
