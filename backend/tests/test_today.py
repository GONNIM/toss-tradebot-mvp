"""1022-10 4단계 · GET /api/v1/today (공개 읽기 · 관리자 칸은 비로그인에 숨김 · 저장된 자료만)."""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

TOKEN = "today_home_test_token_32chars_0000"
H = {"X-API-Token": TOKEN}
NOW = datetime(2026, 10, 30, 1, 0, tzinfo=timezone.utc)  # KST 2026-10-30(금) 10:00
MIDNIGHT_UTC = datetime(2026, 10, 29, 15, 0)  # 오늘 KST 자정 (UTC naive)


@pytest.fixture
async def client(monkeypatch, tmp_path):
    from backend.api.routes import today
    from backend.discovery.activist import state as activist_state
    from backend.services import models as m
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    monkeypatch.delenv("TODAY_NEAR_STOP_PCT", raising=False)
    monkeypatch.setattr(activist_state, "_STATE_PATH", tmp_path / "activist_state.json")
    monkeypatch.setattr(today, "_now_utc", lambda: NOW)
    monkeypatch.setattr(today, "_server_tz", lambda: timezone.utc)  # 밈 알림 저장 시각 = 서버 로컬 · 기본 시험은 UTC 서버
    await init_db()
    async with get_session() as s:
        for tbl in (m.CrazyPick, m.MoonshotPick, m.HoldingSnapshot, m.UserJudgment, m.Watchlist, m.NotificationLog,
                    m.MemeAlertHistory, m.PowderKegEvent):
            await s.execute(delete(tbl))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _add(*rows):
    from backend.services.db import get_session

    async with get_session() as s:
        for r in rows:
            s.add(r)


def _sec(body, source):
    return next(x for x in body["candidates"] if x["source"] == source)


# ─── 비로그인 · 잠금 · 헤더 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anon_locked_no_leak_and_headers(client):
    from backend.services import models as m

    await _add(
        m.CrazyPick(pick_date="2026-10-29", rank=1, ticker="ZZCRAZY", composite_score=71.7, company_name="비밀크레이지"),
        m.MoonshotPick(pick_date="2026-10-29", rank=1, ticker="ZZMOON", composite_score=64.6),
        m.NotificationLog(category="system", dedupe_key="k", title="비밀잡 실패", result="sent", created_at=MIDNIGHT_UTC),
        m.HoldingSnapshot(symbol="777777", market="KR", trade_date=date(2026, 10, 29), kind="holding", qty=3, close=50.0),
        m.UserJudgment(ticker="888888", page_source="t", hypothesis_id="h", thesis_md="x", ts=datetime(2026, 10, 1, 8)),
        m.Watchlist(trade_date="2026-10-30", ticker="005930", rank=1, composite_score=70.0, name="삼성전자"),
    )
    r = await client.get("/api/v1/today")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store" and "cookie" in r.headers["vary"].lower()
    b = r.json()
    assert b["is_admin"] is False and b["today_kst"] == "2026-10-30" and b["fetched_at"] == "2026-10-30T01:00:00Z"
    assert b["failures"] is None and b["judgments_due"] is None and b["holding_alerts"] is None
    assert b["failures_scope"] and b["near_stop_pct"] == 5.0
    for k in ("crazy", "moonshot", "biotech"):
        sec = _sec(b, k)
        assert sec["locked"] is True and sec["as_of"] is None and sec["items"] == []
    assert _sec(b, "watchlist")["items"][0]["ticker"] == "005930"  # 공개 섹션은 보임
    for secret in ("ZZCRAZY", "ZZMOON", "비밀", "777777", "888888", "71.7", "64.6"):
        assert secret not in r.text


@pytest.mark.asyncio
async def test_anon_locked_rows_even_without_data(client):
    b = (await client.get("/api/v1/today")).json()
    assert [x["source"] for x in b["candidates"]] == ["watchlist", "powderkeg", "meme", "activist", "crazy", "moonshot", "biotech"]
    assert all(_sec(b, k)["locked"] for k in ("crazy", "moonshot", "biotech"))
    assert _sec(b, "watchlist")["items"] == [] and _sec(b, "watchlist")["as_of"] is None


@pytest.mark.asyncio
async def test_safety_public_values(client):
    b = (await client.get("/api/v1/today")).json()
    assert set(b["safety"]) == {"live_enabled", "sniper_enabled", "kill_switch_active", "order_target"}
    assert b["safety"]["order_target"] in ("paper", "toss")


# ─── 관리자 ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_unlocked_rows(client):
    from backend.services import models as m

    await _add(
        *[m.CrazyPick(pick_date="2026-10-28", rank=i, ticker=f"OLD{i}", composite_score=1.0) for i in (1, 2)],
        *[m.CrazyPick(pick_date="2026-10-29", rank=i, ticker=f"CR{i}", composite_score=70.0 - i, company_name=f"크레이지{i}")
          for i in range(1, 8)],
        *[m.MoonshotPick(pick_date="2026-10-29", rank=i, ticker=f"MS{i}", composite_score=50.0) for i in range(1, 6)],
    )
    b = (await client.get("/api/v1/today", headers=H)).json()
    assert b["is_admin"] is True
    c = _sec(b, "crazy")
    assert c["locked"] is False and c["as_of"] == "2026-10-29"
    assert [i["ticker"] for i in c["items"]] == ["CR1", "CR2", "CR3", "CR4", "CR5"]  # 최신 날짜만 · 상위 5
    assert c["items"][0]["name"] == "크레이지1" and c["items"][0]["note"] == "1위 · 점수 69.0"
    assert len(_sec(b, "moonshot")["items"]) == 3
    assert b["failures"] == [] and b["judgments_due"] == [] and b["holding_alerts"] == []


# ─── 후보 공개 섹션 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watchlist_prefers_next_trade_date_else_max(client):
    from backend.services import models as m

    # NOW = 금 10:00 KST → next_trade_date = 2026-10-30
    await _add(m.Watchlist(trade_date="2026-10-29", ticker="000001", rank=1, composite_score=1.0),
               m.Watchlist(trade_date="2026-10-30", ticker="000002", rank=1, composite_score=2.0))
    s = _sec((await client.get("/api/v1/today")).json(), "watchlist")
    assert s["as_of"] == "2026-10-30" and [i["ticker"] for i in s["items"]] == ["000002"]


@pytest.mark.asyncio
async def test_watchlist_fallback_to_max_trade_date(client):
    from backend.services import models as m

    await _add(m.Watchlist(trade_date="2026-10-27", ticker="000001", rank=1, composite_score=1.0),
               m.Watchlist(trade_date="2026-10-28", ticker="000002", rank=2, composite_score=2.0),
               m.Watchlist(trade_date="2026-10-28", ticker="000003", rank=1, composite_score=3.0))
    s = _sec((await client.get("/api/v1/today")).json(), "watchlist")
    assert s["as_of"] == "2026-10-28" and [i["ticker"] for i in s["items"]] == ["000003", "000002"]


@pytest.mark.asyncio
async def test_powderkeg_meme_today_only(client):
    from backend.services import models as m

    await _add(
        m.PowderKegEvent(ticker="000010", event_type="A1", source="dart", title="어제 이벤트", detected_at=MIDNIGHT_UTC - timedelta(seconds=1)),
        m.PowderKegEvent(ticker="000011", event_type="A1", source="dart", title="오늘 이벤트", detected_at=MIDNIGHT_UTC),
        m.MemeAlertHistory(ticker="OLDM", alert_type="BLAZING", triggered_at=MIDNIGHT_UTC - timedelta(minutes=1)),
        m.MemeAlertHistory(ticker="NEWM", alert_type="BLAZING", triggered_at=MIDNIGHT_UTC + timedelta(hours=1)),
        m.MemeAlertHistory(ticker="NEWM", alert_type="ERUPTING", triggered_at=MIDNIGHT_UTC + timedelta(hours=2)),
    )
    b = (await client.get("/api/v1/today")).json()
    pk = _sec(b, "powderkeg")
    assert [i["note"] for i in pk["items"]] == ["오늘 이벤트"] and pk["as_of"] == "2026-10-30"
    me = _sec(b, "meme")
    assert [i["ticker"] for i in me["items"]] == ["NEWM"] and me["items"][0]["note"] == "ERUPTING 알림 02:00"


@pytest.mark.asyncio
async def test_meme_uses_server_local_time_when_server_is_kst(client, monkeypatch):
    """밈 알림은 datetime.now() (서버 로컬) 로 저장 · 서버가 KST 면 KST 자정·시각 그대로."""
    from backend.api.routes import today
    from backend.services import models as m

    kst = timezone(timedelta(hours=9))
    monkeypatch.setattr(today, "_server_tz", lambda: kst)
    local_midnight = datetime(2026, 10, 30, 0, 0)  # 서버 로컬(KST) naive
    await _add(
        m.MemeAlertHistory(ticker="OLDK", alert_type="BLAZING", triggered_at=local_midnight - timedelta(minutes=1)),
        m.MemeAlertHistory(ticker="NEWK", alert_type="BLAZING", triggered_at=local_midnight + timedelta(hours=9, minutes=5)),
    )
    me = _sec((await client.get("/api/v1/today")).json(), "meme")
    assert [i["ticker"] for i in me["items"]] == ["NEWK"] and me["items"][0]["note"] == "BLAZING 알림 09:05"


@pytest.mark.asyncio
async def test_activist_from_state_file(client, tmp_path):
    import json

    (tmp_path / "activist_state.json").write_text(json.dumps({"events": [
        {"id": "x", "country": "US", "filer_key": "k", "filer_name": "Trian", "form": "SC 13D", "accession": "a",
         "filing_date": "2026-10-20", "target_desc": "Acme Corp", "target_ticker": "ACME", "score": 80,
         "intensity_label": "CRITICAL", "detected_at": 5.0}]}), encoding="utf-8")
    s = _sec((await client.get("/api/v1/today")).json(), "activist")
    assert s["as_of"] == "2026-10-20" and s["items"][0] == {"ticker": "ACME", "name": "Acme Corp", "note": "SC 13D · Trian · CRITICAL"}


# ─── 한 칸이 실패해도 200 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_candidate_source_raising_only_that_section_empty(client, monkeypatch):
    from backend.api.routes import today
    from backend.services import models as m

    await _add(m.CrazyPick(pick_date="2026-10-29", rank=1, ticker="CR1", composite_score=1.0),
               m.MoonshotPick(pick_date="2026-10-29", rank=1, ticker="MS1", composite_score=1.0))

    async def boom(_today):
        raise RuntimeError("깨짐")

    monkeypatch.setattr(today, "_SECTIONS", [(*x[:3], boom, x[4]) if x[0] == "crazy" else x for x in today._SECTIONS])
    r = await client.get("/api/v1/today", headers=H)
    assert r.status_code == 200
    b = r.json()
    assert _sec(b, "crazy")["items"] == [] and _sec(b, "crazy")["locked"] is False
    assert [i["ticker"] for i in _sec(b, "moonshot")["items"]] == ["MS1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["_failures", "_judgments_due", "_holding_alerts", "_safety"])
async def test_admin_part_raising_still_200(client, monkeypatch, name):
    from backend.api.routes import today
    from backend.services import models as m

    await _add(m.CrazyPick(pick_date="2026-10-29", rank=1, ticker="CR1", composite_score=1.0))

    async def boom(*a):
        raise RuntimeError("깨짐")

    monkeypatch.setattr(today, name, boom)
    r = await client.get("/api/v1/today", headers=H)
    assert r.status_code == 200
    b = r.json()
    key = {"_failures": "failures", "_judgments_due": "judgments_due", "_holding_alerts": "holding_alerts", "_safety": "safety"}[name]
    assert b[key] in ([], None)
    assert [i["ticker"] for i in _sec(b, "crazy")["items"]] == ["CR1"]


# ─── 외부 HTTP 0 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_outbound_http(client, monkeypatch):
    import httpx

    def fail(*a, **k):
        pytest.fail("외부 HTTP 호출 금지")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fail)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    import requests

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fail)
    assert (await client.get("/api/v1/today", headers=H)).status_code == 200
    assert (await client.get("/api/v1/today")).status_code == 200


# ─── 판정 기한 ───────────────────────────────────────────────────────────

def _j(ticker="005930", horizon=7, **kw):
    from backend.services import models as m

    # 2026-10-20(화) 17:00 KST (장 마감 뒤) → 기준일 10-20
    base = dict(ticker=ticker, page_source="t", hypothesis_id="h", thesis_md="x", ts=datetime(2026, 10, 20, 8, 0),
                horizon_days=horizon, strategy="s")
    base.update(kw)
    return m.UserJudgment(**base)


@pytest.mark.asyncio
async def test_judgments_due_boundary(client):
    await _add(_j("000001", 10), _j("000002", 11), _j("000003", 7))  # 기한 10-30(오늘) · 10-31(내일) · 10-27(지남)
    due = (await client.get("/api/v1/today", headers=H)).json()["judgments_due"]
    assert [(d["ticker"], d["due_date"], d["overdue"]) for d in due] == [
        ("000003", "2026-10-27", True), ("000001", "2026-10-30", False)]


@pytest.mark.asyncio
async def test_judgments_due_excludes_superseded_close_and_done(client):
    await _add(_j("000001", 7, superseded_by_id=99), _j("000002", 7, page_source="close"),
               _j("000003", 7, result_at_horizon=0.1), _j("000004", 7))
    due = (await client.get("/api/v1/today", headers=H)).json()["judgments_due"]
    assert [d["ticker"] for d in due] == ["000004"]


@pytest.mark.asyncio
async def test_judgments_due_uses_base_date_rule_and_limit(client):
    # 마감 전(10:00 KST) 만든 판정은 기준일이 전날 · 토요일 생성은 금요일 기준
    await _add(_j("000001", 10, ts=datetime(2026, 10, 21, 1, 0)),   # 10-21 10:00 KST → 기준 10-20 → 10-30 (오늘)
               _j("000002", 10, ts=datetime(2026, 10, 20, 23, 0)),  # 10-21 08:00 KST → 기준 10-20 → 10-30
               _j("000003", 3, ts=datetime(2026, 10, 24, 3, 0)),    # 토 12:00 KST → 기준 금 10-23 → 10-26 지남
               *[_j(f"1000{i:02d}", 7) for i in range(6)])
    due = (await client.get("/api/v1/today", headers=H)).json()["judgments_due"]
    assert len(due) == 5  # 상한
    assert due[0]["ticker"] == "000003" and due[0]["due_date"] == "2026-10-26"


# ─── 보유 알림 ───────────────────────────────────────────────────────────

def _h(sym, close, kind="holding", qty=10, d=date(2026, 10, 29)):
    from backend.services import models as m

    return m.HoldingSnapshot(symbol=sym, market="KR", trade_date=d, kind=kind, qty=qty, close=close, currency="KRW")


def _inv(sym, inv=100.0, **kw):
    # 기한이 먼 판정 (알림은 손절만 보려는 것)
    return _j(sym, 30, invalidation_price=inv, ts=datetime(2026, 10, 29, 8, 0), **kw)


@pytest.mark.asyncio
async def test_holding_stop_hit_near_boundary(client):
    await _add(_h("000001", 99.0), _inv("000001"),          # 이탈
               _h("000002", 100.0), _inv("000002"),         # 정확히 손절가 → 이탈
               _h("000003", 105.0), _inv("000003"),         # 정확히 5% → 근접
               _h("000004", 105.01), _inv("000004"),        # 5% 초과 → 없음
               _h("000005", 120.0), _inv("000005"))
    al = (await client.get("/api/v1/today", headers=H)).json()["holding_alerts"]
    got = {(a["symbol"], a["kind"]): a for a in al}
    assert set(got) == {("000001", "stop_hit"), ("000002", "stop_hit"), ("000003", "stop_near")}
    assert got[("000003", "stop_near")]["gap_pct"] == 5.0 and got[("000001", "stop_hit")]["gap_pct"] == -1.0
    assert [a["kind"] for a in al] == ["stop_hit", "stop_hit", "stop_near"]  # 위험 순


@pytest.mark.asyncio
async def test_holding_candle_close_preferred_and_holding_fallback(client):
    await _add(_h("000001", 90.0), _h("000001", 110.0, kind="candle"), _inv("000001"),   # 봉 110 → 알림 없음
               _h("000002", 150.0), _h("000002", 99.0, kind="candle"), _inv("000002"),   # 봉 99 → 이탈
               _h("000003", 101.0), _inv("000003"))                                      # 봉 없음 → 보유 종가
    al = {a["symbol"]: a for a in (await client.get("/api/v1/today", headers=H)).json()["holding_alerts"]}
    assert "000001" not in al
    assert al["000002"]["price"] == 99.0 and al["000002"]["price_source"] == "candle"
    assert al["000003"]["price"] == 101.0 and al["000003"]["price_source"] == "holding" and al["000003"]["kind"] == "stop_near"
    assert al["000003"]["price_date"] == "2026-10-29" and al["000003"]["currency"] == "KRW"


@pytest.mark.asyncio
async def test_holding_uses_latest_date_and_skips_sold(client):
    await _add(_h("000001", 50.0, d=date(2026, 10, 27)), _h("000001", 200.0, d=date(2026, 10, 29)), _inv("000001"),
               _h("000002", 50.0, d=date(2026, 10, 28), qty=5), _h("000002", 50.0, d=date(2026, 10, 29), qty=0), _inv("000002"))
    assert (await client.get("/api/v1/today", headers=H)).json()["holding_alerts"] == []


@pytest.mark.asyncio
async def test_holding_deadline(client):
    await _add(_h("000001", 500.0), _j("000001", 7, ts=datetime(2026, 10, 20, 8, 0)),    # 기한 10-27 (지남)
               _h("000002", 500.0), _j("000002", 11, ts=datetime(2026, 10, 20, 8, 0)),   # 기한 10-31 (내일)
               _h("000003", 500.0), _j("000003", 10, ts=datetime(2026, 10, 20, 8, 0)))   # 기한 10-30 (오늘)
    al = (await client.get("/api/v1/today", headers=H)).json()["holding_alerts"]
    assert sorted((a["symbol"], a["kind"], a["deadline"]) for a in al) == [
        ("000001", "deadline", "2026-10-27"), ("000003", "deadline", "2026-10-30")]


@pytest.mark.asyncio
async def test_holding_multiple_kinds_and_env_override(client, monkeypatch):
    await _add(_h("000001", 101.0), _j("000001", 7, ts=datetime(2026, 10, 20, 8, 0), invalidation_price=100.0))
    kinds = sorted(a["kind"] for a in (await client.get("/api/v1/today", headers=H)).json()["holding_alerts"])
    assert kinds == ["deadline", "stop_near"]
    monkeypatch.setenv("TODAY_NEAR_STOP_PCT", "0.5")
    r = (await client.get("/api/v1/today", headers=H)).json()
    assert r["near_stop_pct"] == 0.5
    assert [a["kind"] for a in r["holding_alerts"]] == ["deadline"]


# ─── 실패 알림 ───────────────────────────────────────────────────────────

def _n(key, title, result="sent", at=MIDNIGHT_UTC, cat="system"):
    from backend.services import models as m

    return m.NotificationLog(category=cat, dedupe_key=key, title=title, result=result, created_at=at)


@pytest.mark.asyncio
async def test_failures_kst_midnight_boundary(client):
    await _add(_n("a", "어제 작업 실패", at=MIDNIGHT_UTC - timedelta(seconds=1)),
               _n("b", "오늘 작업 실패", at=MIDNIGHT_UTC))
    f = (await client.get("/api/v1/today", headers=H)).json()["failures"]
    assert [x["title"] for x in f] == ["오늘 작업 실패"] and f[0]["at"] == "2026-10-29T15:00:00Z"


@pytest.mark.asyncio
async def test_failures_group_by_dedupe_key_skipped_counted_and_filter(client):
    t = MIDNIGHT_UTC
    await _add(_n("job1", "Crazy 종목 실패", "sent", t + timedelta(hours=1)),
               _n("job1", "Crazy 종목 실패", "skipped", t + timedelta(hours=3)),
               _n("job1", "Crazy 종목 실패", "failed", t + timedelta(hours=2)),
               _n("job2", "섹터 리더 09:05 실패", "skipped", t + timedelta(hours=2), cat="discovery_sector"),
               _n("ok", "Crazy 종목 끝"),          # 「실패」 아님
               _n("info", "새 후보 3건"))
    f = (await client.get("/api/v1/today", headers=H)).json()["failures"]
    assert [(x["title"], x["count"]) for x in f] == [("Crazy 종목 실패", 3), ("섹터 리더 09:05 실패", 1)]  # 최근 순
    assert f[0]["at"] == "2026-10-29T18:00:00Z" and f[1]["category"] == "discovery_sector"


@pytest.mark.asyncio
async def test_failures_limit_10(client):
    await _add(*[_n(f"k{i}", f"작업{i} 실패", at=MIDNIGHT_UTC + timedelta(minutes=i)) for i in range(12)])
    f = (await client.get("/api/v1/today", headers=H)).json()["failures"]
    assert len(f) == 10 and f[0]["title"] == "작업11 실패"


# ─── 응답 시간 (참고) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_response_time_with_seeded_data(client, capsys):
    from backend.services import models as m

    await _add(*[m.CrazyPick(pick_date="2026-10-29", rank=i, ticker=f"CR{i}", composite_score=1.0) for i in range(1, 11)],
               *[m.Watchlist(trade_date="2026-10-30", ticker=f"{i:06d}", rank=i, composite_score=1.0) for i in range(1, 21)],
               *[_n(f"k{i}", f"작업{i} 실패") for i in range(30)],
               *[_j(f"{i:06d}", 7) for i in range(1, 40)],
               *[x for i in range(1, 11) for x in (_h(f"{i:06d}", 101.0), _h(f"{i:06d}", 100.5, kind="candle"), _inv(f"{i:06d}"))])
    ts = []
    for _ in range(5):
        t0 = _time.perf_counter()
        r = await client.get("/api/v1/today", headers=H)
        ts.append((_time.perf_counter() - t0) * 1000)
        assert r.status_code == 200
    with capsys.disabled():
        print(f"\n[today] admin 응답 시간 ms: {[round(x) for x in ts]}")
    assert min(ts) < 2000
