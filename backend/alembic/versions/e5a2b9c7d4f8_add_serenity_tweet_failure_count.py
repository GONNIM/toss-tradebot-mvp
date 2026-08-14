"""add serenity_tweets.extract_failure_count · 독약 트윗 방어 (task #10 · 2026-08-14)

Revision ID: e5a2b9c7d4f8
Revises: d4e8f1c6b3a7
Create Date: 2026-08-14 14:20:00.000000

배경 (2026-08-13 무한 루프 사고 후속):
    파싱 영구 실패 트윗이 매일 크론마다 z.ai 재호출 → 비용 낭비.
    N회 연속 실패 시 error 마킹 + 처리 대상 제외.

컬럼: extract_failure_count (Integer · default 0 · server_default "0")
- extractor 성공 시 0 리셋 (marker append 시)
- 실패 시 +1
- 3회 이상 → processed_at=NOW() 자동 마킹 (독약 격리)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5a2b9c7d4f8"
down_revision: Union[str, Sequence[str], None] = "d4e8f1c6b3a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("serenity_tweets", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("extract_failure_count", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("serenity_tweets", schema=None) as batch_op:
        batch_op.drop_column("extract_failure_count")
