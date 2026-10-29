"""1022-10 3단계 · GET /api/v1/stock/{ticker} (공개 읽기 · 관리자 전용 칸은 비로그인에 숨김)."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

TOKEN = "stock_overview_test_token_32chars_0"
H = {"X-API-Token": TOKEN}


@pytest.fixture
async def client(monkeypatch, tmp_path):
    from backend.discovery.activist import state as activist_state
    from backend.services.db import get_session, init_db
    from backend.services import models as m

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    monkeypatch.setattr(activist_state, "_STATE_PATH", tmp_path / "activist_state.json")  # 파일 없음 상태가 기본
    await init_db()
    async with get_session() as s:
        for tbl in (m.CrazyPick, m.MoonshotPick, m.HoldingSnapshot, m.UserJudgment, m.Watchlist, m.TossStockCode):
            await s.execute(delete(tbl))
        s.add(m.CrazyPick(pick_date="2026-10-29", rank=3, ticker="ZZCR", composite_score=72.4))
        s.add(m.MoonshotPick(pick_date="2026-10-29", rank=1, ticker="ZZCR", composite_score=55.0))
        s.add(m.HoldingSnapshot(symbol="ZZCR", market="US", trade_date=date(2026, 10, 28), kind="holding",
                                qty=0, avg_price=10.0, currency="USD"))
        s.add(m.HoldingSnapshot(symbol="ZZCR", market="US", trade_date=date(2026, 10, 29), kind="holding",
                                qty=25, avg_price=12.5, currency="USD"))
        s.add(m.UserJudgment(ticker="zzcr", page_source="test", hypothesis_id="h1", thesis_md="소문자로 저장된 판정",
                             invalidation_price=9.0, target_price=20.0))
        s.add(m.Watchlist(trade_date="2026-10-29", ticker="005930", rank=2, composite_score=61.2))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _by_source(body):
    return {x["source"]: x for x in body["signals"]}


@pytest.mark.asyncio
async def test_anon_hides_admin_data_and_sets_cache_headers(client):
    r = await client.get("/api/v1/stock/zzcr")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store"
    assert "cookie" in r.headers["vary"].lower()
    b = r.json()
    assert b["ticker"] == "ZZCR" and b["market"] == "US" and b["is_admin"] is False
    assert b["holding"] is None and b["judgments"] is None
    sig = _by_source(b)
    for k in ("crazy", "moonshot"):
        assert sig[k]["locked"] is True and sig[k]["as_of"] is None and sig[k]["summary"] == "로그인하면 보입니다"
    assert "72.4" not in r.text and "3위" not in r.text and "소문자" not in r.text


@pytest.mark.asyncio
async def test_anon_locked_rows_even_without_data(client):
    b = (await client.get("/api/v1/stock/NODATA")).json()
    sig = _by_source(b)
    assert sig["crazy"]["locked"] and sig["moonshot"]["locked"]


@pytest.mark.asyncio
async def test_admin_gets_holding_judgments_and_unlocked_rows(client):
    r = await client.get("/api/v1/stock/ZZCR", headers=H)
    assert r.status_code == 200
    b = r.json()
    assert b["is_admin"] is True
    assert b["holding"] == {"qty": 25.0, "avg_price": 12.5, "currency": "USD", "as_of": "2026-10-29", "sold": False}
    assert len(b["judgments"]) == 1 and b["judgments"][0]["thesis_md"] == "소문자로 저장된 판정"  # 소문자 저장도 찾음
    sig = _by_source(b)
    assert sig["crazy"]["locked"] is False and "3위" in sig["crazy"]["summary"] and "72.4" in sig["crazy"]["summary"]
    assert sig["moonshot"]["as_of"] == "2026-10-29"


@pytest.mark.asyncio
async def test_admin_sold_holding(client):
    from backend.services.db import get_session
    from backend.services.models import HoldingSnapshot

    async with get_session() as s:
        await s.execute(delete(HoldingSnapshot))
        s.add(HoldingSnapshot(symbol="SOLD", market="US", trade_date=date(2026, 10, 29), kind="holding", qty=0))
    b = (await client.get("/api/v1/stock/SOLD", headers=H)).json()
    assert b["holding"]["sold"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["AB CD", "A" * 13, "AAPL%3B", "a;b"])
async def test_invalid_ticker_400(client, bad):
    r = await client.get(f"/api/v1/stock/{bad}")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unknown_ticker_200_empty(client):
    r = await client.get("/api/v1/stock/ZZNONE", headers=H)
    assert r.status_code == 200
    b = r.json()
    assert b["name"] is None and b["holding"] is None and b["judgments"] == []
    assert [x["source"] for x in b["signals"]] == []  # 관리자: 잠금 행 없음 · 자료 없음
    assert b["broker_link"]["kind"] == "search"


@pytest.mark.asyncio
async def test_kr_ticker_uses_kr_sources(client):
    b = (await client.get("/api/v1/stock/005930")).json()
    assert b["market"] == "KR"
    sig = _by_source(b)
    assert "crazy" not in sig and "moonshot" not in sig
    assert sig["watchlist"]["summary"] == "10/29 2위 · 점수 61.2" and sig["watchlist"]["link"] == "/watchlist"
    assert b["broker_link"]["url"].endswith("/stocks/A005930/order")


@pytest.mark.asyncio
async def test_missing_activist_file_and_empty_holding_still_200(client):
    r = await client.get("/api/v1/stock/ZZEMPTY", headers=H)  # activist_state.json 없음 · holding 없음
    assert r.status_code == 200
    b = r.json()
    assert b["holding"] is None
    assert "activist" not in _by_source(b)


@pytest.mark.asyncio
async def test_activist_row_from_state_file(client, tmp_path):
    p = tmp_path / "activist_state.json"
    p.write_text(json.dumps({"events": [{"id": "x", "country": "US", "filer_key": "k", "filer_name": "Trian",
                                         "form": "SC 13D", "accession": "a", "filing_date": "2026-10-20",
                                         "target_desc": "d", "target_ticker": "zzact", "score": 80,
                                         "intensity_label": "CRITICAL"}]}), encoding="utf-8")
    b = (await client.get("/api/v1/stock/ZZACT")).json()
    a = _by_source(b)["activist"]
    assert a["as_of"] == "2026-10-20" and "Trian" in a["summary"] and a["link"] == "/activist-radar"


@pytest.mark.asyncio
async def test_one_source_failure_omits_only_that_row(client, monkeypatch):
    from backend.api.routes import stock

    async def boom(t, kr):
        raise RuntimeError("x")

    monkeypatch.setattr(stock, "_watchlist", boom)
    r = await client.get("/api/v1/stock/005930")
    assert r.status_code == 200 and "watchlist" not in _by_source(r.json())


@pytest.mark.asyncio
async def test_no_outbound_http(client, monkeypatch):
    import httpx

    def fail(*a, **k):
        pytest.fail("외부 HTTP 호출 금지")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fail)  # 실제 네트워크 전송만 막음 (ASGI 는 무관)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fail)
    assert (await client.get("/api/v1/stock/005930", headers=H)).status_code == 200
