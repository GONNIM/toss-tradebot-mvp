"""sniper_signal.exited_at 칸 (1105-05 · 청산 시각)

Revision ID: b7e2a9c41d05
Revises: a1b2c3d4e5f6
Create Date: 2026-11-06

청산 주문을 낸 시각 (UTC · naive). 옛 행은 NULL.
하루 손익 (`audit.daily_pnl_detail`) 이 오늘 청산분만 읽는 데 쓴다.
init_db(create_all) 가 먼저 칸을 만들었을 수 있어 idempotent 하게 쓴다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e2a9c41d05"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns("sniper_signal")}


def upgrade() -> None:
    bind = op.get_bind()
    if "exited_at" not in _cols(bind):
        with op.batch_alter_table("sniper_signal", schema=None) as batch_op:
            batch_op.add_column(sa.Column("exited_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "exited_at" in _cols(bind):
        with op.batch_alter_table("sniper_signal", schema=None) as batch_op:
            batch_op.drop_column("exited_at")
