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
        for tbl in (m.CrazyPick, m.MoonshotPick, m.HoldingSnapshot, m.UserJudgment, m.Watchlist, m.TossStockCode,
                    m.BlueChipCandidate):
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
        s.add(m.BlueChipCandidate(run_id="r1", ticker="005930", tier="premium", pass_count=2))
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
    # 1119-01 · 잠금 행 없음 · 자체 계산 신호는 비로그인에게도 보인다
    sig = _by_source(b)
    assert all(x["locked"] is False for x in b["signals"])
    assert "로그인하면 보입니다" not in r.text
    assert "3위" in sig["crazy"]["summary"] and "72.4" in sig["crazy"]["summary"]
    assert sig["crazy"]["explain"] and "0~100" in sig["crazy"]["explain"]
    # 보유 · 판단 기록은 새지 않음 (수량 · 평단 · 소문자 판정 본문)
    assert "소문자" not in r.text and "12.5" not in r.text and '"qty"' not in r.text


@pytest.mark.asyncio
async def test_anon_no_locked_rows_when_no_data(client):
    b = (await client.get("/api/v1/stock/NODATA")).json()
    assert b["signals"] == []  # 옛 규칙(잠금 행 3개) 폐지


ANON_TOP_KEYS = {"ticker", "market", "name", "is_admin", "fetched_at", "broker_link", "holding", "judgments",
                 "signals", "catalysts", "going_concern", "quote_available", "market_label"}  # 1128-01 market_label 추가 (저장값 · 바깥 호출 0)
ANON_SIGNAL_KEYS = {"source", "label", "as_of", "summary", "link", "locked", "explain"}
YAHOO_KEYS = ("close", "last_price", "target", "market_cap", "high_52w", "low_52w", "short_pct", "total_cash",
              "avg_volume", "opinion", "summary_lines", "avg_price", "analyst", "yahoo", "live", "chart")


@pytest.mark.asyncio
async def test_anon_response_key_list_is_fixed(client):
    """Fable 권고 5 · 비로그인 응답 키 목록 고정 · 야후 값 키 0."""
    b = (await client.get("/api/v1/stock/ZZCR")).json()
    assert set(b) == ANON_TOP_KEYS
    for sg in b["signals"]:
        assert set(sg) == ANON_SIGNAL_KEYS
    low = json.dumps(b).lower()
    for k in YAHOO_KEYS:
        assert f'"{k}"' not in low, k


@pytest.mark.asyncio
async def test_no_yahoo_or_naver_call_and_quote_view_untouched(client, monkeypatch):
    from backend.services import biotech_quotes as bq

    calls = {"n": 0}

    async def spy(*a, **k):
        calls["n"] += 1
        raise AssertionError("종목 API 가 시세 함수를 불렀다")

    for name in ("quote_view", "live_price"):
        if hasattr(bq, name):
            monkeypatch.setattr(bq, name, spy)
    for h in ({}, H):
        assert (await client.get("/api/v1/stock/ZZCR", headers=h)).status_code == 200
    assert calls["n"] == 0


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
    assert [x["source"] for x in b["signals"]] == []  # 자료 없음
    assert b["broker_link"]["kind"] == "search"


@pytest.mark.asyncio
async def test_kr_ticker_uses_kr_sources(client):
    b = (await client.get("/api/v1/stock/005930")).json()
    assert b["market"] == "KR"
    sig = _by_source(b)
    assert "crazy" not in sig and "moonshot" not in sig
    assert sig["watchlist"]["summary"] == "10/29 2위 · 점수 61.2" and sig["watchlist"]["link"] == "/watchlist"
    assert b["broker_link"]["url"].endswith("/stocks/A005930/order")
    # 1029-01 · tier 는 시총 구간 · 「등급 프리미엄」 으로 읽히지 않게
    assert sig["blue_chip"]["summary"] == "5단계 중 2단계 통과 · 시총 10조 이상"


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


# ─── 1119-01 · 새 칸 (일정 · 계속기업 · 후보 여부 · 스나이퍼 가림) · 가짜 종목 TESTA / TESTB ─────────

FORBIDDEN = ("골든", "데드", "크로스", "교차", "정배열", "역배열", "하십시오", "사십시오", "매수", "매도")


def _raise(e):
    def f(*a, **k):
        raise e
    return f


def _patch_bio(monkeypatch, *, cands=("TESTA",), notes=None, store="missing", radar_rows=None, tmp_path=None):
    """후보 목록 · 후보 파일 일정 · 계속기업 장부 · 레이더 행을 가짜로 바꾼다."""
    from backend.api.routes import biotech as R
    from backend.services import biotech_quotes as bq

    async def fake_set():
        if isinstance(cands, Exception):
            raise cands
        return set(cands)

    monkeypatch.setattr(bq, "candidate_set", fake_set)
    monkeypatch.setattr(R, "_latest_candidate_notes", _raise(notes) if isinstance(notes, Exception) else (lambda: notes))
    monkeypatch.setattr(R, "_going_concern_store", lambda: None if store == "missing" else store)
    p = None
    if radar_rows is not None:
        p = tmp_path / "radar.csv"
        p.write_text("ticker,cik,score,time_state\n" + "\n".join(radar_rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(R, "_latest_radar_csv", lambda: p)
    monkeypatch.setattr(R, "_cik_ticker_map", lambda: {})


@pytest.mark.asyncio
async def test_candidate_anon_gets_catalysts_going_concern_and_quote_flag(client, monkeypatch, tmp_path):
    from datetime import timedelta
    from backend.api.routes import biotech as R

    soon = (R._today_kst() + timedelta(days=10)).isoformat()
    past = (R._today_kst() - timedelta(days=3)).isoformat()
    note = f"NCT00000001 · D-10 ({soon} · PHASE3) / NCT00000002 · D-3 ({past} · PHASE2)"
    store = {"rows": {"0000000123": {"state": "present", "form": "10-Q", "filing_date": R._today_kst().isoformat(),
                                    "url": "https://www.sec.gov/Archives/edgar/data/123/x/"}}, "meta": {}}
    _patch_bio(monkeypatch, notes={"TESTA": note}, store=store, radar_rows=["TESTA,0000000123,50.0,A"], tmp_path=tmp_path)
    b = (await client.get("/api/v1/stock/TESTA")).json()
    assert b["quote_available"] is True
    assert [c["nct_id"] for c in b["catalysts"]] == ["NCT00000002", "NCT00000001"]
    assert b["catalysts"][0]["past"] is True and b["catalysts"][1]["past"] is False and b["catalysts"][1]["days_to"] == 10
    assert b["going_concern"]["scope"] == "checked" and b["going_concern"]["detail"]["state"] == "present"
    assert set(b) == ANON_TOP_KEYS


@pytest.mark.asyncio
async def test_not_candidate_and_kr_hide_bio_columns(client, monkeypatch):
    _patch_bio(monkeypatch, cands=("TESTA",), notes={"TESTB": "x"}, store={"rows": {}})
    b = (await client.get("/api/v1/stock/TESTB")).json()
    assert b["quote_available"] is False and b["catalysts"] is None and b["going_concern"] is None
    k = (await client.get("/api/v1/stock/000000")).json()
    assert k["quote_available"] is False and k["catalysts"] is None and k["going_concern"] is None


@pytest.mark.asyncio
async def test_no_catalyst_rows_is_empty_list(client, monkeypatch):
    _patch_bio(monkeypatch, notes={"OTHER": "x"}, store={"rows": {}})
    b = (await client.get("/api/v1/stock/TESTA")).json()
    assert b["catalysts"] == []


@pytest.mark.asyncio
async def test_unparseable_catalyst_note_gives_empty_and_200(client, monkeypatch):
    _patch_bio(monkeypatch, notes={"TESTA": "형식이 다른 문장"}, store={"rows": {}})
    r = await client.get("/api/v1/stock/TESTA")
    assert r.status_code == 200 and r.json()["catalysts"] == []


@pytest.mark.asyncio
async def test_one_bad_catalyst_line_is_dropped_others_stay(client, monkeypatch):
    from datetime import timedelta
    from backend.api.routes import biotech as R

    ok = (R._today_kst() + timedelta(days=5)).isoformat()
    note = f"NCT00000009 · D-5 ({ok} · PHASE1) / NCT00000008 · D-5 (2026-13-99 · PHASE1)"
    _patch_bio(monkeypatch, notes={"TESTA": note}, store={"rows": {}})
    c = (await client.get("/api/v1/stock/TESTA")).json()["catalysts"]
    assert [x["nct_id"] for x in c] == ["NCT00000009"]  # 날짜가 깨진 줄은 빠진다


@pytest.mark.asyncio
async def test_broken_ledger_row_is_unreadable_not_out(client, monkeypatch, tmp_path):
    _patch_bio(monkeypatch, notes={"TESTA": ""}, store={"rows": {"0000000456": {"state": ""}}, "meta": {}},
               radar_rows=["TESTA,0000000456,1,A"], tmp_path=tmp_path)
    assert (await client.get("/api/v1/stock/TESTA")).json()["going_concern"] == {"scope": "unreadable", "detail": None}


@pytest.mark.asyncio
async def test_cik_missing_everywhere_is_no_cik(client, monkeypatch, tmp_path):
    _patch_bio(monkeypatch, notes={"TESTA": ""}, store={"rows": {"0000000456": {"state": "present"}}, "meta": {}},
               radar_rows=["TESTA,,1,A"], tmp_path=tmp_path)
    assert (await client.get("/api/v1/stock/TESTA")).json()["going_concern"] == {"scope": "no_cik", "detail": None}


@pytest.mark.asyncio
async def test_invalid_ticker_message(client):
    r = await client.get("/api/v1/stock/AB CD")
    assert r.status_code == 400 and r.json()["detail"] == "종목 코드 형식이 아닙니다."


@pytest.mark.asyncio
async def test_candidate_files_missing_gives_nulls(client, monkeypatch):
    _patch_bio(monkeypatch, cands=(), notes={}, store="missing")
    b = (await client.get("/api/v1/stock/TESTA")).json()
    assert b["quote_available"] is None and b["catalysts"] is None and b["going_concern"] is None


@pytest.mark.asyncio
async def test_candidate_set_exception_nulls_only_quote_available(client, monkeypatch):
    _patch_bio(monkeypatch, cands=RuntimeError("x"), notes={"TESTA": ""}, store={"rows": {}})
    r = await client.get("/api/v1/stock/ZZCR")
    assert r.status_code == 200
    b = r.json()
    assert b["quote_available"] is None and b["signals"]  # 신호 칸은 정상


@pytest.mark.asyncio
async def test_going_concern_not_in_ledger_is_out_and_not_found_is_distinct(client, monkeypatch, tmp_path):
    store = {"rows": {"0000000456": {"state": "not_found", "form": "10-K", "filing_date": "2026-03-01"}}, "meta": {}}
    _patch_bio(monkeypatch, notes={"TESTA": ""}, store=store, radar_rows=["TESTA,0000000999,1.0,A"], tmp_path=tmp_path)
    assert (await client.get("/api/v1/stock/TESTA")).json()["going_concern"] == {"scope": "out", "detail": None}
    _patch_bio(monkeypatch, notes={"TESTA": ""}, store=store, radar_rows=["TESTA,0000000456,1.0,A"], tmp_path=tmp_path)
    g = (await client.get("/api/v1/stock/TESTA")).json()["going_concern"]
    assert g["scope"] == "checked" and g["detail"]["state"] == "not_found"


@pytest.mark.asyncio
async def test_going_concern_stale_flag_from_old_report(client, monkeypatch, tmp_path):
    from datetime import datetime

    store = {"rows": {"0000000456": {"state": "present", "form": "10-Q", "filing_date": "2020-01-01"}},
             "meta": {"last_run_on": datetime.now().date().isoformat()}}
    _patch_bio(monkeypatch, notes={"TESTA": ""}, store=store, radar_rows=["TESTA,0000000456,1.0,A"], tmp_path=tmp_path)
    d = (await client.get("/api/v1/stock/TESTA")).json()["going_concern"]["detail"]
    assert d["stale"] is True and d["filed"] == "2020-01-01"


@pytest.mark.asyncio
async def test_catalyst_reader_exception_nulls_only_that_column(client, monkeypatch):
    _patch_bio(monkeypatch, notes=RuntimeError("busy"), store={"rows": {}})
    r = await client.get("/api/v1/stock/TESTA")
    assert r.status_code == 200 and r.json()["catalysts"] is None and r.json()["quote_available"] is True


@pytest.mark.asyncio
async def test_db_exception_in_signal_source_keeps_200(client, monkeypatch):
    from backend.api.routes import stock

    async def busy(t, kr):
        raise TimeoutError("database is locked")

    monkeypatch.setattr(stock, "_crazy", busy)
    r = await client.get("/api/v1/stock/ZZCR")
    assert r.status_code == 200 and "crazy" not in _by_source(r.json())


@pytest.mark.asyncio
async def test_kr_sniper_state_words_admin_only(client):
    from datetime import datetime
    from backend.services.db import get_session
    from backend.services import models as m

    async with get_session() as s:
        await s.execute(delete(m.SniperSignal))
        s.add(m.SniperSignal(ticker="000000", detected_at=datetime(2026, 11, 18, 10, 0), tape_score=70.0,
                             entry_price=100.0, exit_price=110.0))
    anon = (await client.get("/api/v1/stock/000000")).json()
    adm = (await client.get("/api/v1/stock/000000", headers=H)).json()
    sa = _by_source(anon)["sniper"]["summary"]
    assert "진입" not in sa and "청산" not in sa and "11/18" in sa and "70.0" in sa
    assert "청산" in _by_source(adm)["sniper"]["summary"]


@pytest.mark.asyncio
async def test_admin_response_has_holding_and_quote_flag_true(client, monkeypatch):
    _patch_bio(monkeypatch, cands=("ZZCR",), notes={"ZZCR": ""}, store={"rows": {}})
    b = (await client.get("/api/v1/stock/ZZCR", headers=H)).json()
    assert b["holding"]["qty"] == 25.0 and len(b["judgments"]) == 1 and b["quote_available"] is True


@pytest.mark.asyncio
async def test_explain_texts_have_no_forbidden_words(client):
    from datetime import datetime
    from backend.services.db import get_session
    from backend.services import models as m

    async with get_session() as s:
        await s.execute(delete(m.MemeScoreHistory))
        s.add(m.MemeScoreHistory(ticker="ZZCR", snapshot_at=datetime(2026, 11, 18), score=0.8, label="HOT"))
        s.add(m.BlueChipCandidate(run_id="r9", ticker="000000", tier="entry", pass_count=3))
        s.add(m.MemeScoreHistory(ticker="ZZOLD", snapshot_at=datetime(2026, 11, 18), score=0.8, label="옛낱말"))
    texts = []
    for t in ("ZZCR", "000000"):
        b = (await client.get(f"/api/v1/stock/{t}")).json()
        texts += [x["explain"] for x in b["signals"] if x["explain"]]
    assert texts and any("HOT" in x for x in texts)
    for x in texts:
        for w in FORBIDDEN:
            assert w not in x, (w, x)
    old = _by_source((await client.get("/api/v1/stock/ZZOLD")).json())
    assert old["meme"]["explain"] is None  # 표에 없는 옛 낱말은 설명 생략


@pytest.mark.asyncio
async def test_candidate_set_caches_empty_result(monkeypatch):
    """Fable 권고 3 · 후보 0개도 5분 기억 (요청마다 파일을 다시 읽지 않음)."""
    from backend.services import biotech_quotes as bq

    n = {"c": 0}

    async def empty(limit=0):
        n["c"] += 1
        return []

    monkeypatch.setattr(bq, "load_candidates", empty)
    bq._CAND_CACHE.update({"at": 0.0, "list": []})
    await bq.candidate_set()
    await bq.candidate_set()
    await bq.candidate_set()
    assert n["c"] == 1
    bq._CAND_CACHE.update({"at": 0.0, "list": []})


@pytest.mark.asyncio
async def test_concurrent_requests_ok(client):
    import asyncio

    rs = await asyncio.gather(*[client.get("/api/v1/stock/ZZCR") for _ in range(8)])
    assert all(r.status_code == 200 for r in rs)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/crazy", "/api/v1/moonshot", "/api/v1/biotech/radar.json"])
async def test_signal_link_admin_only_pages_need_login(client, path):
    """화면 page.tsx 의 ADMIN_ONLY_LINKS (/lab/crazy · /lab/moonshot · /biotech) 근거 · 비로그인은 401."""
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/watchlist", "/api/v1/powderkeg/list", "/api/v1/rulebook/blue-chip/list",
    "/api/v1/principles/screener/latest", "/api/v1/serenity/summary", "/api/v1/sector-leaders/top10",
    "/api/v1/meme-watch/top", "/api/v1/meme-watch/activist/status", "/api/v1/sniper/status"])
async def test_signal_link_public_pages_not_login_gated(client, path):
    """위 목록 밖 링크 화면의 읽기 API 는 비로그인도 읽는다 (401 · 403 이 아님)."""
    assert (await client.get(path)).status_code not in (401, 403)
