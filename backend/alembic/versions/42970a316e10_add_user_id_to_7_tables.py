"""add_user_id_to_7_tables · Stage 3 다중 사용자 대비

7개 discovery/판정 테이블에 user_id 컬럼 추가 (default "owner").
Watchlist·PowderKegList 의 복합 unique 인덱스에 user_id 편입.

참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §1.1
근거: docs/plans/toss-tradebot-tobe/reviews/perspective-d-architecture-business.md
      "user_id 를 지금 안 넣으면 Stage 3 에서 데이터 재구성 6~8주. 지금 하면 3일."

대상 7개:
  crazy_picks · moonshot_picks · sniper_signal · super_signal
  meme_alert_history · watchlist · powderkeg_list

Revision ID: 42970a316e10
Revises: e859d822c111
Create Date: 2026-07-30 09:49:48.987997
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "42970a316e10"
down_revision: Union[str, Sequence[str], None] = "e859d822c111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """user_id 컬럼 7개 + 복합 unique 인덱스 재편 2개."""

    # 1. 단순 add_column (5개 · unique 인덱스 재편 없음)
    with op.batch_alter_table("crazy_picks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.create_index(batch_op.f("ix_crazy_picks_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("meme_alert_history", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.create_index(batch_op.f("ix_meme_alert_history_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("moonshot_picks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.create_index(batch_op.f("ix_moonshot_picks_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("sniper_signal", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.create_index(batch_op.f("ix_sniper_signal_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("super_signal", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.create_index(batch_op.f("ix_super_signal_user_id"), ["user_id"], unique=False)

    # 2. add_column + 복합 unique 인덱스 재편 (2개)
    with op.batch_alter_table("powderkeg_list", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.drop_index(batch_op.f("ix_pk_list_run_ticker"))
        batch_op.create_index("ix_pk_list_run_ticker_user", ["run_id", "ticker", "user_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_powderkeg_list_user_id"), ["user_id"], unique=False)

    with op.batch_alter_table("watchlist", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(length=50), server_default="owner", nullable=False))
        batch_op.drop_index(batch_op.f("ix_watchlist_date_ticker"))
        batch_op.create_index("ix_watchlist_date_ticker_user", ["trade_date", "ticker", "user_id"], unique=True)
        batch_op.create_index(batch_op.f("ix_watchlist_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    """user_id 컬럼·인덱스 제거 · 이전 unique 인덱스 복원."""

    with op.batch_alter_table("watchlist", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_watchlist_user_id"))
        batch_op.drop_index("ix_watchlist_date_ticker_user")
        batch_op.create_index(batch_op.f("ix_watchlist_date_ticker"), ["trade_date", "ticker"], unique=True)
        batch_op.drop_column("user_id")

    with op.batch_alter_table("powderkeg_list", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_powderkeg_list_user_id"))
        batch_op.drop_index("ix_pk_list_run_ticker_user")
        batch_op.create_index(batch_op.f("ix_pk_list_run_ticker"), ["run_id", "ticker"], unique=True)
        batch_op.drop_column("user_id")

    with op.batch_alter_table("super_signal", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_super_signal_user_id"))
        batch_op.drop_column("user_id")

    with op.batch_alter_table("sniper_signal", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sniper_signal_user_id"))
        batch_op.drop_column("user_id")

    with op.batch_alter_table("moonshot_picks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_moonshot_picks_user_id"))
        batch_op.drop_column("user_id")

    with op.batch_alter_table("meme_alert_history", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_meme_alert_history_user_id"))
        batch_op.drop_column("user_id")

    with op.batch_alter_table("crazy_picks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_crazy_picks_user_id"))
        batch_op.drop_column("user_id")
