"""계획 실행기 표 · 계획서 2-2절 (create_all 로 생김 · 기존 표 열 추가 없음).

표 11개 + 하트비트 1행 표(9절 「DB 한 행」).
services/models.py 맨 아래에서 이 모듈을 불러와 create_all 이 함께 만든다.
공개 저장소: 종목 · 금액 · 계좌 값은 코드에 두지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.services.models import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Plan(Base):
    __tablename__ = "plan"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(8), index=True)           # paper | live | test
    source: Mapped[str] = mapped_column(String(8), default="manual")   # manual | draft | adopt
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    state: Mapped[str] = mapped_column(String(16), index=True)
    prev_state: Mapped[Optional[str]] = mapped_column(String(16))      # HALTED 재개 때 돌아갈 상태
    halted_reason: Mapped[Optional[str]] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1)          # 값이 바뀔 때마다 1 늘어남 (4-2-1)
    content_hash: Mapped[str] = mapped_column(String(64), default="")  # 승인 대상 값의 내용 해시
    params_json: Mapped[str] = mapped_column(Text, default="{}")       # 가격 · 수량 · 날짜 · 사다리 폭 · 인수 값
    avg_price: Mapped[Optional[float]] = mapped_column(Float)          # 기준 평균가
    peak_price: Mapped[Optional[float]] = mapped_column(Float)         # 정규장 1분봉 종가 최고값 (7-3)
    pending_peak: Mapped[Optional[float]] = mapped_column(Float)       # 10% 넘게 튄 값 · 보류 중
    plan_qty_hint: Mapped[int] = mapped_column(Integer, default=0)     # 인수 수량(인수 계획) 시작값
    approved_by: Mapped[Optional[str]] = mapped_column(String(40))     # 대표 | Aside(대표 지시)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    timestop_stage: Mapped[str] = mapped_column(String(12), default="none")  # none | lift | clean | stopped
    timestop_lift_session: Mapped[Optional[str]] = mapped_column(String(10))  # 끌어올리기를 한 거래일
    adopt_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    # 실행기만 쓰는 값(현재가 · 실제 다리 · 주문 번호 판 · 거절 횟수 …) · 화면이 고치는 params_json 과 칸을 나눠 서로 덮어쓰지 않는다
    runtime_json: Mapped[str] = mapped_column(Text, default="{}")
    # 낙관적 잠금 · 화면(승인 · 정지 · 수정)과 실행기가 같은 계획을 동시에 고치면 한쪽이 StaleDataError 로 다시 읽는다
    row_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __mapper_args__ = {"version_id_col": row_version}


class PlanLeg(Base):
    __tablename__ = "plan_leg"
    __table_args__ = (Index("ix_plan_leg_plan_status", "plan_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(8))                       # buy | sl | tp1
    seq: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(8), default="cond")       # cond(조건주문) | limit(일반 지정가)
    side: Mapped[str] = mapped_column(String(4), default="SELL")
    toss_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(40), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    watch_price: Mapped[Optional[float]] = mapped_column(Float)
    order_price: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="WATCHING")  # WATCHING | TRIGGERED | FILLED | CANCELED | EXPIRED | UNCERTAIN(확인 대기)
    tag: Mapped[str] = mapped_column(String(12), default="")           # regular | offhours | trail | lift | emergency
    expire_date: Mapped[Optional[str]] = mapped_column(String(10))
    error_count: Mapped[int] = mapped_column(Integer, default=0)       # 같은 다리 오류 3번 → HALTED
    acct_before: Mapped[Optional[int]] = mapped_column(Integer)        # 매수를 내기 직전 계좌 보유 (결과를 모를 때 체결 확인)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PlanFill(Base):
    __tablename__ = "plan_fill"
    __table_args__ = (Index("ux_plan_fill_ref", "order_ref", "fill_seq", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    order_ref: Mapped[str] = mapped_column(String(64))                 # 이 계획이 낸 주문 번호 · 고유 키
    fill_seq: Mapped[int] = mapped_column(Integer, default=0)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlanSellReservation(Base):
    """매도 예약 장부 · 실제 접수된 매도 주문만 (5절 4항)."""

    __tablename__ = "plan_sell_reservation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(16))   # triggered | tp1_watch | time_stop | immediate
    qty: Mapped[int] = mapped_column(Integer)       # 남은 수량
    order_ref: Mapped[Optional[str]] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    leg_seq: Mapped[Optional[int]] = mapped_column(Integer)          # 줄였던 손절 다리 번호 (되돌릴 때)
    order_price: Mapped[Optional[float]] = mapped_column(Float)      # 접수된 지정가
    restore_watch: Mapped[Optional[float]] = mapped_column(Float)    # 취소 뒤 되돌릴 다리 값
    restore_order: Mapped[Optional[float]] = mapped_column(Float)
    below_since: Mapped[Optional[datetime]] = mapped_column(DateTime)  # 현재가가 주문가 아래로 내려간 때 (10초 다시 내기)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(40))   # 낸 주문의 고정 열쇠 (불확실한 실패 뒤 찾을 때)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False)      # 낸 결과가 불확실 (번호 없음 · 시간 초과) · 확인 대기
    acct_before: Mapped[Optional[int]] = mapped_column(Integer)          # 매도를 내기 직전 계좌 보유 (결과를 모를 때 체결 확인)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlanEvent(Base):
    __tablename__ = "plan_event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default="")


class PlanRequest(Base):
    """화면 요청 · tradebot-api 는 토스를 부르지 않고 여기에 남기고 실행기가 처리한다."""

    __tablename__ = "plan_request"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(24))     # approve | adopt | resume | halt | adopt_cancel | timestop_stop | cancel
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # pending | done | failed
    requested_by: Mapped[str] = mapped_column(String(40), default="")
    result: Mapped[Optional[str]] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class PlanLegPending(Base):
    """다리 수정 중 기록 (7-2) · 응답으로 새 번호를 받으면 지운다."""

    __tablename__ = "plan_leg_pending"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    leg_id: Mapped[int] = mapped_column(Integer, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    old_toss_id: Mapped[Optional[str]] = mapped_column(String(64))
    new_watch: Mapped[float] = mapped_column(Float)
    new_order: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    client_order_id: Mapped[Optional[str]] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlanPaperPosition(Base):
    __tablename__ = "plan_paper_position"

    plan_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)


class PlanPaperOrder(Base):
    """모의 가상 주문 (조건주문 · 지정가) · 토스 주문 API 와 무관."""

    __tablename__ = "plan_paper_order"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(8))        # cond | limit
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[int] = mapped_column(Integer)
    watch_price: Mapped[Optional[float]] = mapped_column(Float)
    order_price: Mapped[float] = mapped_column(Float)
    direction: Mapped[Optional[str]] = mapped_column(String(8))  # le(이하) | ge(이상) · 등록 순간 현재가가 정함
    status: Mapped[str] = mapped_column(String(10), default="OPEN", index=True)  # OPEN | TRIGGERED | FILLED | CANCELED
    client_order_id: Mapped[Optional[str]] = mapped_column(String(40))
    child_id: Mapped[Optional[int]] = mapped_column(Integer)  # 조건이 닿아 생긴 가상 지정가 번호
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlanSwitchAudit(Base):
    __tablename__ = "plan_switch_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    switch: Mapped[str] = mapped_column(String(8))      # live | paper
    old: Mapped[bool] = mapped_column(Boolean)
    new: Mapped[bool] = mapped_column(Boolean)
    actor: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(200), default="")


class PlanConfirmChallenge(Base):
    """텔레그램 1회용 확인 코드 · 해시(HMAC)만 저장 (4-2 · 4-2-1)."""

    __tablename__ = "plan_confirm_challenge"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(16), index=True)  # live_on | approve | adopt | resume
    plan_id: Mapped[Optional[int]] = mapped_column(Integer)
    revision: Mapped[Optional[int]] = mapped_column(Integer)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    code_hmac: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    invalid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)   # 틀린 코드 입력 수 (실패 누적에 합산)


class PlanExecutorHeartbeat(Base):
    __tablename__ = "plan_executor_heartbeat"

    id: Mapped[int] = mapped_column(primary_key=True)           # 항상 1
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ws_status: Mapped[str] = mapped_column(String(16), default="none")
    last_resync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    stale_alerted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)  # 같은 끊김에 반복 안 함
    recovered_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 화면용 마지막 값 (실행기가 남김 · 화면 서버는 토스를 부르지 않는다)
    toss_status: Mapped[str] = mapped_column(String(8), default="none")       # none | ok | error
    toss_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    buying_power_usd: Mapped[Optional[float]] = mapped_column(Float)
    buying_power_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    app_conds_json: Mapped[Optional[str]] = mapped_column(Text)               # {종목: 계획 밖(앱) 조건주문 수}
    app_conds_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class PlanOrderBook(Base):
    """주문 장부 · 토스로 보낼 때마다 한 줄 (결과를 모르는 주문을 한 곳에서 대조 · orderbook.py)."""

    __tablename__ = "plan_order_book"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    client_order_id: Mapped[str] = mapped_column(String(48), index=True)
    kind: Mapped[str] = mapped_column(String(8))                  # cond(조건주문) | limit(일반)
    role: Mapped[str] = mapped_column(String(8))                  # buy | sl | tp1 | sell
    side: Mapped[str] = mapped_column(String(4), default="SELL")
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[Optional[float]] = mapped_column(Float)
    watch_price: Mapped[Optional[float]] = mapped_column(Float)
    toss_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer)     # 자식 주문이면 부모 조건주문 줄
    replaces_id: Mapped[Optional[int]] = mapped_column(Integer)   # 수정이면 바꾸려던 옛 줄 (옛 줄은 닫히기 전까지 살아 있는 것으로 둔다)
    leg_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    reservation_id: Mapped[Optional[int]] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(14), default="sent_unknown", index=True)  # sent_unknown | open | closed | not_created | needs_human
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    filled_qty: Mapped[int] = mapped_column(Integer, default=0)
    acct_before: Mapped[Optional[int]] = mapped_column(Integer)   # 매수를 보낼 때 계좌 보유 (경보에만 쓴다 · 체결 근거 아님)
    note: Mapped[Optional[str]] = mapped_column(Text)             # 사유 · 후보 · 사람의 결정 (JSON)
