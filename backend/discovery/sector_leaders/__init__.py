"""Sector Leaders 분석 모듈 — 산업통상부 수출 데이터 ↔ KRX 주도주 매핑.

설계: docs/plans/sector-leaders/01-mvp-design.md
"""
from backend.discovery.sector_leaders.analysis import (
    PairResult,
    compute_sector_leaders,
    persist_sector_leaders,
)
from backend.discovery.sector_leaders.backtest import (
    BacktestBucket,
    LatestSignalHint,
    MonthlyJoinRow,
    compute_monthly_join,
    compute_yoy_buckets,
    daily_to_monthly,
    latest_signal_hint,
)
from backend.discovery.sector_leaders.confluence import (
    ConfluenceResult,
    SignalContribution,
    compute_confluence,
)
from backend.discovery.sector_leaders.top10 import (
    Top10Item,
    compute_attractiveness,
    compute_top10,
)
from backend.discovery.sector_leaders.forecast import (
    FanChartPoint,
    HistoricalBand,
    HorizonForecast,
    OOSMetrics,
    RiskReward,
    StopTakeProfit,
    Verdict,
    compute_rr_ratio,
    compute_verdict,
    fan_chart_points,
    historical_quantiles,
    multi_horizon_forecast,
    oos_validate,
    recommend_stop_take,
)
from backend.discovery.sector_leaders.ingest import (
    ingest_directory,
    ingest_pdf,
)
from backend.discovery.sector_leaders.scheduler import (
    monthly_ingest_job,
    register_monthly_jobs,
)

__all__ = [
    "ingest_pdf",
    "ingest_directory",
    "monthly_ingest_job",
    "register_monthly_jobs",
    "PairResult",
    "compute_sector_leaders",
    "persist_sector_leaders",
    "BacktestBucket",
    "LatestSignalHint",
    "MonthlyJoinRow",
    "compute_monthly_join",
    "compute_yoy_buckets",
    "daily_to_monthly",
    "latest_signal_hint",
    "ConfluenceResult",
    "SignalContribution",
    "compute_confluence",
    "Top10Item",
    "compute_attractiveness",
    "compute_top10",
    "FanChartPoint",
    "HistoricalBand",
    "HorizonForecast",
    "OOSMetrics",
    "RiskReward",
    "StopTakeProfit",
    "Verdict",
    "compute_rr_ratio",
    "compute_verdict",
    "fan_chart_points",
    "historical_quantiles",
    "multi_horizon_forecast",
    "oos_validate",
    "recommend_stop_take",
]
