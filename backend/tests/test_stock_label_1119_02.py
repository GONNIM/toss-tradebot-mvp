"""1119-02 · 종목명 · 종목코드 함께 표시 (서버 쪽) — 한꺼번에 찾기 · 응답 name 칸 · 텔레그램 문장.

가짜 값만 쓴다: 코드 000001 · 테스트전자 · 미국 TESTA / Testa Corp (실제 종목명 · 코드 금지).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete

from backend.services import alert_text as at
from backend.services import stock_names as sn
from backend.tests.plan_fakes import plan_db  # noqa: F401
from backend.tests.test_plan_api import api, hdr, mk_plan  # noqa: F401


@pytest_asyncio.fixture
async def db():
    from backend.services.db import get_session, init_db
    from backend.services.models import (
        KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, MemeUniverse, PowderKegList, TickerUniverse,
    )

    await init_db()
    async with get_session() as session:
        for model in (KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList, TickerUniverse, MemeUniverse):
            await session.execute(delete(model))
    yield


async def _add(*rows):
    from backend.services.db import get_session

    async with get_session() as session:
        for r in rows:
            session.add(r)


def _models():
    from backend.services import models as m

    return m


# ───────────────────────── lookup_kr_names ─────────────────────────

@pytest.mark.asyncio
async def test_kr_names_source_order_and_latest_row(db):
    m = _models()
    await _add(
        m.KrxMarketSnapshot(ticker="000001", snapshot_date="2026-08-01", name="옛이름"),
        m.KrxMarketSnapshot(ticker="000001", snapshot_date="2026-08-13", name="스냅샷이름"),
        m.LiveTapeUniverse(ticker="000002", name="유니버스이름"),
        m.PowderKegList(run_id="20260101-000000", ticker="000003", name="옛목록", status="passed"),
        m.PowderKegList(run_id="20260813-000000", ticker="000003", name="최신목록", status="passed"),
        m.KrxStockMeta(ticker="000004", name="메타이름"),
        # 같은 코드가 여러 표에 있으면 앞 표가 이긴다
        m.LiveTapeUniverse(ticker="000001", name="뒤표이름"),
    )
    got = await sn.lookup_kr_names(["000001", "000002", "000003", "000004", "000009"])
    assert got == {"000001": "스냅샷이름", "000002": "유니버스이름", "000003": "최신목록", "000004": "메타이름"}


@pytest.mark.asyncio
async def test_kr_names_same_as_single_lookup(db):
    m = _models()
    await _add(
        m.KrxMarketSnapshot(ticker="000001", snapshot_date="2026-08-13", name="가"),
        m.LiveTapeUniverse(ticker="000002", name="나"),
        m.PowderKegList(run_id="20260813-000000", ticker="000003", name="다", status="passed"),
        m.KrxStockMeta(ticker="000004", name="라"),
    )
    codes = ["000001", "000002", "000003", "000004", "000005"]
    many = await sn.lookup_kr_names(codes)
    for c in codes:
        assert many.get(c) == await sn.lookup_kr_name(c)


@pytest.mark.asyncio
async def test_kr_names_blank_or_same_as_code_is_not_found(db):
    m = _models()
    await _add(
        m.LiveTapeUniverse(ticker="000001", name="  "),
        m.LiveTapeUniverse(ticker="000002", name="000002"),
        m.KrxStockMeta(ticker="000001", name="메타이름"),     # 앞 표 이름이 빈칸이면 다음 표로
    )
    got = await sn.lookup_kr_names(["000001", "000002"])
    assert got == {"000001": "메타이름"}


@pytest.mark.asyncio
async def test_kr_names_one_query_per_table_and_chunks_of_500(db, monkeypatch):
    calls: list[tuple[int, int]] = []
    real = sn._kr_table

    async def spy(idx, chunk):
        calls.append((idx, len(chunk)))
        return await real(idx, chunk)

    monkeypatch.setattr(sn, "_kr_table", spy)
    await sn.lookup_kr_names([f"{i:06d}" for i in range(1, 51)])
    assert calls == [(0, 50), (1, 50), (2, 50), (3, 50)]          # 표마다 1번
    sn.clear_memo()
    calls.clear()
    await sn.lookup_kr_names([f"{i:06d}" for i in range(1, 1204)])   # 1203개 → 500 · 500 · 203
    assert [c for c in calls if c[0] == 0] == [(0, 500), (0, 500), (0, 203)]
    assert len(calls) == 12


@pytest.mark.asyncio
async def test_kr_names_one_table_fails_next_tables_still_read_and_not_remembered(db, monkeypatch, caplog):
    m = _models()
    await _add(m.KrxStockMeta(ticker="000004", name="메타이름"))
    real = sn._kr_table

    async def boom(idx, chunk):
        if idx == 0:
            raise RuntimeError("database is locked")
        return await real(idx, chunk)

    monkeypatch.setattr(sn, "_kr_table", boom)
    got = await sn.lookup_kr_names(["000004", "000009"])
    assert got == {"000004": "메타이름"}                             # 실패한 표만 건너뜀 · 응답은 정상
    assert any("읽기 실패" in r.message for r in caplog.records)
    # 표를 끝까지 읽지 못했으므로 「못 찾음」을 기억하지 않는다 (Fable 권고 3)
    assert ("KR", "000009") not in sn._memo
    assert ("KR", "000004") in sn._memo                             # 찾은 이름은 기억


@pytest.mark.asyncio
async def test_kr_names_timeout_returns_partial_and_does_not_remember_misses(db, monkeypatch):
    m = _models()
    await _add(m.KrxMarketSnapshot(ticker="000001", snapshot_date="2026-08-13", name="먼저찾음"))
    real = sn._kr_table

    async def slow(idx, chunk):
        if idx >= 1:
            await asyncio.sleep(5)
        return await real(idx, chunk)

    monkeypatch.setattr(sn, "_kr_table", slow)
    monkeypatch.setattr(sn, "TIMEOUT_SEC", 0.2)
    t0 = time.monotonic()
    got = await sn.lookup_kr_names(["000001", "000009"])
    assert time.monotonic() - t0 < 2.0
    assert got == {"000001": "먼저찾음"}                             # 그때까지 찾은 이름만
    assert ("KR", "000009") not in sn._memo


@pytest.mark.asyncio
async def test_kr_names_miss_is_remembered_only_after_full_read(db, monkeypatch):
    m = _models()
    await _add(m.KrxStockMeta(ticker="000004", name="메타이름"))
    assert await sn.lookup_kr_names(["000009"]) == {}
    assert sn._memo[("KR", "000009")][1] is None                    # 끝까지 읽고 없음 → 기억
    calls = []
    real = sn._kr_table

    async def spy(idx, chunk):
        calls.append(idx)
        return await real(idx, chunk)

    monkeypatch.setattr(sn, "_kr_table", spy)
    assert await sn.lookup_kr_names(["000009", "000004"]) == {"000004": "메타이름"}
    assert calls == [0, 1, 2, 3]                                    # 못 찾음 기억분(000009)은 다시 읽지 않고 000004 만 읽음
    calls.clear()
    assert await sn.lookup_kr_names(["000009", "000004"]) == {"000004": "메타이름"}
    assert calls == []                                              # 이제 둘 다 기억 · 조회 0


@pytest.mark.asyncio
async def test_kr_names_memo_expires_after_ten_minutes(db, monkeypatch):
    m = _models()
    await _add(m.KrxStockMeta(ticker="000004", name="메타이름"))
    await sn.lookup_kr_names(["000004"])
    stamp, name = sn._memo[("KR", "000004")]
    sn._memo[("KR", "000004")] = (stamp - sn.MEMO_TTL_SEC - 1, name)
    calls = []
    real = sn._kr_table

    async def spy(idx, chunk):
        calls.append(idx)
        return await real(idx, chunk)

    monkeypatch.setattr(sn, "_kr_table", spy)
    await sn.lookup_kr_names(["000004"])
    assert calls                                                    # 기억이 낡아 다시 읽음


# ───────────────────────── lookup_us_names ─────────────────────────

@pytest.mark.asyncio
async def test_us_names_order_and_us_only(db):
    m = _models()
    await _add(
        m.TickerUniverse(symbol="TESTA", market="NASDAQ", category="core", company_name="Testa Corp"),
        m.MemeUniverse(market="US", ticker="TESTA", name="밈이름A"),
        m.MemeUniverse(market="US", ticker="TESTB", name="Testb Inc"),
        m.MemeUniverse(market="KRX", ticker="TESTC", name="국내표시"),      # US 행만
        m.TickerUniverse(symbol="TESTD", market="NYSE", category="core", company_name=""),
    )
    got = await sn.lookup_us_names(["TESTA", "TESTB", "TESTC", "TESTD", "TESTE"])
    assert got == {"TESTA": "Testa Corp", "TESTB": "Testb Inc"}


@pytest.mark.asyncio
async def test_us_names_db_error_returns_empty_without_raising(db, monkeypatch):
    async def boom(idx, chunk):
        raise RuntimeError("locked")

    monkeypatch.setattr(sn, "_us_table", boom)
    assert await sn.lookup_us_names(["TESTA"]) == {}
    assert ("US", "TESTA") not in sn._memo


@pytest.mark.asyncio
async def test_lookup_names_splits_markets_by_is_kr_code_including_letter_codes(db):
    m = _models()
    await _add(
        m.LiveTapeUniverse(ticker="0000A1", name="영문섞인국내"),
        m.TickerUniverse(symbol="TESTA", market="NASDAQ", category="core", company_name="Testa Corp"),
    )
    got = await sn.lookup_names(["0000A1", "TESTA"])
    assert got == {"0000A1": "영문섞인국내", "TESTA": "Testa Corp"}


@pytest.mark.asyncio
async def test_fill_names_keeps_existing_name_and_survives_failure(db, monkeypatch):
    m = _models()
    await _add(m.LiveTapeUniverse(ticker="000001", name="테스트전자"))
    rows = [{"ticker": "000001"}, {"ticker": "000002", "name": "이미있음"}, {"ticker": "000003"}]
    await sn.fill_names(rows)
    assert rows[0]["name"] == "테스트전자" and rows[1]["name"] == "이미있음" and rows[2]["name"] is None

    async def boom(codes):
        raise RuntimeError("x")

    monkeypatch.setattr(sn, "lookup_kr_names", boom)
    rows2 = [{"ticker": "000099"}]
    await sn.fill_names(rows2)                                       # 예외 없이 name 은 None
    assert rows2[0]["name"] is None


# ───────────────────────── 응답에 name 칸 ─────────────────────────

async def _seed_names():
    from backend.services.db import get_session, init_db

    m = _models()
    await init_db()
    async with get_session() as session:
        for model in (m.KrxMarketSnapshot, m.KrxStockMeta, m.LiveTapeUniverse, m.PowderKegList, m.TickerUniverse, m.MemeUniverse):
            await session.execute(delete(model))
    await _add(
        m.LiveTapeUniverse(ticker="000001", name="테스트전자"),
        m.TickerUniverse(symbol="TESTA", market="NASDAQ", category="core", company_name="Testa Corp"),
    )


@pytest.mark.asyncio
async def test_plans_list_and_detail_have_name_or_null(api):
    await _seed_names()
    plan = await mk_plan(api, symbol="TESTA")
    plan2 = await mk_plan(api, symbol="TESTB")
    rows = {p["symbol"]: p for p in (await api.get("/api/v1/plans", headers=hdr())).json()["plans"]}
    assert rows["TESTA"]["name"] == "Testa Corp"
    assert "name" in rows["TESTB"] and rows["TESTB"]["name"] is None     # 이름 없음 · 키는 있음
    d = (await api.get(f"/api/v1/plans/{plan['id']}", headers=hdr())).json()
    assert d["plan"]["name"] == "Testa Corp"
    d2 = (await api.get(f"/api/v1/plans/{plan2['id']}", headers=hdr())).json()
    assert d2["plan"]["name"] is None
    assert d["plan"]["symbol"] == "TESTA"                                # 기존 키는 그대로


@pytest.mark.asyncio
async def test_judgments_list_has_name(api, db):
    from backend.services.db import get_session
    from backend.services.models import UserJudgment

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(UserJudgment))
        s.add(UserJudgment(ticker="000001", page_source="t", hypothesis_id="h", thesis_md="x", horizon_days=5, mood="cool", market_regime="x"))
        s.add(UserJudgment(ticker="000007", page_source="t", hypothesis_id="h", thesis_md="x", horizon_days=5, mood="cool", market_regime="x"))
    r = await api.get("/api/v1/judgments?days=30", headers=hdr())
    assert r.status_code == 200, r.text
    by = {j["ticker"]: j for j in r.json()}
    assert by["000001"]["name"] == "테스트전자"
    assert "name" in by["000007"] and by["000007"]["name"] is None


@pytest.mark.asyncio
async def test_rulebook_invalidation_hits_has_name(api, db):
    from backend.services.db import get_session
    from backend.services.models import UserJudgment

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(UserJudgment))
        s.add(UserJudgment(ticker="000001", page_source="t", hypothesis_id="h", thesis_md="x", horizon_days=5, mood="cool",
                           market_regime="x", invalidation_hit_ts=datetime.utcnow()))
    r = await api.get("/api/v1/rulebook/invalidation-hits")
    assert r.status_code == 200, r.text
    assert r.json()[0]["name"] == "테스트전자"


@pytest.mark.asyncio
async def test_sniper_signal_history_has_name(api, db):
    from backend.services.db import get_session
    from backend.services.models import SniperSignal

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(SniperSignal))
        s.add(SniperSignal(ticker="000001", detected_at=datetime.now(timezone.utc)))
        s.add(SniperSignal(ticker="000008", detected_at=datetime.now(timezone.utc)))
    r = await api.get("/api/v1/sniper/signals/recent?hours=1")
    by = {x["ticker"]: x for x in r.json()}
    assert by["000001"]["name"] == "테스트전자" and by["000008"]["name"] is None


@pytest.mark.asyncio
async def test_powderkeg_events_and_watchlist_signals_have_name(api, db):
    from backend.services.db import get_session
    from backend.services.models import PowderKegEvent, WatchlistSignal

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(PowderKegEvent))
        await s.execute(delete(WatchlistSignal))
        s.add(PowderKegEvent(ticker="000001", event_type="A1", source="dart", title="가짜 공시", detected_at=datetime.now(timezone.utc)))
        s.add(WatchlistSignal(ticker="000001", source="news_x", signal_type="headline", intensity=1.0, trade_date="2026-11-19",
                              detected_at=datetime.now(timezone.utc)))
    ev = (await api.get("/api/v1/powderkeg/events?hours=1")).json()
    assert ev["items"][0]["name"] == "테스트전자" and ev["items"][0]["ticker"] == "000001"
    sg = (await api.get("/api/v1/watchlist/signals?hours=1")).json()
    assert sg["items"][0]["name"] == "테스트전자"


@pytest.mark.asyncio
async def test_broker_link_codes_table_has_us_name(api, db):
    from backend.services.db import get_session
    from backend.services.models import TossStockCode

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(TossStockCode))
        s.add(TossStockCode(symbol="TESTA", toss_code=None, source="api", verified=False))
    r = await api.get("/api/v1/broker-links/codes", headers=hdr())
    assert r.status_code == 200, r.text
    assert r.json()["codes"][0]["name"] == "Testa Corp"


@pytest.mark.asyncio
async def test_gate_blocked_recent_has_name(api, db):
    from backend.services.db import get_session
    from backend.services.models import PrinciplesGateBlockLog

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(PrinciplesGateBlockLog))
        s.add(PrinciplesGateBlockLog(ticker="000001", source="t", reason="not_pass"))
    r = await api.get("/api/v1/principles/gate/blocked-recent")
    assert r.status_code == 200, r.text
    assert r.json()["recent"][0]["name"] == "테스트전자"


@pytest.mark.asyncio
async def test_today_judgments_due_has_name(db):
    from backend.api.routes import today as T
    from backend.services.db import get_session
    from backend.services.models import UserJudgment

    await _seed_names()
    async with get_session() as s:
        await s.execute(delete(UserJudgment))
        s.add(UserJudgment(ticker="000001", page_source="t", hypothesis_id="h", thesis_md="x", horizon_days=1, mood="cool",
                           market_regime="x", ts=datetime.utcnow() - timedelta(days=30)))
    rows = await T._judgments_due(datetime.now().date())
    assert rows and rows[0].name == "테스트전자"


# ───────────────────────── 텔레그램 문장 ─────────────────────────

def test_us_stock_text_and_cut_at_24():
    assert at.us_stock("TESTA", "Testa Corp") == "TESTA · Testa Corp"
    assert at.us_stock("TESTA", None) == "TESTA"
    assert at.us_stock("TESTA", "  ") == "TESTA"
    assert at.us_stock("TESTA", "TESTA") == "TESTA"                       # 이름이 티커와 같으면 티커만
    long = "A" * 30
    out = at.us_stock("TESTA", long)
    assert out == "TESTA · " + "A" * 24 + "…"
    assert at.us_stock("TESTA", "A" * 24) == "TESTA · " + "A" * 24         # 24자 딱 맞으면 자르지 않음
    assert at.us_stock("TESTA", "A&B Co") == "TESTA · A&amp;B Co"          # HTML 이스케이프


def _pick(**kw):
    base = dict(rank=1, ticker="TESTA", company_name="Testa Corp", current_price=10.0, total_score=70.0,
                manipulation_risk=1, risk_level="low", risk_warning=None, thesis="가짜 근거",
                buy_price_market=10.0, buy_price_limit_3pct=9.7, buy_price_limit_7pct=9.3)
    base.update(kw)
    return SimpleNamespace(**base)


def test_moonshot_and_crazy_alert_show_ticker_and_company_title_has_no_name():
    from backend.services import notifier as nm

    t1, b1 = nm.format_moonshot_alert([_pick(), _pick(rank=2, ticker="TESTB", company_name=None)])
    assert "1. TESTA · Testa Corp " in b1 and "2. TESTB " in b1 and "TESTB ·" not in b1
    assert "Testa" not in t1
    t2, b2 = nm.format_crazy_alert([_pick(company_name="C" * 40)])
    assert "1. TESTA · " + "C" * 24 + "… " in b2
    assert "Testa" not in t2 and "C" * 5 not in t2


def test_sector_alert_name_and_code():
    from backend.services import notifier as nm

    it = SimpleNamespace(rank=1, name="테스트전자", ticker="000001", current_price=1000.0, price_source="live",
                         entry_price=900.0, entry_status="x", point_price=1100.0, point_pct=10.0, horizon_months=6)
    t, b = nm.format_sector_leaders_alert([it], "0.6")
    assert "1. 테스트전자(000001) 1,000원" in b
    assert "테스트전자" not in t


def test_draft_summary_shows_company_after_ticker_only_in_body():
    from backend.execution.plan import drafts as dr

    w = SimpleNamespace(opens="11/20 09:00", ends="11/20 12:00")
    made = SimpleNamespace(action="create", symbol="TESTA", window=w, warnings=[], reasons=[])
    ex = SimpleNamespace(action="exclude", symbol="TESTB", window=None, warnings=[], reasons=["r"])
    title, body = dr.build_summary([made, ex], [], {"TESTA": "Testa Corp"})
    assert "TESTA · Testa Corp · 진입 창" in body and "제외: TESTB(r)" in body
    assert "Testa" not in title
    assert dr.build_summary([made], [])[1].startswith("TESTA · 진입 창")      # 이름 없으면 티커만 (기존 모양)


@pytest.mark.asyncio
async def test_plan_engine_alert_line_uses_remembered_name_only_and_title_has_none(plan_db, monkeypatch):
    from backend.execution.plan.models import Plan
    from backend.tests.plan_fakes import FakeRaw, make_engine

    alerts = []
    eng = make_engine(FakeRaw(), alerts=alerts)
    sent = [(a[1], a[2], a[3]) for a in []]
    plan = Plan(id=7, mode="live", source="manual", symbol="TESTA", state="DRAFT", revision=1)

    async def must_not_query(*a, **k):
        raise AssertionError("알림이 새 이름 조회를 기다리면 안 됨")

    monkeypatch.setattr(sn, "lookup_names", must_not_query)
    monkeypatch.setattr(sn, "lookup_us_names", must_not_query)
    await eng._alert(plan, "info", "제목", "본문")
    sent = [(a[1], a[2], a[3]) for a in alerts]
    assert sent[-1][1] == "계획 번호 7\n종목 TESTA\n본문"                 # 기억에 없으면 티커만
    sn._memo[("US", "TESTA")] = (time.monotonic(), "Testa Corp")
    await eng._alert(plan, "info", "제목", "본문")
    sent = [(a[1], a[2], a[3]) for a in alerts]
    assert sent[-1][1] == "계획 번호 7\n종목 TESTA · Testa Corp\n본문"
    assert sent[-1][0] == "제목"                                          # 제목에는 이름 없음
    assert sent[0][0] == sent[1][0]                                       # 이름 유무가 바뀌어도 제목(재발송 열쇠) 같음


@pytest.mark.asyncio
async def test_exit_approx_alert_is_detached_and_does_not_wait_for_name_lookup(monkeypatch):
    from backend.discovery.live_tape import exit as ex
    from backend.services import notifier as nm

    ex._approx_alerted.clear()
    ex._bg_alerts.clear()
    gate = asyncio.Event()
    sent = []

    async def slow_name(ticker):
        await gate.wait()                                                 # 이름 조회가 끝나지 않는 상황
        return "테스트전자"

    async def fake_warning(self, title, body, **kw):
        sent.append((title, body))
        return True

    monkeypatch.setattr(sn, "lookup_kr_name", slow_name)
    monkeypatch.setattr(nm.TelegramNotifier, "send_warning", fake_warning)
    t0 = time.monotonic()
    ex._alert_approx_once(1, "000001", 12, 30)          # 동기 호출 · 팔 수량을 돌려주기 전 단계
    assert time.monotonic() - t0 < 0.1 and sent == []   # 조회를 기다리지 않고 바로 돌아옴
    assert len(ex._bg_alerts) == 1                       # 참조를 잡아 둠
    ex._alert_approx_once(1, "000001", 12, 30)          # 같은 신호 두 번째는 보내지 않음
    assert len(ex._bg_alerts) == 1
    gate.set()
    await asyncio.sleep(0.05)
    assert len(sent) == 1 and "테스트전자(000001)" in sent[0][1] and "12주" in sent[0][1]
    assert sent[0][0] == "청산 수량 짐작"                  # 제목은 그대로 (이름 없음)
    assert ex._bg_alerts == set()                        # 끝나면 참조 지움


@pytest.mark.asyncio
async def test_exit_approx_alert_exception_is_caught_and_name_lookup_miss_keeps_message(monkeypatch):
    from backend.discovery.live_tape import exit as ex
    from backend.services import notifier as nm

    ex._approx_alerted.clear()
    sent = []

    async def no_name(ticker):
        return None

    async def fake_warning(self, title, body, **kw):
        sent.append(body)
        return True

    monkeypatch.setattr(sn, "lookup_kr_name", no_name)
    monkeypatch.setattr(nm.TelegramNotifier, "send_warning", fake_warning)
    ex._alert_approx_once(2, "000001", 0, 30)
    await asyncio.sleep(0.05)
    assert sent and sent[0].startswith("000001 (종목명 확인 안 됨) 청산에서")   # 이름 없으면 기존 모양 + 내용 그대로

    async def boom(self, title, body, **kw):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(nm.TelegramNotifier, "send_warning", boom)
    ex._alert_approx_once(3, "000001", 5, 30)
    await asyncio.sleep(0.05)                                             # 예외가 밖으로 새지 않음 (작업 안에서 잡음)
    assert ex._bg_alerts == set()


@pytest.mark.asyncio
async def test_runner_tick_prereads_names_in_background(plan_db, monkeypatch):
    from backend.execution.plan import runner as rn
    from backend.execution.plan.models import Plan
    from backend.services.db import get_session

    async with get_session() as s:
        s.add(Plan(mode="live", source="manual", symbol="TESTA", state="HOLDING", revision=1))
    warmed = []
    monkeypatch.setattr(sn, "warm_names_bg", lambda codes: warmed.append(list(codes)))
    r = rn.PlanExecutor.__new__(rn.PlanExecutor)

    async def noop(*a, **k):
        return None

    r.handle_switch_changes = noop
    r.process_requests = noop
    r.gs = get_session
    await r.tick_once()
    assert warmed == [["TESTA"]]
