"""add principles_gate_block_log (gate-design-v1 §3-1 · 2026-08-23)

Revision ID: d9b8e4c3a1f2
Revises: c7f8a2d1b4e6
Create Date: 2026-08-23

PrinciplesGate 차단 이력 · 관리 화면 병치 + 90일 초과 자동 정리
(daily_recompute 말미 DELETE).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9b8e4c3a1f2"
down_revision: Union[str, Sequence[str], None] = "c7f8a2d1b4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "principles_gate_block_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("ticker", sa.String(10), nullable=False),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_principles_gate_block_log_created_at",
        "principles_gate_block_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_principles_gate_block_log_created_at",
        "principles_gate_block_log",
    )
    op.drop_table("principles_gate_block_log")
