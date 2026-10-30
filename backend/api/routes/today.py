"""오늘 홈 API (1022-10 4단계) · GET /api/v1/today.

- 저장된 자료 (DB · 로컬 파일) 만 읽는다. 외부 HTTP 0 · 쓰기 0 · 토스·SEC·뉴스 호출 없음.
  (get_toss_client · radar.get_status · positions 의 토스 경로는 쓰지 않는다.)
- 역할은 get_current_role (예외 없음 · 접근 기록 안 씀). 관리자 칸은 비로그인에게 늘 null / 잠금 행.
- 칸마다 _safe · 칸 하나가 실패해도 그 칸만 비고 200.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Awaitable, Callable, Optional, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from sqlalchemy import desc, func, select

from backend.api.auth import get_current_role
from backend.api.schemas import (
    TodayCandidateItem,
    TodayCandidateSection,
    TodayFailure,
    TodayHoldingAlert,
    TodayJudgmentDue,
    TodayResponse,
)
from backend.services.db import get_session

logger = logging.getLogger(__name__)
router = APIRouter()

_NO_STORE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_KST = ZoneInfo("Asia/Seoul")

# 손절 근접 기준 % — 이 값 한 곳에서만 정한다 (화면 문구도 응답의 near_stop_pct 를 쓴다) · env TODAY_NEAR_STOP_PCT 로 바꿈
NEAR_STOP_PCT_DEFAULT = 5.0

# 칸마다 건수 상한
_LIMIT_FAILURES = 10
_LIMIT_JUDGMENTS = 5
_LIMIT_ALERTS = 10
_LIMITS = {"watchlist": 5, "powderkeg": 5, "meme": 5, "activist": 5, "crazy": 5, "moonshot": 3, "biotech": 5}

# 이 칸이 덮는 범위 — 알림 기록(NotificationLog)에 「…실패」 제목으로 남는 작업만 (1022-10 4단계 확인 결과)
#  · scheduler/cron.py _alert_job_failure : 알림 하루 요약 · 토스 종목 코드 · 토스 보유 기록(국내·미국) · 판정·후보 결과 계산 · Crazy · Moonshot · 섹터 리더(09:05·17:05)
#  · discovery/serenity/scheduler.py _notify_job_result : Serenity 수집·추출·점수 작업
#  · scripts/biotech_h69_aact_weekly.py : 임상시험 주간 자료
#  없음(로그 파일에만 남음): 밈 워치 · Watchlist · 화약고 · 5원칙 · 스나이퍼
_FAILURES_SCOPE = ("알림으로 남는 실패만 보입니다 · 토스 기록·결과 계산·Crazy·Moonshot·섹터 리더·Serenity·바이오 매일 작업·임상시험 주간 자료 작업. "
                   "밈 워치·Watchlist·화약고·5원칙·스나이퍼 작업의 실패는 알림이 없어 여기에 보이지 않습니다.")

T = TypeVar("T")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def near_stop_pct() -> float:
    try:
        v = float(os.environ.get("TODAY_NEAR_STOP_PCT", "").strip() or NEAR_STOP_PCT_DEFAULT)
    except ValueError:
        return NEAR_STOP_PCT_DEFAULT
    return v if v > 0 else NEAR_STOP_PCT_DEFAULT


def _kst_midnight_utc(today: date) -> datetime:
    """오늘 KST 자정 → UTC naive (DB 시각 기준)."""
    return datetime.combine(today, time(0), tzinfo=_KST).astimezone(timezone.utc).replace(tzinfo=None)


def _f(v, nd: int = 1) -> str:
    return f"{v:.{nd}f}" if v is not None else "-"


async def _safe(fn: Callable[[], Awaitable[T]], default: T, name: str) -> T:
    """한 칸이 실패해도 그 칸만 default."""
    try:
        return await fn()
    except Exception as e:  # noqa: BLE001 — 칸 하나 때문에 화면 전체가 죽으면 안 됨
        logger.warning("[today] %s 읽기 실패: %s", name, e)
        return default


# ─── 관리자 칸 ───────────────────────────────────────────────────────────

async def _safety() -> Optional[dict]:
    """/sniper/status 와 같은 값 (env·파일·DB 만)."""
    from backend.api.routes.sniper import sniper_status

    st = await sniper_status()
    return {k: st[k] for k in ("live_enabled", "sniper_enabled", "kill_switch_active", "order_target")}


async def _failures(today: date) -> list[TodayFailure]:
    """오늘(KST) 알림 기록 중 제목에 「실패」 · result 로 거르지 않음 (skipped 도 셈) · dedupe_key 로 묶음."""
    from backend.services.models import NotificationLog as L

    async with get_session() as s:
        rows = (await s.execute(select(L).where(L.created_at >= _kst_midnight_utc(today), L.title.like("%실패%"))
                                .order_by(desc(L.created_at), desc(L.id)).limit(500))).scalars().all()
    groups: dict[str, TodayFailure] = {}
    for r in rows:  # 최근 순이라 먼저 만난 행이 그 묶음의 대표
        g = groups.get(r.dedupe_key)
        if g is None:
            groups[r.dedupe_key] = TodayFailure(title=r.title, category=r.category,
                                                at=r.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"), count=1)
        else:
            g.count += 1
    return list(groups.values())[:_LIMIT_FAILURES]


async def _judgments_due(today: date) -> list[TodayJudgmentDue]:
    """판정 결과 계산 대상(outcomes._judgment_due) 중 기한이 오늘 이전인 것.

    기한 = outcomes 의 기준일(base_date → 직전 평일) + horizon_days. 실제 계산은 만기 이후 첫 봉이라 이 기한은 최소 날짜.
    """
    from backend.services.models import UserJudgment
    from backend.services.outcomes import _judgment_due, _weekday_on_or_before, base_date, market_of

    async with get_session() as s:
        rows = (await s.execute(select(UserJudgment).where(UserJudgment.superseded_by_id.is_(None),
                                                           UserJudgment.result_at_horizon.is_(None))
                                .order_by(UserJudgment.ts).limit(1000))).scalars().all()
    out: list[TodayJudgmentDue] = []
    for j in rows:
        if not _judgment_due(j) or j.ts is None:
            continue
        due = _weekday_on_or_before(base_date(j.ts, market_of(j.ticker))) + timedelta(days=j.horizon_days or 0)
        if due <= today:
            out.append(TodayJudgmentDue(id=j.id, ticker=j.ticker, strategy=j.strategy, ts=j.ts.isoformat(),
                                        due_date=due.isoformat(), overdue=due < today))
    out.sort(key=lambda x: (x.due_date, x.id))
    return out[:_LIMIT_JUDGMENTS]


async def _holding_alerts(today: date) -> list[TodayHoldingAlert]:
    """저장된 보유(HoldingSnapshot) 기준 · 토스 실시간 호출 없음."""
    from backend.api.routes.positions import _build_exit_plan, _latest_judgment
    from backend.services.models import HoldingSnapshot as H

    pct = near_stop_pct()
    alerts: list[TodayHoldingAlert] = []
    async with get_session() as s:
        latest = (select(H.symbol, H.market, func.max(H.trade_date).label("d")).where(H.kind == "holding")
                  .group_by(H.symbol, H.market).subquery())
        holdings = (await s.execute(select(H).join(latest, (H.symbol == latest.c.symbol) & (H.market == latest.c.market)
                                                   & (H.trade_date == latest.c.d))
                                    .where(H.kind == "holding", H.qty > 0).order_by(H.symbol))).scalars().all()
        for h in holdings:
            candle = (await s.execute(select(H.close).where(H.kind == "candle", H.symbol == h.symbol, H.market == h.market,
                                                            H.trade_date == h.trade_date, H.close.is_not(None))
                                      .order_by(desc(H.id)).limit(1))).scalar()
            price, source = (candle, "candle") if candle is not None else (h.close, "holding")
            j = await _latest_judgment(s, h.symbol)
            plan = _build_exit_plan(j, price)
            inv = plan.invalidation_price
            gap = round((price / inv - 1) * 100, 2) if price is not None and inv else None
            base = dict(symbol=h.symbol, market=h.market, price=price, price_date=h.trade_date.isoformat(),
                        price_source=source, invalidation_price=inv, gap_pct=gap, currency=h.currency)
            if price is not None and inv:
                if plan.trigger_hit and plan.trigger_reason == "invalidation_hit":
                    alerts.append(TodayHoldingAlert(kind="stop_hit", **base))
                elif (price / inv - 1) * 100 <= pct + 1e-9:  # 손절가 < 가격 ≤ 손절가 × (1 + pct/100)
                    alerts.append(TodayHoldingAlert(kind="stop_near", **base))
            if plan.deadline is not None:
                dl = plan.deadline.replace(tzinfo=timezone.utc).astimezone(_KST).date() if plan.deadline.tzinfo is None \
                    else plan.deadline.astimezone(_KST).date()
                if dl <= today:
                    alerts.append(TodayHoldingAlert(kind="deadline", deadline=dl.isoformat(), **base))
    order = {"stop_hit": 0, "stop_near": 1, "deadline": 2}
    alerts.sort(key=lambda a: (order[a.kind], a.gap_pct if a.gap_pct is not None else 1e9, a.symbol))
    return alerts[:_LIMIT_ALERTS]


# ─── 후보 섹션 ───────────────────────────────────────────────────────────

async def _watchlist(today: date):
    from backend.discovery.watchlist.store import next_trade_date
    from backend.services.models import Watchlist as W

    n = _LIMITS["watchlist"]
    async with get_session() as s:
        td = next_trade_date(_now_utc())
        has = (await s.execute(select(W.id).where(W.trade_date == td).limit(1))).first()
        if not has:
            td = (await s.execute(select(func.max(W.trade_date)))).scalar()
        if not td:
            return None, []
        rows = (await s.execute(select(W).where(W.trade_date == td).order_by(W.rank).limit(n))).scalars().all()
    return td, [TodayCandidateItem(ticker=r.ticker, name=r.name, note=f"{r.rank}위 · 점수 {_f(r.composite_score)}")
                for r in rows]


async def _powderkeg(today: date):
    from backend.services.models import PowderKegEvent as E

    async with get_session() as s:
        rows = (await s.execute(select(E).where(E.detected_at >= _kst_midnight_utc(today))
                                .order_by(desc(E.detected_at)).limit(_LIMITS["powderkeg"]))).scalars().all()
    return (today.isoformat() if rows else None), [TodayCandidateItem(ticker=r.ticker, note=(r.title or "")[:120]) for r in rows]


def _server_tz():
    """서버 시스템 시간대 · 밈 알림은 datetime.now() (서버 로컬 시각 · alert.py) 로 저장된다."""
    return datetime.now().astimezone().tzinfo


async def _meme(today: date):
    from backend.services.models import MemeAlertHistory as A

    local = _server_tz()
    # KST 자정을 서버 로컬 naive 시각으로 바꿔 비교 (meme_watch.py 와 같은 로컬 기준 · 1022-10 4단계 Fable -11)
    cut = datetime.combine(today, time.min, tzinfo=_KST).astimezone(local).replace(tzinfo=None)
    async with get_session() as s:
        rows = (await s.execute(select(A).where(A.triggered_at >= cut)
                                .order_by(desc(A.triggered_at)).limit(100))).scalars().all()
    seen: set[str] = set()
    items: list[TodayCandidateItem] = []
    for r in rows:  # 종목마다 가장 최근 알림 1건
        if r.ticker in seen:
            continue
        seen.add(r.ticker)
        kst = r.triggered_at.replace(tzinfo=local).astimezone(_KST)
        items.append(TodayCandidateItem(ticker=r.ticker, note=f"{r.alert_type} 알림 {kst:%H:%M}"))
        if len(items) >= _LIMITS["meme"]:
            break
    return (today.isoformat() if items else None), items


async def _activist(today: date):
    """activist_state.json 읽기만 (SEC 보충 호출 없음)."""
    from backend.discovery.activist.state import ActivistState

    evs = ActivistState.load().recent_events(_LIMITS["activist"])
    items = [TodayCandidateItem(ticker=e.target_ticker or None, name=(e.target_desc or None),
                                note=f"{e.form} · {e.filer_name} · {e.intensity_label}") for e in evs]
    return (max((e.filing_date or "" for e in evs), default="") or None), items


async def _crazy(today: date):
    from backend.services.models import CrazyPick as P

    async with get_session() as s:
        d = (await s.execute(select(func.max(P.pick_date)))).scalar()
        if not d:
            return None, []
        rows = (await s.execute(select(P).where(P.pick_date == d).order_by(P.rank).limit(_LIMITS["crazy"]))).scalars().all()
    return d, [TodayCandidateItem(ticker=r.ticker, name=r.company_name, note=f"{r.rank}위 · 점수 {_f(r.composite_score)}")
               for r in rows]


async def _moonshot(today: date):
    from backend.services.models import MoonshotPick as P

    async with get_session() as s:
        d = (await s.execute(select(func.max(P.pick_date)))).scalar()
        if not d:
            return None, []
        rows = (await s.execute(select(P).where(P.pick_date == d).order_by(P.rank).limit(_LIMITS["moonshot"]))).scalars().all()
    return d, [TodayCandidateItem(ticker=r.ticker, name=r.company_name, note=f"{r.rank}위 · 점수 {_f(r.composite_score)}")
               for r in rows]


async def _biotech(today: date):
    """레이더 CSV (biotech 라우트와 같은 파일 찾기 · 읽기만)."""
    import csv

    from backend.api.routes.biotech import _latest_radar_csv

    path = _latest_radar_csv()
    if not path or not path.exists():
        return None, []
    items: list[TodayCandidateItem] = []
    with path.open(encoding="utf-8") as f:
        for idx, row in enumerate(csv.DictReader(f), 1):
            if idx > _LIMITS["biotech"]:
                break
            items.append(TodayCandidateItem(ticker=(row.get("ticker") or "").strip().upper() or None,
                                            note=f"{idx}위 · 점수 {_f(float(row.get('score') or 0))} · 시점 {row.get('time_state') or '-'}"))
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat(), items


# 섹션 순서: (source, label, link, 읽기 함수, 관리자 전용)
_SECTIONS = [
    ("watchlist", "Watchlist", "/watchlist", _watchlist, False),
    ("powderkeg", "화약고 이벤트", "/powderkeg", _powderkeg, False),
    ("meme", "밈 워치 알림", "/lab/meme-watch", _meme, False),
    ("activist", "행동주의 공시", "/activist-radar", _activist, False),
    ("crazy", "Crazy 후보", "/lab/crazy", _crazy, True),
    ("moonshot", "Moonshot 후보", "/lab/moonshot", _moonshot, True),
    ("biotech", "바이오 레이더", "/biotech", _biotech, True),
]


# ─── 라우트 ──────────────────────────────────────────────────────────────

@router.get("", response_model=TodayResponse)
async def get_today(response: Response, role: str = Depends(get_current_role)) -> TodayResponse:
    response.headers.update(_NO_STORE)
    admin = role == "admin"
    now = _now_utc()
    today = now.astimezone(_KST).date()

    candidates: list[TodayCandidateSection] = []
    for source, label, link, fn, admin_only in _SECTIONS:
        if admin_only and not admin:  # 자료 유무와 상관없이 고정 잠금 행
            candidates.append(TodayCandidateSection(source=source, label=label, link=link, locked=True))
            continue
        as_of, items = await _safe(lambda fn=fn: fn(today), (None, []), source)
        candidates.append(TodayCandidateSection(source=source, label=label, link=link, as_of=as_of, items=items))

    return TodayResponse(
        is_admin=admin,
        fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        today_kst=today.isoformat(),
        safety=await _safe(_safety, None, "safety"),
        failures=await _safe(lambda: _failures(today), [], "failures") if admin else None,
        failures_scope=_FAILURES_SCOPE,
        judgments_due=await _safe(lambda: _judgments_due(today), [], "judgments_due") if admin else None,
        holding_alerts=await _safe(lambda: _holding_alerts(today), [], "holding_alerts") if admin else None,
        near_stop_pct=near_stop_pct(),
        candidates=candidates,
    )
