"""Telegram Bot API notifier (Phase 6).

환경변수:
  TELEGRAM_BOT_TOKEN — BotFather 발급 토큰
  TELEGRAM_CHAT_ID   — 사용자 chat_id (getUpdates 확인)

미설정 시 send_message 는 조용히 False 반환 → 잡 실패 방지.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_TIMEOUT_SEC = 10.0


def is_configured() -> bool:
    return bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_CHAT_ID", "").strip()
    )


async def send_message(
    text: str,
    chat_id: Optional[str] = None,
    token: Optional[str] = None,
    parse_mode: str = "Markdown",
) -> bool:
    """Telegram Bot API sendMessage.

    Returns: True on 200, False on any failure or missing config.
    """
    token = (token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = (chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat_id:
        logger.info("[telegram] token/chat_id 미설정 — skip")
        return False

    url = f"{_API_BASE}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=_TIMEOUT_SEC)
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.warning(f"[telegram] sendMessage failed: {e}")
        return False
