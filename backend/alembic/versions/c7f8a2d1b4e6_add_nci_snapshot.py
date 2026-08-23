"""add principles_financial_cache.noncontrolling_interest_snapshot (v1.0.9)

Revision ID: c7f8a2d1b4e6
Revises: b3f4e7a1d5c9
Create Date: 2026-08-23

charter v1.0.9 · Owner 세분 없는 회사 (예: S-Oil) net_income 프록시 판정용.
NCI 부재 or |NCI| < total_equity × 0.01 조건 시 프록시 허용.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7f8a2d1b4e6"
down_revision: Union[str, Sequence[str], None] = "b3f4e7a1d5c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "principles_financial_cache",
        sa.Column("noncontrolling_interest_snapshot", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column(
        "principles_financial_cache", "noncontrolling_interest_snapshot"
    )
