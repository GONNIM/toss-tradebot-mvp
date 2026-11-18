"""1116-01 · 웹소켓 클라이언트 · 7-6 sanity 시험 (가짜 서버 · 실제 토스 연결 0)."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest

from backend.execution.plan import sanity, ws
from backend.tests.plan_fakes import FakeRaw, Clock, make_engine, plan_db, seed_holding  # noqa: F401

D = Decimal


# ── 프레임 · 선언 ─────────────────────────────────────────────

def test_declaration_is_full_replace_array_with_us_and_kr_channels():
    d = json.loads(ws.build_declaration(["TESTB", "TESTA", "005930"], "r1"))
    assert d[0] == {"id": "r1"}
    assert {"type": "trade:us", "codes": ["TESTA", "TESTB"]} in d and {"type": "trade:kr", "codes": ["005930"]} in d
    assert json.loads(ws.build_declaration([])) == []                     # 빈 배열 = 전부 해제
    many = json.loads(ws.build_declaration([f"T{i:03d}" for i in range(150)]))
    assert sum(len(x["codes"]) for x in many) == 100                       # 연결당 100개


def test_parse_frames():
    t = ws.parse_frame(json.dumps({"type": "message", "topic": "trade:us:TESTA",
                                   "data": {"price": "243.26", "volume": "8", "timestamp": "x", "currency": "USD"}}))
    assert t == {"kind": "tick", "symbol": "TESTA", "price": "243.26"}     # 종목은 topic 3번째 칸
    assert ws.parse_frame('{"type":"pong"}')["kind"] == "pong"
    assert ws.parse_frame('{"type":"subscriptions","subscribed":["a"],"rejected":[{"target":"b"}]}')["rejected"] == [{"target": "b"}]
    assert ws.parse_frame('{"type":"error","error":{"code":"auth-revoked"}}') == {"kind": "error", "code": "auth-revoked"}
    assert ws.parse_frame("not json")["kind"] == "other" and ws.parse_frame("[1]")["kind"] == "other"


def test_backoff_doubles_with_jitter_and_caps():
    assert [ws.backoff_delay(a, lambda: 0) for a in (0, 1, 2, 3)] == [1, 2, 4, 8]
    assert ws.backoff_delay(10, lambda: 0) == 60 and ws.backoff_delay(1, lambda: 1) == 2.5


def test_price_store_age():
    t = {"v": 0.0}
    st = ws.PriceStore(clock=lambda: t["v"])
    st.put("TESTA", "10.5")
    t["v"] = 9
    assert st.fresh("TESTA") == D("10.5")
    t["v"] = 11
    assert st.fresh("TESTA") is None and st.get("TESTA")[1] == 11


# ── 가짜 연결로 흐름 시험 ─────────────────────────────────────

class FakeConn:
    def __init__(self, script=None):
        self.sent, self.q, self.closed = [], asyncio.Queue(), False
        for f in script or []:
            self.q.put_nowait(f if isinstance(f, str) else json.dumps(f))

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        return await self.q.get()

    async def close(self):
        self.closed = True


def tick(sym, price):
    return {"type": "message", "topic": f"trade:us:{sym}", "data": {"price": price, "volume": "1", "timestamp": "t", "currency": "USD"}}


async def _run_for(client, stop, secs):
    task = asyncio.create_task(client.run(stop))
    await asyncio.sleep(secs)
    stop.set()
    await asyncio.wait_for(task, 5)


async def test_subscribes_stores_ticks_sends_ping_and_closes():
    conn = FakeConn([{"type": "subscriptions", "subscribed": ["trade:us:TESTA"], "rejected": []}, tick("TESTA", "10.25")])
    seen = {}

    async def connect(url, headers):
        seen.update(url=url, headers=headers)
        return conn

    async def syms():
        return ["TESTA"]

    store = ws.PriceStore()
    c = ws.PlanWsClient(store, token_fn=lambda: "fake-token", symbols_fn=syms, connect=connect, ping_every=0.2)
    await _run_for(c, asyncio.Event(), 0.7)
    assert seen["url"] == ws.WS_URL and seen["headers"] == {"Authorization": "Bearer fake-token"}
    assert json.loads(conn.sent[0])[1] == {"type": "trade:us", "codes": ["TESTA"]}
    assert store.fresh("TESTA") == D("10.25")
    assert conn.sent.count("PING") >= 2                                    # 데이터가 흘러도 PING 은 계속
    assert conn.closed and c.status == "down"


async def test_resubscribes_when_symbol_set_changes_and_reports_rejected():
    conn = FakeConn([{"type": "subscriptions", "subscribed": [], "rejected": [{"target": "trade:us:ZZZ", "code": "stock-not-found"}]}])
    state = {"s": ["TESTA"]}

    async def connect(url, headers):
        return conn

    async def syms():
        return list(state["s"])

    c = ws.PlanWsClient(ws.PriceStore(), connect=connect, symbols_fn=syms, ping_every=30, poll_every=0.1)
    task = asyncio.create_task(c.run(stop := asyncio.Event()))
    await asyncio.sleep(0.3)
    state["s"] = ["TESTA", "TESTB"]
    await asyncio.sleep(1.3)
    stop.set()
    await asyncio.wait_for(task, 5)
    decls = [json.loads(m) for m in conn.sent if m != "PING"]
    assert len(decls) == 2 and decls[1][-1]["codes"] == ["TESTA", "TESTB"]    # 전체를 다시 선언 (덮어쓰기)
    assert c.rejected and c.rejected[0]["code"] == "stock-not-found"


@pytest.mark.parametrize("code", ["auth-revoked", "server-shutdown"])
async def test_error_frames_close_old_connection_then_reconnect_and_redeclare(code, monkeypatch):
    monkeypatch.setattr(ws, "backoff_delay", lambda a, r=None: 0.05)
    conns = [FakeConn([{"type": "error", "error": {"code": code}}]), FakeConn([tick("TESTA", "9.9")])]
    opened = []

    async def connect(url, headers):
        c = conns[len(opened)]
        opened.append(c)
        return c

    async def syms():
        return ["TESTA"]

    store = ws.PriceStore()
    c = ws.PlanWsClient(store, token_fn=lambda: "t", connect=connect, symbols_fn=syms, ping_every=30)
    await _run_for(c, asyncio.Event(), 0.6)
    assert len(opened) == 2 and conns[0].closed                             # 옛 연결을 먼저 닫음
    assert json.loads(conns[1].sent[0])[-1]["codes"] == ["TESTA"]           # 다시 선언
    assert store.fresh("TESTA") == D("9.9") and c.reconnects >= 1


async def test_connection_failure_retries_with_backoff(monkeypatch):
    monkeypatch.setattr(ws, "backoff_delay", lambda a, r=None: 0.05)
    attempts = []

    async def connect(url, headers):
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("down")
        return FakeConn([tick("TESTA", "1.5")])

    store = ws.PriceStore()
    c = ws.PlanWsClient(store, connect=connect, symbols_fn=None, ping_every=30)
    await _run_for(c, asyncio.Event(), 0.6)
    assert len(attempts) >= 3


async def test_rate_limit_error_waits_then_redeclares():
    conn = FakeConn([{"type": "error", "error": {"code": "rate-limit-exceeded"}}])
    slept = []

    async def fake_sleep(x):
        slept.append(x)

    async def connect(url, headers):
        return conn

    async def syms():
        return ["TESTA"]

    c = ws.PlanWsClient(ws.PriceStore(), connect=connect, symbols_fn=syms, ping_every=30, poll_every=0.1, sleep=fake_sleep)
    await _run_for(c, asyncio.Event(), 0.5)
    assert slept == [1.0]
    assert len([m for m in conn.sent if m != "PING"]) >= 2                  # 1초 뒤 다시 선언


async def test_real_local_server_handshake_header_declaration_and_ping():
    """진짜 웹소켓 서버(내 컴퓨터 안)로 헤더 · 선언 · PING 을 확인한다."""
    import websockets
    from websockets.asyncio.server import serve

    got = {"headers": None, "msgs": []}

    async def handler(sock):
        got["headers"] = sock.request.headers.get("Authorization")
        async for m in sock:
            got["msgs"].append(m)
            if m != "PING":
                await sock.send(json.dumps({"type": "subscriptions", "subscribed": ["trade:us:TESTA"], "rejected": []}))
                await sock.send(json.dumps(tick("TESTA", "12.34")))
            else:
                await sock.send('{"type":"pong"}')

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        async def syms():
            return ["TESTA"]

        store = ws.PriceStore()
        c = ws.PlanWsClient(store, token_fn=lambda: "fake-token", symbols_fn=syms, url=f"ws://127.0.0.1:{port}/ws/v1",
                            ping_every=0.2)
        await _run_for(c, asyncio.Event(), 0.8)
    assert got["headers"] == "Bearer fake-token"
    assert json.loads(got["msgs"][0])[-1] == {"type": "trade:us", "codes": ["TESTA"]}
    assert "PING" in got["msgs"] and store.fresh("TESTA") == D("12.34")


def test_idle_rule_constants_match_docs():
    assert ws.PING_EVERY_SEC == 60.0 and ws.IDLE_LIMIT_SEC == 180.0 and ws.PING_EVERY_SEC * 2 < ws.IDLE_LIMIT_SEC
    assert ws.WS_URL == "wss://openapi-ws.tossinvest.com/ws/v1"


# ── 7-6 sanity ─────────────────────────────────────────────────

def test_sanity_pure():
    assert sanity.check_band("9.0", "10") is None and sanity.check_band("6.0", "10") is None
    assert sanity.check_band("5.99", "10") and sanity.check_band("14.01", "10")
    assert sanity.check_tp1("12", "10") is None and sanity.check_tp1("40", "10") is None
    assert sanity.check_tp1("10", "10") and sanity.check_tp1("40.01", "10")
    assert sanity.check_trail("9.99", "10.00") is None
    assert "익절 뒤 대기" in sanity.check_trail("10.00", "10.00")


async def test_sanity_rejects_far_stop_registration_and_alerts_but_still_sells_crossed(plan_db):
    from backend.execution.plan.sessions import Values
    from backend.services.db import get_session

    raw = FakeRaw("10")
    raw.acct = 60
    eng = make_engine(raw)
    async with get_session() as s:
        plan = await seed_holding(s, eng)
        leg = await eng._register_leg(s, plan, 1, 20, Values(D("5.00"), D("4.90")), "regular")   # 현재가 10 의 −50%
        assert leg is None and raw.count("cond_create") == 0
        assert any(a[1] == "등록 거부 · 값 점검" for a in eng._alerts)
        raw.price = D("3")                                                    # 폭락 · 이미 넘은 다리는 즉시 매도 (막지 않음)
        await eng._register_leg(s, plan, 1, 20, Values(D("5.00"), D("4.90")), "regular")
        assert raw.count("limit_create") == 1


async def test_sanity_rejects_wild_buy_and_bad_tp1(plan_db):
    from backend.execution.plan import state
    from backend.services.db import get_session

    raw = FakeRaw("10")
    eng = make_engine(raw)
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="live", params={"buy_watch": 3.0, "buy_order": 3.0, "qty": 6})
        plan.state = state.APPROVED
        await eng.start_entry(s, plan)
        assert raw.calls == [] or all(c[0] != "cond_create" for c in raw.calls)
        assert any(a[1] == "등록 거부 · 값 점검" for a in eng._alerts)
    raw2 = FakeRaw("10")
    raw2.acct = 60
    eng2 = make_engine(raw2)
    async with get_session() as s:
        p = await seed_holding(s, eng2, symbol="TESTB", extra={"tp1_watch": 9.0, "tp1_order": 9.0})
        await eng2._tp1_step(s, p, True)
        await eng2._tp1_step(s, p, True)                                       # 같은 사유 알림은 한 번
        assert raw2.count("cond_create") == 0
        assert len([a for a in eng2._alerts if a[1] == "등록 거부 · 값 점검"]) == 1
