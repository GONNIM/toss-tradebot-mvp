"""1025-08 · 토스 참고 환율 (USD→KRW · GET /api/v1/exchange-rate).

토스 명세: baseCurrency·quoteCurrency 필수 · rate 는 문자열 소수 · 1분 갱신 참고용 (실제 환전과 다를 수 있음).
출처를 셋으로 밝힌다: toss (방금 받음) · cached (5분 안 · 또는 실패 시 마지막 성공 값) · fallback (성공 기록 없음 → 1330 고정).
파싱 실패는 성공으로 치지 않는다 (다음 호출에 다시 묻는다).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

FALLBACK_USD_KRW = 1330.0
CACHE_SEC = 300.0


@dataclass(frozen=True)
class FxQuote:
    rate: float
    source: str  # toss | cached | fallback
    valid_from: Optional[str] = None


_last: Optional[FxQuote] = None
_last_at: float = 0.0


def reset_cache() -> None:
    global _last, _last_at
    _last, _last_at = None, 0.0


def _parse(data) -> Optional[float]:
    if not isinstance(data, dict):
        return None
    try:
        v = float(data.get("rate"))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def usd_krw(client=None, now: Optional[float] = None) -> FxQuote:
    """USD→KRW 환율 · 토스 호출은 서버에서만 (client 없으면 서버 토스 클라이언트)."""
    global _last, _last_at
    now = time.time() if now is None else now
    if _last is not None and now - _last_at < CACHE_SEC:
        return FxQuote(_last.rate, "cached", _last.valid_from)
    try:
        if client is None:
            from backend.execution.brokers.toss_client import get_toss_client

            client = get_toss_client()
        data = client.get(
            "/api/v1/exchange-rate",
            params={"baseCurrency": "USD", "quoteCurrency": "KRW"},
            use_account_header=False,
        )
        rate = _parse(data)
        if rate is not None:
            _last = FxQuote(rate, "toss", data.get("validFrom"))
            _last_at = now
            return _last
        logger.warning("[fx] 환율 응답을 읽지 못함 · 키 rate 없음 또는 숫자 아님")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fx] 환율 조회 실패 · %s", type(exc).__name__)
    if _last is not None:
        return FxQuote(_last.rate, "cached", _last.valid_from)
    return FxQuote(FALLBACK_USD_KRW, "fallback", None)
