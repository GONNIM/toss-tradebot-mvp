"""Pydantic v2 응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CrazyPickResponse(BaseModel):
    """Crazy Pick API 응답 — models.CrazyPick 필드 매핑."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    pick_date: str
    rank: int
    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    close_price: Optional[float] = None
    market_cap: Optional[float] = None
    composite_score: Optional[float] = None
    thesis: Optional[str] = None
    catalysts: Optional[str] = None     # JSON string
    risks: Optional[str] = None
    news_summary: Optional[str] = None
    created_at: datetime


class MoonshotPickResponse(BaseModel):
    """Moonshot Pick API 응답 — models.MoonshotPick 필드 매핑."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    pick_date: str
    rank: int
    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    market_cap: Optional[float] = None
    current_price: Optional[float] = None
    risk_level: Optional[str] = None
    market_cap_category: Optional[str] = None
    manipulation_risk: Optional[int] = None
    composite_score: Optional[float] = None
    # 9 인자 점수
    score_volatility: Optional[float] = None
    score_catalyst: Optional[float] = None
    score_squeeze: Optional[float] = None
    score_social: Optional[float] = None
    score_news: Optional[float] = None
    score_technical: Optional[float] = None
    score_gap_volume: Optional[float] = None
    score_low_rebound: Optional[float] = None
    score_insider: Optional[float] = None
    # 매수 3 가격대 (Decision 33)
    buy_price_a: Optional[float] = None  # 시장가
    buy_price_b: Optional[float] = None  # -5% drop
    buy_price_c: Optional[float] = None  # +8% breakout
    # 매도 정책 (Decision 34)
    target_sell_multiplier: Optional[float] = None
    stop_loss_multiplier: Optional[float] = None
    time_stop_days: Optional[int] = None
    # LLM 콘텐츠
    thesis: Optional[str] = None
    catalysts: Optional[str] = None
    risks: Optional[str] = None
    news_summary: Optional[str] = None
    # 추적
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    created_at: datetime


class PositionResponse(BaseModel):
    """보유 종목 응답 (Phase K)."""
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    shares: float
    avg_cost: float
    current_price: Optional[float]
    unrealized_pnl_pct: Optional[float]
    risk_level: str


class DashboardSummary(BaseModel):
    """대시보드 요약."""
    total_value_usd: float
    total_cost_usd: float
    realized_pnl_usd: float
    unrealized_pnl_usd: float
    open_positions: int
    last_trade_at: Optional[datetime]
    engine_status: str  # running/stopped/paused


class LogEntry(BaseModel):
    """감사 로그 단일 entry."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    level: str
    module: str
    message: str
    context: Optional[str]


class SettingsResponse(BaseModel):
    """파라미터 응답."""
    key: str
    value: str
    description: Optional[str]


# ─────────────────────────────────────────────────────────────────
# Sector Leaders (B-2e)
# ─────────────────────────────────────────────────────────────────


class SectorLeaderResponse(BaseModel):
    """단일 (품목, 종목) 분석 결과."""
    model_config = ConfigDict(from_attributes=True)

    item: str
    ticker: str
    name: str
    rank: int
    score: float
    market_cap_krw: Optional[float] = None
    export_ratio_hint: Optional[float] = None
    pearson_r0: Optional[float] = None
    best_r: Optional[float] = None
    best_lag_months: Optional[int] = None
    sample_n: Optional[int] = None
    confidence: str
    computed_at: datetime


class ExportSeriesPoint(BaseModel):
    """월별 수출 데이터 1행."""
    month: str               # 'YYYY-MM'
    value_musd: float        # 백만 달러
    yoy_pct: Optional[float] = None


class PriceSeriesPoint(BaseModel):
    """일봉 1행."""
    date: str                # 'YYYY-MM-DD'
    close: float
    return_pct: Optional[float] = None


class SectorItemSummary(BaseModel):
    """품목 카드 요약 — 사이드 리스트용."""
    item: str
    latest_value_musd: Optional[float] = None
    latest_yoy_pct: Optional[float] = None
    top_confidence: str       # strong/medium/weak (품목 내 최강 페어 기준)
    leader_count: int         # 매핑된 종목 수


class SectorItemDetail(BaseModel):
    """단일 품목 상세 — 메인 패널용.

    수출 13M 시계열 + 주도주 Top N + 각 종목의 r/lag/배지.
    """
    item: str
    description: Optional[str] = None
    export_series: list[ExportSeriesPoint]
    leaders: list[SectorLeaderResponse]


class TickerDetail(BaseModel):
    """단일 종목 상세 — 24M 일봉 + 해당 품목 수출 시계열 + r/lag."""
    leader: SectorLeaderResponse
    price_series: list[PriceSeriesPoint]
    export_series: list[ExportSeriesPoint]


# ─── Sector Leader Analysis Panel (B-2f) ──────────────────────


class BacktestBucketResponse(BaseModel):
    label: str
    threshold_low: Optional[float] = None
    threshold_high: Optional[float] = None
    n_months: int
    mean_return_pct: float
    cumulative_return_pct: float


class MonthlyJoinRowResponse(BaseModel):
    month: str
    export_value_musd: Optional[float] = None
    export_yoy_pct: Optional[float] = None
    price_close: Optional[float] = None
    return_pct: Optional[float] = None
    signal: str  # agree_up / agree_down / disagree / neutral / no_data


class LatestSignalHintResponse(BaseModel):
    month: str
    export_yoy_pct: Optional[float] = None
    bucket_label: str
    expected_window: str
    regime: str
    direction: str          # up / down
    based_on_lag: int


class TickerAnalysisResponse(BaseModel):
    """분석 패널 단일 응답 — leader + 차트 데이터 + 백테스트 + 시그널."""
    leader: SectorLeaderResponse
    correlation_sign: int    # +1 / -1 (r 부호)
    export_series: list[ExportSeriesPoint]
    monthly_close: list[PriceSeriesPoint]
    backtest_lag0: list[BacktestBucketResponse]
    backtest_best_lag: list[BacktestBucketResponse]
    monthly_join: list[MonthlyJoinRowResponse]
    latest_signal: Optional[LatestSignalHintResponse] = None


# ─── Forecast (B-2g) ──────────────────────────────────────────


class HorizonForecastResponse(BaseModel):
    horizon_months: int
    n_samples: int
    alpha: float
    beta: float
    r_squared: float
    p_value_approx: float
    rmse: float
    hit_rate: float
    latest_input_yoy: float
    point_estimate_pct: float
    ci_low_pct: float
    ci_high_pct: float
    sample_warning: bool


class FanChartPointResponse(BaseModel):
    month_offset: int
    target_month: str
    point_estimate_pct: float
    sigma_pct: float
    ci_low_pct: float
    ci_high_pct: float


class OOSMetricsResponse(BaseModel):
    train_n: int
    test_n: int
    mae: float
    rmse: float
    hit_rate: float
    directional_accuracy: Optional[float] = None


class HistoricalBandResponse(BaseModel):
    horizon_months: int
    n_windows: int
    p10_pct: float
    p50_pct: float
    p90_pct: float


class VerdictResponse(BaseModel):
    color: str
    label: str
    context: str
    action_hint: str


class RiskRewardResponse(BaseModel):
    ratio: float
    grade: str
    grade_label: str
    upside_pct: float
    downside_pct: float


class StopTakeProfitResponse(BaseModel):
    stop_price: float
    stop_pct: float
    stop_basis: str
    take_price: float
    take_pct: float
    take_basis: str


class ForecastDisclaimer(BaseModel):
    method: str = "lagged_linear_regression_ols"
    ci_method: str = "z_1.96_normal_approx_small_sample"
    sample_window: str
    limitations: list[str]


class SignalContributionResponse(BaseModel):
    name: str
    label: str
    raw_value: Optional[float] = None
    raw_label: str
    normalized: float
    weight: float
    contribution: float
    detail: str
    direction: str


class ConfluenceResponse(BaseModel):
    score: float
    score_pct: float
    direction: str
    agreement_count: int
    disagreement_count: int
    total_signals: int
    contributions: list[SignalContributionResponse]
    grade: str
    grade_label: str
    grade_color: str
    interpretation: str


class TickerConfluenceResponse(BaseModel):
    leader: SectorLeaderResponse
    correlation_sign: int
    latest_data_month: str
    confluence: ConfluenceResponse


# ─── Top 10 (B-2j) ──────────────────────────────────────────


class Top10ItemResponse(BaseModel):
    rank: int
    ticker: str
    name: str
    item: str
    market_cap_krw: Optional[float] = None

    current_price: float
    entry_price: float
    entry_status: str
    entry_gap_pct: float

    point_price: float
    point_pct: float
    stop_price: Optional[float] = None
    stop_pct: Optional[float] = None
    take_price: Optional[float] = None
    take_pct: Optional[float] = None

    confluence_score: float
    confidence_stars: str
    confidence_label: str
    attractiveness: float

    horizon_months: int
    best_r: Optional[float] = None
    sample_warning: bool

    price_source: str = "fallback"
    price_at: Optional[str] = None
    price_market_status: Optional[str] = None


class Top10Response(BaseModel):
    items: list[Top10ItemResponse]
    total_candidates: int
    computed_at: str


class HorizonAdvice(BaseModel):
    """horizon 별 종합 판정·R/R·Stop/Take (B-2g v4)."""
    horizon_months: int
    verdict: VerdictResponse
    risk_reward: Optional[RiskRewardResponse] = None
    stop_take: Optional[StopTakeProfitResponse] = None


class TickerForecastResponse(BaseModel):
    leader: SectorLeaderResponse
    correlation_sign: int
    latest_data_month: str
    latest_input_yoy: float
    latest_close_krw: Optional[float] = None  # 가격 시나리오 환산 기준 — live 우선
    latest_close_date: Optional[str] = None   # fallback 시 일봉 date, live 시 None
    horizons: list[HorizonForecastResponse]
    fan_chart: list[FanChartPointResponse]
    historical_bands: list[HistoricalBandResponse] = []
    advice_by_horizon: list[HorizonAdvice] = []  # v4 종합 판정
    oos_metrics: Optional[OOSMetricsResponse] = None
    disclaimer: ForecastDisclaimer

    # 현재가 출처 (live = 네이버 polling, fallback = 일봉 마지막 종가)
    price_source: str = "fallback"
    price_at: Optional[str] = None
    price_market_status: Optional[str] = None


# ─── Meme Watch (Phase 1e) ────────────────────────────────────


class MemeSignalContributionResponse(BaseModel):
    name: str          # social / volume / oversold / short / catalyst
    label: str
    raw_value: Optional[float] = None
    raw_label: str
    normalized: float
    weight: float
    contribution: float
    detail: str


class MemeIntensityResponse(BaseModel):
    """Meme Intensity Index (Phase 3-E) — 현재 폭등 강도 0~10."""
    intensity: float
    label: str      # ERUPTING / SURGING / RISING / STABILIZING / FLAT
    emoji: str      # 🌋 / 🚀 / 📈 / 〰️ / 💤
    return_1d: Optional[float] = None
    return_5d: Optional[float] = None
    acceleration: Optional[float] = None
    volume_ratio: Optional[float] = None
    sample_days: int = 0


class MemeScoreResponse(BaseModel):
    ticker: str
    name: Optional[str] = None
    market: Optional[str] = None
    sector: Optional[str] = None
    market_cap: Optional[float] = None

    score: float
    label: str             # BLAZING / HOT / WATCH / OBSERVE / SLEEP
    emoji: str             # 🔥🔥 / 🔥 / ⚠️ / 👀 / 💤

    active_signals: int
    strongest_signal: str
    confidence_label: str  # strong / medium / weak
    sample_warning: bool
    contributions: list[MemeSignalContributionResponse]

    # Phase 3-D — 가격 (일봉 마지막 close). US=USD, KRX=원.
    current_price: Optional[float] = None
    return_1d_pct: Optional[float] = None

    # Phase 3-E — 상승 강도
    intensity: Optional[MemeIntensityResponse] = None


class MemeWatchTopResponse(BaseModel):
    items: list[MemeScoreResponse]
    total: int
    computed_at: str
    sources_status: dict[str, str]   # {"apewisdom":"ok","stocktwits":"blocked",...}
