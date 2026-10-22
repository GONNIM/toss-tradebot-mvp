"""알림 고장 수리 0순위 (F1~F6) 회귀 테스트.

실 DB·실 텔레그램을 쓰지 않는다 (notifier mock · 상태 파일은 tmp).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

TOKEN = "alerts_p0_test_token_32chars_000000"


# ─── F1 · apewisdom 패키지가 모듈을 가리지 않는다 ───
def test_f1_apewisdom_package_exports_both():
    from backend.discovery.data_sources.apewisdom import (
        ApewisdomClient,
        MentionStats,
        fetch_filter,
    )

    assert callable(fetch_filter)
    assert MentionStats is not None
    assert ApewisdomClient.__name__ == "ApewisdomClient"


def test_f1_cron_build_clients_no_import_error():
    from backend.discovery.data_sources.apewisdom import ApewisdomClient
    from backend.scheduler import cron

    clients = cron._build_clients()
    assert isinstance(clients, dict)
    assert isinstance(clients["apewisdom"], ApewisdomClient)


def test_f1_meme_path_import_regression():
    from backend.discovery.meme_watch import social_signal  # noqa: F401


# ─── F2 · Sector Leaders None 칸 ───
def _sector_item(**kw):
    base = dict(
        rank=1, name="테스트", ticker="000000", attractiveness=0.7,
        item="반도체", price_source="live", current_price=10000.0,
        entry_price=9500.0, entry_status="🟢 진입 가능",
        point_price=12000.0, point_pct=20.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_f2_overheat_item_entry_price_none_formats():
    from backend.services.notifier import format_sector_leaders_alert

    it = _sector_item(entry_price=None, entry_gap_pct=None, entry_status="🔴 과열")
    title, body = format_sector_leaders_alert([it], "0.6")
    assert "Sector Leaders" in title
    assert "진입가: -  (🔴 과열)" in body
    assert "None" not in body


def test_f2_normal_item_unchanged():
    from backend.services.notifier import format_sector_leaders_alert

    _, body = format_sector_leaders_alert([_sector_item()], "0.6")
    assert "진입가: 9,500원" in body
    assert "예측수익가: 12,000원  (+20.0%)" in body


# ─── F3 · A3 본문에 '<' 가 없다 / 400 본문 로그 ───
def test_f3_a3_body_has_no_angle_bracket():
    from backend.powderkeg.triggers import _body_for_direction

    body = _body_for_direction("observed_negative", "기본")
    assert "<" not in body
    assert ">" not in body
    assert "미만" in body and "이상" in body


@pytest.mark.real_notifier_send  # httpx.AsyncClient 를 아래에서 가짜로 바꾸므로 외부 발송 없음
@pytest.mark.asyncio
async def test_f3_http_error_logs_response_body_not_token(monkeypatch, caplog):
    import httpx

    from backend.services import notifier as nmod

    secret = "123456:SECRET_TOKEN_VALUE"
    n = nmod.TelegramNotifier.__new__(nmod.TelegramNotifier)
    n.config = SimpleNamespace(bot_token=secret, chat_id="1")
    n._dedupe_check = lambda key: True
    n._hash = lambda t, b: "k"

    class _Resp:
        status_code = 400
        text = "Bad Request: can't parse entities"

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None):
            req = httpx.Request("POST", url)
            resp = httpx.Response(400, text=_Resp.text, request=req)
            return resp

    monkeypatch.setattr(nmod.httpx, "AsyncClient", _Client)
    with caplog.at_level("ERROR"):
        ok = await n.send(nmod.Level.INFO, "t", "b", force=True)
    assert ok is False
    log = caplog.text
    assert "can't parse entities" in log
    assert secret not in log


# ─── F5 · sniper kill-switch 엔드포인트 ───
@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    from backend.execution import kill_switch as ks
    from backend.services.db import get_session, init_db
    from backend.services.models import SniperApiAccess

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    notifier = SimpleNamespace(send_critical=_noop_send)
    switch = ks.KillSwitch(state_path=tmp_path / "kill_switch.json", notifier=notifier)
    monkeypatch.setattr(ks, "_switch", switch)
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SniperApiAccess))
        await session.commit()

    from backend.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.switch = switch  # type: ignore[attr-defined]
        yield ac


async def _noop_send(title, body):
    return True


@pytest.mark.asyncio
async def test_f5_kill_switch_requires_auth(client):
    r = await client.get("/api/v1/sniper/kill-switch/status")
    assert r.status_code in (401, 403)
    r = await client.delete("/api/v1/sniper/kill-switch")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_f5_status_and_deactivate_with_token(client):
    h = {"X-API-Token": TOKEN}
    r = await client.get("/api/v1/sniper/kill-switch/status", headers=h)
    assert r.status_code == 200 and r.json()["active"] is False

    client.switch.activate(reason="test", actor="auto:test")
    r = await client.get("/api/v1/sniper/kill-switch/status", headers=h)
    assert r.json()["active"] is True and r.json()["reason"] == "test"

    r = await client.delete("/api/v1/sniper/kill-switch?actor=user:tester", headers=h)
    assert r.status_code == 200
    assert r.json() == {"active": False, "deactivated_by": "user:tester"}

    r = await client.get("/api/v1/sniper/kill-switch/status", headers=h)
    body = r.json()
    assert body["active"] is False and body["deactivated_by"] == "user:tester"


def test_f5_alert_body_points_to_new_path():
    import inspect

    from backend.execution import kill_switch as ks

    src = inspect.getsource(ks.KillSwitch._notify_urgent)
    assert "/api/v1/sniper/kill-switch" in src
    assert "/execution/kill-switch" not in src


# ─── F6 · 잡 실패 warning 1일 1회 ───
@pytest.mark.asyncio
async def test_f6_failure_warning_once_per_day(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod

    calls = []

    class _FakeNotifier:
        async def send_warning(self, title, body):
            calls.append((title, body))
            return True

    monkeypatch.setattr(nmod, "TelegramNotifier", _FakeNotifier)
    monkeypatch.setattr(cron, "_failure_alerted", {})

    async def boom():
        raise RuntimeError("x" * 500)

    monkeypatch.setattr(cron, "run_crazy_picks_job", boom)
    await cron.job_crazy_picks()
    await cron.job_crazy_picks()
    assert len(calls) == 1
    title, body = calls[0]
    assert title == "Crazy Picks 실패"
    assert body.startswith("RuntimeError: ") and len(body) < 260
    assert body.count("x") == 200  # 메시지는 200자로 잘림

    # 다른 잡은 별도로 1회
    monkeypatch.setattr(cron, "run_moonshot_picks_job", boom)
    await cron.job_moonshot_picks()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_f6_new_day_alerts_again(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod

    calls = []

    class _FakeNotifier:
        async def send_warning(self, title, body):
            calls.append(title)
            return True

    monkeypatch.setattr(nmod, "TelegramNotifier", _FakeNotifier)
    monkeypatch.setattr(cron, "_failure_alerted", {"Sector Leaders 09:05": "2000-01-01"})

    async def boom(slot="default"):
        raise ValueError("fail")

    monkeypatch.setattr(cron, "run_sector_leaders_alert_job", boom)
    await cron.job_sector_leaders_alert_0905()
    assert calls == ["Sector Leaders 09:05 실패"]


@pytest.mark.asyncio
async def test_f6_alert_failure_does_not_raise(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod

    class _Bad:
        async def send_warning(self, title, body):
            raise RuntimeError("telegram down")

    monkeypatch.setattr(nmod, "TelegramNotifier", _Bad)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    await cron._alert_job_failure("Crazy Picks", ValueError("x"))


class _Rec:
    """send_warning 호출을 기록하는 가짜 notifier 팩토리."""

    def __init__(self, results):
        self.calls = []
        self._results = list(results)

    def __call__(self):
        outer = self

        class _N:
            async def send_warning(self, title, body):
                outer.calls.append((title, body))
                return outer._results.pop(0) if outer._results else True

        return _N()


@pytest.mark.asyncio
async def test_f6_body_is_html_escaped(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod

    rec = _Rec([True])
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    await cron._alert_job_failure("Crazy Picks", ValueError("bad <b> & x"))
    body = rec.calls[0][1]
    assert "&lt;b&gt;" in body and "&amp;" in body
    assert "<b>" not in body


@pytest.mark.asyncio
async def test_f6_body_masks_secrets(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod

    rec = _Rec([True])
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    await cron._alert_job_failure(
        "Crazy Picks", RuntimeError("GET https://x/y?token=abc123&a=1 failed")
    )
    body = rec.calls[0][1]
    assert "abc123" not in body
    assert "MASKED" in body


@pytest.mark.asyncio
async def test_f6_send_failure_not_recorded_retries_next_time(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as nmod

    rec = _Rec([False, True, True])
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    await cron._alert_job_failure("Crazy Picks", ValueError("a"))
    assert cron._failure_alerted == {}
    await cron._alert_job_failure("Crazy Picks", ValueError("a"))  # 재시도 → 성공
    assert len(rec.calls) == 2
    await cron._alert_job_failure("Crazy Picks", ValueError("a"))  # 이제 dedupe
    assert len(rec.calls) == 2


# ─── F5 actor 검증 · F2 음수 퍼센트 ───
@pytest.mark.asyncio
async def test_f5_actor_with_newline_rejected(client):
    h = {"X-API-Token": TOKEN}
    r = await client.delete("/api/v1/sniper/kill-switch?actor=a%0Ab", headers=h)
    assert r.status_code == 422


def test_f2_negative_pct_has_no_plus_minus():
    from backend.services.notifier import _fmt_pct, format_sector_leaders_alert

    assert _fmt_pct(-3.0) == "-3.0%"
    assert "+-" not in _fmt_pct(-3.0)
    assert _fmt_pct(2.0) == "+2.0%"
    _, body = format_sector_leaders_alert([_sector_item(point_pct=-4.0)], "0.6")
    assert "+-" not in body and "(-4.0%)" in body
