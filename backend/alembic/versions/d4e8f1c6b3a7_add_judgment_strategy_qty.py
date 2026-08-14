"""add user_judgments.strategy · qty · 전술 격벽 (Fable 5 · 2026-08-14)

Revision ID: d4e8f1c6b3a7
Revises: c3f8e2b5a9d1
Create Date: 2026-08-14 13:15:00.000000

전술 격벽 (Fable 5):
- strategy: core (장기) | swing (단기) | event (사건 조건)
- 생성 후 수정 불가 · supersede 만 가능
- qty: 트랑셰 수량 (동일 티커 여러 판정 지원 · '005930 100주 = 🏛70 + 🌊30')

기존 3건 마이그레이션:
- id=4 (005930) → strategy=core (Fable 5 지정 · qty 는 사용자 편집)
- id=5 (WEN)    → strategy=event
- id=6 (TTD)    → strategy=swing (원래 정체 = 단기)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e8f1c6b3a7"
down_revision: Union[str, Sequence[str], None] = "c3f8e2b5a9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_judgments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("strategy", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("qty", sa.Float(), nullable=True))
        batch_op.create_index(
            "ix_user_judgments_strategy",
            ["strategy"],
            unique=False,
        )

    # 기존 3건 자동 라벨 (Fable 5 지시 그대로)
    # id=4 · 005930 · core (장기 분할 계획)
    # id=5 · WEN    · event (Trian 사건 조건)
    # id=6 · TTD    · swing (실제 정체 = 단기)
    op.execute("UPDATE user_judgments SET strategy = 'core'  WHERE id = 4 AND strategy IS NULL")
    op.execute("UPDATE user_judgments SET strategy = 'event' WHERE id = 5 AND strategy IS NULL")
    op.execute("UPDATE user_judgments SET strategy = 'swing' WHERE id = 6 AND strategy IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("user_judgments", schema=None) as batch_op:
        batch_op.drop_index("ix_user_judgments_strategy")
        batch_op.drop_column("qty")
        batch_op.drop_column("strategy")
