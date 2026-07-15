"""YouTube 채널 감시 · Sprint 2 T56.

YouTube Data API v3 · 4개 채널 신규 upload 감시 · matcher 로 종목 매칭.

환경변수:
  · YOUTUBE_API_KEY  (필수 · Google Cloud Console 발급)
  · YOUTUBE_CHANNELS (선택 · JSON `{"source_key": "channel_id"}` · 기본값 override)

quota: search.list = 100 units/call · 4채널 × 24회/일 (1h 주기) = 9600 units/day (< 10000)

계획서: docs/plans/sniper/03-sprint2-week1-tasks.md T56
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from .matcher import get_matcher
from .store import upsert_signal

logger = logging.getLogger(__name__)


# 채널 ID · placeholder · 실 값은 T56 착수 시 확인 후 SOPS 로 override 권장
# Google 검색: `youtube.com/@슈카월드` 페이지 소스에서 "channelId":"UC..." 추출
_DEFAULT_CHANNELS: dict[str, str] = {
    "youtube_shuka": "UCsJ6RuBiTVWRX156FVbeaGg",     # 슈카월드 · 확인됨
    "youtube_sampro": "UChlv4GSd7OQl3js-jkLOnFA",    # 삼프로TV · 확인됨
    "youtube_hantoo": "",                              # 한투군 · TBD (env override 필요)
    "youtube_jungpro": "",                             # 정프로 · TBD (env override 필요)
}

_API_URL = "https://www.googleapis.com/youtube/v3/search"
_TIMEOUT_SEC = 8
_UPLOAD_LOOKBACK_HOURS = 12  # 최근 12시간 이내 upload 만


def _resolve_channels() -> dict[str, str]:
    override = os.environ.get("YOUTUBE_CHANNELS", "").strip()
    channels = dict(_DEFAULT_CHANNELS)
    if override:
        try:
            channels.update(json.loads(override))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[youtube] YOUTUBE_CHANNELS parse 실패 · %s · default 유지", exc)
    # 빈 ID 제거
    return {k: v for k, v in channels.items() if v}


def _api_key() -> Optional[str]:
    return os.environ.get("YOUTUBE_API_KEY") or None


async def _fetch_channel(
    client: httpx.AsyncClient, api_key: str, source: str, channel_id: str,
) -> list[dict[str, Any]]:
    params = {
        "key": api_key,
        "channelId": channel_id,
        "part": "snippet",
        "order": "date",
        "maxResults": 5,
        "type": "video",
    }
    try:
        resp = await client.get(_API_URL, params=params, timeout=_TIMEOUT_SEC)
        if resp.status_code != 200:
            logger.warning("[youtube] %s · HTTP %s · %s", source, resp.status_code, resp.text[:150])
            return []
        data = resp.json()
        return list(data.get("items") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[youtube] %s · %s", source, exc)
        return []


def _parse_published(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        # 2026-07-13T15:30:00Z
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


async def poll_youtube_channels() -> dict[str, Any]:
    """4개 채널 신규 upload 매칭 · 저장.

    Returns:
        {"per_source": {source: stats}, "total_inserted": N, ...}
    """
    api_key = _api_key()
    if not api_key:
        logger.info("[youtube] YOUTUBE_API_KEY 미설정 · skip")
        return {"error": "no_api_key"}

    channels = _resolve_channels()
    if not channels:
        return {"error": "no_channels"}

    matcher = get_matcher()
    await matcher.ensure_loaded()
    if matcher.size() == 0:
        return {"error": "empty_matcher"}

    start = datetime.now(tz=timezone.utc)
    cutoff = start - timedelta(hours=_UPLOAD_LOOKBACK_HOURS)

    per_source: dict[str, dict[str, int]] = {}
    total_inserted = 0

    async with httpx.AsyncClient() as client:
        for source, channel_id in channels.items():
            items = await _fetch_channel(client, api_key, source, channel_id)
            fetched = len(items)
            matched = 0
            inserted = 0
            for item in items:
                snippet = item.get("snippet") or {}
                video_id = (item.get("id") or {}).get("videoId")
                title = snippet.get("title") or ""
                desc = snippet.get("description") or ""
                published = _parse_published(snippet.get("publishedAt"))
                if published is None or published < cutoff:
                    continue
                tickers = matcher.match_text(f"{title} {desc}")
                if not tickers:
                    continue
                matched += 1
                for ticker in tickers:
                    row_id = await upsert_signal(
                        ticker=ticker,
                        source=source,
                        signal_type="video_upload",
                        intensity=1.0,
                        payload={
                            "title": title[:200],
                            "video_id": video_id,
                            "channel_id": channel_id,
                            "published": published.isoformat(),
                        },
                        detected_at=published,
                    )
                    if row_id is not None:
                        inserted += 1
            per_source[source] = {"fetched": fetched, "matched": matched, "inserted": inserted}
            total_inserted += inserted
            await asyncio.sleep(0.3)  # quota 여유 · 채널 간 폴 사이

    elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
    stats = {
        "per_source": per_source,
        "total_inserted": total_inserted,
        "channels": len(channels),
        "elapsed_sec": round(elapsed, 2),
    }
    logger.info("[youtube] %s", stats)
    return stats
