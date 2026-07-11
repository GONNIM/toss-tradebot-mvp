"""Notifier Profile — v2 트랙 C Phase 3.

TELEGRAM_PROFILE 환경변수 기반 알림 필터링.

- SCOUT (기본): 모든 시그널 즉시 발송 · 하드코어 유저
- SNIPER: SUPER_SIGNAL + URGENT 만 즉시 · 나머지 스킵
- WATCH: 즉시 발송 대신 30분 배치 요약 (모든 알림 큐잉 후 요약)

각 채널이 TelegramNotifier.send() 호출 전에 `should_send_by_profile()` 확인.

스펙: docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §6-2
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


VALID_PROFILES = {"SCOUT", "SNIPER", "WATCH"}
_DEFAULT_PROFILE = "SCOUT"


@dataclass(frozen=True)
class NotifyContext:
    """알림 결정 컨텍스트."""
    source: str                # meme_stock | vip | activist | super_signal | execution | kill_switch
    level: str = "INFO"        # INFO | WARNING | URGENT | CRITICAL
    tags: tuple[str, ...] = ()  # 추가 태그 (예: "SUPER_SIGNAL")


def current_profile() -> str:
    raw = os.environ.get("TELEGRAM_PROFILE", _DEFAULT_PROFILE).upper()
    return raw if raw in VALID_PROFILES else _DEFAULT_PROFILE


def should_send_by_profile(ctx: NotifyContext) -> bool:
    """profile + 컨텍스트 → 즉시 발송 여부."""
    profile = current_profile()
    if profile == "SCOUT":
        return True
    if profile == "WATCH":
        return False   # 배치로 처리
    if profile == "SNIPER":
        # SUPER_SIGNAL · URGENT 이상만 즉시
        if ctx.source == "super_signal" or "SUPER_SIGNAL" in ctx.tags:
            return True
        if ctx.level.upper() in {"URGENT", "CRITICAL"}:
            return True
        # execution/kill_switch 는 항상 예외적으로 즉시 (안전 시스템)
        if ctx.source in {"kill_switch", "execution"}:
            return True
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# WATCH 프로파일 · 30분 배치 큐
# ═══════════════════════════════════════════════════════════════
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_QUEUE_PATH = _PROJECT_ROOT / "backend" / "data" / "watch_queue.json"


class WatchQueue:
    """WATCH 프로파일용 알림 큐. 파일 기반 · thread-safe."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_QUEUE_PATH
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, items: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def enqueue(self, ctx: NotifyContext, title: str, body: str) -> None:
        with self._lock:
            items = self._load()
            items.append(
                {
                    "at": datetime.now(tz=timezone.utc).isoformat(),
                    "source": ctx.source,
                    "level": ctx.level,
                    "tags": list(ctx.tags),
                    "title": title,
                    "body": body[:300],
                }
            )
            self._save(items)

    def drain(self) -> list[dict]:
        with self._lock:
            items = self._load()
            self._save([])
            return items


_queue: Optional[WatchQueue] = None


def get_watch_queue() -> WatchQueue:
    global _queue
    if _queue is None:
        _queue = WatchQueue()
    return _queue


async def flush_watch_batch(send_async: Callable[[str, str], Awaitable[bool]]) -> dict:
    """30분 배치 · WATCH 큐 → 요약 메시지 1건 발송.

    APScheduler 30분 잡으로 등록 · 큐가 비면 no-op.
    send_async: async (title, body) → bool
    """
    items = get_watch_queue().drain()
    if not items:
        return {"sent": False, "count": 0}

    by_source: dict[str, int] = {}
    urgent_lines: list[str] = []
    for item in items:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
        if item.get("level", "").upper() in {"URGENT", "CRITICAL"}:
            urgent_lines.append(f"  • {item['title']}")

    title = f"📊 WATCH 요약 · {len(items)}건 (30분)"
    lines = ["<b>소스별</b>"]
    for src, cnt in sorted(by_source.items(), key=lambda x: -x[1]):
        lines.append(f"  · {src}: {cnt}")
    if urgent_lines:
        lines.append("\n<b>URGENT</b>")
        lines.extend(urgent_lines[:10])
    body = "\n".join(lines)

    try:
        ok = await send_async(title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WATCH 배치 발송 실패 · %s", exc)
        return {"sent": False, "count": len(items), "error": str(exc)}
    return {"sent": bool(ok), "count": len(items)}
