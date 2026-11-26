"""큰손 발자국 ② · 국내 공시 수집 새 표 (1119-03 · 기획서 ② · 조건 라).

표: dart_insider_row · dart_majorstock_row · dart_doc_cache · dart_collect_cursor · big_hands_price_daily.
services/models.py 맨 아래에서 이 모듈을 불러와 create_all 이 함께 만든다. 기존 표에 칸을 더하지 않는다.
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


class DartInsiderRow(Base):
    """임원 · 주요주주 소유보고(elestock) 한 줄. 같은 접수번호에 줄이 여럿일 수 있어 row_key 가 고유.

    processed_at: 원문 단계(취득 방법 · 단가 읽기)를 끝냈거나 원문이 필요 없다고 정한 시각. NULL 이면 아직.
    """

    __tablename__ = "dart_insider_row"
    __table_args__ = (Index("idx_dart_insider_corp_date", "corp_code", "rcept_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    row_key: Mapped[str] = mapped_column(String(40), unique=True)
    rcept_no: Mapped[str] = mapped_column(String(32), index=True)
    corp_code: Mapped[str] = mapped_column(String(8))
    stock_code: Mapped[Optional[str]] = mapped_column(String(10))
    rcept_date: Mapped[date] = mapped_column(Date)
    report_nm: Mapped[Optional[str]] = mapped_column(String(200))   # 목록에서 얻을 때만 (정정 · 철회 표시)
    repror: Mapped[str] = mapped_column(String(100))                # 보고자
    position: Mapped[Optional[str]] = mapped_column(String(100))    # 직위
    is_main_holder: Mapped[Optional[str]] = mapped_column(String(40))   # 주요주주 여부 칸 원문
    hold_qty: Mapped[Optional[float]] = mapped_column(Float)
    change_qty: Mapped[Optional[float]] = mapped_column(Float)
    hold_rate: Mapped[Optional[float]] = mapped_column(Float)
    change_rate: Mapped[Optional[float]] = mapped_column(Float)
    trade_date: Mapped[Optional[date]] = mapped_column(Date)        # 원문에서 읽은 매매일
    method: Mapped[Optional[str]] = mapped_column(String(60))       # 원문에서 읽은 취득 방법
    unit_price: Mapped[Optional[float]] = mapped_column(Float)      # 원문에서 읽은 단가
    doc_status: Mapped[Optional[str]] = mapped_column(String(16))   # none(필요 없음) | parsed | unparsed | missing
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DartMajorstockRow(Base):
    """대량보유(5%) 공시(majorstock) 한 줄."""

    __tablename__ = "dart_majorstock_row"
    __table_args__ = (Index("idx_dart_major_corp_date", "corp_code", "rcept_date"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    row_key: Mapped[str] = mapped_column(String(40), unique=True)
    rcept_no: Mapped[str] = mapped_column(String(32), index=True)
    corp_code: Mapped[str] = mapped_column(String(8))
    stock_code: Mapped[Optional[str]] = mapped_column(String(10))
    rcept_date: Mapped[date] = mapped_column(Date)
    report_nm: Mapped[Optional[str]] = mapped_column(String(200))
    report_tp: Mapped[Optional[str]] = mapped_column(String(40))
    repror: Mapped[str] = mapped_column(String(100))
    hold_qty: Mapped[Optional[float]] = mapped_column(Float)
    change_qty: Mapped[Optional[float]] = mapped_column(Float)
    hold_rate: Mapped[Optional[float]] = mapped_column(Float)
    change_rate: Mapped[Optional[float]] = mapped_column(Float)
    report_resn: Mapped[Optional[str]] = mapped_column(String(200))
    purpose: Mapped[Optional[str]] = mapped_column(String(16))      # management | simple | NULL(모름) · 원문에서 읽음
    doc_status: Mapped[Optional[str]] = mapped_column(String(16))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DartDocCache(Base):
    """공시 원문 캐시 · 접수번호가 열쇠. 같은 접수번호는 다시 받지 않는다 (호출 수 줄임)."""

    __tablename__ = "dart_doc_cache"

    rcept_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(12))                 # ok | missing(원문 없음) | error
    body_text: Mapped[Optional[str]] = mapped_column(Text)          # 태그를 걷어 낸 글 (최대 20만 자)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class DartCollectCursor(Base):
    """회사 · 종류별 수집 처리 표시 (과거 채우기가 다시 돌아도 같은 회사를 다시 부르지 않음)."""

    __tablename__ = "dart_collect_cursor"

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12), primary_key=True)  # elestock | majorstock
    rows_seen: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class PriceDaily(Base):
    """장부 종목 일봉 · 지수 일봉 저장 표 (조건 라 · 이번 묶음은 표만 · 채우는 코드는 첫 성적표 묶음).

    kind: stock | index. 토스 가격이라 로그인 화면에서만 쓴다(결정 ㉥).
    """

    __tablename__ = "big_hands_price_daily"
    __table_args__ = (
        UniqueConstraint("kind", "code", "trade_date", "adjusted", name="uq_big_hands_price_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(6))
    code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date)
    adjusted: Mapped[bool] = mapped_column(Boolean, default=True)   # 수정주가 여부
    open: Mapped[Optional[float]] = mapped_column(Float)
    high: Mapped[Optional[float]] = mapped_column(Float)
    low: Mapped[Optional[float]] = mapped_column(Float)
    close: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[float]] = mapped_column(Float)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
