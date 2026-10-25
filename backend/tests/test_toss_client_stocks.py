"""1025-06 · 토스 종목 정보 조회 · token-revoked 처리 (실제 호출 없음)."""
from __future__ import annotations

import httpx
import pytest

from backend.execution.brokers.toss_client import TossClient
from backend.execution.exceptions import BrokerCommunicationError


def _client(tmp_path):
    return TossClient(client_id="id", client_secret="secret", account_seq="1", token_cache_path=tmp_path / "tok.json")


def test_stocks_no_account_header(tmp_path, monkeypatch):
    c = _client(tmp_path)
    seen = {}

    def fake_get(path, *, params=None, use_account_header=True):
        seen.update(path=path, params=params, account=use_account_header)
        return [{"symbol": "WEN", "listDate": "1981-05-27"}]

    monkeypatch.setattr(c, "get", fake_get)
    assert c.stocks(["WEN", "AAPL"]) == [{"symbol": "WEN", "listDate": "1981-05-27"}]
    assert seen == {"path": "/api/v1/stocks", "params": {"symbols": "WEN,AAPL"}, "account": False}


def test_stocks_over_200_raises(tmp_path):
    with pytest.raises(ValueError):
        _client(tmp_path).stocks([f"S{i}" for i in range(201)])


def test_stocks_empty_is_empty(tmp_path, monkeypatch):
    c = _client(tmp_path)
    monkeypatch.setattr(c, "get", lambda *a, **k: pytest.fail("호출하면 안 됨"))
    assert c.stocks([]) == []


def test_token_revoked_clears_cache(tmp_path):
    c = _client(tmp_path)
    cache = tmp_path / "tok.json"
    cache.write_text('{"access_token": "x", "expires_at": 9999999999}', encoding="utf-8")
    resp = httpx.Response(401, json={"error": {"code": "token-revoked", "message": "새로 발급된 토큰으로 대체"}},
                          request=httpx.Request("GET", "https://openapi.tossinvest.com/api/v1/stocks"))
    with pytest.raises(BrokerCommunicationError):
        c._raise_from_response(resp)
    assert not cache.exists()
