"""SignalHit 삽입 헬퍼 — v2 트랙 C Phase 3.

discovery 3채널(meme/vip/activist) 에서 알림 성공 직후 호출.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from backend.services.db import get_session
from backend.services.models import SignalHit

logger = logging.getLogger(__name__)


async def record_hit(
    *,
    ticker: str,
    source: str,
    signal_id: str,
    action: str = "buy",
    strength: int = 0,
    metadata: Optional[dict] = None,
) -> bool:
    """단일 SignalHit INSERT.

    strength: 0~100 (Router 와 동일 스케일). score = strength / 100.
    실패해도 상위 흐름(텔레그램 알림·Router)에 영향 없음 · 로그만 남김.
    """
    score = max(0.0, min(1.0, float(strength) / 100.0))
    try:
        async with get_session() as session:
            row = SignalHit(
                ticker=ticker,
                source=source,
                signal_id=signal_id[:120],
                score=score,
                action=action,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
            )
            session.add(row)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[signal_hit] INSERT 실패 · %s · %s", signal_id, exc)
        return False
