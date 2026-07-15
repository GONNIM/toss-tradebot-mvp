"""Naver 종토방 · Sprint 2 T55 단위 테스트.

검증:
- timestamp regex 파싱
- z-score threshold 판정
- 유니버스 순회 · 실 HTTP 우회 (stub)
- 저조종목 skip · 급증 종목 저장
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.watchlist import naver_board as nb
from backend.discovery.watchlist.store import recent_signals
from backend.services.db import get_session, init_db
from backend.services.models import LiveTapeUniverse, WatchlistSignal


_KST = timezone(timedelta(hours=9))


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
        await session.execute(delete(LiveTapeUniverse))
    yield


async def _seed_universe(items: list[tuple[str, str]]):
    async with get_session() as session:
        for code, name in items:
            session.add(LiveTapeUniverse(
                ticker=code, name=name, market="KOSDAQ",
                dept=None, close_price=1000.0, market_cap_krw=100_000_000_000,
                shares=1_000_000, amount_today=1_000_000_000,
                amount_20d_avg=None, is_squeeze_candidate=False,
                refreshed_at=datetime.now(tz=timezone.utc),
            ))


def _build_board_html(post_times_kst: list[datetime]) -> str:
    rows = "".join(
        f'<td><span class="tah p10 gray03">{t.strftime("%Y.%m.%d %H:%M")}</span></td>'
        for t in post_times_kst
    )
    return f"<html><body><table>{rows}</table></body></html>"


def test_parse_timestamps_extracts_kst():
    now_kst = datetime(2026, 7, 13, 15, 0, tzinfo=_KST)
    html = _build_board_html([now_kst, now_kst - timedelta(minutes=10)])
    parsed = nb._parse_timestamps(html)
    assert len(parsed) == 2
    # UTC 변환 검증 (KST 15:00 → UTC 06:00)
    utcs = [p.replace(microsecond=0) for p in parsed]
    assert now_kst.astimezone(timezone.utc).replace(microsecond=0) in utcs


class _StubResp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status


class _StubClient:
    def __init__(self, html_by_ticker: dict[str, str]):
        self._map = html_by_ticker

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    async def get(self, url, timeout=None, follow_redirects=True):
        for t, html in self._map.items():
            if f"code={t}" in url:
                return _StubResp(html, 200)
        return _StubResp("", 404)


@pytest.mark.asyncio
async def test_poll_naver_boards_signals_high_velocity(monkeypatch):
    """급증 종목 저장 · 저조 종목 skip."""
    await _seed_universe([("005930", "삼성전자"), ("000660", "SK하이닉스")])

    now_kst = datetime.now(tz=_KST)
    # 삼성전자 · 최근 30분 내 12건 (급증 · z=(12-5)/3 ≈ 2.33 · 통과)
    hot_times = [now_kst - timedelta(minutes=i) for i in range(1, 25, 2)]
    # SK하이닉스 · 최근 30분 내 2건 (저조 · min_count 미달)
    cold_times = [now_kst - timedelta(minutes=5), now_kst - timedelta(minutes=25)]

    html_map = {
        "005930": _build_board_html(hot_times),
        "000660": _build_board_html(cold_times),
    }

    class _ClientCls:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return _StubClient(html_map)
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(nb.httpx, "AsyncClient", _ClientCls)
    monkeypatch.setattr(nb, "_REQUEST_INTERVAL_SEC", 0.0)

    stats = await nb.poll_naver_boards()

    assert stats["universe_size"] == 2
    assert stats["signaled"] == 1  # 삼성전자만

    items = await recent_signals(hours=1)
    assert len(items) == 1
    assert items[0]["ticker"] == "005930"
    assert items[0]["source"] == "board_naver"
    assert items[0]["intensity"] >= 2.0
    assert items[0]["payload"]["recent_count"] >= nb._MIN_COUNT_FOR_SIGNAL


@pytest.mark.asyncio
async def test_poll_naver_boards_empty_universe():
    stats = await nb.poll_naver_boards()
    assert stats.get("error") == "empty_universe"
