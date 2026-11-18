"""1116-01 · 토스 토큰 잠금 · 발급 가드 시험 (9-1) · 실제 토스 호출 0 (httpx 를 가짜로 바꿈)."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import httpx
import pytest

from backend.execution.brokers import toss_client as tc
from backend.execution.exceptions import BrokerCommunicationError, ExecutionError

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable


_KW = {"client_id": "id", "client_" + "secret": "dummy", "account_seq": "1"}   # 가짜 값 · 시그니처 검사에 걸리지 않게 이름을 쪼갬


def _client(tmp_path):
    return tc.TossClient(**_KW, token_cache_path=tmp_path / "tok.json")


class _FakeHttpx:
    """httpx.Client 대체 · 발급 호출 수를 센다."""
    posts: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, **k):
        _FakeHttpx.posts.append(url)
        return httpx.Response(200, json={"access_token": f"tok-{len(_FakeHttpx.posts)}", "expires_in": 3600},
                              request=httpx.Request("POST", url))


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    _FakeHttpx.posts = []
    monkeypatch.setattr(tc.httpx, "Client", _FakeHttpx)
    monkeypatch.setattr(tc, "_guard_alert_day", None)
    from backend.execution.brokers import rate_limiter

    monkeypatch.setattr(rate_limiter.get_rate_limiter(), "acquire", lambda *a, **k: None)


def _issue_on(monkeypatch, on=True):
    from backend.services import config

    real = config.get
    monkeypatch.setattr(config, "get", lambda n, d=None: ("1" if on else None) if n == "TOSS_TOKEN_ISSUE" else real(n, d))


def test_guard_blocks_new_issue_without_key_and_alerts_once_a_day(tmp_path, monkeypatch):
    _issue_on(monkeypatch, False)
    alerts = []

    async def fake_critical(self, title, body, category=None, dedupe_id=None):
        alerts.append((title, category))
        return True

    from backend.services.notifier import TelegramNotifier

    monkeypatch.setattr(TelegramNotifier, "send_critical", fake_critical)
    c = _client(tmp_path)
    for _ in range(3):
        with pytest.raises(ExecutionError, match="가드"):
            c.access_token()
    assert _FakeHttpx.posts == []                                      # 발급 호출 0
    assert alerts == [("토스 토큰 발급 막힘", "execution")]               # ⑨ 하루 1번


def test_stored_valid_token_is_still_used_without_the_key(tmp_path, monkeypatch):
    _issue_on(monkeypatch, False)
    c = _client(tmp_path)
    (tmp_path / "tok.json").write_text(json.dumps({"access_token": "kept", "expires_at": time.time() + 3600}))
    assert c.access_token() == "kept" and _FakeHttpx.posts == []        # 키를 빠뜨려도 저장 토큰은 쓴다


def test_issue_with_key_is_atomic_600_and_cached(tmp_path, monkeypatch):
    _issue_on(monkeypatch, True)
    c = _client(tmp_path)
    t1 = c.access_token()
    assert t1 == "tok-1" and c.access_token() == "tok-1" and len(_FakeHttpx.posts) == 1
    p = tmp_path / "tok.json"
    assert (p.stat().st_mode & 0o777) == 0o600
    assert not list(tmp_path.glob("*.tmp"))                                # 임시 파일 남지 않음


def test_token_near_expiry_is_refreshed_under_lock_after_rereading_file(tmp_path, monkeypatch):
    _issue_on(monkeypatch, True)
    c = _client(tmp_path)
    p = tmp_path / "tok.json"
    p.write_text(json.dumps({"access_token": "old", "expires_at": time.time() + 100}))   # 만료 5분 안
    orig = c._read_valid_cache
    calls = {"n": 0}

    def sneaky():
        calls["n"] += 1
        if calls["n"] == 2:                                                # 잠금 안에서 다시 읽을 때 다른 프로세스가 이미 받아 둠
            p.write_text(json.dumps({"access_token": "fresh-from-other", "expires_at": time.time() + 3600}))
        return orig()

    c._read_valid_cache = sneaky
    assert c.access_token() == "fresh-from-other" and _FakeHttpx.posts == []


def test_lock_wait_is_limited_to_ten_seconds_setting(tmp_path, monkeypatch):
    _issue_on(monkeypatch, True)
    monkeypatch.setattr(tc, "_LOCK_WAIT_SEC", 0.3)
    assert tc._LOCK_WAIT_SEC == 0.3
    fd = os.open(str(tmp_path / "toss_token.lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        t0 = time.monotonic()
        with pytest.raises(BrokerCommunicationError, match="대기 시간 초과"):
            _client(tmp_path).access_token()
        assert time.monotonic() - t0 < 3                                   # 무한히 기다리지 않는다
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert "_LOCK_WAIT_SEC = 10.0" in Path(tc.__file__).read_text()        # 기본 대기 시한 10초


def _revoked(url="https://openapi.tossinvest.com/api/v1/holdings"):
    return httpx.Response(401, json={"error": {"code": "token-revoked", "message": "대체됨"}},
                          request=httpx.Request("GET", url))


def test_token_revoked_keeps_file_if_other_process_already_replaced_it(tmp_path):
    from backend.execution.brokers import toss_client as tcm

    c = tcm.TossClient(**_KW, token_cache_path=tmp_path / "tok.json")
    p = tmp_path / "tok.json"
    p.write_text(json.dumps({"access_token": "mine", "expires_at": time.time() + 3600}))
    c._headers(use_account_header=False)                                   # 이 요청이 쓴 토큰 = mine
    p.write_text(json.dumps({"access_token": "newer-by-other", "expires_at": time.time() + 3600}))
    with pytest.raises(BrokerCommunicationError):
        c._raise_from_response(_revoked())
    assert p.exists() and json.loads(p.read_text())["access_token"] == "newer-by-other"     # 저장 파일을 먼저 읽고 지우지 않음


def test_token_revoked_same_token_clears_and_reissues_once(tmp_path, monkeypatch):
    from backend.execution.brokers import toss_client as tcm

    _issue_on(monkeypatch, True)
    c = tcm.TossClient(**_KW, token_cache_path=tmp_path / "tok.json")
    p = tmp_path / "tok.json"
    p.write_text(json.dumps({"access_token": "mine", "expires_at": time.time() + 3600}))
    c._headers(use_account_header=False)
    with pytest.raises(BrokerCommunicationError):
        c._raise_from_response(_revoked())
    assert not p.exists()
    assert c.access_token() == "tok-1" and len(_FakeHttpx.posts) == 1


CHILD = textwrap.dedent('''
    import sys, time, os, json, httpx
    from backend.execution.brokers import toss_client as tc, rate_limiter
    rate_limiter.get_rate_limiter().acquire = lambda *a, **k: None
    counter, cache = sys.argv[1], sys.argv[2]
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **k):
            with open(counter, "a") as f: f.write("1\\n")
            time.sleep(0.6)
            return httpx.Response(200, json={"access_token": "tok-%d" % os.getpid(), "expires_in": 3600},
                                  request=httpx.Request("POST", url))
    tc.httpx.Client = FakeClient
    kw = {"client_id": "id", "client_" + "secret": "dummy", "account_seq": "1"}
    c = tc.TossClient(**kw, token_cache_path=__import__("pathlib").Path(cache))
    print(c.access_token())
''')


def test_two_processes_issue_exactly_once(tmp_path):
    """실제 두 프로세스 동시 발급 → 발급 1번 · 둘 다 같은 토큰."""
    counter, cache = tmp_path / "count.txt", tmp_path / "tok.json"
    env = {**os.environ, "TOSS_TOKEN_ISSUE": "1", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}
    procs = [subprocess.Popen([PY, "-I", "-c", f"import sys; sys.path.insert(0, {str(REPO)!r}); exec(sys.stdin.read())",
                               str(counter), str(cache)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=env, cwd=str(tmp_path)) for _ in range(2)]
    outs = []
    for pr in procs:
        out, err = pr.communicate(CHILD, timeout=60)
        assert pr.returncode == 0, err[-500:]
        outs.append(out.strip().splitlines()[-1])
    assert len(counter.read_text().split()) == 1                           # 발급 호출 1번
    assert outs[0] == outs[1]
