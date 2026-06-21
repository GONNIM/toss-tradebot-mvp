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
