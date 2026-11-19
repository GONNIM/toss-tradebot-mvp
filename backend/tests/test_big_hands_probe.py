"""1119-03 ① · 확인 스크립트 토큰 길 시험 (Fable 조건 다) · 실제 호출 길(Prober.toss_get)로, 바깥 네트워크 없음."""
from __future__ import annotations

import json
import logging
import time
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
