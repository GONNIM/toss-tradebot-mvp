"""add principles_runs · tickers_json + excluded_count + preferred_filter_conflict_count

Revision ID: b3f4e7a1d5c9
Revises: a8e2f9d1c5b7
Create Date: 2026-08-23

charter v1.0.8 · 재현성 스냅샷 + 우선주 필터 관측성.
- tickers_json: JSON list of str · run 단위 실제 판정 대상 티커
- excluded_count: raw 유니버스 대비 필터로 제외된 우선주 수
- preferred_filter_conflict_count: 이름 매치 but corp_code 있어 배제 안 한 종목 수
  (조용한 누락 감지용 · 직전 run 대비 ±10 초과 시 로그 경고 · 보정 · 오탐 방어)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f4e7a1d5c9"
down_revision: Union[str, Sequence[str], None] = "a8e2f9d1c5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "principles_runs",
        sa.Column("tickers_json", sa.String(65535), nullable=True),
    )
    op.add_column(
        "principles_runs",
        sa.Column("excluded_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "principles_runs",
        sa.Column("preferred_filter_conflict_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("principles_runs", "preferred_filter_conflict_count")
    op.drop_column("principles_runs", "excluded_count")
    op.drop_column("principles_runs", "tickers_json")
