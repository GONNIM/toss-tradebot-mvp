"""실행기 진입 · 계획서 2절 · 4-3 · 9절.

- `TOSS_TOKEN_ISSUE=1` 이 있는 곳(운영 서버)에서만 시작한다. 없으면 로그 1줄만 남기고 시작하지 않는다.
  `APP_ENV` 는 운영 서버에 없어 판단에 쓰지 않는다.
- 잠금 파일(backend/data/plan_executor.lock · flock)로 하나만 돈다. 잠금을 못 잡으면 시작하지 않고 시스템 경고.
- tradebot-cron 프로세스의 이벤트 루프 안에서 돈다. 동기 토스 호출은 RealRaw 가 asyncio.to_thread 로 돌린다.
- 한 바퀴: 스위치 읽기(5초) → 화면 요청 처리 → 모의 가상 체결 → 계획별 한 걸음 → 하트비트(30초) → 다시 맞추기(5분).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from . import drafts, heartbeat, resync, sizing, state
from .brokers import DirectionGate, PaperRaw, RawBroker, RealRaw, access_token as _token
from .engine import PlanEngine, set_runtime
from .models import Plan, PlanEvent, PlanLeg, PlanPaperOrder, PlanRequest, utcnow
from .switches import read_switches
from .ws import PriceStore, PlanWsClient

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = _PROJECT_ROOT / "backend" / "data" / "plan_executor.lock"

SWITCH_POLL_SEC = 5
TICK_SEC = 5
RESYNC_SEC = 300

_LIVE_ACTIVE = (state.APPROVED, state.ENTRY_ARMED, state.ENTRY_RETRY, state.HOLDING, state.TP1_WAIT,
                state.TRAILING, state.ADOPT_PENDING, state.HALTED)


def executor_enabled() -> bool:
    from backend.services import config

    return (config.get("TOSS_TOKEN_ISSUE") or "").strip() == "1"


def acquire_lock(path: Path = LOCK_PATH) -> Optional[int]:
    """flock 비차단 · 잡으면 열린 fd(프로세스가 끝날 때까지 유지) · 못 잡으면 None."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover
        return -1
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


async def default_notify(level: str, title: str, body: str, category: str) -> None:
    from backend.services.notifier import TelegramNotifier

    n = TelegramNotifier()
    if level == "critical":
        await n.send_critical(title, body, category=category)
    elif level == "warning":
        await n.send_warning(title, body, category=category)
    else:
        await n.send_info(title, body, category=category)


def _kill_state() -> tuple[bool, bool]:
    from backend.execution.kill_switch import get_kill_switch

    st = get_kill_switch().status()
    return bool(getattr(st, "active", False)), bool(getattr(st, "sell_allowed", True))


def _limit_factor_from_calendar(now: datetime):
    from decimal import Decimal

    from backend.execution.market_calendar import get_market_calendar
    from backend.execution.models import MarketState

    st = get_market_calendar().windows("US").state(now.replace(tzinfo=timezone.utc))
    if st == MarketState.REGULAR:
        return Decimal("0.98")
    if st in (MarketState.PRE_MARKET, MarketState.AFTER_HOURS):
        return Decimal("0.97")
    return None   # 데이마켓 · 장 밖: 지정가를 낼 수 없는 것으로 본다 (보고서 「확인 못 한 것」)


def _regular_window_from_calendar(now: datetime):
    from backend.execution.market_calendar import get_market_calendar

    w = get_market_calendar().windows("US").regular_market
    if not w:
        return None
    return (w[0].replace(tzinfo=None), w[1].replace(tzinfo=None))


class PlanExecutor:
    def __init__(self, *, real_engine: PlanEngine, paper_engine: PlanEngine, paper_raw: PaperRaw,
                 session_factory=None, notify=default_notify, store: Optional[PriceStore] = None):
        from backend.services.db import get_session

        self.engines = {"live": real_engine, "test": real_engine, "paper": paper_engine}
        self.paper_raw = paper_raw
        self.gs = session_factory or get_session
        self.notify = notify
        self.store = store or PriceStore()
        self.ws = PlanWsClient(self.store, token_fn=_token, symbols_fn=self._open_symbols)
        self._prev_sw = {"live": False, "paper": False}
        self._last_resync = 0.0
        self._recovered_sent = False

    @classmethod
    def build(cls, *, notify=default_notify) -> "PlanExecutor":
        store = PriceStore()
        real_raw = RealRaw()
        live_gate = DirectionGate(real_raw, store)

        async def _price(symbol):
            return await real_raw.last_price_rest(None, symbol)

        paper_raw = PaperRaw(_price)
        paper_gate = DirectionGate(paper_raw, store)
        common = dict(notify=notify, limit_factor=_limit_factor_from_calendar,
                      regular_window=_regular_window_from_calendar, kill_state=_kill_state)
        return cls(real_engine=PlanEngine(live_gate, **common), paper_engine=PlanEngine(paper_gate, **common),
                   paper_raw=paper_raw, notify=notify, store=store)

    async def _open_symbols(self) -> list[str]:
        async with self.gs() as s:
            rows = await s.scalars(select(Plan.symbol).where(Plan.state.in_(_LIVE_ACTIVE)))
            return sorted(set(rows))

    def _engine(self, plan: Plan) -> PlanEngine:
        return self.engines[plan.mode]

    # ── 스위치 변화 ──
    async def handle_switch_changes(self) -> None:
        sw = read_switches()
        if self._prev_sw["live"] and not sw["live"]:
            for pid in await self._plan_ids(("live", "test")):
                async with self.gs() as s:                      # 계획마다 세션 (토스 호출 동안 다른 계획의 쓰기를 막지 않는다)
                    p = await s.get(Plan, pid)
                    if p is not None:
                        await self.engines["live"].cancel_buys_on_switch_off(s, p)
        if self._prev_sw["paper"] and not sw["paper"]:
            for pid in await self._plan_ids(("paper",)):
                async with self.gs() as s:
                    p = await s.get(Plan, pid)
                    if p is not None:
                        await self._virtual_close(s, p)         # 모의 스위치를 끄면 남은 모의 계획을 가상 정리(CLOSED)
        self._prev_sw = {"live": sw["live"], "paper": sw["paper"]}

    async def _plan_ids(self, modes: tuple) -> list[int]:
        async with self.gs() as s:
            return list(await s.scalars(select(Plan.id).where(Plan.mode.in_(modes), Plan.state.in_(_LIVE_ACTIVE)).order_by(Plan.id)))

    async def _virtual_close(self, s, plan: Plan) -> None:
        for o in await s.scalars(select(PlanPaperOrder).where(PlanPaperOrder.plan_id == plan.id,
                                                              PlanPaperOrder.status == "OPEN")):
            o.status = "CANCELED"
        for leg in await s.scalars(select(PlanLeg).where(PlanLeg.plan_id == plan.id, PlanLeg.status == "WATCHING")):
            leg.status = "CANCELED"
        plan.state = state.CLOSED
        await state.event(s, plan.id, "paper_closed", "모의 스위치 꺼짐 · 가상 정리")

    # ── 화면 요청 ──
    async def process_requests(self) -> int:
        """화면이 남긴 요청을 하나씩 · 요청마다 세션을 따로 쓴다."""
        async with self.gs() as s:
            ids = list(await s.scalars(select(PlanRequest.id).where(PlanRequest.status == "pending").order_by(PlanRequest.id)))
        for rid in ids:
            async with self.gs() as s:
                r = await s.get(PlanRequest, rid)
                if r is None or r.status != "pending":
                    continue
                plan = await s.get(Plan, r.plan_id) if r.plan_id else None
                try:
                    if plan is None:
                        raise ValueError("계획 없음")
                    eng = self._engine(plan)
                    if r.action == "stop":
                        await eng._cancel_pending_buys(s, plan)
                    elif r.action == "resume":
                        r.result = await eng.resume_plan(s, plan)
                    elif r.action == "adopt_cancel":
                        if plan.state == state.ADOPT_PENDING:
                            await state.transition(s, plan, state.CANCELLED, reason="인수 취소")
                    elif r.action == "resync":
                        r.result = json.dumps(await resync.resync_plan(s, eng, plan), ensure_ascii=False, default=str)[:300]
                    elif r.action == "timestop_stop":
                        await eng.stop_timestop(s, plan)
                    else:
                        raise ValueError("알 수 없는 요청")
                    r.status = "done"
                except Exception as exc:  # noqa: BLE001
                    r.status, r.result = "failed", f"{exc.__class__.__name__}: {exc}"[:300]
                r.done_at = utcnow()
        return len(ids)

    # ── 한 바퀴 ──
    async def tick_once(self) -> None:
        await self.handle_switch_changes()
        await self.process_requests()
        async with self.gs() as s:
            ids = list(await s.scalars(select(Plan.id).where(Plan.state.in_(_LIVE_ACTIVE)).order_by(Plan.id)))
        for pid in ids:
            try:
                async with self.gs() as s:                      # 계획마다 세션 · 토스 호출 결과는 엔진이 바로 commit
                    plan = await s.get(Plan, pid)
                    if plan is None:
                        continue
                    if plan.mode == "paper":
                        px = await self.paper_raw.last_price_rest(s, plan.symbol)
                        if px is not None:
                            await self.paper_raw.on_price(s, plan.symbol, px)
                    await self._engine(plan).tick_plan(s, plan)
                    await self._record_runtime(s, plan)
            except Exception as exc:  # noqa: BLE001 — 한 계획의 오류(낙관적 잠금 충돌 포함)가 다른 계획을 멈추지 않는다
                logger.error("[plan] tick 실패 · 계획 %s · %s", pid, exc.__class__.__name__)

    async def _record_runtime(self, s, plan: Plan) -> None:
        """화면용 마지막 값: 현재가 · 다음 시간대 전환 시각(KST) · 토스 연결 상태 (읽기만 · 실패해도 계획 처리는 계속)."""
        eng = self._engine(plan)
        now = utcnow()
        try:
            cur = await eng.gate.current(s, plan.symbol)
        except Exception:  # noqa: BLE001
            await heartbeat.mark_toss(s, False)
            return
        await heartbeat.mark_toss(s, True)
        nxt = None
        reg = eng.regular_window(now)
        if reg:
            from datetime import timedelta as _td

            cands = [t for t in (reg[0] + _td(minutes=1), reg[1] + _td(minutes=1)) if t > now]
            if cands:
                nxt = min(cands).replace(tzinfo=timezone.utc).astimezone(timezone(_td(hours=9))).isoformat(timespec="seconds")
        set_runtime(plan, price=float(cur), price_at=now.isoformat(), next_swap_at=nxt)

    async def _snapshot_for_screen(self, s) -> None:
        """다시 맞추기 때: 계정 USD 매수 가능 금액 · 종목별 앱(계획 밖) 조건주문 수를 남긴다 (새 계획 검증용)."""
        eng = self.engines["live"]
        try:
            bp = await eng.gate.raw.buying_power_usd(s)
            own = {l.toss_id for l in await s.scalars(select(PlanLeg)) if l.toss_id}
            counts: dict[str, int] = {}
            for o in await eng.gate.cond_open_list(s, None):
                if o and o.get("id") not in own and o.get("symbol"):
                    counts[o["symbol"]] = counts.get(o["symbol"], 0) + 1
            await heartbeat.save_resync_snapshot(s, buying_power=bp, app_conds=counts)
            await heartbeat.mark_toss(s, True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[plan] 화면용 스냅샷 실패 · %s", exc.__class__.__name__)
            await heartbeat.mark_toss(s, False)

    async def resync_once(self) -> tuple[int, int]:
        """모든 열린 계획을 하나씩(계획마다 세션) 다시 맞춘다. 반환: (일치한 손절 다리 수, 불변식을 통과 못 한 계획 수)."""
        total = bad = 0
        for mode_modes, eng in ((("live", "test"), self.engines["live"]), (("paper",), self.engines["paper"])):
            for pid in await self._plan_ids(mode_modes):
                async with self.gs() as s:
                    p = await s.get(Plan, pid)
                    if p is None:
                        continue
                    rep = await resync.resync_plan(s, eng, p)
                    if rep.get("ok") and rep.get("ladder") in ("ok", "fixed", "skipped"):
                        total += len(await sizing.live_sl_legs(s, p.id))
                    else:
                        bad += 1
        async with self.gs() as s:
            await self._snapshot_for_screen(s)
            await heartbeat.write(s, ws_status=self.ws.status, last_resync_at=utcnow())
        return total, bad

    async def _send_urgent(self, title: str, body: str) -> bool:
        await self.notify("critical", title, body, "execution")
        return True

    async def _startup_resync(self, stop: asyncio.Event) -> tuple[int, int]:
        """기동 다시 맞추기. 토스 · DB 가 잠깐 안 되어도 실행기가 죽지 않고 성공할 때까지 되풀이한다(1·2·4…초 · 최대 60초)."""
        attempt = 0
        while not stop.is_set():
            try:
                return await self.resync_once()
            except Exception as exc:  # noqa: BLE001
                logger.error("[plan] 기동 다시 맞추기 실패 · %s · 다시 시도", exc.__class__.__name__)
                attempt += 1
                try:
                    await asyncio.wait_for(stop.wait(), timeout=min(2 ** attempt, 60))
                except asyncio.TimeoutError:
                    pass
        return 0, 0

    async def run(self, stop: asyncio.Event) -> None:
        import time

        ws_task = asyncio.create_task(self.ws.run(stop))     # 웹소켓 1연결 (끊기면 스스로 다시 연결 · REST 가 대신 읽음)
        async with self.gs() as s:
            await heartbeat.write(s, ws_status=self.ws.status)   # 기록이 있어야 서버 쪽 끊김 감시가 시작된다
        n, bad = await self._startup_resync(stop)
        if not stop.is_set():
            if bad == 0:                                         # 불변식을 확인한 뒤에만 「복구」 알림 (9절)
                async with self.gs() as s:
                    await heartbeat.notify_recovered(s, self._send_urgent, n)
            else:
                await self.notify("critical", "실행기 시작 · 불변식 확인 필요",
                                  f"실행기를 시작했지만 계획 {bad}건이 불변식 확인을 통과하지 못했습니다. 화면에서 확인해 주십시오.", "execution")
        last_hb = last_rs = time.monotonic()
        while not stop.is_set():
            try:
                await self.tick_once()
                now = time.monotonic()
                if now - last_hb >= heartbeat.WRITE_EVERY_SEC:
                    async with self.gs() as s:
                        await heartbeat.write(s, ws_status=self.ws.status)
                    last_hb = now
                if now - last_rs >= RESYNC_SEC:
                    await self.resync_once()
                    last_rs = now
            except Exception as exc:  # noqa: BLE001
                logger.error("[plan] 실행기 바퀴 실패 · %s", exc.__class__.__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=TICK_SEC)
            except asyncio.TimeoutError:
                pass
        await asyncio.gather(ws_task, return_exceptions=True)


async def start_executor(stop: asyncio.Event) -> Optional[asyncio.Task]:
    """cron 데몬이 부른다. 키가 없으면 로그 1줄만 · 잠금을 못 잡으면 시스템 경고 · 아니면 실행기 task."""
    if not executor_enabled():
        logger.info("[plan] TOSS_TOKEN_ISSUE 없음 · 계획 실행기를 시작하지 않음")
        return None
    try:                                        # cron 프로세스에는 create_all 이 없다 → 계획 표를 여기서 만든다 (이미 있으면 그대로)
        from backend.services.db import init_db

        await init_db()
    except Exception as exc:  # noqa: BLE001
        logger.error("[plan] 표 만들기 실패 · %s · 실행기를 시작하지 않음", exc.__class__.__name__)
        return None
    fd = acquire_lock()
    if fd is None:
        logger.error("[plan] 실행기 잠금을 잡지 못해 시작하지 않음")
        try:
            await default_notify("warning", "계획 실행기 시작 안 함", "이미 다른 실행기가 잠금을 쥐고 있습니다.", "system")
        except Exception:  # noqa: BLE001
            pass
        return None
    ex = PlanExecutor.build()
    ex._lock_fd = fd   # 프로세스가 끝날 때까지 유지
    return asyncio.create_task(ex.run(stop))


# ─── 자동 초안 잡 (cron 프로세스 · 실행기가 켜진 곳에서만 등록) ───────────────

def _make_draft_loader(today):
    """기존 바이오 산출물 + 토스 시세(읽기)를 연결한 로더 (draft_sources.py 머리말 참고)."""
    from .draft_sources import BiotechDraftLoader

    real = RealRaw()

    async def _price(symbol):
        return await real.last_price_rest(None, symbol)

    return BiotechDraftLoader(today, _price)


async def job_plan_draft(now_utc: Optional[datetime] = None) -> str:
    """오늘 레이더가 나왔는지 보고 초안을 만든다. 반환: skip | wait | no_rule | warned."""
    from backend.services.db import get_session

    now = now_utc or utcnow()
    today = drafts.today_kst(now)
    now_kst = (now.replace(tzinfo=timezone.utc)).astimezone(drafts._KST)
    n = drafts.attempt_number(now_kst)
    async with get_session() as s:
        key = f"draft:{today.isoformat()}"
        done = await s.scalar(select(PlanEvent.id).where(PlanEvent.kind == "draft_done", PlanEvent.detail == key).limit(1))
        if done is not None:
            return "skip"
        if drafts.radar_ready(drafts.radar_dir(), today):
            s.add(PlanEvent(plan_id=None, kind="draft_done", detail=key))
            eng = PlanEngine(DirectionGate(RawBroker.__new__(RawBroker)), notify=default_notify)   # DB 만 쓴다 (브로커 부르지 않음)
            symbols = drafts.radar_symbols(drafts.radar_dir(), today)
            decisions, expired = await drafts.run_draft_cycle(s, eng, today=today, symbols=symbols, loader=_make_draft_loader(today))
            summary = drafts.build_summary(decisions, expired)
            if summary:
                await default_notify("info", summary[0], summary[1], "biotech")      # 「바이오」 범주 1건 요약
            if any(d.action in ("create", "update") for d in decisions):
                return "drafted"
            s.add(PlanEvent(plan_id=None, kind="draft_none", detail=f"후보 {len(symbols)}건 · 만든 초안 0건"))
            return "no_rule"
        if n == drafts.MAX_ATTEMPTS:
            s.add(PlanEvent(plan_id=None, kind="draft_done", detail=key))
            await default_notify("warning", "자동 초안 없음", "오늘 날짜 레이더 파일이 08:05 까지 없어 초안을 만들지 않았습니다.", "system")
            return "warned"
        return "wait"
