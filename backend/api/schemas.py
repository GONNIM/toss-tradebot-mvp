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
    # Phase B 주 4-1 · outcome UI 노출 (리뷰 A 권고 2 · cherry-pick 방지)
    perf_1w: Optional[float] = None      # T+7 실 수익률
    perf_1m: Optional[float] = None      # T+30 실 수익률
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
    # Phase B 주 4-1 · outcome UI 노출 (리뷰 A 권고 2)
    perf_1d: Optional[float] = None
    perf_3d: Optional[float] = None
    perf_5d: Optional[float] = None
    max_price_after: Optional[float] = None
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


# ─── Toss 실계좌 (2026-08-13 · Fable 5 · 인증 필수 · '내 계좌' 미러링) ────
# 원칙: 브로커 API 원본 사용 · 자체 재계산은 검산 병기만 (broker-api-source-of-truth)
# 색상 한국 관례: 이익 red · 손실 blue (프론트 렌더)

class TossHolding(BaseModel):
    """단일 보유종목 · 통화 원본 값 유지 (KR = KRW · US = USD)."""
    symbol: str
    name: Optional[str] = None            # 한글명 (API 응답에 있으면)
    currency: str                         # "KRW" | "USD"
    qty: float                            # 수량 (소수점 · B안 지원)
    avg_price: float                      # 평균 매수가 · currency 단위
    current_price: Optional[float]        # 현재가 (lastPrice) · currency 단위
    market_value: Optional[float]         # 평가금액 · currency 단위 (API 우선 · 없으면 qty × current)
    cost_basis: float                     # 원가 · currency 단위 (API 우선 · 없으면 qty × avg)
    unrealized_pnl: Optional[float]       # 손익 · currency 단위
    unrealized_pnl_pct: Optional[float]   # 손익률
    market_value_krw: Optional[float]     # KRW 환산 평가 (US 종목 표시용)
    journal_recorded: bool                # Fable 5 30건 캠페인 트리거


class TossAccountSnapshot(BaseModel):
    """토스 '내 계좌' 3층 미러링 · 회계 항등식 (Fable 5 · 2026-08-13).

    3층 구조 (토스 앱 위계):
      총 자산
      ├── 주문 가능 (현금 · 손익 없음)
      └── 내 투자 (손익 여기 붙음)
          ├── 국내주식
          └── 해외주식
    """
    ok: bool
    error_reason: Optional[str] = None
    last_success_at: Optional[datetime] = None
    fetched_at: datetime
    market_open: bool
    price_source: str

    # 층 1 · 총 자산 (헤더 · 손익 없음 · 배지 부착 금지)
    total_asset_krw: Optional[float] = None

    # 층 2A · 주문 가능 (현금 · 손익 없음)
    order_available_krw: Optional[float] = None
    cash_krw: Optional[float] = None
    cash_usd: Optional[float] = None

    # 층 2B · 내 투자 (손익 배지 · 수익률 분모 = 투자 원금)
    investment_market_value_krw: Optional[float] = None  # 현재 평가 (₩8,241,516)
    investment_cost_krw: Optional[float] = None          # 투자 원금 (₩3,596,977 · 분모 명시)
    investment_pnl_krw: Optional[float] = None           # 손익 (₩4,644,539)
    investment_pnl_pct: Optional[float] = None           # 손익률 (129.12% · 원금 기준)
    investment_pnl_source: str = "computed"              # "api" (원본) | "computed" (자체 합산)

    # 층 3A · 국내주식 (내 투자 하위)
    kr_market_value: Optional[float] = None
    kr_cost: Optional[float] = None
    kr_pnl: Optional[float] = None
    kr_pnl_pct: Optional[float] = None
    kr_holdings: list[TossHolding] = []

    # 층 3B · 해외주식 (내 투자 하위)
    us_market_value_krw: Optional[float] = None
    us_cost_krw: Optional[float] = None
    us_pnl_krw: Optional[float] = None
    us_pnl_pct: Optional[float] = None
    us_holdings: list[TossHolding] = []

    # 회계 항등식 게이트 (±1원 · 근사 X · 원본 로그)
    identity_asset_ok: bool = True                       # 주문가능 + 내투자 == 총자산
    identity_asset_diff: Optional[float] = None          # 위반 시 차액 (KRW)
    identity_investment_ok: bool = True                  # 국내 + 해외 == 내투자
    identity_investment_diff: Optional[float] = None


# ─── 보유 작전실 (Fable 5 · 2026-08-14 · 청산 계획 강제) ───────────────

class PositionExitPlan(BaseModel):
    """청산 계획 3칸 · 저널 (UserJudgment) 에서 읽음."""
    has_plan: bool                                       # False = ⚠ 청산 계획 없음 (적색)
    price_condition: Optional[str] = None                # "손절 $X · 목표 $Y" or "트레일링 -N%"
    event_condition: Optional[str] = None                # 사건 조건 (thesis_md 발췌)
    deadline: Optional[datetime] = None                  # ts + horizon_days (기한)
    thesis_excerpt: Optional[str] = None                 # thesis_md 200자
    judgment_id: Optional[int] = None                    # UserJudgment.id (편집 링크)
    horizon_days: Optional[int] = None
    trigger_hit: bool = False                            # 손절/목표 도달 → 카드 적색
    trigger_reason: Optional[str] = None                 # "invalidation_hit" | "target_reached"


class SerenitySignalPreview(BaseModel):
    """positions 카드 인라인 · 최근 signal 요약 (task #23 · 2026-08-14)."""
    ts: datetime                          # signal 시각 (posted_at)
    sentiment: str                        # bullish/bearish/neutral/calibration
    thesis_type: Optional[str] = None
    reasoning: Optional[str] = None       # 200자 excerpt


class PositionCard(BaseModel):
    """종목별 작전 카드 · dashboard holdings + 저널 + activist 조합."""
    symbol: str
    name: Optional[str] = None
    currency: str
    qty: float
    avg_price: float
    current_price: Optional[float]
    market_value: Optional[float]
    market_value_krw: Optional[float]
    unrealized_pnl: Optional[float]
    unrealized_pnl_pct: Optional[float]
    exit_plan: PositionExitPlan
    activist_symbol: bool = False                        # activist universe 소속 여부
    recent_filings: list[dict] = []                      # 최근 SEC 필링 (activist 심볼만)
    # Serenity signal 인라인 (task #23 · 2026-08-14)
    serenity_recent_signals: list[SerenitySignalPreview] = []  # 최근 3건 (있으면)
    serenity_bearish_alert: bool = False                 # 최근 bearish 감지 시 alert


class PositionsPlanResponse(BaseModel):
    """/positions/plan · 인증 필수."""
    ok: bool
    error_reason: Optional[str] = None
    fetched_at: datetime
    positions: list[PositionCard] = []
    total_missing_plans: int = 0                         # 청산 계획 미기록 종목 수 (캠페인 트리거)


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
    entry_price: Optional[float] = None  # v2.0: 과열 시 None
    entry_status: str
    entry_gap_pct: Optional[float] = None  # v2.0: 과열 시 None

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

    # v2.0 진입가 근거 (2026-07-08~)
    high_52w: float = 0.0
    low_52w: float = 0.0
    pos_52w: float = 0.5
    atr14: float = 0.0
    ma200: Optional[float] = None
    ma200_deviation: Optional[float] = None
    overheat: bool = False
    entry_method: str = "v2.0-atr"


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
    """Meme Intensity Index (Phase 3-E + 4 + 5) — 현재 폭등 강도 0~10."""
    intensity: float
    label: str      # ERUPTING / SURGING / RISING / STABILIZING / FLAT
    emoji: str      # 🌋 / 🚀 / 📈 / 〰️ / 💤
    return_1d: Optional[float] = None
    return_5d: Optional[float] = None
    acceleration: Optional[float] = None
    volume_ratio: Optional[float] = None
    score_delta_24h: Optional[float] = None
    time_in_blazing_7d: int = 0
    mention_velocity_30m: Optional[float] = None   # Phase 5
    sample_days: int = 0


class MemeScoreHistoryPoint(BaseModel):
    """Score 시계열 1 point (Phase 5)."""
    snapshot_at: str      # ISO
    score: float
    label: str
    active_signals: int


class MemeScoreHistoryResponse(BaseModel):
    ticker: str
    points: list[MemeScoreHistoryPoint]
    hours: int


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
