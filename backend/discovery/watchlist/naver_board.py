"""Naver 종토방 Velocity Crawler · Sprint 2 T55.

- URL: finance.naver.com/item/board.naver?code={ticker}&page=1  (200)
- 최근 30분 게시글수 카운트 · 간이 z-score · watchlist_signal 저장
- v1 · 60일 baseline 없음 · 고정 baseline_avg=5 · std=3 사용
- v1.5 에서 실 baseline 축적 후 재계산

부하 관리:
- concurrency 5 · 요청 간격 200ms
- HTTP 실패 시 skip (재시도 없음 · 30분 뒤 재실행)

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T55
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from backend.discovery.live_tape.universe import list_universe

from .store import upsert_signal

logger = logging.getLogger(__name__)

_BOARD_URL = "https://finance.naver.com/item/board.naver?code={ticker}&page=1"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
_TIMEOUT_SEC = 6
_CONCURRENCY = 5
_REQUEST_INTERVAL_SEC = 0.2
_LOOKBACK_MIN = 30

# v1 baseline (fixed) · Week 2+ 에서 실측 재계산
_BASELINE_AVG = 5.0
_BASELINE_STD = 3.0
_MIN_COUNT_FOR_SIGNAL = 5
_Z_THRESHOLD = 2.0

_KST = timezone(timedelta(hours=9))
# 페이지 내 post row 마크업 근사 · <span class="tah p10 gray03">2026.07.13 14:09</span>
_TIMESTAMP_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})")


def _parse_timestamps(html: str) -> list[datetime]:
    """페이지에서 게시글 timestamp 추출 (KST → UTC)."""
    out: list[datetime] = []
    for m in _TIMESTAMP_RE.finditer(html):
        try:
            yr, mo, dy, hh, mm = (int(x) for x in m.groups())
            kst_dt = datetime(yr, mo, dy, hh, mm, tzinfo=_KST)
            out.append(kst_dt.astimezone(timezone.utc))
        except ValueError:
            continue
    return out


async def _fetch_board(
    client: httpx.AsyncClient, ticker: str, sem: asyncio.Semaphore,
) -> tuple[str, Optional[str]]:
    async with sem:
        await asyncio.sleep(_REQUEST_INTERVAL_SEC)
        try:
            resp = await client.get(
                _BOARD_URL.format(ticker=ticker),
                timeout=_TIMEOUT_SEC, follow_redirects=True,
            )
            if resp.status_code != 200:
                return ticker, None
            return ticker, resp.text
        except Exception as exc:  # noqa: BLE001
            logger.debug("[naver_board] fetch %s · %s", ticker, exc)
            return ticker, None


async def poll_naver_boards() -> dict[str, Any]:
    """유니버스 순회 · 30분 velocity · z >= 2.0 저장.

    Returns:
        {"universe_size": N, "processed": M, "signaled": K, "elapsed_sec": T}
    """
    universe = await list_universe(limit=500)
    if not universe:
        logger.warning("[naver_board] 유니버스 비어있음 · universe refresh 선행 필요")
        return {"error": "empty_universe"}

    tickers = [u["ticker"] for u in universe]
    start = datetime.now(tz=timezone.utc)
    cutoff = start - timedelta(minutes=_LOOKBACK_MIN)

    sem = asyncio.Semaphore(_CONCURRENCY)
    signaled = 0
    processed = 0
    fetch_errors = 0

    async with httpx.AsyncClient(headers={
        "User-Agent": _USER_AGENT,
        "Referer": "https://finance.naver.com/",
    }) as client:
        tasks = [_fetch_board(client, t, sem) for t in tickers]
        for coro in asyncio.as_completed(tasks):
            ticker, html = await coro
            processed += 1
            if html is None:
                fetch_errors += 1
                continue

            timestamps = _parse_timestamps(html)
            recent_count = sum(1 for ts in timestamps if ts >= cutoff)
            if recent_count < _MIN_COUNT_FOR_SIGNAL:
                continue

            z = (recent_count - _BASELINE_AVG) / _BASELINE_STD if _BASELINE_STD > 0 else 0.0
            if z < _Z_THRESHOLD:
                continue

            row_id = await upsert_signal(
                ticker=ticker,
                source="board_naver",
                signal_type="board_post_velocity",
                intensity=float(z),
                payload={
                    "recent_count": recent_count,
                    "lookback_min": _LOOKBACK_MIN,
                    "baseline_avg": _BASELINE_AVG,
                    "baseline_std": _BASELINE_STD,
                },
            )
            if row_id is not None:
                signaled += 1

    elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
    stats = {
        "universe_size": len(tickers),
        "processed": processed,
        "fetch_errors": fetch_errors,
        "signaled": signaled,
        "elapsed_sec": round(elapsed, 2),
    }
    logger.info("[naver_board] %s", stats)
    return stats
