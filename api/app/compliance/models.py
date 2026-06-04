"""compliance_rule — 위법 문구 룰셋 (F6.1). 시드 파일이 SSOT, DB는 런타임 캐시."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, PkMixin, StoreScopedMixin, TimestampMixin

SCOPE_LISTING = "listing"
SCOPE_CS = "cs"
SCOPE_BOTH = "both"

ACTION_BLOCK = "block"
ACTION_WARN = "warn"


class ComplianceRule(Base, PkMixin, StoreScopedMixin, TimestampMixin):
    __tablename__ = "compliance_rule"

    rule_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # listing | cs | both
    pattern: Mapped[str] = mapped_column(Text, nullable=False)  # 정규화 텍스트 대상 regex
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # block | warn
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
