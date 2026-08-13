"""add serenity_tweet.processed_at (idempotent extractor · 2026-08-13 사고 대응)

Revision ID: a1f7c9b3d2e4
Revises: 9fe06de4bdc6
Create Date: 2026-08-13 05:50:00.000000

정책 (A-3 backfill · 사용자 승인):
- 컬럼 신설 · Nullable · Index
- 기존 트윗 전부 processed_at=CURRENT_TIMESTAMP 백필 → 재처리 방지 (안전 입기)
- 신규 트윗만 pending (NULL) → 다음 크론 처리 대상

배경:
2026-08-13 z.ai extractor 무한 루프 사고 · signals=[] 반환 트윗이 마커 없이
매 라운드 재선택 → 1,250 트윗 반복 스캔. processed_at 마킹으로 재발 원천 차단.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1f7c9b3d2e4"
down_revision: Union[str, Sequence[str], None] = "9fe06de4bdc6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("serenity_tweets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("processed_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_serenity_tweets_processed_at",
            ["processed_at"],
            unique=False,
        )

    # A-3 backfill · 기존 전질 skip 마킹 (SQLite/PG 공통)
    op.execute(
        "UPDATE serenity_tweets SET processed_at = CURRENT_TIMESTAMP "
        "WHERE processed_at IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("serenity_tweets", schema=None) as batch_op:
        batch_op.drop_index("ix_serenity_tweets_processed_at")
        batch_op.drop_column("processed_at")
