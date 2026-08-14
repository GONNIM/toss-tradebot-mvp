"""add user_judgments.superseded_by_id · 티커당 1건 원칙 (2026-08-14 · Fable 5)

Revision ID: c3f8e2b5a9d1
Revises: b2e9d4a7c8f1
Create Date: 2026-08-14 11:00:00.000000

배경: 첫날 밤 저장된 6건 (positions 3 + manual 3) · 같은 티커 중복.
     append-only · 삭제 금지 · 새 판정이 대체 시 supersede 마킹.

컬럼:
- superseded_by_id: 대체 판정 id (self-FK)
- superseded_at: 대체 시각 (UTC)
- supersede_reason: "superseded by manual-N" 등
- updated_history: PATCH 이력 (JSON · invalidation/target 갱신 추적)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8e2b5a9d1"
down_revision: Union[str, Sequence[str], None] = "b2e9d4a7c8f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_judgments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("superseded_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("superseded_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("supersede_reason", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("updated_history", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_user_judgments_superseded_by_id",
            ["superseded_by_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("user_judgments", schema=None) as batch_op:
        batch_op.drop_index("ix_user_judgments_superseded_by_id")
        batch_op.drop_column("updated_history")
        batch_op.drop_column("supersede_reason")
        batch_op.drop_column("superseded_at")
        batch_op.drop_column("superseded_by_id")
