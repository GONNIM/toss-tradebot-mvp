"""watchlist_rank_daily 표 + watchlist_signal.source 길이 20→30 (1030-04)

Revision ID: a1b2c3d4e5f6
Revises: e5c1d7f9b3a8
Create Date: 2026-10-30

init_db(create_all) 가 먼저 표를 만들었을 수 있어 idempotent 하게 쓴다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e5c1d7f9b3a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "watchlist_rank_daily" not in insp.get_table_names():
        op.create_table(
            "watchlist_rank_daily",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("trade_date", sa.String(length=10), nullable=False),
            sa.Column("kind", sa.String(length=30), nullable=False),
            sa.Column("ticker", sa.String(length=10), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=True),
            sa.Column("change_rate", sa.Float(), nullable=True),
            sa.Column("ranked_at", sa.DateTime(), nullable=True),
            sa.Column("captured_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_wl_rank_daily_date_kind_ticker", "watchlist_rank_daily",
            ["trade_date", "kind", "ticker"], unique=True,
        )
        op.create_index("ix_wl_rank_daily_kind_date", "watchlist_rank_daily", ["kind", "trade_date"])

    # rank_individual_netbuy (22자) 가 들어가도록 source 확장
    # SQLite 는 VARCHAR 길이를 지키지 않아 바꿀 필요가 없다 · 운영 DB 는 SQLite 라 큰 표 (약 36만 행) 를 다시 만들지 않는다
    if bind.dialect.name == "sqlite":
        return
    cols = {c["name"]: c for c in insp.get_columns("watchlist_signal")}
    cur = getattr(cols.get("source", {}).get("type"), "length", None)
    if cur is not None and cur < 30:
        with op.batch_alter_table("watchlist_signal", schema=None) as batch_op:
            batch_op.alter_column(
                "source", existing_type=sa.String(length=cur), type_=sa.String(length=30), existing_nullable=False,
            )


def downgrade() -> None:
    op.drop_index("ix_wl_rank_daily_kind_date", table_name="watchlist_rank_daily")
    op.drop_index("ix_wl_rank_daily_date_kind_ticker", table_name="watchlist_rank_daily")
    op.drop_table("watchlist_rank_daily")
    # source 길이는 되돌리지 않는다 (긴 값이 이미 들어갔을 수 있다)
