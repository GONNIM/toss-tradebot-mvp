"""add verification_tags column + principles_verification_confirm table

Revision ID: e5c1d7f9b3a8
Revises: d9b8e4c3a1f2
Create Date: 2026-08-23

gate-design-v1 §3-3 · 세션 B · 실체 검증 태깅.
- principles_results.verification_tags: JSON list of str (PASS 종목 태그)
- principles_verification_confirm: 확인 이력 · PK (ticker, tags_hash)
  · 태그 구성 동일 시 확인 유지 · 변경 시 자동 실효
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5c1d7f9b3a8"
down_revision: Union[str, Sequence[str], None] = "d9b8e4c3a1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "principles_results",
        sa.Column("verification_tags", sa.Text(), nullable=True),
    )
    op.create_table(
        "principles_verification_confirm",
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("tags_hash", sa.String(16), primary_key=True),
        sa.Column("tags_json", sa.String(300), nullable=False),
        sa.Column(
            "confirmed_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("confirmed_by", sa.String(80), nullable=True),
        sa.Column("run_id_at_confirm", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("principles_verification_confirm")
    op.drop_column("principles_results", "verification_tags")
