"""국회 의안·정부 RSS · Sprint 2 T57 단위 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.watchlist import assembly as ab
from backend.discovery.watchlist import gov_press as gp
from backend.discovery.watchlist.industry_map import match_industries
from backend.discovery.watchlist.store import recent_signals
from backend.services.db import get_session, init_db
from backend.services.models import WatchlistSignal


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
    yield


def test_industry_map_reads_multiple_keywords():
    hits = match_industries("정부가 반도체 지원법 통과 · 배터리 관련 추가 예산 확보")
    # 반도체 · 배터리 매칭
    assert "005930" in hits  # 삼성전자 (반도체)
    assert "373220" in hits  # LG에너지솔루션 (배터리)


def test_industry_map_no_hit():
    assert match_industries("오늘 날씨 좋다") == []


@pytest.mark.asyncio
async def test_assembly_missing_key(monkeypatch):
    monkeypatch.delenv("ASSEMBLY_API_KEY", raising=False)
    result = await ab.poll_assembly_bills()
    assert result.get("error") == "no_api_key"


class _StubResp:
    def __init__(self, data, status: int = 200, text: str = ""):
        self._data = data
        self.status_code = status
        self.text = text

    def json(self): return self._data


class _StubClient:
    def __init__(self, response):
        self._resp = response

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, url, params=None, timeout=None, follow_redirects=True):
        return self._resp


@pytest.mark.asyncio
async def test_assembly_matches_industry_and_stores(monkeypatch):
    monkeypatch.setenv("ASSEMBLY_API_KEY", "test_key")

    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    payload = {"nzmimeepazxkubdpn": [
        {"head": [{"list_total_count": 2}]},
        {"row": [
            {"BILL_NO": "2200001", "BILL_NAME": "반도체 산업 지원 특별법", "PROPOSER": "홍길동 의원 외 10인", "PROPOSE_DT": today},
            {"BILL_NO": "2200002", "BILL_NAME": "일반 법률 개정안", "PROPOSER": "김철수 의원", "PROPOSE_DT": today},
        ]},
    ]}

    class _Cls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return _StubClient(_StubResp(payload, 200))
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(ab.httpx, "AsyncClient", _Cls)

    result = await ab.poll_assembly_bills()

    assert result["fetched"] == 2
    assert result["matched"] == 1  # 반도체 지원법만 매칭
    # propose_date 는 오늘 자정 UTC 이므로 최근 hours 커버 위해 30h 조회
    items = await recent_signals(hours=30)
    tickers = {i["ticker"] for i in items}
    # 반도체 매핑 대표주 중 최소 1개
    assert "005930" in tickers


@pytest.mark.asyncio
async def test_gov_press_processes_rss_and_stores(monkeypatch):
    """정부 RSS · mock XML 로 검증."""
    def _recent_pubdate():
        dt = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <item>
                <title>2차전지 관련 세제 지원 확대</title>
                <description>배터리 산업 세액공제 신설</description>
                <link>https://example.com/1</link>
                <pubDate>{_recent_pubdate()}</pubDate>
            </item>
        </channel>
    </rss>"""

    monkeypatch.setenv("GOV_RSS_SOURCES", '{"moef_rss":"https://example.com/rss.xml"}')

    class _StubHttp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, timeout=None, follow_redirects=True):
            class _R:
                status_code = 200
                text = xml
            return _R()

    class _Cls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return _StubHttp()
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(gp.httpx, "AsyncClient", _Cls)

    result = await gp.poll_gov_press()

    assert result["total_inserted"] > 0
    items = await recent_signals(hours=2)
    tickers = {i["ticker"] for i in items}
    # 2차전지 매핑
    assert "373220" in tickers  # LG에너지솔루션
