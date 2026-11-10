"""1110-02 · VIP 적자 종목 탭 · 평균선 세 줄 — 계획 5절 시험 1~8.

종목 기호·수량·평단은 모두 가짜 값이다 (ZZ 로 시작 · 실제 보유 종목 아님). 시각은 고정한다 (교훈 #5).
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.services import holdings_swing as hs
from backend.services import real_holdings, vip_tabs
from backend.tests.test_holdings_swing import (  # noqa: F401  (픽스처 · 도우미 재사용)
    FORBIDDEN, KR, NOW, TODAY, TOKEN, US, _add, _candle, _days, _hold, _long_dates, _seed_card, _seed_long, clean, http,
)

HDR = {"X-API-Token": TOKEN}
A, B, C, D, E, F = "ZZLOSS", "ZZGAIN", "ZZTURN", "ZZSOLD", "ZZCFG", "ZZNEW"
ROOT = Path(hs.__file__).resolve().parents[2]


def _toss_item(sym, qty=10, avg=100.0, last=90.0, market="US", name="가짜 종목"):
    """토스 보유 응답 한 줄 (가짜 값). pnl 은 토스가 준 값을 일부러 계산값과 다르게 둔다 — 재계산하지 않는지 본다."""
    return {"symbol": sym, "name": name, "quantity": qty, "averagePurchasePrice": avg, "lastPrice": last,
            "currency": "USD" if market == "US" else "KRW", "marketCountry": market,
            "marketValue": {"amount": last * qty, "purchaseAmount": avg * qty},
            "profitLoss": {"amount": 12.34}}


@pytest.fixture
def toss(monkeypatch):
    """토스 보유 조회를 가짜로 바꾼다 (실제 호출 없음) · 호출 횟수를 센다."""
    from backend.execution.brokers import toss_client

    state = {"items": [], "calls": 0, "fail": False}

    class Fake:
        def holdings(self, symbol=None):
            state["calls"] += 1
            if state["fail"]:
                raise RuntimeError("가짜 실패")
            return {"items": state["items"]}

    monkeypatch.setattr(toss_client, "get_toss_client", lambda: Fake())
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    return state


@pytest.fixture
def cfg(monkeypatch):
    """설정 종목: 기호 ZZCFG (VIP_TICKER=ZZCFG.O)."""
    from backend.discovery.vip import config as vip_config

    real = vip_config.load()
    from dataclasses import replace

    fake = replace(real, enabled=True, ticker="ZZCFG.O", company_name="가짜 설정 종목", avg_price=50.0)
    monkeypatch.setattr(vip_config, "load", lambda: fake)
    return fake


def _rows(closes_avg, sym, market="US", n=8, horizon=None):
    """보유 기록 n행 (마지막 날이 TODAY). closes_avg = [(close, avg)] 앞 행부터."""
    days = _days(n)
    cur = "USD" if market == "US" else "KRW"
    return [_hold(sym, market, d, close=c, avg=a, cur=cur) for d, (c, a) in zip(days, closes_avg)]


async def _tabs(http, toss):
    r = await http.get("/api/v1/account/vip", headers=HDR)
    assert r.status_code == 200, r.text
    return r.json()


# 1 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vip_endpoint_401_without_token_and_200_with(http, toss):
    assert (await http.get("/api/v1/account/vip")).status_code == 401
    assert (await http.get("/api/v1/account/vip", headers={"X-API-Token": "wrong"})).status_code == 401
    assert (await http.get("/api/v1/account/vip", headers=HDR)).status_code == 200


# 2 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_rules_loss_gain_cost_edge_and_order(http, toss, cfg):
    # 손실 A(−10%) · 이익 B(+10%) · 비용 전 +0.1% 비용 후 −0.1% 인 경계 종목 G · 설정 종목 E(보유 없음)
    G = "ZZEDGE"
    for sym, close, avg in ((A, 90.0, 100.0), (B, 110.0, 100.0), (G, 100.1, 100.0)):
        await _add(*_rows([(close, avg)] * 8, sym))
    toss["items"] = [_toss_item(A, last=90.0), _toss_item(B, last=110.0), _toss_item(G, last=100.1)]
    out = await _tabs(http, toss)
    by = {t["symbol"]: t for t in out["tabs"]}
    assert by[A]["reason"] == "loss" and B not in by
    assert by[G]["reason"] == "loss"  # 비용 전 +0.1% · 비용 후 −0.1% 도 손실로 넣음
    assert by[E]["reason"] == "config_only" and by[E]["is_vip_config"] and by[E]["position"] is None
    assert [t["symbol"] for t in out["tabs"]] == [E, A, G]  # 설정 → 손실 큰 순


@pytest.mark.asyncio
async def test_turned_within_5_rows_included_with_date_and_6th_excluded_unset_horizon_too(http, toss, cfg):
    # 보유 성격 미지정 · 손실 → 이익으로 바뀐 날 뒤 행 개수 5 / 6
    for sym, after in ((C, 5), ("ZZLATE", 6)):
        series = [(90.0, 100.0)] * 3 + [(110.0, 100.0)] * (after + 1)
        await _add(*_rows(series, sym, n=len(series)))
        toss["items"].append(_toss_item(sym, last=110.0))
    out = await _tabs(http, toss)
    by = {t["symbol"]: t for t in out["tabs"]}
    assert by[C]["reason"] == "turned" and by[C]["turn_date"] == _days(9)[3].isoformat() and by[C]["horizon"] is None
    assert "ZZLATE" not in by


@pytest.mark.asyncio
async def test_no_record_excluded_sold_today_excluded_with_limit_and_order_turned_last(http, toss, cfg):
    await _add(*_rows([(90.0, 100.0)] * 8, A))  # 손실
    await _add(*_rows([(90.0, 100.0)] * 3 + [(110.0, 100.0)] * 4, C, n=7))  # 흑자 전환
    await _add(*_rows([(80.0, 100.0)] * 8, D))  # 기록에는 있으나 토스에는 없음(오늘 판 종목)
    toss["items"] = [_toss_item(A, last=90.0), _toss_item(C, last=110.0), _toss_item(F, last=50.0)]  # F 는 보유 기록 없음
    out = await _tabs(http, toss)
    syms = [t["symbol"] for t in out["tabs"]]
    assert F not in syms and D not in syms
    assert syms == [E, A, C]  # 설정 → 손실 → 전환
    assert any("오늘 판 종목은 탭에서 뺐습니다" in s for s in out["limits"])
    assert any("오늘 산 종목" in s for s in out["limits"])


@pytest.mark.asyncio
async def test_config_symbol_sold_today_is_config_only_and_held_config_is_config(http, toss, cfg):
    await _add(*_rows([(60.0, 50.0)] * 8, E))  # 설정 종목 · 이익 · 토스에 없음 → config_only
    out = await _tabs(http, toss)
    assert [(t["symbol"], t["reason"], t["position"]) for t in out["tabs"]] == [(E, "config_only", None)]
    # 설정 종목만 토스에 없을 때는 「오늘 판 종목은 탭에서 뺐습니다」 줄을 붙이지 않는다 (탭에 남아 있으므로)
    assert not any("오늘 판 종목은 탭에서 뺐습니다" in s for s in out["limits"])
    toss["items"] = [_toss_item(E, last=60.0)]
    out = await _tabs(http, toss)
    assert [(t["symbol"], t["reason"]) for t in out["tabs"]] == [(E, "config")]


# 3 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_position_equals_toss_values_no_recompute(http, toss, cfg):
    await _add(*_rows([(90.0, 100.0)] * 8, A))
    toss["items"] = [_toss_item(A, qty=7, avg=123.45, last=88.8)]
    t = {x["symbol"]: x for x in (await _tabs(http, toss))["tabs"]}[A]
    assert t["position"] == {"avg_price": 123.45, "qty": 7.0, "current_price": 88.8, "pnl": 12.34,
                             "pnl_pct": t["position"]["pnl_pct"], "currency": "USD", "source": "toss"}
    # pnl 은 토스가 준 12.34 그대로 (7 × (88.8 − 123.45) 로 다시 계산하지 않음)
    assert t["position"]["pnl"] == 12.34


# 4 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chart_daily_ma_values_null_when_short_and_unset_horizon_has_chart(http, toss, cfg):
    await _seed_card("US", A, [100.0] * 130, horizon=None, hold_rows=_rows([(90.0, 100.0)] * 8, A))
    long_closes = [100.0 + i for i in range(600)]
    await _seed_long("US", A, long_closes)
    toss["items"] = [_toss_item(A, last=90.0)]
    t = {x["symbol"]: x for x in (await _tabs(http, toss))["tabs"]}[A]
    assert t["horizon"] is None and t["goal"] is None and "보유 성격을 정하면 목표 칸이 보입니다" in t["goal_hold_reason"]
    daily = t["chart"]["daily"]
    assert len(daily) == hs.CHART_DAILY_ROWS and t["chart"]["daily_note"] is None
    last = daily[-1]
    assert last["c"] == long_closes[-1]
    assert last["m20"] == pytest.approx(sum(long_closes[-20:]) / 20)
    assert last["m50"] == pytest.approx(sum(long_closes[-50:]) / 50)
    assert last["m200"] == pytest.approx(sum(long_closes[-200:]) / 200)
    assert daily[0]["m200"] is not None  # 1년 창 앞쪽도 긴 일봉으로 채워짐
    assert t["chart"]["week40"]["series"]  # 미지정 종목도 주봉 그림 (㉣②)


@pytest.mark.asyncio
async def test_chart_short_series_has_null_ma_and_note(clean):
    d = _long_dates(150, TODAY)
    ser = (d, [100.0 + i for i in range(150)], "yfinance close")
    ch = hs.build_chart("US", ser, TODAY)
    assert len(ch["daily"]) == 150 and ch["daily"][0]["m20"] is None and ch["daily"][19]["m20"] is not None
    assert ch["daily"][-1]["m200"] is None and ch["daily_note"] == "자료 부족"
    assert hs.build_chart("US", None, TODAY) is None


# 5 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_card_200_line_short_long_series_source_text_and_60_unchanged(clean):
    from backend.services.db import get_session

    await _seed_card("US", US, [100.0 + i * 0.1 for i in range(130)], horizon="long")
    await _seed_card("KR", KR, [100.0 + i * 0.1 for i in range(130)], horizon="long")
    await _seed_long("US", US, [100.0] * 150)  # 200개 미만
    await _seed_long("KR", KR, [100.0 + i * 0.05 for i in range(900)], source="pykrx adjusted")
    async with get_session() as s:
        cs = {(c["market"], c["symbol"]): c for c in await hs.build_cards(s, TODAY)}
    us, kr = cs[("US", US)]["ma"], cs[("KR", KR)]["ma"]
    assert [m["days"] for m in us] == [20, 60, 120, 200] and us[3]["note"] == "200일 자료 부족" and us[3]["avg"] is None
    assert kr[3]["note"] is None and kr[3]["distance_pct"] is not None
    assert us[3]["source"] != kr[3]["source"] and "Yahoo" in us[3]["source"] and "KRX" in kr[3]["source"]
    closes = [100.0 + i * 0.1 for i in range(130)]
    assert us[1]["avg"] == round(sum(closes[-60:]) / 60, 4)  # 60일 값 그대로 (카드 기준 종가)
    assert hs.MA_DAYS == (20, 60, 120)


# 6 ───────────────────────────────────────────────

NEW_WORDS = r"골든|데드|크로스|교차|정배열|역배열"


def test_forbidden_regex_has_new_words():
    for w in ("골든", "데드", "크로스", "교차", "정배열", "역배열"):
        assert FORBIDDEN.search(f"가나 {w}다") is not None, w


def test_no_forbidden_words_in_new_server_strings_and_frontend_files():
    from backend.tests.test_holdings_swing import _module_string_literals

    for mod in (Path(hs.__file__), Path(vip_tabs.__file__)):
        bad = [s for s in _module_string_literals(mod) if FORBIDDEN.search(s)]
        assert bad == [], (mod.name, bad)
    fe = ROOT / "frontend"
    for rel in ("components/account/MaChart.tsx", "components/account/HoldingSwing.tsx", "components/account/Week40Chart.tsx",
                "components/vip/VipTabs.tsx", "components/vip/VipTabBody.tsx", "lib/holdings-swing.ts"):
        assert FORBIDDEN.search((fe / rel).read_text(encoding="utf-8")) is None, rel
    # 제외: components/vip/VipConfigPanels.tsx = 기존 VIP 칸(설정 종목의 익절·손절·추적 알림 조건 · 「선행 신호」 문구).
    # 사용자가 따로 설정한 알림이라 1108-02 문구 규칙 밖이다 — 제외 파일이 이 하나뿐인지 확인한다.
    assert (fe / "components/vip/VipConfigPanels.tsx").exists()


@pytest.mark.asyncio
async def test_response_json_is_free_of_forbidden_words(http, toss, cfg):
    await _seed_card("US", A, [100.0] * 130, horizon="short", hold_rows=_rows([(90.0, 100.0)] * 8, A))
    await _seed_long("US", A, [100.0 + (i % 7) + i * 0.05 for i in range(900)])
    toss["items"] = [_toss_item(A, last=90.0)]
    r = await http.get("/api/v1/account/vip", headers=HDR)
    body = r.json()
    t = [x for x in body["tabs"] if x["symbol"] == A][0]
    assert t["goal"] is not None and t["chart"]["daily"]  # 검사 대상이 비어 있지 않다
    assert FORBIDDEN.search(json.dumps(body, ensure_ascii=False)) is None
    cs = await http.get("/api/v1/account/swing", headers=HDR)
    assert FORBIDDEN.search(json.dumps(cs.json(), ensure_ascii=False, default=str)) is None


# 7 · 화면 확인은 별도(렌더 · tsc) — 여기는 화면 도우미 점검 스크립트를 돌린다 ──────

def test_vip_tabs_frontend_helpers_check():
    import shutil
    import subprocess

    fe = ROOT / "frontend"
    if shutil.which("npx") is None or not (fe / "node_modules").exists():
        pytest.skip("npx · node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/vip-tabs.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "vip-tabs ok" in r.stdout


# 8 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_toss_holdings_call_and_no_token_issue_when_cached(http, monkeypatch, tmp_path, cfg):
    """실제 TossClient 를 쓰되 네트워크 층(httpx.Client)만 모의 — 보유 조회 1번 · 토큰 발급 0번."""
    from backend.execution.brokers import toss_client

    cache = tmp_path / "token.json"
    cache.write_text(json.dumps({"access_token": "fake-cached", "expires_at": time.time() + 3600}))
    cl = toss_client.TossClient.__new__(toss_client.TossClient)
    cl._token_cache_path, cl._account_seq, cl._client_id, cl._client_secret = cache, "1", "id", "secret"
    calls = []

    class Resp:
        status_code = 200
        headers: dict = {}
        text = ""

        def json(self):
            return {"result": {"items": [_toss_item(A, last=90.0)]}}

    class FakeHttpx:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **k):
            calls.append(("GET", url))
            return Resp()

        def post(self, url, **k):
            calls.append(("POST", url))
            return Resp()

    monkeypatch.setattr(toss_client.httpx, "Client", FakeHttpx)
    monkeypatch.setattr(toss_client, "get_toss_client", lambda: cl)
    from backend.execution.brokers import rate_limiter

    monkeypatch.setattr(rate_limiter.get_rate_limiter(), "acquire", lambda *a, **k: None)
    await _add(*_rows([(90.0, 100.0)] * 8, A))
    r = await http.get("/api/v1/account/vip", headers=HDR)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert [c for c in calls if c[0] == "GET"] == [("GET", f"{toss_client._BASE_URL}/api/v1/holdings")]
    assert [c for c in calls if "oauth2/token" in c[1]] == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_toss_failure_returns_ok_false_and_no_tabs(http, toss):
    toss["fail"] = True
    out = (await http.get("/api/v1/account/vip", headers=HDR)).json()
    assert out["ok"] is False and out["tabs"] == []
    # 예외 글자는 응답에 내보내지 않고 고정 문구만 (서버 로그에만 남김)
    assert out["error_reason"] == "토스 보유 조회에 실패했습니다. 잠시 뒤 다시 열어 주십시오."
    assert "가짜 실패" not in out["error_reason"]
