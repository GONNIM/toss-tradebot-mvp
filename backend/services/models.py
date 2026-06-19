"""SQLAlchemy 2.0 ORM 모델 정의.

테이블 분류:
- Discovery (Phase B~D 활성): crazy_picks, moonshot_picks, daily_candles, logs, ticker_universe
- 자동매매 코어 (Phase K 활성): accounts, account_positions, orders, engine_status, audit_trades

모든 테이블 SQLite·Postgres 호환.
JSON 컬럼은 Text (SQLite) 으로 저장, 코드에서 json.dumps/loads.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 모델의 베이스 클래스."""

    pass


# ─────────────────────────────────────────────────────────────────
# Discovery 모듈 테이블 (Phase B~D)
# ─────────────────────────────────────────────────────────────────


class CrazyPick(Base):
    """Crazy Picks 일일 추천 (결정 14~22).

    매일 06:30 KST cron 으로 10건 누적. 1주/1개월 후 perf 자동 추적.
    """

    __tablename__ = "crazy_picks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pick_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    rank: Mapped[int]  # 1~10
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    sector: Mapped[Optional[str]] = mapped_column(String(50))

    # 가격 데이터 (Stooq 1차, 결정 15)
    close_price: Mapped[Optional[float]]
    pct_from_52w_high: Mapped[Optional[float]]
    pct_from_52w_low: Mapped[Optional[float]]
    return_1m: Mapped[Optional[float]]
    return_3m: Mapped[Optional[float]]
    return_6m: Mapped[Optional[float]]
    volume: Mapped[Optional[int]]
    avg_volume: Mapped[Optional[int]]
    market_cap: Mapped[Optional[float]]

    # 5 인자 가중 점수 (결정 14)
    composite_score: Mapped[Optional[float]]  # 0~100
    factor_breakdown: Mapped[Optional[str]] = mapped_column(Text)  # JSON

    # LLM thesis (결정 16, Claude Haiku 4.5)
    thesis: Mapped[Optional[str]] = mapped_column(Text)
    catalysts: Mapped[Optional[str]] = mapped_column(Text)  # JSON: 어닝일·FDA·발표 등
    risks: Mapped[Optional[str]] = mapped_column(Text)
    news_summary: Mapped[Optional[str]] = mapped_column(Text)
    analyst_data: Mapped[Optional[str]] = mapped_column(Text)  # JSON

    # 자동 추적 (결정 19)
    perf_1w: Mapped[Optional[float]]  # T+7일 수익률
    perf_1m: Mapped[Optional[float]]  # T+30일 수익률

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("idx_crazy_picks_date_rank", "pick_date", "rank"),
    )


class MoonshotPick(Base):
    """Moonshot Picks 일일 추천 (결정 27~36, 40, 41).

    매일 16:50 KST cron 으로 10건 누적, Top 3 표시.
    9 인자 가중 (결정 32 — 학술 검증 후 재조정 2026-06-19).
    """

    __tablename__ = "moonshot_picks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pick_date: Mapped[str] = mapped_column(String(10), index=True)
    rank: Mapped[int]  # 1~10
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    market_cap: Mapped[Optional[float]]
    current_price: Mapped[Optional[float]]
    high_52w: Mapped[Optional[float]]
    low_52w: Mapped[Optional[float]]

    # 9 인자 점수 (결정 32 — 학술 검증 후)
    score_volatility: Mapped[Optional[float]]
    score_catalyst: Mapped[Optional[float]]
    score_squeeze: Mapped[Optional[float]]
    score_social: Mapped[Optional[float]]
    score_news: Mapped[Optional[float]]
    score_technical: Mapped[Optional[float]]
    score_gap_volume: Mapped[Optional[float]]
    score_low_rebound: Mapped[Optional[float]]
    score_insider: Mapped[Optional[float]]  # 결정 41
    composite_score: Mapped[Optional[float]]  # 가중 합 0~100

    # 매수가 3 옵션 (결정 33)
    buy_price_a: Mapped[Optional[float]]  # 즉시 진입
    buy_price_b: Mapped[Optional[float]]  # 떡락 -5%
    buy_price_c: Mapped[Optional[float]]  # 돌파 +8%

    # 매도 정책 (결정 34)
    target_sell_multiplier: Mapped[float] = mapped_column(default=2.0)  # +100%
    stop_loss_multiplier: Mapped[float] = mapped_column(default=0.5)    # -50%
    time_stop_days: Mapped[int] = mapped_column(default=5)              # 5일

    # 위험 분류 (결정 40)
    market_cap_category: Mapped[Optional[str]] = mapped_column(String(10))  # MICRO/SMALL/MID
    risk_level: Mapped[Optional[str]] = mapped_column(String(10))           # HIGH/MED/LOW
    manipulation_risk: Mapped[Optional[int]]  # 1~5 (LLM 평가)

    # LLM 생성 (Claude Haiku 4.5)
    thesis: Mapped[Optional[str]] = mapped_column(Text)
    catalysts: Mapped[Optional[str]] = mapped_column(Text)
    risks: Mapped[Optional[str]] = mapped_column(Text)
    news_summary: Mapped[Optional[str]] = mapped_column(Text)

    # 사용자 수동 매수 추적 (옵션 — 사용자가 토스 WTS 매수 시 기록)
    user_bought: Mapped[bool] = mapped_column(default=False)
    user_buy_price: Mapped[Optional[float]]
    user_buy_option: Mapped[Optional[str]] = mapped_column(String(1))  # 'a'/'b'/'c'
    user_sold: Mapped[bool] = mapped_column(default=False)
    user_sell_price: Mapped[Optional[float]]
    user_realized_pnl: Mapped[Optional[float]]
    user_sell_trigger: Mapped[Optional[str]] = mapped_column(String(20))
    # 'TARGET' / 'STOP_LOSS' / 'TIME_STOP' / 'MANUAL'

    # 자동 추적
    max_price_after: Mapped[Optional[float]]  # 추천 후 최고가
    perf_1d: Mapped[Optional[float]]
    perf_3d: Mapped[Optional[float]]
    perf_5d: Mapped[Optional[float]]

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("idx_moonshot_picks_date_rank", "pick_date", "rank"),
        Index("idx_moonshot_picks_bought", "user_bought"),
    )


class DailyCandle(Base):
    """일봉 캐시 (Discovery + 자동매매 공통).

    Discovery: Stooq 직접 제공 52w 사용 (결정 15·23).
    자동매매: Toss API 일봉 252개 직접 계산 (결정 23).
    """

    __tablename__ = "daily_candles"

    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    open: Mapped[float]
    high: Mapped[float]
    low: Mapped[float]
    close: Mapped[float]
    volume: Mapped[int]
    source: Mapped[str] = mapped_column(String(20))  # 'toss' / 'stooq' / 'yahoo'
    cached_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Log(Base):
    """감사 로그 — 모든 모듈 공통."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    level: Mapped[str] = mapped_column(String(10))   # INFO/WARN/ERROR/CRITICAL
    module: Mapped[str] = mapped_column(String(50))  # crazy/moonshot/auto/api/cli
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[Optional[str]] = mapped_column(Text)  # JSON


class TickerUniverse(Base):
    """종목 universe — 자동매매·Discovery 공통.

    - core: SPCX (Phase K)
    - satellite: 빅7 + 섹터1위 15~17종 (Phase K)
    - discovery_whitelist: 양자 5 + 보안 8 = 13종 (결정 21 와이트리스트)
    - moonshot_dynamic: 매일 발굴되는 후보 (저장 안 함, picks 테이블 사용)
    """

    __tablename__ = "ticker_universe"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    market: Mapped[str] = mapped_column(String(20))         # NYSE/NASDAQ/NYSE_AMERICAN
    category: Mapped[str] = mapped_column(String(30))       # core/satellite/discovery_whitelist
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    company_name: Mapped[Optional[str]] = mapped_column(String(200))
    market_cap: Mapped[Optional[float]]
    active: Mapped[bool] = mapped_column(default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ─────────────────────────────────────────────────────────────────
# 자동매매 코어 테이블 (Phase K 활성 — 현재 스키마만 정의)
# ─────────────────────────────────────────────────────────────────


class Account(Base):
    """계좌·잔고 (결정 8 — 평단 +20% 익절 산출용)."""

    __tablename__ = "accounts"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    krw_balance: Mapped[Optional[float]]
    usd_balance: Mapped[Optional[float]]
    total_value: Mapped[Optional[float]]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AccountPosition(Base):
    """종목별 포지션 — 평단 + 보유 수량."""

    __tablename__ = "account_positions"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    qty: Mapped[Optional[float]]
    avg_price: Mapped[Optional[float]]
    currency: Mapped[Optional[str]] = mapped_column(String(3))  # KRW/USD
    buy_tier_count: Mapped[int] = mapped_column(default=0)      # 결정 6 — 다단계 매수 횟수 (0~3)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Order(Base):
    """주문 (Toss API 발주 → Reconciler 추적)."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), index=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    side: Mapped[str] = mapped_column(String(4))    # BUY/SELL
    price: Mapped[Optional[float]]
    qty: Mapped[Optional[float]]
    state: Mapped[str] = mapped_column(String(20), index=True)
    # REQUESTED/PENDING/FILLED/PARTIAL_FILLED/CANCELED/FAILED
    requested_at: Mapped[Optional[datetime]]
    executed_at: Mapped[Optional[datetime]]
    provider_uuid: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    meta: Mapped[Optional[str]] = mapped_column(Text)  # JSON (전략 컨텍스트)


class EngineStatus(Base):
    """엔진 운영 상태 (heartbeat, mode)."""

    __tablename__ = "engine_status"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    is_running: Mapped[bool] = mapped_column(default=False)
    last_heartbeat: Mapped[Optional[datetime]]
    last_mode: Mapped[Optional[str]] = mapped_column(String(10))  # LIVE/TEST
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AuditTrade(Base):
    """매매 감사 로그 (Phase K — 모든 자동매매 결정 기록)."""

    __tablename__ = "audit_trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    bar_time: Mapped[Optional[str]] = mapped_column(String(30))
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    type: Mapped[str] = mapped_column(String(10))     # BUY/SELL
    reason: Mapped[Optional[str]] = mapped_column(String(50))
    # DRAWDOWN_TIER1/2/3 / TAKE_PROFIT / TIME_STOP 등
    price: Mapped[Optional[float]]
    qty: Mapped[Optional[float]]
    entry_price: Mapped[Optional[float]]    # SELL 시 매수 평단
    pct_from_52w_high: Mapped[Optional[float]]
    pnl_pct: Mapped[Optional[float]]
    meta: Mapped[Optional[str]] = mapped_column(Text)  # JSON
