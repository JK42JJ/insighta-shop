"""compliance_rule + customer_pii (F6.1, F6.3)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-04

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_rule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("store_id", sa.BigInteger(), nullable=True),
        sa.Column("rule_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_unique_constraint("uq_compliance_rule_key", "compliance_rule", ["rule_key"])
    op.create_index("ix_compliance_rule_store_id", "compliance_rule", ["store_id"])

    op.create_table(
        "customer_pii",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("store_id", sa.BigInteger(), nullable=True),
        # FK는 orders 테이블 생성(M3) 후 추가
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_customer_pii_store_id", "customer_pii", ["store_id"])
    op.create_index("ix_customer_pii_order_id", "customer_pii", ["order_id"])
    op.create_index("ix_customer_pii_retain_until", "customer_pii", ["retain_until"])


def downgrade() -> None:
    op.drop_table("customer_pii")
    op.drop_table("compliance_rule")
