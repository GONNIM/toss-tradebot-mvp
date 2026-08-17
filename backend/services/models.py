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

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text, func
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
    # Stage 3 다중 사용자 대비 · 현재 "owner" 고정 · toss-tradebot-tobe stage2-architecture §1.1
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
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
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
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


# ─────────────────────────────────────────────────────────────────
# Sector Leaders 모듈 테이블 (Phase B-2 — 산업통상부 월간 수출입동향)
#   설계: docs/plans/sector-leaders/01-mvp-design.md
# ─────────────────────────────────────────────────────────────────


class MotirItemExport(Base):
    """20대 품목 × 월별 수출 실적 (산업통상부 보도자료 참고 표 ②).

    잠정치 → 확정치 BACKFILL: 발표 후 약 9개월 후 정정 가능 ('27.2월 확정 발표 시).
    매월 1일 PDF 다운로드 후 적재. is_provisional=True 로 저장, 확정 발표 시 갱신.
    """

    __tablename__ = "motir_item_exports"

    item: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 보도자료 정식 명칭 (예: '반도체', '무선통신기기'). ITEM_ORDER_20 참조
    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # 'YYYY-MM'
    value_musd: Mapped[float] = mapped_column(Float)               # 수출액 (백만 달러)
    yoy_pct: Mapped[Optional[float]] = mapped_column(Float)        # 전년동월대비 %. PDF 결함 시 None
    share_pct: Mapped[Optional[float]] = mapped_column(Float)      # 전체 수출 중 비중 %
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    source_report_month: Mapped[str] = mapped_column(String(7))    # 출처 보도자료 발표월 'YYYY-MM'
    source_pdf: Mapped[str] = mapped_column(String(255))           # 출처 PDF 파일명
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # 확정 발표로 갱신된 시각

    __table_args__ = (
        Index("idx_motir_item_month", "month"),
        Index("idx_motir_item_source", "source_report_month"),
    )


class MotirRegionExport(Base):
    """10대 지역(9대+베트남) × 월별 수출 실적."""

    __tablename__ = "motir_region_exports"

    region: Mapped[str] = mapped_column(String(10), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    value_musd: Mapped[float] = mapped_column(Float)
    yoy_pct: Mapped[Optional[float]] = mapped_column(Float)
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    source_report_month: Mapped[str] = mapped_column(String(7))
    source_pdf: Mapped[str] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("idx_motir_region_month", "month"),
    )


class KrxStockMeta(Base):
    """KRX 종목 메타정보 — FDR StockListing 기반 (B-2c).

    매일 1회 갱신 또는 분석 직전 fetch.
    """

    __tablename__ = "krx_stock_meta"

    ticker: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    market: Mapped[Optional[str]] = mapped_column(String(10))   # KOSPI/KOSDAQ
    market_cap_krw: Mapped[Optional[float]] = mapped_column(Float)
    shares_outstanding: Mapped[Optional[float]] = mapped_column(Float)
    last_close: Mapped[Optional[float]] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class KrxDailyCandle(Base):
    """KRX 일봉 캐시 — pykrx 수집 (B-2c).

    Sector Leaders 24개월 분석용. 24M = 약 500 거래일 / 종목.
    """

    __tablename__ = "krx_daily_candles"

    ticker: Mapped[str] = mapped_column(String(6), primary_key=True)
    date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    return_pct: Mapped[Optional[float]] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_krx_candle_ticker_date", "ticker", "date"),
    )


class MotirExportHistory(Base):
    """잠정 → 확정 갱신 이력 (BACKFILL).

    동일 (kind, key, month) 에 대해 잠정치 값이 변경될 때마다 1행 추가.
    kind: 'item' / 'region'.  key: 품목명 / 지역명.
    """

    __tablename__ = "motir_export_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(10), index=True)  # 'item' / 'region'
    key: Mapped[str] = mapped_column(String(20), index=True)   # 품목명 또는 지역명
    month: Mapped[str] = mapped_column(String(7), index=True)
    value_musd: Mapped[float] = mapped_column(Float)
    yoy_pct: Mapped[Optional[float]] = mapped_column(Float)
    share_pct: Mapped[Optional[float]] = mapped_column(Float)
    is_provisional: Mapped[bool] = mapped_column(Boolean)
    source_report_month: Mapped[str] = mapped_column(String(7))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CustomsInterimExport(Base):
    """관세청 10일 단위 잠정 수출 통계 (B-2k).

    cntyMmUtPrviExpAcrs API 응답:
      - 매월 1~10일, 1~20일, 1~말일 3회 잠정 발표
      - 전체 + 10개 주요국 (CN·US·EU·VN·HK·JP·TW·IN·SG·MY)
      - 단위: 천 달러
    """

    __tablename__ = "customs_interim_exports"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    period: Mapped[str] = mapped_column(String(5), primary_key=True)
    # '01~10' / '01~20' / '01~31'
    country_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    # 'TOTAL' / 'CN' / 'US' / 'EU' / 'VN' / 'HK' / 'JP' / 'TW' / 'IN' / 'SG' / 'MY'
    usd_amount_thousand: Mapped[float] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_customs_month_period", "month", "period"),
    )


class SectorLeader(Base):
    """Sector Leaders 분석 결과 — 품목 × 종목 페어별 (B-2d).

    매월 1일 PDF 적재 후 재계산.
    confidence 배지: strong (|r|≥0.7) / medium (0.4~0.7) / weak (<0.4).
    """

    __tablename__ = "sector_leaders"

    item: Mapped[str] = mapped_column(String(20), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    market_cap_krw: Mapped[Optional[float]] = mapped_column(Float)
    export_ratio_hint: Mapped[Optional[float]] = mapped_column(Float)
    pearson_r0: Mapped[Optional[float]] = mapped_column(Float)
    best_r: Mapped[Optional[float]] = mapped_column(Float)
    best_lag_months: Mapped[Optional[int]] = mapped_column(Integer)
    sample_n: Mapped[Optional[int]] = mapped_column(Integer)
    confidence: Mapped[str] = mapped_column(String(10))  # strong/medium/weak
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_sector_leader_item_rank", "item", "rank"),
    )


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


# ─────────────────────────────────────────────────────────────────
# Execution Layer 감사 로그 (v2 트랙 C · Phase 1)
#   스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §9
# ─────────────────────────────────────────────────────────────────


class OrderAudit(Base):
    """OMI 주문 감사 로그 — Paper/Toss 어댑터 공통.

    audit_trades (기존 Golden Cross 시절) 와는 별개.
    Order (Phase K 초기) 와도 다름 — order_uuid PRIMARY KEY 기반.
    """

    __tablename__ = "order_audit"

    order_uuid: Mapped[str] = mapped_column(String(36), primary_key=True)
    broker_kind: Mapped[str] = mapped_column(String(10))          # paper | toss
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(64))
    ticker: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))                  # buy | sell
    order_type: Mapped[str] = mapped_column(String(10))           # market | limit
    qty: Mapped[int]
    price: Mapped[Optional[float]]
    signal_source: Mapped[Optional[str]] = mapped_column(String(30))
    signal_id: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(15))               # OrderStatus 값
    filled_qty: Mapped[int] = mapped_column(default=0)
    avg_fill_price: Mapped[Optional[float]]
    total_fee: Mapped[float] = mapped_column(default=0.0)
    error_code: Mapped[Optional[str]] = mapped_column(String(50))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    raw_response: Mapped[Optional[str]] = mapped_column(Text)     # JSON dump
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_order_audit_ticker_created", "ticker", "created_at"),
        Index("ix_order_audit_signal", "signal_source", "signal_id"),
        Index("ix_order_audit_broker_created", "broker_kind", "created_at"),
    )


# ─────────────────────────────────────────────────────────────────
# 급등주 스나이퍼 · Sprint 1 (2026-07-11~)
#   설계: docs/plans/sniper/00-sprint1-plan.md
# ─────────────────────────────────────────────────────────────────


class LiveTapeUniverse(Base):
    """KOSDAQ 유니버스 · nightly 22:00 KST refresh.

    필터 통과 종목만 저장. Sniper 는 이 유니버스만 스캔.
    """

    __tablename__ = "live_tape_universe"

    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(10), default="KOSDAQ")
    dept: Mapped[Optional[str]] = mapped_column(String(50))          # 중견/우량/벤처/기술성장

    close_price: Mapped[Optional[float]]
    market_cap_krw: Mapped[Optional[float]]                          # 시가총액
    shares: Mapped[Optional[int]]                                    # 발행주식수 (유통 근사)
    amount_today: Mapped[Optional[float]]                            # 당일 거래대금
    amount_20d_avg: Mapped[Optional[float]]                          # 20일 ADV (Sprint 1.5)

    is_squeeze_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LiveTapeRanking(Base):
    """Toss rankings 폴링 스냅샷 (rank velocity 계산 원본)."""

    __tablename__ = "live_tape_ranking"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10))
    rank: Mapped[Optional[int]]
    volume_amount: Mapped[Optional[float]]
    price: Mapped[Optional[float]]
    return_pct: Mapped[Optional[float]]
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_lt_ranking_ticker_time", "ticker", "captured_at"),
    )


class SniperSignal(Base):
    """스나이퍼 진입/청산 이력. order_audit 과 연결 (order_uuid FK)."""

    __tablename__ = "sniper_signal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    tape_score: Mapped[Optional[float]]
    rank_velocity: Mapped[Optional[float]]
    trades_intensity: Mapped[Optional[float]]
    orderbook_imbalance: Mapped[Optional[float]]
    entry_order_uuid: Mapped[Optional[str]] = mapped_column(String(36))
    entry_price: Mapped[Optional[float]]
    exit_order_uuid: Mapped[Optional[str]] = mapped_column(String(36))
    exit_price: Mapped[Optional[float]]
    peak_price: Mapped[Optional[float]]                              # trailing 추적용
    pnl_pct: Mapped[Optional[float]]
    reason: Mapped[Optional[str]] = mapped_column(String(20))        # trailing · hard_sl · force_close


# ─────────────────────────────────────────────────────────────────
# Super Signal 데이터 소스 (v2 트랙 C · Phase 3)
#   설계: docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §6-1
# ─────────────────────────────────────────────────────────────────


class SignalHit(Base):
    """discovery 3채널(meme/vip/activist) 알림 성공 시 병행 INSERT.

    Super Signal 병합기의 원천 데이터. 30일 window 종목별 히트 카운트/스코어 산출.
    """

    __tablename__ = "signal_hit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(30))          # meme_stock | vip | activist
    signal_id: Mapped[str] = mapped_column(String(120))      # 원 시그널 ID (감사 추적)
    score: Mapped[float]                                     # 0.0~1.0 (원 시그널 강도 fraction)
    action: Mapped[str] = mapped_column(String(4))           # buy | sell
    hit_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_signal_hit_ticker_time", "ticker", "hit_at"),
        Index("ix_signal_hit_source_time", "source", "hit_at"),
    )


class SuperSignal(Base):
    """Super Signal 승격 이벤트 (2+ source hit within 30d).

    OCO 조건주문 등록 · 알림 · UI 표시의 원본.
    """

    __tablename__ = "super_signal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    intensity: Mapped[float]                                 # Σ(hit_score × source_weight)
    sources: Mapped[str] = mapped_column(String(120))        # "meme_stock+vip+activist" (구분자 +)
    hit_count: Mapped[int]                                   # window 내 총 히트 수
    first_hit_at: Mapped[datetime] = mapped_column(DateTime)
    last_hit_at: Mapped[datetime] = mapped_column(DateTime)
    promoted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    order_uuid: Mapped[Optional[str]] = mapped_column(String(36))  # SignalRouter 실행 시
    oco_id: Mapped[Optional[str]] = mapped_column(String(120))     # Toss conditionalOrderId
    oco_status: Mapped[Optional[str]] = mapped_column(String(20))  # OPEN·TRIGGERED·CANCELED
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_super_signal_ticker_time", "ticker", "promoted_at"),
    )


# ─────────────────────────────────────────────────────────────────
# Meme Watch 모듈 테이블 (Phase 1a — 화끈한 밈주 찾기)
#   설계: docs/plans/meme-stock-discovery/01-signal-sources.md
# ─────────────────────────────────────────────────────────────────


class MemeUniverse(Base):
    """추적 대상 종목 마스터 — US(시총 ≤ 5B$) + KOSDAQ(시총 ≤ 1조원)."""

    __tablename__ = "meme_universe"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(10), index=True)  # "US" / "KRX"
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100))
    sector: Mapped[Optional[str]] = mapped_column(String(50))
    market_cap: Mapped[Optional[float]]  # USD (US) / KRW (KRX)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_meme_universe_market_ticker", "market", "ticker", unique=True),
    )


class MemeSocialSignal(Base):
    """소셜 시그널 — 5분 batch 누적."""

    __tablename__ = "meme_social_signal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(30))
    # "reddit" / "stocktwits" / "google_trends"
    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    weighted_score: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_delta: Mapped[Optional[float]] = mapped_column(Float)
    # stocktwits 전용: (Bullish − Bearish) / total
    window_hours: Mapped[int] = mapped_column(Integer, default=24)


class MemeShortInterest(Base):
    """공매도 잔고 — US FINRA(격주) + KRX 일별."""

    __tablename__ = "meme_short_interest"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    market: Mapped[str] = mapped_column(String(10))     # "US" / "KRX"
    as_of_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    pct_of_float: Mapped[float]
    days_to_cover: Mapped[Optional[float]]
    source: Mapped[str] = mapped_column(String(30))
    # "finra" / "krx" / "yahoo_estimate"


class MemeAlertHistory(Base):
    """Telegram alert 발송 이력 (Phase 6) — 종목별 24h 중복 방지."""

    __tablename__ = "meme_alert_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    alert_type: Mapped[str] = mapped_column(String(30))
    # "ERUPTING" (Intensity ≥ 8.0) / "BLAZING" (Score ≥ 1.0)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    payload: Mapped[Optional[str]] = mapped_column(Text)  # JSON


class MemeScoreHistory(Base):
    """Meme Score 5분 batch 이력 (Phase 4).

    Intensity 의 score_delta / Time-in-BLAZING / persistence 등 시계열
    지표 계산 baseline. 매 5분 top N 종목 저장.
    """

    __tablename__ = "meme_score_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    market: Mapped[Optional[str]] = mapped_column(String(10))
    score: Mapped[float]
    label: Mapped[str] = mapped_column(String(20))
    active_signals: Mapped[int] = mapped_column(Integer, default=0)


class MemeCatalystEvent(Base):
    """외부 catalyst 이벤트 — DART 공시 / KRX VI / FINRA halt 등 (Phase 3-B).

    event_id 는 source 내 고유 ID (DART rcept_no 등) — UPSERT 중복 방지.
    24h 윈도우 ticker 별 카운트 → catalyst_score 산출.
    """

    __tablename__ = "meme_catalyst_event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(30))     # "dart" / "krx_vi" / "finra"
    event_type: Mapped[str] = mapped_column(String(50)) # "B" / "C" / "halt" / "VI" 등
    event_label: Mapped[Optional[str]] = mapped_column(Text)  # 공시 제목·이벤트 설명
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    # source 별 고유 ID (DART rcept_no = 14자리 / KRX = date+ticker+seq)
    payload: Mapped[Optional[str]] = mapped_column(Text)   # JSON


class MemeVolumeSnapshot(Base):
    """일봉 거래량·반등·RSI 스냅샷 — 5분 batch.

    Phase 2 튜닝: volume_z_20d 외에 volume_ratio_20d (단순 배수) 도 적재 —
    백테스트로 z-score 가 폭증 누적 시 std 폭증으로 무뎌짐 확인됨.
    """

    __tablename__ = "meme_volume_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    volume: Mapped[float]
    volume_z_20d: Mapped[float]
    volume_ratio_20d: Mapped[Optional[float]]  # Phase 2: today / 20D 평균
    return_1d_pct: Mapped[float]
    rsi_14: Mapped[Optional[float]]
    halt_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    close: Mapped[Optional[float]]  # Phase 3-D: 일봉 마지막 종가 (UI current_price)


# ─────────────────────────────────────────────────────────────────
# Watchlist Signal (Sprint 2 · 야간 축적 신호)
#   설계: docs/plans/sniper/03-sprint2-week1-tasks.md T58
# ─────────────────────────────────────────────────────────────────


class WatchlistSignal(Base):
    """마감 후 야간 축적 신호. 다음날 Watchlist 승격의 원천 데이터.

    source 별 예시:
      · news_yhap · news_edaily · news_fnnews · news_herald · news_sedaily
      · board_naver
      · youtube_hantoo · youtube_shuka · youtube_jungpro · youtube_sampro
      · assembly · motie_rss · msit_rss · moef_rss · molit_rss
      · prev_day_derivative
    """

    __tablename__ = "watchlist_signal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    signal_type: Mapped[str] = mapped_column(String(30))
    intensity: Mapped[float]
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    trade_date: Mapped[str] = mapped_column(String(10), index=True)

    __table_args__ = (
        Index("ix_watchlist_signal_ticker_date", "ticker", "trade_date"),
        Index("ix_watchlist_signal_source_time", "source", "detected_at"),
    )


class Watchlist(Base):
    """개장 전 확정된 Top 30 Watchlist · Sprint 2 Week 2 T60.

    unique(trade_date, ticker) · finalize 잡이 매일 08:30 KST 재생성.
    locked=True 항목은 finalize 시 유지 (사용자 수동 lock).
    """

    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
    trade_date: Mapped[str] = mapped_column(String(10), index=True)   # YYYY-MM-DD
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    rank: Mapped[int]                                                  # 1 = top
    composite_score: Mapped[float]
    news_score: Mapped[float] = mapped_column(Float, default=0.0)
    board_score: Mapped[float] = mapped_column(Float, default=0.0)
    youtube_score: Mapped[float] = mapped_column(Float, default=0.0)
    event_score: Mapped[float] = mapped_column(Float, default=0.0)
    prev_day_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_breakdown: Mapped[Optional[str]] = mapped_column(Text)      # JSON: {source: {count, intensity_sum}}
    locked: Mapped[bool] = mapped_column(Boolean, default=False)       # 사용자 수동 lock
    added_by: Mapped[str] = mapped_column(String(10), default="auto")  # auto | user
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Stage 3 다중 사용자 대비 · trade_date + ticker + user_id unique
        Index("ix_watchlist_date_ticker_user", "trade_date", "ticker", "user_id", unique=True),
        Index("ix_watchlist_date_rank", "trade_date", "rank"),
    )


# ─────────────────────────────────────────────────────────────────
# Powder Keg Screener (Phase 7 · 화약고 스크리너)
#   지시서: docs/plans/powderkeg-screener/phase7-powderkeg-screener.md
#   원칙: hypothesis 상태 유지 · 자동매매 절대 연결 금지
# ─────────────────────────────────────────────────────────────────


class FinancialSnapshot(Base):
    """DART 재무제표 스냅샷 · Phase 7-1b.

    reference_date (보고 대상 기간) vs release_date (공시 접수일) 분리 저장 · as-of 규약 준수.
    unique(ticker, reference_date, report_code) — 같은 기간의 정정보고서는 최신 release_date 우선.
    """

    __tablename__ = "powderkeg_financial_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    reference_date: Mapped[str] = mapped_column(String(10))    # 회계 기말 YYYY-MM-DD
    release_date: Mapped[datetime] = mapped_column(DateTime, index=True)   # 공시 접수일시
    report_code: Mapped[str] = mapped_column(String(5))        # 11011(사업)·11012(반기)·11013(1분기)·11014(3분기)
    # 재무상태표
    cash_and_equivalents: Mapped[Optional[float]]              # 현금및현금성자산
    short_term_investments: Mapped[Optional[float]]            # 단기금융상품
    total_debt: Mapped[Optional[float]]                        # 총차입금 (단기+장기)
    total_equity: Mapped[Optional[float]]                      # 자본총계
    retained_earnings: Mapped[Optional[float]]                 # 이익잉여금
    # v1.30 · 3차 리뷰 P2 · 계약부채 (수주산업 조정 net_cash 계산용)
    #   서희건설 등 수주산업은 선수금(=계약부채) 가 cash_and_equivalents 에 섞여
    #   순현금 과대평가. total_debt 는 차입금·사채만이라 계약부채 미포함.
    #   조정 순현금 = cash - total_debt - contract_liabilities.
    contract_liabilities: Mapped[Optional[float]] = mapped_column(default=None)
    # 손익계산서
    operating_income: Mapped[Optional[float]]                  # 영업이익
    net_income: Mapped[Optional[float]]                        # 당기순이익
    interest_income: Mapped[Optional[float]]                   # 이자수익
    revenue: Mapped[Optional[float]]                           # 매출액 (Piotroski §8-9)
    gross_profit: Mapped[Optional[float]]                      # 매출총이익
    # 재무상태표 추가 (Piotroski + 부채비율)
    total_assets: Mapped[Optional[float]]                      # 자산총계
    current_assets: Mapped[Optional[float]]                    # 유동자산
    current_liabilities: Mapped[Optional[float]]               # 유동부채
    # 현금흐름표
    cash_flow_from_operations: Mapped[Optional[float]]         # 영업활동현금흐름 (Piotroski §2,4)
    # 발행주식수 (Piotroski §7 · 유상증자 여부)
    shares_outstanding: Mapped[Optional[float]]
    # 감사의견 · "적정" / "한정" / "부적정" / "의견거절"
    audit_opinion: Mapped[Optional[str]] = mapped_column(String(20))
    raw_json: Mapped[Optional[str]] = mapped_column(Text)      # 원문 응답 보존 (감사·튜닝)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # v1.30 · 3차 리뷰 P2 · 상폐사 판별 (PIT 층화 백테스트 · 생존편향 방지)
    #   기본 False (상장 중) · P2-1 수집기가 KRX 상폐 목록 조회 후 True 로 갱신.
    is_delisted: Mapped[Optional[bool]] = mapped_column(default=False)
    delisted_at: Mapped[Optional[str]] = mapped_column(String(10), default=None)   # YYYY-MM-DD

    __table_args__ = (
        Index("ix_pk_fin_ticker_ref", "ticker", "reference_date", "report_code", unique=True),
    )


class KrxMarketSnapshot(Base):
    """KRX 시장 데이터 · Phase 7-1c.

    일일 갱신 · 시가총액·PBR·거래대금·상장시장.
    """

    __tablename__ = "powderkeg_krx_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)   # YYYY-MM-DD
    name: Mapped[Optional[str]] = mapped_column(String(100))             # 종목명 (FDR StockListing)
    market: Mapped[Optional[str]] = mapped_column(String(10))            # KOSPI / KOSDAQ
    close_price: Mapped[Optional[float]]
    market_cap: Mapped[Optional[float]]
    pbr: Mapped[Optional[float]]
    avg_daily_amount_60d: Mapped[Optional[float]]                        # 60일 평균 거래대금

    __table_args__ = (
        Index("ix_pk_krx_ticker_date", "ticker", "snapshot_date", unique=True),
    )


class BigBusinessGroup(Base):
    """공정위 공시대상기업집단 명단 · Phase 7-1d.

    연 1회 갱신 · 대기업집단 소속 종목 배제용 필터.
    """

    __tablename__ = "powderkeg_big_biz_group"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(index=True)
    group_name: Mapped[str] = mapped_column(String(100))        # 예: "삼성", "SK"
    corp_name: Mapped[str] = mapped_column(String(100))         # 계열사 명
    corp_id: Mapped[Optional[str]] = mapped_column(String(20))  # 사업자등록번호 등
    ticker: Mapped[Optional[str]] = mapped_column(String(10), index=True)

    __table_args__ = (
        Index("ix_pk_big_biz_year_ticker", "year", "ticker"),
    )


class MajorShareholder(Base):
    """최대주주 및 특수관계인 지분율 · Phase 7-1b.

    DART fetch_majorstock 로 축적 · 분기~반기 주기 갱신.
    """

    __tablename__ = "powderkeg_major_shareholder"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    reference_date: Mapped[str] = mapped_column(String(10))       # 지분율 기준 시점
    release_date: Mapped[datetime] = mapped_column(DateTime)
    major_pct: Mapped[float]                                      # 최대주주 지분율 (총계)
    related_pct: Mapped[float]                                    # 특수관계인 총계
    treasury_pct: Mapped[Optional[float]]                         # 자기주식 비율
    raw_json: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_pk_major_ticker_ref", "ticker", "reference_date", unique=True),
    )


class PowderKegList(Base):
    """스크리닝 결과 (화약고 리스트) · Phase 7-2.

    분기 1회 + 수동 트리거 실행 · run_id 로 히스토리 유지.
    """

    __tablename__ = "powderkeg_list"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
    run_id: Mapped[str] = mapped_column(String(20), index=True)   # YYYYMMDD-HHMMSS
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))               # passed / rejected / cash_suspect
    # 서브스코어 (§7-2 마지막 문단)
    net_cash_ratio: Mapped[Optional[float]]                       # 순현금 / 시총
    piotroski_f_score: Mapped[Optional[int]]
    owner_pct: Mapped[Optional[float]]                            # 최대+특수관계인
    treasury_pct: Mapped[Optional[float]]                         # 자사주 비율
    pbr: Mapped[Optional[float]]
    dividend_payout: Mapped[Optional[float]]                      # 배당성향
    # 조건별 통과/탈락 상세 (JSON: {"pbr":true, "net_cash":false, ...})
    conditions_json: Mapped[Optional[str]] = mapped_column(Text)
    reject_reasons: Mapped[Optional[str]] = mapped_column(Text)   # 콤마 분리
    # Phase C 주 5-1 · 자산화 4요소 (2026-07-30)
    # 참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §4-1
    hypothesis_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    # 예: "v2.0-powderkeg-6cond" · 판정 시점 가설 버전 각인 (리뷰 C 리스크 C2)
    market_context: Mapped[Optional[str]] = mapped_column(String(30))
    # 예: "bull" | "bear" | "choppy" | "crisis" | "unknown" · KOSPI 20MA·VKOSPI 자동 태깅
    retrospect_url: Mapped[Optional[str]] = mapped_column(Text)
    # 승격 후 이벤트·매수·결과 링크 (사용자 수동 or 미래 자동)
    # 조건별 margin 값 (예: {"1_pbr": {"value": 0.42, "margin": 0.18}, ...}) · 강등/복귀 추이 분석 근거
    conditions_margins_json: Mapped[Optional[str]] = mapped_column(Text)
    # 사용자 편집 (Phase 7-2 · UI)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)          # 스크리너 재실행 후에도 유지
    added_by: Mapped[str] = mapped_column(String(10), default="auto")     # auto | user
    user_note: Mapped[Optional[str]] = mapped_column(Text)                # 사용자 코멘트
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        # Stage 3 다중 사용자 대비 · run_id + ticker + user_id unique
        Index("ix_pk_list_run_ticker_user", "run_id", "ticker", "user_id", unique=True),
    )


class PowderKegEvent(Base):
    """이벤트 트리거 로그 · Phase 7-3.

    Type A/B 분류 · LLM classifier 결과 포함 · needs_human_review 플래그.
    """

    __tablename__ = "powderkeg_event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    event_type: Mapped[str] = mapped_column(String(10))           # A1/A2/.../B1/B2/B3
    source: Mapped[str] = mapped_column(String(20))               # dart / news_xxx
    source_id: Mapped[Optional[str]] = mapped_column(String(50))  # DART rcept_no · 뉴스 URL 해시
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    release_date: Mapped[Optional[datetime]] = mapped_column(DateTime)   # 공시/기사 원본 시각
    llm_classification: Mapped[Optional[str]] = mapped_column(Text)      # JSON: {label, confidence, rationale}
    confidence: Mapped[Optional[float]]
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(30))       # notified / list_removed / order_ticket_created
    validated: Mapped[bool] = mapped_column(Boolean, default=False)        # 백테스트 통과 시 True

    __table_args__ = (
        Index("ix_pk_event_ticker_time", "ticker", "detected_at"),
        Index("ix_pk_event_source_id", "source", "source_id"),
    )


class DartCorpCodeMap(Base):
    """DART corp_code ↔ KRX stock_code 매핑 · Phase 7-1g.

    fetch_corp_codes 로 월 1회 갱신 · 100k+ 항목 (상장·비상장 포함).
    수집기가 ticker → corp_code 해결 시 사용.
    """

    __tablename__ = "powderkeg_dart_corp_code"

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    stock_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    modify_date: Mapped[Optional[str]] = mapped_column(String(10))
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PowderKegBacktestReport(Base):
    """백테스트 리포트 캐시 · §9-1 정밀화 후 5년 표본으로 계산 시 60s 초과.

    POST /backtest/{event_type} · 계산 + 저장 (upsert)
    GET  /report/{event_type} · 캐시 읽기만 (즉시 응답)
    """

    __tablename__ = "powderkeg_backtest_report"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(4), unique=True, index=True)
    aggregate_json: Mapped[str] = mapped_column(Text)                       # AggregatedResult JSON
    decision_json: Mapped[str] = mapped_column(Text)                        # ValidationDecision JSON
    total_events: Mapped[int] = mapped_column(default=0)
    valid_events: Mapped[int] = mapped_column(default=0)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PowderKegOrderTicket(Base):
    """반자동 주문 티켓 · Phase 7-5 · 1클릭 승인 필수.

    validated 트리거만 티켓 생성 가능 · 무효화 조건 미입력 시 차단.
    """

    __tablename__ = "powderkeg_order_ticket"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(index=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    proposed_qty: Mapped[int]
    proposed_price: Mapped[Optional[float]]                             # 지정가 or None(시장가)
    invalidation_price: Mapped[float]                                   # 필수 · 가격 무효화 (예: -15%)
    invalidation_logic: Mapped[str] = mapped_column(Text)               # 필수 · 논리 무효화 (예: 무혐의 확정)
    holding_days_max: Mapped[int] = mapped_column(default=365)          # 보유 상한 (기본 12개월)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected/executed
    approver: Mapped[Optional[str]] = mapped_column(String(50))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    executed_order_uuid: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PowderKegRun(Base):
    """스크리너 run 자체 기록 · P4-1 provenance/RunDiff.

    - `run_id` = 기존 문자열 형식(YYYYMMDD-HHMMSSK) 재사용 · PK
    - trigger = auto(scheduler) / manual(API)
    - git_sha = 배포 SHA (SSR 푸터와 일치 · 데이터 재현성)
    """

    __tablename__ = "powderkeg_run"

    run_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ticker_count: Mapped[int] = mapped_column(default=0)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    git_sha: Mapped[Optional[str]] = mapped_column(String(40))


class PowderKegDelistedIssue(Base):
    """KIND 상장폐지 종목 스냅샷 · P2-1.

    kind.krx.co.kr/investwarn/delcompany.do 크롤링 결과 append-only 저장.
    P2-1 재무 백필 대상 후보 · P2-2 PIT 백테스트 생존 편향 해소용.
    """

    __tablename__ = "powderkeg_delisted_issue"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    market: Mapped[Optional[str]] = mapped_column(String(20))     # KOSPI/KOSDAQ/KONEX
    delisted_date: Mapped[Optional[str]] = mapped_column(String(20))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    note: Mapped[Optional[str]] = mapped_column(String(200))
    is_transitional: Mapped[bool] = mapped_column(Boolean, default=False)  # 이관성 (이전상장/합병 등)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_pk_delisted_ticker_snap", "ticker", "snapshot_date"),
    )


class PowderKegDelistedBackfillProgress(Base):
    """P2-1 상폐사 재무 백필 진행 저장 (재개 지원)."""

    __tablename__ = "powderkeg_delisted_backfill_progress"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    last_offset: Mapped[int] = mapped_column(default=0)
    total_candidates: Mapped[int] = mapped_column(default=0)
    inserted: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/paused/done/error
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PowderKegKrxIssue(Base):
    """KRX 관리종목 · 매매거래정지 스냅샷 · P4-5.

    KIND(kind.krx.co.kr) 크롤링 결과를 매일 append-only 로 저장 · 이력 유지.
    스크리너 조건 ⑩ (관리종목 이력 없음) 실 데이터 근거.
    """

    __tablename__ = "powderkeg_krx_issue"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))                   # admin (관리종목) / halt (매매거래정지)
    reason: Mapped[Optional[str]] = mapped_column(String(500))
    designation_date: Mapped[Optional[str]] = mapped_column(String(20))   # 원문 or ISO
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)    # YYYY-MM-DD
    refreshed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_pk_krx_issue_ticker_kind_snap", "ticker", "kind", "snapshot_date"),
    )


class PowderKegRunDiff(Base):
    """조건 단위 변화 로그 · P4-1 provenance/RunDiff.

    변경된 조건만 삽입 (동일 값 skip · 값 또는 상태 변화 최소 1건 필수).
    condition_key 예시:
      · 조건 판정: "1_pbr", "2_net_cash_ratio", ..., "10_no_bad_history"
      · 티어 이동: "tier"
      · 서브스코어: "pbr", "net_cash_ratio", "owner_pct", "piotroski_f_score"
    """

    __tablename__ = "powderkeg_run_diff"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(20), index=True)     # PowderKegRun FK (soft)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    condition_key: Mapped[str] = mapped_column(String(64), index=True)
    prev_value: Mapped[Optional[str]] = mapped_column(Text)         # JSON 인코딩 (숫자/문자/null)
    curr_value: Mapped[Optional[str]] = mapped_column(Text)
    prev_status: Mapped[Optional[str]] = mapped_column(String(16))  # pass/fail/na/skip/null
    curr_status: Mapped[Optional[str]] = mapped_column(String(16))
    reason_hint: Mapped[Optional[str]] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_pk_run_diff_ticker_time", "ticker", "changed_at"),
        Index("ix_pk_run_diff_cond_time", "condition_key", "changed_at"),
    )


# ─────────────────────────────────────────────────────────────────
# Judgment Journal (Phase B 주 3 · 2026-08-12 예정 · 조기 착수 2026-07-30)
#   설계: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1
#   근거: reviews/perspective-a-quant-psychology.md 권고 1
#         "판정→결과 폐루프 · 모든 페이지 판정 병치 (self-page 편애 방지)"
# ─────────────────────────────────────────────────────────────────


class UserJudgment(Base):
    """사용자 판정 저널 · rejection criteria 강제 · outcome 자동 계산.

    Stage 1 진짜 KPI (자기 판단 오류율 측정·감소) 의 원자 단위.
    Powderkeg lock · Watchlist 편입 · Sniper enable 시 팝업으로 강제 기록.
    Stage 2 지식 자산화 시 상품(Weekly Report · 컨설팅) 의 원천.
    """

    __tablename__ = "user_judgments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    user_id: Mapped[str] = mapped_column(String(50), server_default="owner", default="owner", index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    page_source: Mapped[str] = mapped_column(String(30), index=True)
    # 예: "powderkeg" | "watchlist" | "sniper" | "activist" | "vip" | "manual"

    # 가설 버전 각인 (v1.x 판정 무효화 방지 · 리뷰 C 리스크 C2)
    hypothesis_id: Mapped[str] = mapped_column(String(50), index=True)
    # 예: "v2.0-powderkeg-6cond" | "sniper-v1.55-tape-score" | "manual-thesis"

    # 판정 본문 (마크다운 · 자유 서술)
    thesis_md: Mapped[str] = mapped_column(Text)

    # 반증 기준 (필수 · rejection criteria)
    invalidation_price: Mapped[Optional[float]]  # 이 가격 이탈 시 판정 무효
    target_price: Mapped[Optional[float]]        # 목표가 (선택)
    horizon_days: Mapped[int] = mapped_column(Integer, default=7)  # T+N 검증 기간
    # 진입가 (Rulebook R:R 계산용 · 2026-08-02 · 존마 원칙 2)
    #   R:R = (target - entry) / (entry - invalidation) · target·invalidation 있어야 함
    #   미입력 시 R:R baseline 에서 제외
    entry_price: Mapped[Optional[float]] = mapped_column(default=None)

    # 사용자 상태 (Kahneman hot/cold state · 리뷰 A 권고 5)
    mood: Mapped[str] = mapped_column(String(20), default="neutral")
    # cool | neutral | revenge | fomo

    # 시장 컨텍스트 (자동 태깅 · KOSPI 20MA·VKOSPI 기반)
    market_regime: Mapped[str] = mapped_column(String(30), default="unknown")
    # bull | bear | choppy | crisis | unknown

    # 자동 outcome (T+N 실현 수익률 · 크론 자동 계산)
    result_at_horizon: Mapped[Optional[float]] = mapped_column(default=None)
    result_computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)

    # 물타기 감지 (Rulebook Phase 1-B · 2026-08-02 · 존마 원칙 3)
    # 판정 후 T+horizon_days 기간 내 저가가 invalidation_price 이하 이탈했으면 기록.
    # invalidation_hit_ts != NULL AND result_at_horizon < 0 이면 "물타기" 로 카운트.
    invalidation_hit_ts: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    invalidation_hit_low: Mapped[Optional[float]] = mapped_column(default=None)

    # 재현성 (판정 시점 배포 SHA)
    git_sha: Mapped[Optional[str]] = mapped_column(String(40))

    # ─── Supersede · 티커당 판정 1건 원칙 (2026-08-14 · Fable 5) ─────
    # append-only · 삭제 금지 · 새 판정이 대체 시 이전 판정에 by_id 기록
    superseded_by_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, default=None)
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)
    supersede_reason: Mapped[Optional[str]] = mapped_column(String(200), default=None)

    # PATCH 이력 (invalidation/target/thesis 갱신 추적 · JSON 문자열)
    updated_history: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ─── 전술 격벽 (2026-08-14 · Fable 5) ─────────────────────────────
    # strategy: core (장기 · 최후 방어선) | swing (단기 · 타이트 손절) | event (사건 조건)
    # 생성 후 수정 불가 · supersede 만 가능 (전술 전환 = 새 판정)
    strategy: Mapped[Optional[str]] = mapped_column(String(20), default=None, index=True)
    qty: Mapped[Optional[float]] = mapped_column(default=None)  # 트랑셰 수량

    __table_args__ = (
        Index("ix_judgment_user_ts", "user_id", "ts"),
        Index("ix_judgment_ticker_ts", "ticker", "ts"),
        Index("ix_judgment_hyp_ts", "hypothesis_id", "ts"),
    )


# ─────────────────────────────────────────────────────────────────
# Powderkeg Tier History (Phase C 주 5-2 · 2026-07-30)
#   설계: docs/plans/toss-tradebot-tobe/stage2-architecture.md §4-3
#   근거: reviews/perspective-c-knowledge-assetization.md 권고 3
#         "경인전자 강등(v2 정체성 부적합)처럼 tier 이동 자체가 인용 가능한 이벤트"
# ─────────────────────────────────────────────────────────────────


class PowderKegTierHistory(Base):
    """종목별 tier 이동 시계열 · Weekly Report·컨설팅 소재.

    run 단위 스냅샷(powderkeg_list)과 별개 · 종목 단위 시계열.
    승격·강등 이벤트마다 append (동일 tier 반복 저장 안 함).
    """

    __tablename__ = "powderkeg_tier_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    run_id: Mapped[str] = mapped_column(String(20), index=True)     # 이 run 에서 감지
    prev_tier: Mapped[Optional[str]] = mapped_column(String(30))    # None = 첫 등장
    curr_tier: Mapped[str] = mapped_column(String(30))              # tier_1_passed / tier_2_near / rejected / ...
    change_type: Mapped[str] = mapped_column(String(20))            # promoted / demoted / stable_first / rejected
    note: Mapped[Optional[str]] = mapped_column(Text)               # 예: "v2 정체성 부적합"
    hypothesis_id: Mapped[Optional[str]] = mapped_column(String(50))
    changed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_pk_tier_hist_ticker_time", "ticker", "changed_at"),
        Index("ix_pk_tier_hist_run", "run_id"),
    )


# ─────────────────────────────────────────────────────────────────
# Sniper API Access Audit (Phase D 주 7 · 2026-07-31)
#   설계: docs/plans/toss-tradebot-tobe/roadmap-12week.md Phase D
#         "sniper_api_access 감사 테이블 실체화 · auth.py DB write 승격"
#   근거: 인증 이관 시 실 감사 이벤트를 DB에 축적 · Stage 3 SLA 근거
# ─────────────────────────────────────────────────────────────────


class SniperApiAccess(Base):
    """관리자 인증·감사 이벤트 append-only 로그.

    auth.py의 require_sniper_token/require_sniper_live_token 통과·실패,
    세션 로그인/로그아웃 이벤트를 그대로 기록. Sentry 관측성과 병존.
    표준 로그로만 남기던 것을 DB write로 승격 (Phase D).
    """

    __tablename__ = "sniper_api_access"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    event: Mapped[str] = mapped_column(String(30), index=True)
    # login_ok | login_fail | logout | auth_ok | auth_fail | live_block | server_misconfig
    role: Mapped[str] = mapped_column(String(20), default="anon")
    # admin | subscriber | anon
    path: Mapped[str] = mapped_column(String(200))
    method: Mapped[Optional[str]] = mapped_column(String(10))
    ip: Mapped[Optional[str]] = mapped_column(String(45))          # IPv6 max 45
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    token_source: Mapped[Optional[str]] = mapped_column(String(10))  # cookie | header | none
    detail: Mapped[Optional[str]] = mapped_column(Text)             # 실패 사유·메타 JSON

    __table_args__ = (
        Index("ix_sniper_access_event_ts", "event", "ts"),
        Index("ix_sniper_access_ip_ts", "ip", "ts"),
    )


# ─────────────────────────────────────────────────────────────────
# Rulebook · Blue-Chip Screener (Phase E+ · 2026-08-02)
#   존마 강의 원칙 1 · 5단계 우량주 필터 결과 저장.
#   Powderkeg 패턴 미러 · run_id 시계열 · 매일 22:30 KST nightly.
#   설계: docs/plans/toss-tradebot-tobe/rulebook-integration.md
# ─────────────────────────────────────────────────────────────────


class BlueChipRun(Base):
    """5단계 스크리너 run 메타 · 재현성 (git_sha·trigger·기간)."""

    __tablename__ = "blue_chip_runs"

    run_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # YYYYMMDD-HHMMSSK
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(20), default="cron")  # cron | manual | api
    universe_size: Mapped[int] = mapped_column(default=0)
    passed_count: Mapped[int] = mapped_column(default=0)   # 5단계 모두 통과
    partial_count: Mapped[int] = mapped_column(default=0)  # 3+ 통과 (재검토)
    git_sha: Mapped[Optional[str]] = mapped_column(String(40))


class BlueChipCandidate(Base):
    """5단계 필터 결과 스냅샷 · run_id + ticker unique.

    5단계 (사용자 확정 · Q1=C, Q2=모든 섹터, Q3=A, Q4=A):
        1. 시총 ≥ 5조 (10조↑=premium tier)
        2. 업종 (자동 통과 · 정보성 라벨)
        3. 매출·순이익 3년 연속 증가
        4. 연봉 3년 연평균 증가 (턴어라운드)
        5. 월봉 종가 5MA 위 3개월+ 유지
    """

    __tablename__ = "blue_chip_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(20), index=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    sector: Mapped[Optional[str]] = mapped_column(String(60))       # KRX 업종 (참조용 · 필터 안 함)
    market: Mapped[Optional[str]] = mapped_column(String(10))       # KOSPI | KOSDAQ

    # 단계 1 · 시총
    market_cap_krw: Mapped[Optional[float]]                          # 원 단위
    tier: Mapped[str] = mapped_column(String(10), default="none")   # premium (10조+) | entry (5조+) | none
    close_price: Mapped[Optional[float]]

    # 단계 3 · 매출·순이익 3년 연속 증가
    revenue_3y_growing: Mapped[bool] = mapped_column(Boolean, default=False)
    net_income_3y_growing: Mapped[bool] = mapped_column(Boolean, default=False)
    financial_years: Mapped[Optional[str]] = mapped_column(String(30))  # "2023,2024,2025"

    # 단계 4 · 연봉 3년 연평균 증가 (턴어라운드)
    annual_turnaround: Mapped[bool] = mapped_column(Boolean, default=False)
    annual_yoy_pcts: Mapped[Optional[str]] = mapped_column(String(80))  # "0.15,0.22,0.18"

    # 단계 5 · 월봉 5MA 위 3개월+
    monthly_ma5_above: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_ma5_months_above: Mapped[int] = mapped_column(default=0)     # 연속 개월수

    # 종합
    conditions_json: Mapped[Optional[str]] = mapped_column(Text)         # {"1":bool,"2":bool,...}
    pass_count: Mapped[int] = mapped_column(default=0)                   # 5단계 중 통과 수
    overall_pass: Mapped[bool] = mapped_column(Boolean, default=False)   # 5단계 모두 통과
    reject_reasons: Mapped[Optional[str]] = mapped_column(Text)          # 실패 단계 요약

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_bluechip_run_pass", "run_id", "overall_pass"),
        Index("ix_bluechip_ticker_time", "ticker", "created_at"),
    )


# ─────────────────────────────────────────────────────────────────
# Serenity Integration (Phase L1 · 2026-08-02)
#   설계: docs/plans/serenity-integration/02-backend-arch.md
#   원천: vendor/serenity-tracker (yan-labs/serenity-aleabitoreddit · submodule)
#
#   SQLite 호환 재작성 (문서의 Supabase DDL 이관):
#     UUID       → String(36)  · str(uuid.uuid4())
#     TIMESTAMPTZ → DateTime (UTC 저장)
#     JSONB      → Text (json.dumps/loads)
#     TEXT[]     → Text (CSV or JSON serialized)
#     ENUM       → String(20) + application-level check
#     NUMERIC    → Float
#     DATE       → String(10) YYYY-MM-DD
#
#   Supabase 이관 시 database_url() (services/config.py) 만 갱신하면 됨.
# ─────────────────────────────────────────────────────────────────


class SerenityTweet(Base):
    """@aleabitoreddit 트윗 아카이브 append-only."""

    __tablename__ = "serenity_tweets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4 hex
    tweet_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    url: Mapped[str] = mapped_column(String(255))
    posted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    text: Mapped[str] = mapped_column(Text)
    reply_to_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    quoted_id: Mapped[Optional[int]] = mapped_column(Integer)
    metrics: Mapped[Optional[str]] = mapped_column(Text)     # JSON · likes·views·retweets
    raw_json: Mapped[Optional[str]] = mapped_column(Text)    # 원본 트윗 JSON
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    """Extractor 처리 완료 시각. NULL = 미처리 (다음 배치 대상).

    signals 유무 무관 · z.ai 응답 성공 시 마킹 (2026-08-13 무한 루프 사고 대응).
    실패 시 NULL 유지 → 다음 배치에서 재시도.
    """
    # 독약 트윗 방어 (2026-08-14 · task #10)
    # 파싱 영구 실패 트윗이 매일 크론마다 z.ai 재호출 → 비용 낭비 방지.
    # N회 (예: 3회) 연속 실패 시 processed_at 마킹 + 처리 대상 제외.
    extract_failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


# Serenity ENUM 값 (application-level validation)
SERENITY_SENTIMENTS = ("bullish", "bearish", "neutral", "calibration")
SERENITY_THESIS_TYPES = ("new_bottleneck", "reaffirmation", "watchlist", "victory_lap")
SERENITY_EVIDENCE_TYPES = (
    "earnings", "contract", "insider_buy", "sellside_upgrade",
    "macro", "policy", "ownership_disclosure", "watchlist", "other",
)
SERENITY_FINANCING_TIERS = ("S", "A", "B", "C", "D", "F")


class SerenitySignal(Base):
    """트윗별 z.ai 추출 signal · (tweet_id, ticker) unique."""

    __tablename__ = "serenity_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4 hex
    tweet_id: Mapped[int] = mapped_column(Integer, index=True)      # FK → serenity_tweets.tweet_id
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    sentiment: Mapped[str] = mapped_column(String(20))              # SERENITY_SENTIMENTS
    thesis_type: Mapped[Optional[str]] = mapped_column(String(30))  # SERENITY_THESIS_TYPES
    evidence_type: Mapped[Optional[str]] = mapped_column(String(30))  # SERENITY_EVIDENCE_TYPES
    confidence: Mapped[float] = mapped_column(Float)                # 0.00 ~ 1.00
    extracted_reasoning: Mapped[Optional[str]] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_serenity_signal_tweet_ticker", "tweet_id", "ticker", unique=True),
        Index("ix_serenity_signal_ticker_time", "ticker", "extracted_at"),
        Index("ix_serenity_signal_sentiment_time", "sentiment", "extracted_at"),
    )


class DiscoverySerenityScore(Base):
    """티커별 15원칙 스코어 · 매일 갱신 · 단일 행 per ticker."""

    __tablename__ = "discovery_serenity_scores"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 원칙 1 · Bottleneck (0~10)
    bottleneck_score: Mapped[Optional[int]]
    bom_pct: Mapped[Optional[float]]                       # 다운스트림 BOM 내 비율 %
    # 원칙 3 · Contract ARR
    contracted_arr_multiple: Mapped[Optional[float]]
    # 원칙 4 · Mag7 (0~7)
    mag7_customer_count: Mapped[Optional[int]]
    # 원칙 5 · GAAP Margin
    gaap_gross_margin: Mapped[Optional[float]]             # %
    # 원칙 6 · Qualification
    is_pre_ramp: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    # 원칙 7 · Dilution
    active_atm_pct_of_mc: Mapped[Optional[float]]          # > 40 % → auto_avoid 후보
    # 원칙 8 · Financing Tier · SERENITY_FINANCING_TIERS
    financing_tier: Mapped[Optional[str]] = mapped_column(String(2))
    # 원칙 9 · Short Squeeze
    short_interest_pct: Mapped[Optional[float]]
    is_profitable: Mapped[Optional[bool]] = mapped_column(Boolean, default=None)
    # 원칙 11 · Institutional Lag
    institutional_holdings_delta_30d: Mapped[Optional[float]]  # Δ %
    # 원칙 13 · Serenity Conviction Tier · SERENITY_FINANCING_TIERS
    serenity_tier: Mapped[Optional[str]] = mapped_column(String(2))
    # 원칙 14 · Anti-patterns (CSV · e.g. "non_gaap_abuse,sbc_high")
    anti_pattern_flags: Mapped[Optional[str]] = mapped_column(Text)
    # 종합
    total_score: Mapped[int] = mapped_column(default=0)
    auto_avoid: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    domain_tags: Mapped[Optional[str]] = mapped_column(Text)  # CSV · e.g. "optical_cpo,inp_substrates"
    last_signal_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_serenity_score_total_desc", "total_score"),
    )


class SerenityBacktest(Base):
    """signal → 실 주가 (yfinance) 대조 · 매일 재계산 · unique(signal_id).

    Phase L14 v6 (2026-08-04 · Fable 5 6차 GO):
      - return_1d/3d 추가 · 급등주 검증 임계 (+1d/+3d ≥10%)
      - entry_next_open_price · entry_with_slippage_price · gap_next_open_pct
        · entry 기준가 = 다음 거래일 시가 (look-ahead 방지)
        · entry_with_slippage_price 는 참고 컬럼 (v6 D1 · 계산 진입점 아님)
      - return_* 컬럼은 raw 저장 (다음 시가 기준 무조정 · v6 D1 이중 차감 제거 원칙)
      - delisting_flag · signal_date+30d 이후 history 종료 heuristic
      - benchmark_iwm_return_*/spy_return_* · 초과수익 산출용
    """

    __tablename__ = "serenity_backtest"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    signal_date: Mapped[str] = mapped_column(String(10))    # YYYY-MM-DD
    price_at_signal: Mapped[Optional[float]]                # signal_date 종가 (참고)
    # Phase L14 · 진입 실무 (Fable 5 · look-ahead 방지)
    entry_next_open_price: Mapped[Optional[float]]          # 다음 거래일 시가 (실제 매수 가능 지점)
    entry_with_slippage_price: Mapped[Optional[float]]      # 시가 + 1% (참고 · v6 D1 원칙 · 계산 진입 아님)
    gap_next_open_pct: Mapped[Optional[float]]              # (다음 시가 - signal 종가) / signal 종가 × 100
    # Forward return (%) · v6 D1: raw · 다음 거래일 시가 기준 (무조정)
    return_1d: Mapped[Optional[float]]
    return_3d: Mapped[Optional[float]]
    return_5d: Mapped[Optional[float]]
    return_10d: Mapped[Optional[float]]
    return_30d: Mapped[Optional[float]]
    return_60d: Mapped[Optional[float]]
    return_180d: Mapped[Optional[float]]
    # Phase L14 · 상장폐지·티커 소멸 감지 (v6 §2.7 valid 카운트 포함)
    delisting_flag: Mapped[bool] = mapped_column(default=False)
    # Phase L14 · 벤치마크 forward return (IWM · SPY · 초과수익 산출용)
    benchmark_iwm_return_1d: Mapped[Optional[float]]
    benchmark_iwm_return_3d: Mapped[Optional[float]]
    benchmark_iwm_return_5d: Mapped[Optional[float]]
    benchmark_iwm_return_10d: Mapped[Optional[float]]
    benchmark_iwm_return_30d: Mapped[Optional[float]]
    benchmark_spy_return_1d: Mapped[Optional[float]]
    benchmark_spy_return_3d: Mapped[Optional[float]]
    benchmark_spy_return_5d: Mapped[Optional[float]]
    benchmark_spy_return_10d: Mapped[Optional[float]]
    benchmark_spy_return_30d: Mapped[Optional[float]]
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_serenity_backtest_ticker_date", "ticker", "signal_date"),
    )


class SerenityBenchmarkPrice(Base):
    """벤치마크 지수 (IWM · SPY) 일 종가 캐시 · Phase L14 · 2026-08-04.

    목적: 각 first_mention 이벤트마다 동일 signal_date 기준 벤치마크 forward return 계산
    → 초과수익 (signal_return − benchmark_return) 판정.

    구조: (symbol, snapshot_date) 복합 PK · 매일 IWM + SPY 400d 갱신 (KST 00:30).
    """

    __tablename__ = "serenity_benchmark_prices"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)   # IWM · SPY
    snapshot_date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    open: Mapped[Optional[float]]
    close: Mapped[Optional[float]]
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_serenity_benchmark_symbol_date", "symbol", "snapshot_date"),
    )


class SerenityTickerPrice(Base):
    """티커별 최신 종가 스냅샷 · yfinance 배치 (매일 09:30 KST) · Phase L9 · 2026-08-03.

    UX 목적: Ticker Card 상단 "vs prior close · +X.X%" 표시.
    구조: ticker PK · upsert (매일 최신 값으로 덮어씀 · 시계열 필요 시 별도 히스토리 테이블).
    """

    __tablename__ = "serenity_ticker_prices"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (yf 최근 거래일)
    close: Mapped[Optional[float]]
    prior_close: Mapped[Optional[float]]
    vs_prior_close_pct: Mapped[Optional[float]]
    # Phase L10 · Gain since first mention (yfinance 배치 시 first_mention_at 시점 종가 함께 upsert)
    first_mention_date: Mapped[Optional[str]] = mapped_column(String(10))  # 사용한 first_mention YYYY-MM-DD (재조회 트리거)
    first_mention_price: Mapped[Optional[float]]  # 최초 언급일 종가
    gain_since_first_mention_pct: Mapped[Optional[float]]  # (close - first_mention_price)/first_mention_price*100
    yahoo_symbol: Mapped[Optional[str]] = mapped_column(String(20))
    error: Mapped[Optional[str]] = mapped_column(String(200))  # yfinance 실패 사유
    # Phase L13 · yfinance sector/industry (테이블 Industry 컬럼 UX 정확화)
    sector: Mapped[Optional[str]] = mapped_column(String(80))
    industry: Mapped[Optional[str]] = mapped_column(String(120))
    # Phase L14 · 시총 + 유동성 (Hunter 리스크 관리 · RISK-PRINCIPLES §3)
    market_cap: Mapped[Optional[float]]                              # USD · yf.info.marketCap
    market_cap_source: Mapped[Optional[str]] = mapped_column(String(20))  # "yf" / "computed"
    shares_outstanding: Mapped[Optional[float]]                       # yf.info.sharesOutstanding · sanity 검산용 (2026-08-13 MU 사고 대응)
    avg_dollar_volume_20d: Mapped[Optional[float]]                   # USD · Close × Volume 20일 평균
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())



# ─────────────────────────────────────────────────────────────────
# Principles v1.0.2 (2026-08-17) — 저평가 우량주 5원칙 스크리너
#   설계: backend/principles/charter.json
# ─────────────────────────────────────────────────────────────────


class PrinciplesFinancialCache(Base):
    """DART 재무 캐시 (분기별) · 감지 배치가 미수집 분기만 upsert.

    복합 PK (ticker, fiscal_year, fiscal_quarter).
    fiscal_quarter: 1=Q1, 2=Q2, 3=Q3, 4=Q4(사업보고서).
    누적값 저장 (DART 원본) · Q단독 값은 조회 시점에 재계산 (Q4 = 사업보고서 − 3Q 누적).
    """

    __tablename__ = "principles_financial_cache"

    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(primary_key=True)
    fiscal_quarter: Mapped[int] = mapped_column(primary_key=True)  # 1|2|3|4

    corp_code: Mapped[Optional[str]] = mapped_column(String(10))

    # 누적값 (DART 원본 · 손익계산서)
    revenue_cum: Mapped[Optional[float]]
    operating_income_cum: Mapped[Optional[float]]
    net_income_owner_cum: Mapped[Optional[float]]  # 지배주주순이익
    interest_expense_cum: Mapped[Optional[float]]  # 이자보상배율 분모

    # 재무상태표 (분기말 스냅샷)
    total_assets: Mapped[Optional[float]]
    total_liabilities: Mapped[Optional[float]]
    total_equity: Mapped[Optional[float]]

    # 현금흐름표 (누적 · 자기주식 취득 절대값 저장 · v1.0.2)
    buyback_cashflow_cum: Mapped[Optional[float]]

    # 배당 (사업보고서 · Q4 만 유효)
    dividend_per_share: Mapped[Optional[float]]
    dividend_total: Mapped[Optional[float]]

    # 메타
    disclosure_no: Mapped[Optional[str]] = mapped_column(String(20))  # rcept_no
    disclosure_date: Mapped[Optional[str]] = mapped_column(String(10))  # YYYY-MM-DD
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_principles_fincache_ticker_year", "ticker", "fiscal_year"),
    )


class PrinciplesDartRetryQueue(Base):
    """DART 호출 실패 재시도 큐 · rate limit / 5xx / parse fail 대응."""

    __tablename__ = "principles_dart_retry_queue"

    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(primary_key=True)
    fiscal_quarter: Mapped[int] = mapped_column(primary_key=True)
    attempt: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    retry_after: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PrinciplesRun(Base):
    """일일 재계산 배치 헤더 · id (auto) + 통계."""

    __tablename__ = "principles_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(20), default="cron")
    charter_version: Mapped[Optional[str]] = mapped_column(String(20))

    universe_size: Mapped[int] = mapped_column(default=0)
    pass_count: Mapped[int] = mapped_column(default=0)
    fail_count: Mapped[int] = mapped_column(default=0)
    insufficient_count: Mapped[int] = mapped_column(default=0)

    dart_call_count: Mapped[int] = mapped_column(default=0)
    elapsed_sec: Mapped[Optional[float]]


class PrinciplesResult(Base):
    """배치별 종목 판정 · 5원칙 지표 + reasons_json (5원칙 전체 근거)."""

    __tablename__ = "principles_results"

    run_id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    verdict: Mapped[str] = mapped_column(String(20))  # PASS | FAIL | INSUFFICIENT_DATA

    # 산업 분류 (v1.0.2 · 자동감지+override 최종값)
    industry_code: Mapped[Optional[str]] = mapped_column(String(20))
    is_financial_sector: Mapped[bool] = mapped_column(Boolean, default=False)

    # 5원칙 지표
    per_ttm: Mapped[Optional[float]]
    per_operating: Mapped[Optional[float]]
    payout_ratio_3y_avg: Mapped[Optional[float]]
    dividend_years: Mapped[Optional[int]]        # 최근 연속 배당 지급 년수
    dividend_cut: Mapped[Optional[bool]] = mapped_column(Boolean)  # 기간 중 감배 여부
    debt_ratio: Mapped[Optional[float]]
    interest_coverage: Mapped[Optional[float]]

    # 근거 (5원칙 전체 · v1.0.2 reasons_json 개명)
    reasons_json: Mapped[Optional[str]] = mapped_column(Text)
    missing_fields_json: Mapped[Optional[str]] = mapped_column(Text)  # INSUFFICIENT_DATA 결측 항목

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_principles_result_run_verdict", "run_id", "verdict"),
        Index("ix_principles_result_ticker_time", "ticker", "created_at"),
    )
