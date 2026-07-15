"""News RSS Crawler · Sprint 2 T54 단위 테스트.

검증:
- feedparser · title+summary 파싱
- matcher · 이름 매칭
- upsert_signal · watchlist_signal 저장
- 5개 소스 병렬 실패 격리
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.watchlist import news_rss as rss_mod
from backend.discovery.watchlist.matcher import MatcherEntry, TickerMatcher, get_matcher
from backend.discovery.watchlist.store import recent_signals
from backend.services.db import get_session, init_db
from backend.services.models import WatchlistSignal


# 최근 시각 · lookback window 안쪽
def _recent_pubdate() -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(minutes=30)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def _build_mock_xml(items: list[tuple[str, str]]) -> str:
    entries = "".join(
        f"""<item>
            <title>{title}</title>
            <description>{desc}</description>
            <link>https://example.com/{i}</link>
            <pubDate>{_recent_pubdate()}</pubDate>
        </item>"""
        for i, (title, desc) in enumerate(items)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>Mock RSS</title>
            {entries}
        </channel>
    </rss>"""


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
    yield


@pytest_asyncio.fixture
async def stub_matcher(monkeypatch):
    """실제 DB/FDR 우회 · 5종목 stub."""
    m = TickerMatcher()
    m._entries = [
        MatcherEntry("005930", "삼성전자", "KOSPI"),
        MatcherEntry("373220", "LG에너지솔루션", "KOSPI"),
        MatcherEntry("000660", "SK하이닉스", "KOSPI"),
        MatcherEntry("035420", "NAVER", "KOSPI"),
        MatcherEntry("068270", "셀트리온", "KOSPI"),
    ]
    m._entries.sort(key=lambda e: -len(e.name))
    m._name_index = [(e.name.lower(), e.ticker) for e in m._entries]
    m._loaded_at = datetime.now(tz=timezone.utc)
    monkeypatch.setattr(rss_mod, "get_matcher", lambda: m)
    return m


def _mock_httpx_client(xml_by_url: dict[str, str], monkeypatch):
    """httpx.AsyncClient.get 를 stub · URL 별 XML 반환."""
    class _FakeResp:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

    class _FakeClient:
        def __init__(self, *args, **kwargs): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def get(self, url, timeout=None, follow_redirects=True):
            if url in xml_by_url:
                return _FakeResp(xml_by_url[url], 200)
            return _FakeResp("", 404)

    monkeypatch.setattr(rss_mod.httpx, "AsyncClient", _FakeClient)


@pytest.mark.asyncio
async def test_poll_news_rss_matches_and_stores(stub_matcher, monkeypatch):
    """5소스 stub · 매칭·저장 검증."""
    xml_map = {
        rss_mod.RSS_SOURCES["news_yhap"]: _build_mock_xml([
            ("삼성전자 실적 호조 · 반도체 강세", "2분기 영업이익 급증"),
            ("SK하이닉스 신제품 발표", "HBM3E 양산 개시"),
        ]),
        rss_mod.RSS_SOURCES["news_edaily"]: _build_mock_xml([
            ("LG에너지솔루션 수주 대박", "GM 신규 계약"),
        ]),
        rss_mod.RSS_SOURCES["news_fnnews"]: _build_mock_xml([
            ("NAVER AI 서비스 확대", "클라우드 호조"),
        ]),
        rss_mod.RSS_SOURCES["news_hankyung"]: _build_mock_xml([
            ("셀트리온 FDA 승인", "바이오시밀러 첫 승인"),
        ]),
        rss_mod.RSS_SOURCES["news_yonhap"]: _build_mock_xml([
            ("증시 종합", "관련 종목 없음"),
        ]),
    }
    _mock_httpx_client(xml_map, monkeypatch)

    result = await rss_mod.poll_news_rss()

    assert result["matcher_size"] == 5
    assert result["total_inserted"] >= 5   # 5 언론 각각 1건 이상 매칭

    items = await recent_signals(hours=2)
    tickers = {i["ticker"] for i in items}
    assert "005930" in tickers   # 삼성전자
    assert "373220" in tickers   # LG에너지솔루션
    assert "000660" in tickers   # SK하이닉스
    assert "035420" in tickers   # NAVER
    assert "068270" in tickers   # 셀트리온

    # payload 검증 · title 포함
    samsung = [i for i in items if i["ticker"] == "005930"][0]
    assert "삼성전자" in samsung["payload"]["title"]
    assert samsung["source"] == "news_yhap"


@pytest.mark.asyncio
async def test_poll_news_rss_isolates_source_failure(stub_matcher, monkeypatch):
    """한 소스 실패해도 나머지 정상 처리."""
    xml_map = {
        # yhap 만 정상 · 나머지는 404
        rss_mod.RSS_SOURCES["news_yhap"]: _build_mock_xml([
            ("삼성전자 급등", "실적 서프라이즈"),
        ]),
    }
    _mock_httpx_client(xml_map, monkeypatch)

    result = await rss_mod.poll_news_rss()

    assert result["total_inserted"] >= 1
    assert result["per_source"]["news_yhap"]["inserted"] == 1
    # 다른 소스는 error=1 또는 fetched=0
    for source in ("news_edaily", "news_fnnews", "news_hankyung", "news_yonhap"):
        stats = result["per_source"][source]
        assert stats.get("inserted", 0) == 0


@pytest.mark.asyncio
async def test_poll_news_rss_empty_matcher(monkeypatch):
    """matcher 비어있으면 fetch 없이 early exit."""
    m = TickerMatcher()
    m._entries = []
    m._name_index = []
    m._loaded_at = datetime.now(tz=timezone.utc)
    monkeypatch.setattr(rss_mod, "get_matcher", lambda: m)

    result = await rss_mod.poll_news_rss()

    assert result.get("error") == "empty_matcher"
