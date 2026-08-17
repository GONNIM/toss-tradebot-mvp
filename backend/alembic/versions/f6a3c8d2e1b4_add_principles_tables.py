"""add principles tables (v1.0.2 · 5원칙 스크리너 · 2026-08-17)

Revision ID: f6a3c8d2e1b4
Revises: e5a2b9c7d4f8
Create Date: 2026-08-17

principles_financial_cache · principles_dart_retry_queue · principles_runs · principles_results
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a3c8d2e1b4"
down_revision: Union[str, Sequence[str], None] = "e5a2b9c7d4f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "principles_financial_cache",
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("fiscal_year", sa.Integer, primary_key=True),
        sa.Column("fiscal_quarter", sa.Integer, primary_key=True),
        sa.Column("corp_code", sa.String(10)),
        sa.Column("revenue_cum", sa.Float),
        sa.Column("operating_income_cum", sa.Float),
        sa.Column("net_income_owner_cum", sa.Float),
        sa.Column("interest_expense_cum", sa.Float),
        sa.Column("total_assets", sa.Float),
        sa.Column("total_liabilities", sa.Float),
        sa.Column("total_equity", sa.Float),
        sa.Column("buyback_cashflow_cum", sa.Float),
        sa.Column("dividend_per_share", sa.Float),
        sa.Column("dividend_total", sa.Float),
        sa.Column("disclosure_no", sa.String(20)),
        sa.Column("disclosure_date", sa.String(10)),
        sa.Column("fetched_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_principles_fincache_ticker_year",
        "principles_financial_cache",
        ["ticker", "fiscal_year"],
    )

    op.create_table(
        "principles_dart_retry_queue",
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("fiscal_year", sa.Integer, primary_key=True),
        sa.Column("fiscal_quarter", sa.Integer, primary_key=True),
        sa.Column("attempt", sa.Integer, server_default="0"),
        sa.Column("last_error", sa.String(300)),
        sa.Column("retry_after", sa.DateTime),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "principles_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now(), index=True),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("trigger", sa.String(20), server_default="cron"),
        sa.Column("charter_version", sa.String(20)),
        sa.Column("universe_size", sa.Integer, server_default="0"),
        sa.Column("pass_count", sa.Integer, server_default="0"),
        sa.Column("fail_count", sa.Integer, server_default="0"),
        sa.Column("insufficient_count", sa.Integer, server_default="0"),
        sa.Column("dart_call_count", sa.Integer, server_default="0"),
        sa.Column("elapsed_sec", sa.Float),
    )

    op.create_table(
        "principles_results",
        sa.Column("run_id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String(10), primary_key=True),
        sa.Column("name", sa.String(200)),
        sa.Column("verdict", sa.String(20)),
        sa.Column("industry_code", sa.String(20)),
        sa.Column("is_financial_sector", sa.Boolean, server_default=sa.text("0")),
        sa.Column("per_ttm", sa.Float),
        sa.Column("per_operating", sa.Float),
        sa.Column("payout_ratio_3y_avg", sa.Float),
        sa.Column("dividend_years", sa.Integer),
        sa.Column("dividend_cut", sa.Boolean),
        sa.Column("debt_ratio", sa.Float),
        sa.Column("interest_coverage", sa.Float),
        sa.Column("reasons_json", sa.Text),
        sa.Column("missing_fields_json", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_principles_result_run_verdict",
        "principles_results",
        ["run_id", "verdict"],
    )
    op.create_index(
        "ix_principles_result_ticker_time",
        "principles_results",
        ["ticker", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_principles_result_ticker_time", "principles_results")
    op.drop_index("ix_principles_result_run_verdict", "principles_results")
    op.drop_table("principles_results")
    op.drop_table("principles_runs")
    op.drop_table("principles_dart_retry_queue")
    op.drop_index("ix_principles_fincache_ticker_year", "principles_financial_cache")
    op.drop_table("principles_financial_cache")
