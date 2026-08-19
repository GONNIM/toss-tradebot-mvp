"""add source_account col (v1.0.6-rev3 · 2026-08-19)

Revision ID: c9d4a1e8f2b6
Revises: b8e3f6d9c2a4
Create Date: 2026-08-19

sanity check 1차 계정 검증 · 파서 매칭 account_id/nm 저장.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d4a1e8f2b6"
down_revision: Union[str, Sequence[str], None] = "b8e3f6d9c2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "principles_financial_cache",
        sa.Column("net_income_owner_source_account", sa.String(100)),
    )


def downgrade() -> None:
    op.drop_column(
        "principles_financial_cache", "net_income_owner_source_account"
    )
