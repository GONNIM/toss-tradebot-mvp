"""add cum_fallback_fields col (v1.0.7 · 2026-08-21)

Revision ID: a8e2f9d1c5b7
Revises: c9d4a1e8f2b6
Create Date: 2026-08-21

파서 v1.0.7 · _cum 컬럼 누적 저장 계약 강제 · thstrm_add_amount 우선 사용 ·
add 부재로 thstrm_amount fallback 한 필드를 JSON list 로 기록.
값 있음 = 정합성 미검증 · screener 에서 cum_fallback_unverified reason 발생.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8e2f9d1c5b7"
down_revision: Union[str, Sequence[str], None] = "c9d4a1e8f2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "principles_financial_cache",
        sa.Column("cum_fallback_fields", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("principles_financial_cache", "cum_fallback_fields")
