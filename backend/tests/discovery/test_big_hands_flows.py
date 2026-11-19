"""1119-03 ① · ㉤ 외국인 · 기관 저장 + 기존 값이 안 바뀐다는 시험 (Fable 질문 3 (마) (바)) · 가짜 토스 · 바깥 호출 없음."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import DateTime, delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.big_hands import flows
from backend.discovery.big_hands.models import (
    InvestorFlowDaily, SignalEvent, SignalOutcome, SignalSource,
)
from backend.discovery.watchlist import rank_signals as rs
from backend.services.db import get_session, init_db
from backend.services.models import WatchlistRankDaily, WatchlistSignal

_KST = timezone(timedelta(hours=9))
_DAY1 = datetime(2026, 10, 30, 20, 30, tzinfo=_KST)
_DAY2 = datetime(2026, 11, 2, 20, 30, tzinfo=_KST)


@pytest_asyncio.fixture(autouse=True)
async def _clean(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHLIST_RUNTIME_DIR", str(tmp_path))
    await init_db()
    async with get_session() as session:
        for model in (WatchlistSignal, WatchlistRankDaily, InvestorFlowDaily, SignalEvent, SignalSource, SignalOutcome):
            await session.execute(delete(model))
    yield


def _grp(ranked_at, buys, sells):
    return {"rankedAt": ranked_at,
            "netBuyRankings": [{"rank": r, "symbol": s, "currency": "KRW", "netBuyAmount": str(9000 - r)} for s, r in buys],
            "netSellRankings": [{"rank": r, "symbol": s, "currency": "KRW", "netSellAmount": str(8000 - r)} for s, r in sells]}


def _investor(day, indiv, foreign=None, inst=None, foreign_at=None, inst_at=None):
    iso = f"{day}T20:30:00+09:00"
    return {"individual": _grp(iso, indiv, []),
            "foreigner": _grp(foreign_at or iso, *(foreign or ([], []))),
            "institution": _grp(inst_at or iso, *(inst or ([], [])))}


def _ranking(ranked_at, rows):
    return {"rankedAt": ranked_at, "rankings": [
        {"rank": r, "symbol": s, "currency": "KRW",
         "price": {"lastPrice": "1000", "basePrice": "900", "changeRate": cr},
         "tradingVolume": "1", "tradingAmount": str(1000 - r)} for s, r, cr in rows]}


class FakeToss:
    def __init__(self, day, investor, toss_amt):
        iso = f"{day}T20:30:00+09:00"
        self.investor = investor
        self.daily = {"TOSS_SECURITIES_TRADING_AMOUNT": _ranking(iso, [(s, r, "0.02") for s, r in toss_amt]),
                      "TOSS_SECURITIES_TRADING_VOLUME": _ranking(iso, []),
                      "MARKET_TRADING_AMOUNT": _ranking(iso, []), "MARKET_TRADING_VOLUME": _ranking(iso, [])}
        self.investor_calls = 0

    def rankings(self, *, type, market="KR", duration="realtime", exclude_caution=True, count=100):
        return SimpleNamespace(result=self.daily.get(type))

    def investor_trading_rankings(self, *, count=100):
        self.investor_calls += 1
        return SimpleNamespace(result=self.investor)

    def prices(self, symbols):
        return []

    def candles(self, symbol, count=200):
        return []


async def _dump(model):
    async with get_session() as session:
        rows = (await session.execute(select(model).order_by(model.id))).scalars().all()
    skip = {c.name for c in model.__table__.columns if isinstance(c.type, DateTime) or c.name == "id"}
    return [{c.name: getattr(r, c.name) for c in model.__table__.columns if c.name not in skip} for r in rows]


async def _two_days(with_flows: bool):
    f = ([("900001", 1), ("900002", 2)], [("900003", 1)]) if with_flows else ([], [])
    c1 = FakeToss("2026-10-30", _investor("2026-10-30", [("111111", 5)], f, f), [("111111", 5)])
    await rs.collect_rank_daily(c1, now=_DAY1)
    c2 = FakeToss("2026-11-02", _investor("2026-11-02", [("111111", 3), ("222222", 2)], f, f),
                  [("111111", 3), ("222222", 2)])
    await rs.collect_rank_daily(c2, now=_DAY2)
    return c2


async def _snapshot():
    return {"rank": await _dump(WatchlistRankDaily), "signal": await _dump(WatchlistSignal),
            "status": {k: v for k, v in rs.read_status()["daily"].items() if k != "run_at"}}


async def _reset_all():
    async with get_session() as session:
        for model in (WatchlistSignal, WatchlistRankDaily, InvestorFlowDaily):
            await session.execute(delete(model))
    os.remove(os.path.join(os.environ["WATCHLIST_RUNTIME_DIR"], rs.STATUS_FILE))


# ─── 저장 ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_saves_foreigner_and_institution_buy_and_sell_without_new_call():
    c = await _two_days(True)
    assert c.investor_calls == 1                      # 순위 호출을 늘리지 않음
    rows = await _dump(InvestorFlowDaily)
    d2 = [r for r in rows if r["trade_date"] == "2026-11-02"]
    assert {(r["investor"], r["side"], r["ticker"]) for r in d2} == {
        (i, s, t) for i in ("foreigner", "institution") for s, t in (("buy", "900001"), ("buy", "900002"), ("sell", "900003"))}
    assert next(r for r in d2 if r["side"] == "sell")["amount"] == pytest.approx(7999.0)


@pytest.mark.asyncio
async def test_resave_same_day_replaces_rows_not_duplicates():
    await flows.save_investor_flows(_investor("2026-11-02", [], ([("900001", 1)], []), ([], [])), "2026-11-02")
    await flows.save_investor_flows(_investor("2026-11-02", [], ([("900001", 2)], []), ([], [])), "2026-11-02")
    rows = await _dump(InvestorFlowDaily)
    assert len(rows) == 1 and rows[0]["rank"] == 2


@pytest.mark.asyncio
async def test_each_group_judges_its_own_ranked_at():
    # 외국인은 어제 값(저장 안 함) · 기관은 오늘 값(저장)
    res = _investor("2026-11-02", [], ([("900001", 1)], []), ([("900002", 1)], []), foreign_at="2026-10-30T20:30:00+09:00")
    saved = await flows.save_investor_flows(res, "2026-11-02")
    assert saved == {"institution": 1}
    rows = await _dump(InvestorFlowDaily)
    assert {r["investor"] for r in rows} == {"institution"}


def test_new_kinds_are_not_in_existing_kind_lists():
    assert all("foreign" not in k and "institution" not in k for k in rs.ALL_KINDS)
    assert all("foreign" not in k and "institution" not in k for k in rs.KIND_SOURCE)


# ─── Fable (마): 세 묶음 응답이어도 기존 결과가 같다 ──────────────
@pytest.mark.asyncio
async def test_existing_outputs_same_with_and_without_flow_groups():
    await _two_days(False)
    without = await _snapshot()
    await _reset_all()
    await _two_days(True)
    with_groups = await _snapshot()
    assert with_groups == without
    assert "foreigner" not in str(with_groups["status"]) and "institution" not in str(with_groups["status"])
    assert with_groups["signal"], "비교가 빈 값끼리가 되지 않게 신호가 실제로 있어야 한다"


# ─── Fable (바): 새 저장이 예외를 내도 기존 결과가 같다 ───────────
@pytest.mark.asyncio
async def test_existing_outputs_same_when_new_save_raises(monkeypatch, caplog):
    await _two_days(True)
    ok = await _snapshot()
    await _reset_all()

    async def boom(*_a, **_k):
        raise RuntimeError("새 저장 실패 시험")

    monkeypatch.setattr(flows, "save_investor_flows", boom)
    with caplog.at_level("WARNING"):
        await _two_days(True)
    assert await _snapshot() == ok
    assert await _dump(InvestorFlowDaily) == []
    assert "외국인·기관 저장 실패" in caplog.text
