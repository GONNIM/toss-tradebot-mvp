"""1119-03 ① · 확인 스크립트 토큰 길 시험 (Fable 조건 다) · 실제 호출 길(Prober.toss_get)로, 바깥 네트워크 없음."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.execution.brokers.toss_client import TossClient
from backend.scripts import big_hands_probe as probe

_KST = timezone(timedelta(hours=9))


@pytest.fixture
def token_file(tmp_path):
    p = tmp_path / "toss_token.json"
    p.write_text(json.dumps({"access_token": "dummy-token-for-test", "expires_at": time.time() + 3600}))
    return p


@pytest.fixture
def issue_counter(monkeypatch):
    """TossClient 의 발급 · 갱신 · 파일 지움 길이 불리는지 센다 (불리면 시험이 실패)."""
    calls = []
    for name in ("access_token", "_refresh_token", "_issue_token_locked", "_raise_from_response"):
        monkeypatch.setattr(TossClient, name, lambda *a, _n=name, **k: calls.append(_n))
    return calls


def _prober(token_file, handler, sleeps=None):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return probe.Prober(token_file, http=http, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def test_401_stops_and_leaves_token_file_untouched(token_file, issue_counter):
    before = token_file.read_bytes()
    seen = []

    def handler(req):
        seen.append(req.headers["authorization"])
        return httpx.Response(401, json={"error": {"code": "token-revoked"}})

    p = _prober(token_file, handler)
    with pytest.raises(probe.ProbeStop) as e:
        p.toss_get("/api/v1/candles", {"symbol": "000000"})
    assert e.value.code == probe.EXIT_UNAUTHORIZED
    assert len(seen) == 1                       # 다시 시도하지 않음
    assert token_file.read_bytes() == before    # 파일 그대로
    assert issue_counter == []                  # 발급 · 갱신 · 지움 길 0회


def test_success_path_never_touches_issue_paths_or_file(token_file, issue_counter):
    before = token_file.stat().st_mtime_ns
    p = _prober(token_file, lambda req: httpx.Response(200, json={"result": []}))
    assert p.toss_get("/api/v1/candles").status_code == 200
    assert issue_counter == [] and token_file.stat().st_mtime_ns == before


def test_expiring_token_ends_without_any_http_call(token_file, issue_counter):
    token_file.write_text(json.dumps({"access_token": "x", "expires_at": time.time() + 200}))   # 만료 5분 안
    called = []
    p = _prober(token_file, lambda req: called.append(1) or httpx.Response(200, json={}))
    with pytest.raises(probe.ProbeStop) as e:
        p.toss_get("/api/v1/candles")
    assert e.value.code == probe.EXIT_NO_TOKEN and called == [] and issue_counter == []


def test_token_file_is_reread_every_call(token_file, issue_counter):
    p = _prober(token_file, lambda req: httpx.Response(200, json={}))
    p.toss_get("/a")
    token_file.write_text(json.dumps({"access_token": "x", "expires_at": time.time() + 10}))    # 호출 사이에 만료 임박
    with pytest.raises(probe.ProbeStop):
        p.toss_get("/b")


def test_missing_token_file_ends(tmp_path):
    p = _prober(tmp_path / "none.json", lambda req: httpx.Response(200, json={}))
    with pytest.raises(probe.ProbeStop) as e:
        p.toss_get("/a")
    assert e.value.code == probe.EXIT_NO_TOKEN


def test_gap_of_one_second_and_call_limit(token_file, issue_counter, monkeypatch):
    sleeps: list[float] = []
    p = _prober(token_file, lambda req: httpx.Response(200, json={}), sleeps)
    p.toss_get("/a")
    p.toss_get("/b")
    assert sleeps and all(s <= probe.MIN_GAP_SEC for s in sleeps) and max(sleeps) > 0.5
    p.toss_calls = probe.TOSS_MAX_CALLS
    with pytest.raises(probe.ProbeStop) as e:
        p.toss_get("/c")
    assert e.value.code == probe.EXIT_LIMIT


def test_block_paths_raise_when_called(monkeypatch):
    saved = {n: TossClient.__dict__[n] for n in ("access_token", "_refresh_token", "_issue_token_locked", "_raise_from_response")}
    try:
        probe.block_token_issue_paths()
        c = TossClient(client_id="a", client_secret="b")
        for name in saved:
            with pytest.raises(RuntimeError):
                getattr(c, name)()
    finally:
        for n, f in saved.items():
            setattr(TossClient, n, f)


def test_httpx_logs_raised_to_warning_by_main(monkeypatch):
    monkeypatch.setattr(probe, "in_forbidden_window", lambda now=None: True)    # 호출 없이 끝나는 길
    logging.getLogger("httpx").setLevel(logging.INFO)
    assert probe.main(["--symbol", "000000"]) == probe.EXIT_BAD_TIME
    # 시각 제한 길은 로그 설정 전에 끝나므로, 설정 길은 --ignore-time-window 없이 확인하지 않고 아래에서 따로 본다


def test_main_sets_httpx_warning_and_ends_without_token(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "in_forbidden_window", lambda now=None: False)
    monkeypatch.setattr(TossClient, "__init__", lambda self, **k: setattr(self, "_token_cache_path", tmp_path / "none.json"))
    saved = {n: TossClient.__dict__[n] for n in ("access_token", "_refresh_token", "_issue_token_locked", "_raise_from_response")}
    try:
        code = probe.main(["--symbol", "000000"])
    finally:
        for n, f in saved.items():
            setattr(TossClient, n, f)
    assert code == probe.EXIT_NO_TOKEN
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_forbidden_windows():
    assert probe.in_forbidden_window(datetime(2026, 11, 20, 10, 0, tzinfo=_KST))      # 장 시간
    assert probe.in_forbidden_window(datetime(2026, 11, 20, 6, 0, tzinfo=_KST))       # 05:55-06:45
    assert not probe.in_forbidden_window(datetime(2026, 11, 20, 22, 0, tzinfo=_KST))


def test_market_hours_weekday_only():
    # 11/21 은 토요일 · 11/22 일요일 — 장 시간 제한 없음, 정해진 작업 시각은 그대로 막음
    assert not probe.in_forbidden_window(datetime(2026, 11, 21, 11, 29, tzinfo=_KST))
    assert not probe.in_forbidden_window(datetime(2026, 11, 22, 14, 0, tzinfo=_KST))
    assert probe.in_forbidden_window(datetime(2026, 11, 21, 6, 0, tzinfo=_KST))
    assert probe.in_forbidden_window(datetime(2026, 11, 21, 9, 5, tzinfo=_KST))
    assert probe.in_forbidden_window(datetime(2026, 11, 22, 20, 30, tzinfo=_KST))
    # 평일 경계 — 09:15 막음 · 15:30 풀림
    assert probe.in_forbidden_window(datetime(2026, 11, 20, 9, 15, tzinfo=_KST))
    assert probe.in_forbidden_window(datetime(2026, 11, 20, 15, 29, tzinfo=_KST))
    assert not probe.in_forbidden_window(datetime(2026, 11, 20, 15, 30, tzinfo=_KST))


# ---- 막음 1 · 2 · 권고 ㄴ · 투자자 매매동향 (명세 v1.2.28 예시 모양) ----
def _candle(ts, close="100"):
    return {"timestamp": ts, "openPrice": "1", "highPrice": "1", "lowPrice": "1", "closePrice": close, "volume": "1", "currency": "KRW"}


def _spec_handler(seen):
    def handler(req):
        seen.append((req.url.path, dict(req.url.params)))
        path, q = req.url.path, req.url.params
        if path.endswith("/investor-trading"):
            yr = q["until"][:4]
            return httpx.Response(200, json={"result": {"records": [{"date": f"{yr}-01-05"}, {"date": f"{yr}-01-04"}], "nextUntil": f"{yr}-01-03"}})
        close = "90" if q.get("adjusted") == "true" else "100"
        return httpx.Response(200, json={"result": {"candles": [_candle("2016-01-08T00:00:00+09:00", close), _candle("2015-06-01T00:00:00+09:00", close)],
                                                     "nextBefore": "2015-05-31T00:00:00+09:00"}})
    return handler


def test_candle_rows_reads_spec_object_and_list_shapes():
    r1 = httpx.Response(200, json={"result": {"candles": [_candle("2016-01-08T00:00:00+09:00")], "nextBefore": None}})
    r2 = httpx.Response(200, json={"result": [_candle("2016-01-08T00:00:00+09:00")]})
    assert len(probe._candle_rows(r1)) == 1 and len(probe._candle_rows(r2)) == 1
    assert probe._candle_rows(httpx.Response(200, text="x")) == []


def test_probe_toss_runs_end_to_end_within_limit(token_file, issue_counter):
    seen = []
    p = _prober(token_file, _spec_handler(seen))
    out = probe.probe_toss(p, "000000", "000001")
    assert out["stock_oldest_year"] == 2015 and out["stock_adjusted_oldest_year"] == 2015
    assert out["adjusted_diff_count"] == 2 and out["delisted_status"] == 200
    assert out["kospi_oldest_year"] == 2015 and out["kosdaq_oldest_year"] == 2015
    assert out["investor_until_2016"] == {"status": 200, "records": 2, "oldest_year": 2016}
    assert out["investor_until_2020"]["oldest_year"] == 2020 and out["investor_until_2023"]["oldest_year"] == 2023
    assert p.toss_calls == 8 and p.toss_calls <= probe.TOSS_MAX_CALLS
    deep = [q for path, q in seen if path == "/api/v1/candles" and "before" in q]
    assert deep and all(q["before"].startswith("2016-01-08") for q in deep)      # 쪽 넘기기 없이 직접 지정
    assert issue_counter == []
    assert "000000" not in json.dumps(out) and "000001" not in json.dumps(out)    # 결과에 종목 코드 없음


def test_probe_toss_transport_error_logs_only_type_and_continues(token_file, issue_counter):
    def handler(req):
        if "investor-trading" in req.url.path:
            raise httpx.ReadTimeout("secret-detail https://x/000000?crtfc_key=ABC")
        return httpx.Response(200, json={"result": {"candles": [_candle("2016-01-08T00:00:00+09:00")]}})

    out = probe.probe_toss(_prober(token_file, handler), "000000", None)
    assert out["investor_until_2016"] == "전송 오류 ReadTimeout"
    assert out["stock_oldest_year"] == 2016 and "secret" not in json.dumps(out, ensure_ascii=False)


def test_probe_dart_runs_end_to_end_and_survives_transport_error():
    def handler(req):
        if req.url.path.endswith("document.xml") and req.url.params["rcept_no"] == "2":
            raise httpx.ConnectError("detail with key")
        if req.url.path.endswith("document.xml"):
            return httpx.Response(200, content=b"<x>rcept_tm</x>")
        return httpx.Response(200, json={"list": [{"rcept_dt": "20160105"}, {"rcept_dt": "20200101"}]})

    p = probe.Prober(Path("none"), http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, dart_key="k")
    out = probe.probe_dart(p, "c", "1", "2")
    assert out["document_status"] == 200 and out["document_has_time_field"] is True
    assert out["first_version_status"] == "전송 오류 ConnectError"
    assert out["elestock_total"] == 2 and out["elestock_2016_count"] == 1 and p.dart_calls == 3


def test_main_catches_transport_error_with_type_only(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(probe, "in_forbidden_window", lambda now=None: False)
    monkeypatch.setattr(TossClient, "__init__", lambda self, **k: setattr(self, "_token_cache_path", tmp_path / "t.json"))
    monkeypatch.setattr(probe, "probe_toss", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectTimeout("SECRETURL")))
    saved = {n: TossClient.__dict__[n] for n in ("access_token", "_refresh_token", "_issue_token_locked", "_raise_from_response")}
    try:
        with caplog.at_level(logging.INFO):
            code = probe.main(["--symbol", "000000"])
    finally:
        for n, f in saved.items():
            setattr(TossClient, n, f)
    assert code == probe.EXIT_TRANSPORT and "ConnectTimeout" in caplog.text and "SECRETURL" not in caplog.text
