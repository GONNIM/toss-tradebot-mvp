"""holding_horizon 에 deadline · memo 칸 (1108-02 3단계)

Revision ID: d4a9c7e15b82
Revises: b7e2a9c41d05
Create Date: 2026-11-08

기한(DATE NULL) · 사용자 메모(VARCHAR(200) NULL). 표 holding_horizon 은 init_db(create_all) 가 만든다.
표가 아직 없으면 아무것도 하지 않는다 (create_all 이 새 칸까지 만든다). 칸이 이미 있으면 건너뛴다.
새 표 swing_long_close 도 create_all 이 만든다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a9c7e15b82"
down_revision: Union[str, Sequence[str], None] = "b7e2a9c41d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "holding_horizon"


def _cols(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        return
    have = _cols(bind)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        if "deadline" not in have:
            batch_op.add_column(sa.Column("deadline", sa.Date(), nullable=True))
        if "memo" not in have:
            batch_op.add_column(sa.Column("memo", sa.String(length=200), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        return
    have = _cols(bind)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        if "memo" in have:
            batch_op.drop_column("memo")
        if "deadline" in have:
            batch_op.drop_column("deadline")
