"""국회 의안정보 API · Sprint 2 T57.

open.assembly.go.kr · 최근 발의 법안 조회 · 산업 keyword 매핑.

환경변수:
  · ASSEMBLY_API_KEY  (필수 · https://open.assembly.go.kr 발급)

API: https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn?KEY={key}&Type=json&pIndex=1&pSize=100
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from .industry_map import match_industries
from .store import upsert_signal

logger = logging.getLogger(__name__)

_API_URL = "https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn"
_TIMEOUT_SEC = 10
_LOOKBACK_DAYS = 3   # 최근 3일 이내 발의


def _api_key() -> Optional[str]:
    return os.environ.get("ASSEMBLY_API_KEY") or None


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def poll_assembly_bills() -> dict[str, Any]:
    """국회 최근 발의 법안 · 산업 매칭 · 저장.

    Returns:
        {"fetched": N, "matched": M, "inserted": K, ...}
    """
    api_key = _api_key()
    if not api_key:
        logger.info("[assembly] ASSEMBLY_API_KEY 미설정 · skip")
        return {"error": "no_api_key"}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    params = {"KEY": api_key, "Type": "json", "pIndex": 1, "pSize": 100}

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(_API_URL, params=params, timeout=_TIMEOUT_SEC)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[assembly] fetch 실패 · %s", exc)
            return {"error": str(exc)[:100]}

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}

    payload = resp.json()
    # open.assembly.go.kr 응답 구조: {"nzmimeepazxkubdpn":[{"head":[...]},{"row":[...]}]}
    key = "nzmimeepazxkubdpn"
    root = payload.get(key)
    if not isinstance(root, list) or len(root) < 2:
        return {"error": "unexpected_shape"}
    rows = root[1].get("row") if isinstance(root[1], dict) else None
    if not rows:
        return {"fetched": 0, "matched": 0, "inserted": 0}

    matched = 0
    inserted = 0
    for row in rows:
        title = str(row.get("BILL_NAME") or "")
        proposer = str(row.get("PROPOSER") or "")
        propose_date = _parse_date(row.get("PROPOSE_DT"))
        bill_no = str(row.get("BILL_NO") or "")
        if propose_date is not None and propose_date < cutoff:
            continue
        tickers = match_industries(title)
        if not tickers:
            continue
        matched += 1
        for ticker in tickers:
            row_id = await upsert_signal(
                ticker=ticker,
                source="assembly",
                signal_type="bill_registered",
                intensity=0.5,
                payload={"bill_no": bill_no, "title": title[:200], "proposer": proposer[:100]},
                detected_at=propose_date or datetime.now(tz=timezone.utc),
            )
            if row_id is not None:
                inserted += 1

    stats = {"fetched": len(rows), "matched": matched, "inserted": inserted}
    logger.info("[assembly] %s", stats)
    return stats
