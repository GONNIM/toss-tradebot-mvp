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
    # 1105-05 · kill_switch_sell_allowed (홈 「긴급 정지」 줄을 새 진입만 / 모든 주문으로 나눔)
    return {k: st[k] for k in ("live_enabled", "sniper_enabled", "kill_switch_active", "kill_switch_sell_allowed", "order_target")}


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
# 1108-01 · 후보 줄은 「이름 · 왜 올라왔는지 한 줄」로 통일한다 (사용자 지시 11/08).
#   점수는 「무엇을 본 점수 N/100」 으로 보인다. 환산: Watchlist·바이오 0~1 → ×100 · Crazy·Moonshot 은 이미 0~100.
#   영어 약어(BLAZING·13D·D002·STRONG 등)는 한국어 뜻으로 바꾼다. 판정·점수 계산은 바꾸지 않는다.

def _score100(v, scale: float) -> str:
    """점수를 0~100 정수 글자로. scale = 원래 만점 (1 또는 100)."""
    try:
        n = round(float(v) / scale * 100)
    except (TypeError, ValueError):
        return "-"
    return str(max(0, min(100, n)))


# Watchlist 칸 이름 → 사용자 말 (scoring.py 칸 5개)
_WATCH_CELL = (
    ("news_score", "뉴스가 많이 나옴"),
    ("board_score", "개인 투자자 관심이 큼"),
    ("youtube_score", "유튜브 영상이 많음"),
    ("event_score", "공시·정책 소식이 있음"),
    ("prev_day_score", "전날 거래가 늘어남"),
)


def _watch_reason(r) -> Optional[str]:
    """가장 강한 칸 하나를 이유로. 모두 0 이면 None."""
    best = max(_WATCH_CELL, key=lambda c: getattr(r, c[0], 0) or 0)
    return best[1] if (getattr(r, best[0], 0) or 0) > 0 else None


_MEME_ALERT = {
    "BLAZING": "급등 신호 여러 개가 한꺼번에 켜짐",
    "ERUPTING": "지금 가격·거래가 폭등하는 중",
}


def _kr_form(form: str) -> Optional[str]:
    """국내 지분 공시·미국 Form 4 양식 → 쉬운 이름. 모르면 None."""
    f = form or ""
    if f.startswith("대량보유"):
        if "MANAGEMENT" in f:
            base = "5% 이상 대량 보유 · 경영 참여 목적"
        elif "PASSIVE" in f:
            base = "5% 이상 대량 보유 · 단순 투자"
        else:
            base = "5% 이상 대량 보유 보고"
        # radar.py 가 붙인 지분율(「 · 5.20% ▲0.50%」)은 그대로 살린다 (Fable 1108-01-01 권고 3)
        rest = f.split(")", 1)[1].strip() if ")" in f else ""
        return f"{base} {rest}".strip() if rest.startswith("·") else base
    if f.startswith("Form 4"):
        # radar._form4_label: 「Form 4 · 매수 · $1.2M」·「Form 4 · non-trade (옵션·수여·증여)」 (권고 1)
        rest = f[len("Form 4"):].strip(" ·")
        rest = rest.replace("non-trade", "매매 아님")
        return f"임원·주요주주 매매 보고 · {rest}" if rest else "임원·주요주주 매매 보고"
    if f.startswith("D002"):
        if "BUY" in f:
            return "임원·주요주주가 주식을 삼"
        if "SELL" in f:
            return "임원·주요주주가 주식을 팖"
        return "임원·주요주주 보유 주식 변동"
    return None


def _form_text(form: str) -> str:
    from backend.services.alert_text import sec_form_text

    kr = _kr_form(form)
    if kr:
        return kr
    text = sec_form_text(form)
    return text if text != form else (form or "공시")


def _target_name(desc: Optional[str]) -> Optional[str]:
    """「회사 — 보고서 제목」 에서 회사 이름만."""
    if not desc:
        return None
    return desc.split(" — ")[0].strip() or None


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
    return td, [TodayCandidateItem(ticker=r.ticker, name=r.name, note=" · ".join(x for x in (f"{r.rank}위", _watch_reason(r), f"관심 점수 {_score100(r.composite_score, 1)}/100") if x))
                for r in rows]


async def _powderkeg(today: date):
    from backend.services.models import PowderKegEvent as E

    async with get_session() as s:
        rows = (await s.execute(select(E).where(E.detected_at >= _kst_midnight_utc(today))
                                .order_by(desc(E.detected_at)).limit(_LIMITS["powderkeg"]))).scalars().all()
    from backend.services.alert_text import POWDERKEG_TYPE
    from backend.services.stock_names import lookup_kr_name

    cache: dict = {}
    items = []
    for r in rows:
        kind = POWDERKEG_TYPE.get(r.event_type)
        title = (r.title or "")[:100]
        items.append(TodayCandidateItem(ticker=r.ticker, name=await lookup_kr_name(r.ticker, cache),
                                        note=f"{kind} · {title}" if kind else title))
    return (today.isoformat() if rows else None), items


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
        # 1108-01 · 밈 대상 목록의 이름 (국내·미국 모두) · 없으면 국내 이름 찾기로
        from backend.services.models import MemeUniverse as U

        tks = {r.ticker for r in rows}
        names = dict((await s.execute(select(U.ticker, U.name).where(U.ticker.in_(tks)))).all()) if tks else {}
    from backend.services.stock_names import lookup_kr_name

    cache: dict = {}
    seen: set[str] = set()
    items: list[TodayCandidateItem] = []
    for r in rows:  # 종목마다 가장 최근 알림 1건
        if r.ticker in seen:
            continue
        seen.add(r.ticker)
        kst = r.triggered_at.replace(tzinfo=local).astimezone(_KST)
        name = names.get(r.ticker) or (await lookup_kr_name(r.ticker, cache) if r.ticker.isdigit() else None)
        what = _MEME_ALERT.get(r.alert_type, r.alert_type)
        items.append(TodayCandidateItem(ticker=r.ticker, name=name, note=f"{what} · {kst:%H:%M}"))
        if len(items) >= _LIMITS["meme"]:
            break
    return (today.isoformat() if items else None), items


async def _activist(today: date):
    """activist_state.json 읽기만 (SEC 보충 호출 없음)."""
    from backend.discovery.activist.state import ActivistState

    evs = ActivistState.load().recent_events(_LIMITS["activist"])
    from backend.services.alert_text import ACTIVIST_LEVEL

    def note(e) -> str:
        form = _form_text(e.form)
        # 국내 D002: 공시한 사람이 「임원·주요주주 (회사)」 라 같은 말이 겹친다 → 양식 글만 (권고 2)
        if (e.filer_name or "").startswith("임원·주요주주"):
            return form
        return f"{e.filer_name} · {form} · 신호 {ACTIVIST_LEVEL.get(e.intensity_label, e.intensity_label)}"

    items = [TodayCandidateItem(ticker=e.target_ticker or None, name=_target_name(e.target_desc), note=note(e))
             for e in evs]
    return (max((e.filing_date or "" for e in evs), default="") or None), items


async def _crazy(today: date):
    from backend.services.models import CrazyPick as P

    async with get_session() as s:
        d = (await s.execute(select(func.max(P.pick_date)))).scalar()
        if not d:
            return None, []
        rows = (await s.execute(select(P).where(P.pick_date == d).order_by(P.rank).limit(_LIMITS["crazy"]))).scalars().all()
    return d, [TodayCandidateItem(ticker=r.ticker, name=r.company_name, note=f"{r.rank}위 · 급등 가능성 점수 {_score100(r.composite_score, 100)}/100")
               for r in rows]


async def _moonshot(today: date):
    from backend.services.models import MoonshotPick as P

    async with get_session() as s:
        d = (await s.execute(select(func.max(P.pick_date)))).scalar()
        if not d:
            return None, []
        rows = (await s.execute(select(P).where(P.pick_date == d).order_by(P.rank).limit(_LIMITS["moonshot"]))).scalars().all()
    return d, [TodayCandidateItem(ticker=r.ticker, name=r.company_name, note=f"{r.rank}위 · 급등 가능성 점수 {_score100(r.composite_score, 100)}/100")
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
            why = (row.get("why_easy") or "").strip()
            parts = [f"{idx}위", why or None, f"점수 {_score100(row.get('score') or 0, 1)}/100"]
            items.append(TodayCandidateItem(ticker=(row.get("ticker") or "").strip().upper() or None,
                                            name=(row.get("name") or "").strip() or None,
                                            note=" · ".join(p for p in parts if p)))
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date().isoformat(), items


# 섹션 순서: (source, label, link, 읽기 함수, 관리자 전용)
_SECTIONS = [
    ("watchlist", "국내 · 오늘 관심 종목", "/watchlist", _watchlist, False),
    ("powderkeg", "국내 · 화약고 공시", "/powderkeg", _powderkeg, False),
    ("meme", "밈 급등 신호 (국내·미국)", "/lab/meme-watch", _meme, False),
    ("activist", "큰손 지분 공시 (행동주의)", "/activist-radar", _activist, False),
    ("crazy", "미국 · 중대형주 급등 후보 (Crazy)", "/lab/crazy", _crazy, True),
    ("moonshot", "미국 · 소형주 고위험 급등 후보 (Moonshot)", "/lab/moonshot", _moonshot, True),
    ("biotech", "미국 · 바이오 소식 앞둔 종목", "/biotech", _biotech, True),
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
