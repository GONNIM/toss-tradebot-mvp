"""Webhooks 라우트 · Phase D 주 8 · 2026-07-31.

Stage 3 유료 구독(Toss Payments · Stripe 등) 실제 훅 이전의 임시 엔드포인트.

엔드포인트:
    POST /api/v1/webhooks/payment  — 200 반환 · 이벤트 요약을 감사 로그에 기록

설계:
- 인증 없음 (외부 결제사가 서명·webhook secret 로 검증하는 게 표준).
  실제 구현 시 X-Signature 헤더 검증 로직 추가.
- 요청 본문은 sniper_api_access.detail (JSON 잘라서) 에 기록 · 별도 테이블은 실제 결제 훅 착수 시 신설.
- 지금은 스텁 · 항상 200. 재시도 정책·중복 방지 로직은 실제 훅 도입 시 설계.

참조: docs/plans/toss-tradebot-tobe/roadmap-12week.md Phase D 주 8
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request

from backend.api.auth import _record_access

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/payment")
async def payment_webhook_stub(request: Request) -> dict[str, Any]:
    """결제 webhook 스텁 · 200 반환 · 이벤트 요약을 감사 로그에 append."""
    raw = await request.body()
    detail: dict[str, Any] = {"size": len(raw)}
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
        # 흔한 필드만 골라서 축약 저장 (원문 전체는 남기지 않음 · PII 방지)
        for key in ("event", "type", "orderId", "id", "status"):
            if key in payload:
                detail[key] = str(payload[key])[:60]
    except Exception:  # noqa: BLE001
        detail["parse"] = "invalid_json"

    await _record_access(
        request,
        event="payment_webhook",
        role="anon",
        token_source="none",
        detail=json.dumps(detail, ensure_ascii=False)[:200],
    )
    logger.info("[webhook] payment stub · %s", detail)
    return {"ok": True, "stub": True}
