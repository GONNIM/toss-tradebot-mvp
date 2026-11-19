"""큰손 발자국 새 표 4개 (1119-03 ① · 기획서 3-2 · 3-7) · create_all 로 생김 · 기존 표 열 추가 없음.

표: signal_event · signal_source · signal_outcome · investor_flow_daily.
services/models.py 맨 아래에서 이 모듈을 불러와 create_all 이 함께 만든다 (계획 실행기 표와 같은 방식).
공개 저장소: 실제 종목 · 보고자 이름은 코드에 두지 않는다.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.services.models import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SignalEvent(Base):
    """사건 하나 = 한 줄 (같은 종목 첫 신호 날짜부터 5거래일 안 신호는 한 사건)."""

    __tablename__ = "signal_event"
    __table_args__ = (
        UniqueConstraint("market", "code", "first_signal_date", name="uq_signal_event_first"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(4))                  # KR | US
    code: Mapped[str] = mapped_column(String(16), index=True)
    first_signal_date: Mapped[date] = mapped_column(Date)
    establish_dates: Mapped[Optional[str]] = mapped_column(Text)    # JSON {유형: 성립 날짜}
    state: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SignalSource(Base):
    """원 공시 한 건 = 한 줄 · 진입 전 알던 내용만 판정에 쓰고 최종본은 표시용."""

    __tablename__ = "signal_source"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    rcept_no: Mapped[str] = mapped_column(String(32), unique=True)
    event_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    rcept_date: Mapped[date] = mapped_column(Date)
    known_at_entry: Mapped[Optional[str]] = mapped_column(Text)     # JSON 매매일 · 매매일 종가 · 수량 · 단가 · 취득 방법
    final_rcept_no: Mapped[Optional[str]] = mapped_column(String(32))
    final_content: Mapped[Optional[str]] = mapped_column(Text)      # 표시용 (판정 금지)
    later_events: Mapped[Optional[str]] = mapped_column(Text)       # JSON 뒤에 생긴 정정 · 철회 · 곧 매도
    first_version_missing: Mapped[bool] = mapped_column(Boolean, default=False)   # 「첫 판 없음」 (Fable 권고 ㄱ)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SignalOutcome(Base):
    """성립 하나 = 성적 한 줄 · (시장 · 코드 · 유형 · 진입 날짜 · 기간) 고유 (Fable 조건 마)."""

    __tablename__ = "signal_outcome"
    __table_args__ = (
        UniqueConstraint("market", "code", "signal_type", "entry_date", "horizon_days", name="uq_signal_outcome_key"),
        Index("idx_signal_outcome_type_entry", "signal_type", "entry_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    market: Mapped[str] = mapped_column(String(4))
    code: Mapped[str] = mapped_column(String(16))
    signal_type: Mapped[str] = mapped_column(String(16))
    horizon_days: Mapped[int] = mapped_column(Integer)
    entry_date: Mapped[date] = mapped_column(Date)
    entry_price: Mapped[Optional[float]] = mapped_column(Float)
    exit_price: Mapped[Optional[float]] = mapped_column(Float)
    return_pct: Mapped[Optional[float]] = mapped_column(Float)
    index_return_pct: Mapped[Optional[float]] = mapped_column(Float)
    excess_pct: Mapped[Optional[float]] = mapped_column(Float)
    cost_pct: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))                 # ok | delisted | halted | no_price
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class InvestorFlowDaily(Base):
    """토스 투자자별 순위의 외국인 · 기관 순매수 · 순매도 하루 1회 저장분 (㉤) · ⑤ 전에는 어디서도 읽지 않는다."""

    __tablename__ = "investor_flow_daily"
    __table_args__ = (
        UniqueConstraint("trade_date", "investor", "side", "ticker", name="uq_investor_flow_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(10))
    investor: Mapped[str] = mapped_column(String(12))               # foreigner | institution
    side: Mapped[str] = mapped_column(String(4))                    # buy | sell
    ticker: Mapped[str] = mapped_column(String(10))
    rank: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Optional[float]] = mapped_column(Float)          # 순매수 · 순매도 거래액 (원)
    ranked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # 토스 rankedAt (UTC naive)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
