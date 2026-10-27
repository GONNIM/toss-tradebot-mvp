"""RSSClient 수신 경로 — 시간 제한 · 캐시 (2026-10-23 · 1023-01)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest

from backend.discovery.data_sources import rss as rss_mod
from backend.discovery.data_sources.rss import FEED_TIMEOUT_SEC, RSSClient


def _feed_xml(title: str) -> str:
    pub = format_datetime(datetime.now(timezone.utc))
    return f"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>{title}</title><description>d</description><link>https://x/1</link><pubDate>{pub}</pubDate></item>
</channel></rss>"""


class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status


def test_timeout_returns_empty_and_is_cached(monkeypatch):
    """시간 초과면 빈 목록 · 실패도 캐시해 다음 종목에서 다시 받지 않음."""
    calls: list[dict] = []

    def _get(url, **kw):
        calls.append(kw)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(rss_mod.httpx, "get", _get)
    client = RSSClient(feeds={"A": "https://a", "B": "https://b"})
    assert client.fetch_for_ticker("AAPL", 24) == []
    assert client.fetch_for_ticker("MSFT", 24) == []
    assert len(calls) == 2  # 피드 2개 × 1번
    assert all(kw["timeout"] == FEED_TIMEOUT_SEC for kw in calls)


def test_parses_text_and_filters_ticker(monkeypatch):
    monkeypatch.setattr(rss_mod.httpx, "get", lambda url, **kw: _Resp(_feed_xml("Apple (NASDAQ: AAPL) beats")))
    client = RSSClient(feeds={"A": "https://a"})
    items = client.fetch_for_ticker("AAPL", 24)
    assert len(items) == 1
    assert items[0].ticker == "AAPL"
    assert client.fetch_for_ticker("MSFT", 24) == []


def test_cache_reused_across_tickers_and_threads(monkeypatch):
    """여러 스레드가 동시에 불러도 피드마다 한 번만 받음."""
    calls: list[str] = []
    lock = threading.Lock()

    def _get(url, **kw):
        with lock:
            calls.append(url)
        return _Resp(_feed_xml("$TSLA news"))

    monkeypatch.setattr(rss_mod.httpx, "get", _get)
    client = RSSClient(feeds={"A": "https://a", "B": "https://b", "C": "https://c", "D": "https://d"})
    threads = [threading.Thread(target=client.fetch_for_ticker, args=("TSLA", 24)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(calls) == ["https://a", "https://b", "https://c", "https://d"]


def test_http_error_status_returns_empty(monkeypatch):
    monkeypatch.setattr(rss_mod.httpx, "get", lambda url, **kw: _Resp("", status=503))
    client = RSSClient(feeds={"A": "https://a"})
    assert client.fetch_recent(24) == []


def test_total_worst_case_under_step_timeout():
    """피드당 제한 × 기본 피드 수 < crazy_picks PER_STEP_TIMEOUT (20초)."""
    import inspect

    from backend.discovery import crazy_picks

    # PER_STEP_TIMEOUT 은 함수 안 지역 상수라 소스로 확인
    assert "PER_STEP_TIMEOUT = 20.0" in inspect.getsource(crazy_picks)
    assert FEED_TIMEOUT_SEC * len(rss_mod.DEFAULT_FEEDS) < 20.0


def test_same_release_in_two_feeds_counted_once(monkeypatch):
    """피드끼리 겹친 보도자료 (같은 link) 는 한 번만 센다 (1023-07)."""
    pub = format_datetime(datetime.now(timezone.utc))

    def _xml(link: str) -> str:
        return f"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Acme (NASDAQ: ACME) news</title><description>d</description><link>{link}</link><pubDate>{pub}</pubDate></item>
</channel></rss>"""

    bodies = {"https://all": _xml("https://x/1"), "https://health": _xml("https://x/1"), "https://fin": _xml("https://x/2")}
    monkeypatch.setattr(rss_mod.httpx, "get", lambda url, **kw: _Resp(bodies[url]))
    client = RSSClient(feeds={"All": "https://all", "Health": "https://health", "Fin": "https://fin"})
    assert [i.link for i in client.fetch_for_ticker("ACME", 24)] == ["https://x/1", "https://x/2"]


def test_default_feeds_are_prnewswire_only():
    """403 (Akamai) 피드는 빼고 PRNewswire 공식 피드만 (1023-07)."""
    assert all("prnewswire.com/rss/" in u for u in rss_mod.DEFAULT_FEEDS.values())
