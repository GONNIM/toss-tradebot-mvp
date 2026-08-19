"""add principles_dividend_raw (v1.0.5 · 이슈 C · 2026-08-19)

Revision ID: b8e3f6d9c2a4
Revises: a7d2b5c9e3f1
Create Date: 2026-08-19

DART alotMatter 원시 응답 저장 · 재호출 방지.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8e3f6d9c2a4"
down_revision: Union[str, Sequence[str], None] = "a7d2b5c9e3f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "principles_dividend_raw",
        sa.Column("corp_code", sa.String(10), primary_key=True),
        sa.Column("bsns_year", sa.Integer, primary_key=True),
        sa.Column("raw_json", sa.Text),
        sa.Column("fetched_at", sa.DateTime, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("principles_dividend_raw")
