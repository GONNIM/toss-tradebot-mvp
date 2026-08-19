"""add principles_industry_codes (v1.0.5 · 이슈 B · 2026-08-19)

Revision ID: a7d2b5c9e3f1
Revises: f6a3c8d2e1b4
Create Date: 2026-08-19

DART 기업개황 induty_code 캐시 · KSIC 대분류 K (64·65·66) = 금융업.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2b5c9e3f1"
down_revision: Union[str, Sequence[str], None] = "f6a3c8d2e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "principles_industry_codes",
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("corp_code", sa.String(10)),
        sa.Column("induty_code", sa.String(10)),
        sa.Column("corp_name", sa.String(200)),
        sa.Column("fetched_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("principles_industry_codes")
