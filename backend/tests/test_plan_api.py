"""1116-01 · 계획 API 인증 · 확인 코드 · 스위치 시험 (가짜 토큰 · 가짜 확인 코드 발송 · 토스 호출 0)."""
from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient

from backend.execution.plan import switches as sw
from backend.tests.plan_fakes import plan_db  # noqa: F401

TOKEN = "plan_api_test_token_32_chars_long_0"
OK_ORIGIN = {"Origin": "http://localhost:4000"}
BAD_ORIGIN = {"Origin": "https://evil.example.com"}
PARAMS = {"buy_watch": 9.5, "buy_order": 9.5, "qty": 60, "ladder_pcts": [0.03, 0.05, 0.07]}


class Phone:
    """대표 휴대폰 (텔레그램) · 보낸 코드를 시험이 읽는다."""

    def __init__(self):
        self.msgs = []

    async def send(self, title, body):
        self.msgs.append((title, body))
        return True

    @property
    def code(self):
        return re.search(r"확인 코드: (\d{6})", self.msgs[-1][1]).group(1)


@pytest.fixture
async def api(plan_db, monkeypatch):
    from backend.api.routes import plans as plans_mod
    from backend.execution.brokers import toss_client

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    monkeypatch.setenv("PLAN_CONFIRM_HMAC_KEY", "test-only-hmac-key-not-a-secret")
    monkeypatch.setenv("PLAN_MAX_ORDER_USD", "1000")
    monkeypatch.setenv("PLAN_TOTAL_CAP_USD", "5000")
    monkeypatch.setenv("PLAN_TEST_MAX_USD", "100")
    phone = Phone()
    monkeypatch.setattr(plans_mod, "_send_code", phone.send)

    async def _noalert(*a, **k):
        return None

    monkeypatch.setattr(plans_mod, "_alert", _noalert)
    monkeypatch.setattr(plans_mod, "_kill_state", lambda: (False, True))
    monkeypatch.setattr(toss_client, "get_toss_client", lambda: pytest.fail("화면 서버는 토스를 부르면 안 됨"))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.phone = phone
        yield ac


def cookie(ac):
    ac.cookies.set("sniper_session", TOKEN)


def hdr():
    return {"X-API-Token": TOKEN}


async def mk_plan(ac, mode="paper", symbol="TESTA"):
    cookie(ac)
    r = await ac.post("/api/v1/plans", json={"symbol": symbol, "mode": mode, "params": PARAMS}, headers=OK_ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["plan"]


# ── 로그아웃 상태 · 모든 계획 API 401 ───────────────────────────────

async def test_logged_out_every_plan_route_is_401(api):
    from backend.api.main import app

    spec = app.openapi()["paths"]
    plan_paths = {p: m for p, m in spec.items() if p.startswith("/api/v1/plans")}
    assert len(plan_paths) >= 12
    n = 0
    for path, methods in plan_paths.items():
        for method in methods:
            url = re.sub(r"\{[^}]+\}", "1", path)
            r = await api.request(method.upper(), url, json={} if method != "get" else None)
            assert r.status_code == 401, f"{method.upper()} {path} → {r.status_code}"
            n += 1
    assert n == sum(len(m) for m in plan_paths.values()) and n >= 14


async def test_wrong_token_is_401(api):
    api.cookies.set("sniper_session", "wrong")
    assert (await api.get("/api/v1/plans")).status_code == 401


# ── 쿠키 전용 동작 ─────────────────────────────────────────────

COOKIE_ONLY = [
    ("post", "/api/v1/plans/switches/live/challenge", {}),
    ("post", "/api/v1/plans/switches/live", {"on": False}),
    ("post", "/api/v1/plans/switches/paper", {"on": False}),
    ("post", "/api/v1/plans/confirm/challenge", {"action": "approve", "plan_id": 1}),
    ("post", "/api/v1/plans/1/approve", {}),
    ("post", "/api/v1/plans/1/resume", {}),
]


@pytest.mark.parametrize("method,path,body", COOKIE_ONLY)
async def test_cookie_only_actions_reject_header_token_and_bad_origin(api, method, path, body):
    r = await api.request(method.upper(), path, json=body, headers=hdr())
    assert r.status_code == 403                                                   # 헤더 토큰은 403
    cookie(api)
    r = await api.request(method.upper(), path, json=body, headers=BAD_ORIGIN)
    assert r.status_code == 403                                                   # Origin 다름 403
    r = await api.request(method.upper(), path, json=body)
    assert r.status_code == 403                                                   # Origin 없음 403


async def test_reads_work_with_header_and_cookie_without_origin(api):
    assert (await api.get("/api/v1/plans", headers=hdr())).status_code == 200
    cookie(api)
    assert (await api.get("/api/v1/plans/executor/status")).status_code == 200


async def test_create_and_stop_allow_header_but_cookie_needs_origin(api):
    r = await api.post("/api/v1/plans", json={"symbol": "TESTA", "mode": "paper", "params": PARAMS}, headers=hdr())
    assert r.status_code == 200                                                    # 헤더는 Origin 검사 없음
    pid = r.json()["plan"]["id"]
    api.cookies.clear()
    cookie(api)
    assert (await api.post("/api/v1/plans", json={"symbol": "TESTB", "mode": "paper", "params": {}})).status_code == 403
    api.cookies.clear()
    assert (await api.post(f"/api/v1/plans/{pid}/stop", headers=hdr())).status_code == 200   # 정지는 헤더 허용


async def test_stop_keeps_sell_legs_and_queues_buy_cancel(api):
    from sqlalchemy import select

    from backend.execution.plan.models import Plan, PlanLeg, PlanRequest
    from backend.services.db import get_session

    plan = await mk_plan(api)
    async with get_session() as s:
        p = await s.get(Plan, plan["id"])
        p.state = "HOLDING"
        s.add(PlanLeg(plan_id=p.id, role="sl", seq=1, qty=6, watch_price=9.0, order_price=8.9, status="WATCHING", toss_id="X"))
    api.cookies.clear()                                    # 헤더로만 호출
    r = await api.post(f"/api/v1/plans/{plan['id']}/stop", headers=hdr())
    assert r.json()["halted"] is True
    async with get_session() as s:
        assert (await s.scalars(select(PlanLeg).where(PlanLeg.status == "WATCHING"))).first() is not None
        assert (await s.scalars(select(PlanRequest).where(PlanRequest.action == "stop"))).first() is not None


# ── 승인 · 확인 코드 ────────────────────────────────────────────

async def test_paper_approval_needs_no_code_and_aside_may_approve(api):
    plan = await mk_plan(api)
    r = await api.post(f"/api/v1/plans/{plan['id']}/approve", json={"approver": "Aside(대표 지시)"}, headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json()["plan"]["state"] == "APPROVED"
    assert r.json()["plan"]["approved_by"] == "Aside(대표 지시)"


async def test_live_approval_requires_code_and_rejects_aside(api):
    plan = await mk_plan(api, "live")
    url = f"/api/v1/plans/{plan['id']}/approve"
    r = await api.post(url, json={}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "code_required"       # 코드 없이 거부
    r = await api.post(url, json={"approver": "Aside(대표 지시)"}, headers=OK_ORIGIN)
    assert r.status_code == 400                                                            # Aside 는 실전 승인 불가
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    assert c.status_code == 200 and "code" not in c.text.lower().replace("challenge", "")  # 응답에 코드 없음
    bad = await api.post(url, json={"challenge_id": c.json()["challenge_id"], "code": "000000" if api.phone.code != "000000" else "111111"}, headers=OK_ORIGIN)
    assert bad.status_code == 400 and bad.json()["detail"]["reason"] == "wrong"
    ok = await api.post(url, json={"challenge_id": c.json()["challenge_id"], "code": api.phone.code}, headers=OK_ORIGIN)
    assert ok.status_code == 200 and ok.json()["plan"]["state"] == "APPROVED"
    again = await api.post(url, json={"challenge_id": c.json()["challenge_id"], "code": api.phone.code}, headers=OK_ORIGIN)
    assert again.status_code in (400, 409)                                                 # 재사용 거부


async def test_code_for_other_plan_or_action_or_live_on_is_rejected(api):
    a = await mk_plan(api, "live", "TESTA")
    b = await mk_plan(api, "live", "TESTB")
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": a["id"]}, headers=OK_ORIGIN)
    code_a = api.phone.code
    r = await api.post(f"/api/v1/plans/{b['id']}/approve", json={"challenge_id": c.json()["challenge_id"], "code": code_a}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "mismatch"           # 다른 계획 번호
    r = await api.post(f"/api/v1/plans/{a['id']}/resume", json={"challenge_id": c.json()["challenge_id"], "code": code_a}, headers=OK_ORIGIN)
    assert r.status_code in (400, 409)                                                     # 다른 동작 (정지 상태도 아님)
    lc = await api.post("/api/v1/plans/switches/live/challenge", json={}, headers=OK_ORIGIN)
    r = await api.post(f"/api/v1/plans/{a['id']}/approve", json={"challenge_id": lc.json()["challenge_id"], "code": api.phone.code}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "mismatch"           # 실거래 켜기 코드로 승인 거부


async def test_edit_after_code_request_invalidates_the_code(api):
    plan = await mk_plan(api, "live")
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    code = api.phone.code
    r = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"qty": 66}}, headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json()["plan"]["revision"] == plan["revision"] + 1
    r = await api.post(f"/api/v1/plans/{plan['id']}/approve", json={"challenge_id": c.json()["challenge_id"], "code": code}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "changed"             # 값이 바뀌었습니다


async def test_non_draft_values_cannot_be_edited(api):
    plan = await mk_plan(api)
    await api.post(f"/api/v1/plans/{plan['id']}/approve", json={}, headers=OK_ORIGIN)
    api.cookies.clear()
    r = await api.patch(f"/api/v1/plans/{plan['id']}", json={"values": {"qty": 12}}, headers=hdr())
    assert r.status_code == 409


async def test_confirm_challenge_for_paper_plan_is_refused(api):
    plan = await mk_plan(api)
    r = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    assert r.status_code == 400


async def test_test_plan_needs_code_and_respects_test_cap(api):
    cookie(api)
    big = await api.post("/api/v1/plans", json={"symbol": "TESTA", "mode": "test", "params": {**PARAMS, "qty": 60}}, headers=OK_ORIGIN)
    pid = big.json()["plan"]["id"]
    c = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": pid}, headers=OK_ORIGIN)
    r = await api.post(f"/api/v1/plans/{pid}/approve", json={"challenge_id": c.json()["challenge_id"], "code": api.phone.code}, headers=OK_ORIGIN)
    assert r.status_code == 409 and "상한" in r.json()["detail"]                          # 570 > 시험 상한 100


async def test_one_open_plan_per_symbol(api):
    await mk_plan(api, "paper", "TESTA")
    await api.post("/api/v1/plans/1/approve", json={}, headers=OK_ORIGIN)
    cookie(api)
    r = await api.post("/api/v1/plans", json={"symbol": "TESTA", "mode": "paper", "params": PARAMS}, headers=OK_ORIGIN)
    assert r.status_code == 409


# ── 스위치 ─────────────────────────────────────────────────────

async def test_switches_default_off_and_live_on_needs_code_and_reason(api):
    cookie(api)
    st = (await api.get("/api/v1/plans/executor/status")).json()
    assert st["switches"] == {"live": False, "paper": False}
    r = await api.post("/api/v1/plans/switches/live", json={"on": True, "reason": "시험"}, headers=OK_ORIGIN)
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "code_required"        # 코드 없이 켜기 거부
    c = await api.post("/api/v1/plans/switches/live/challenge", json={}, headers=OK_ORIGIN)
    r = await api.post("/api/v1/plans/switches/live", json={"on": True, "reason": "", "challenge_id": c.json()["challenge_id"], "code": api.phone.code}, headers=OK_ORIGIN)
    assert r.status_code == 400                                                              # 까닭 필수
    r = await api.post("/api/v1/plans/switches/live", json={"on": True, "reason": "첫 소액 시험", "challenge_id": c.json()["challenge_id"], "code": api.phone.code}, headers=OK_ORIGIN)
    assert r.status_code == 200 and r.json() == {"live": True, "previous": False}
    assert sw.read_switches()["live"] is True
    st = (await api.get("/api/v1/plans/executor/status")).json()
    assert st["switches"]["live"] is True and st["last_change"]["reason"] == "첫 소액 시험"
    # 끄기는 코드 없이 한 번 누름
    r = await api.post("/api/v1/plans/switches/live", json={"on": False}, headers=OK_ORIGIN)
    assert r.status_code == 200 and sw.read_switches()["live"] is False


async def test_paper_switch_on_needs_reason_not_code(api):
    cookie(api)
    assert (await api.post("/api/v1/plans/switches/paper", json={"on": True}, headers=OK_ORIGIN)).status_code == 400
    r = await api.post("/api/v1/plans/switches/paper", json={"on": True, "reason": "모의 시작"}, headers=OK_ORIGIN)
    assert r.status_code == 200 and sw.read_switches()["paper"] is True


async def test_daily_lock_blocks_codes_but_stop_and_off_still_work(api):
    plan = await mk_plan(api, "live")
    cookie(api)
    c = await api.post("/api/v1/plans/switches/live/challenge", json={}, headers=OK_ORIGIN)
    for _ in range(5):
        await api.post("/api/v1/plans/switches/live", json={"on": True, "reason": "x", "challenge_id": c.json()["challenge_id"], "code": "abcdef"}, headers=OK_ORIGIN)
    c2 = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    for _ in range(5):
        await api.post(f"/api/v1/plans/{plan['id']}/approve", json={"challenge_id": c2.json()["challenge_id"], "code": "abcdef"}, headers=OK_ORIGIN)
    lock = await api.post("/api/v1/plans/switches/live/challenge", json={}, headers=OK_ORIGIN)
    assert lock.status_code == 423                                                           # 합산 10번 → 켜기 잠금
    lock2 = await api.post("/api/v1/plans/confirm/challenge", json={"action": "approve", "plan_id": plan["id"]}, headers=OK_ORIGIN)
    assert lock2.status_code == 423
    assert (await api.post("/api/v1/plans/switches/live", json={"on": False}, headers=OK_ORIGIN)).status_code == 200
    api.cookies.clear()
    assert (await api.post(f"/api/v1/plans/{plan['id']}/stop", headers=hdr())).status_code == 200


async def test_screen_server_never_calls_toss_and_health_exposes_only_a_number(api):
    r = await api.get("/health")
    body = r.json()
    assert set(body) == {"status", "service", "plan_executor_heartbeat_age_sec"}
    assert body["plan_executor_heartbeat_age_sec"] is None or isinstance(body["plan_executor_heartbeat_age_sec"], int)
    from backend.api.routes.plans import _NoBroker
    import asyncio

    with pytest.raises(Exception):
        asyncio.get_event_loop().run_until_complete(_NoBroker().cond_create(None))


async def test_detail_shows_invariant_and_values(api):
    plan = await mk_plan(api)
    r = await api.get(f"/api/v1/plans/{plan['id']}", headers=hdr())
    d = r.json()
    assert d["plan"]["state"] == "DRAFT" and d["invariant"]["status"] in ("ok", "shortage") and "content_hash" in d
    assert (await api.get("/api/v1/plans/999", headers=hdr())).status_code == 404
