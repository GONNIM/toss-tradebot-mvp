"""add serenity_ticker_prices.shares_outstanding (MU 사고 sanity 검산 · 2026-08-13)

Revision ID: b2e9d4a7c8f1
Revises: a1f7c9b3d2e4
Create Date: 2026-08-13 07:00:00.000000

Fable 5 리뷰 반영:
  절대 범위 하드코딩 대신 내부 일관성 불변식 사용.
  검산: |marketCap − sharesOutstanding × close| / marketCap > 10% → warning
  이 검산에는 shares_outstanding 별도 저장 필요.

컬럼 · Nullable · 인덱스 없음 (sanity check 시에만 사용).
Backfill 없음 (신규 스냅샷부터 채워짐).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2e9d4a7c8f1"
down_revision: Union[str, Sequence[str], None] = "a1f7c9b3d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("serenity_ticker_prices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("shares_outstanding", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("serenity_ticker_prices", schema=None) as batch_op:
        batch_op.drop_column("shares_outstanding")
