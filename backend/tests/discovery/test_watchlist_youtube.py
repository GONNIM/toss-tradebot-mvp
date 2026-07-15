"""YouTube 채널 감시 · Sprint 2 T56 단위 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.watchlist import youtube as yt
from backend.discovery.watchlist.matcher import MatcherEntry, TickerMatcher
from backend.discovery.watchlist.store import recent_signals
from backend.services.db import get_session, init_db
from backend.services.models import WatchlistSignal


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
    yield


def _recent_iso() -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest_asyncio.fixture
async def stub_matcher(monkeypatch):
    m = TickerMatcher()
    m._entries = [
        MatcherEntry("005930", "삼성전자", "KOSPI"),
        MatcherEntry("068270", "셀트리온", "KOSPI"),
    ]
    m._entries.sort(key=lambda e: -len(e.name))
    m._name_index = [(e.name.lower(), e.ticker) for e in m._entries]
    m._loaded_at = datetime.now(tz=timezone.utc)
    monkeypatch.setattr(yt, "get_matcher", lambda: m)
    return m


class _StubResp:
    def __init__(self, data: dict, status: int = 200):
        self._data = data
        self.status_code = status
        self.text = ""

    def json(self): return self._data


class _StubClient:
    def __init__(self, payload_by_channel: dict[str, dict]):
        self._map = payload_by_channel

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, url, params=None, timeout=None):
        cid = (params or {}).get("channelId")
        payload = self._map.get(cid) or {"items": []}
        return _StubResp(payload)


@pytest.mark.asyncio
async def test_missing_api_key_skips(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    result = await yt.poll_youtube_channels()
    assert result.get("error") == "no_api_key"


@pytest.mark.asyncio
async def test_polls_and_matches_uploads(stub_matcher, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CHANNELS", '{"youtube_shuka":"UC_shuka","youtube_sampro":"UC_sampro"}')

    payload_by_channel = {
        "UC_shuka": {"items": [{
            "id": {"videoId": "vid1"},
            "snippet": {
                "title": "삼성전자 급등 · 왜 오르는가",
                "description": "실적 서프라이즈",
                "publishedAt": _recent_iso(),
            }
        }]},
        "UC_sampro": {"items": [{
            "id": {"videoId": "vid2"},
            "snippet": {
                "title": "셀트리온 FDA 승인",
                "description": "바이오시밀러",
                "publishedAt": _recent_iso(),
            }
        }]},
    }

    class _Cls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return _StubClient(payload_by_channel)
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(yt.httpx, "AsyncClient", _Cls)

    result = await yt.poll_youtube_channels()

    assert result["total_inserted"] == 2
    assert result["per_source"]["youtube_shuka"]["inserted"] == 1
    assert result["per_source"]["youtube_sampro"]["inserted"] == 1

    items = await recent_signals(hours=1)
    tickers = {i["ticker"] for i in items}
    assert tickers == {"005930", "068270"}


@pytest.mark.asyncio
async def test_stale_uploads_skipped(stub_matcher, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test_key")
    monkeypatch.setenv("YOUTUBE_CHANNELS", '{"youtube_shuka":"UC_shuka"}')

    stale_iso = (datetime.now(tz=timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {"UC_shuka": {"items": [{
        "id": {"videoId": "old_vid"},
        "snippet": {
            "title": "삼성전자 예전 영상",
            "description": "1일 전",
            "publishedAt": stale_iso,
        }
    }]}}

    class _Cls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return _StubClient(payload)
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(yt.httpx, "AsyncClient", _Cls)

    result = await yt.poll_youtube_channels()
    assert result["total_inserted"] == 0
