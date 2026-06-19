"""Pydantic v2 응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CrazyPickResponse(BaseModel):
    """Crazy Pick API 응답."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    rank: int
    company_name: str
    sector: Optional[str]
    current_price: float
    market_cap_usd: Optional[float]
    total_score: float
    thesis: str
    catalysts: list[str]
    risks: list[str]
    news_summary: str
    manipulation_risk: int
    created_at: datetime


class MoonshotPickResponse(BaseModel):
    """Moonshot Pick API 응답."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    rank: int
    company_name: str
    sector: Optional[str]
    current_price: float
    market_cap_usd: Optional[float]
    risk_level: str
    total_score: float
    thesis: str
    catalysts: list[str]
    risks: list[str]
    news_summary: str
    manipulation_risk: int
    buy_price_market: float
    buy_price_limit_3pct: float
    buy_price_limit_7pct: float
    risk_warning: str
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
    level: str
    category: str
    message: str
    metadata: Optional[dict]
    created_at: datetime


class SettingsResponse(BaseModel):
    """파라미터 응답."""
    key: str
    value: str
    description: Optional[str]
