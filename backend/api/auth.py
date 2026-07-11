"""실주문 API 인증 계층 · Sprint 1 T44.

서버 로그인 기능이 없으므로 자금이 움직이는 모든 엔드포인트에
`X-API-Token` 헤더 검증을 강제한다.

토큰:
- 환경변수 `SNIPER_API_TOKEN` (SOPS 저장 · 최소 32자 랜덤)
- 미설정 시 인증 자체가 항상 실패 (안전측)

활성화 스위치:
- `SNIPER_LIVE_ENABLED=true` env 명시 시에만 실주문 라우트 활성
- 기본 false · Paper 모드로 fallback

감사 로그:
- 요청 IP · User-Agent · 결과 → `sniper_api_access` 테이블 (Sprint 1.5 · Sprint 1은 표준 로그)

참조: feedback_sniper_security_and_flexibility
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Header, HTTPException, Request, status

logger = logging.getLogger(__name__)


def is_sniper_live_enabled() -> bool:
    """실주문 활성 스위치 · 기본 false."""
    raw = os.environ.get("SNIPER_LIVE_ENABLED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _get_configured_token() -> Optional[str]:
    token = os.environ.get("SNIPER_API_TOKEN", "").strip()
    return token or None


async def require_sniper_token(
    request: Request,
    x_api_token: Optional[str] = Header(None, alias="X-API-Token"),
) -> str:
    """FastAPI 의존성 · 실주문/파라미터 편집 라우트에서 사용.

    - SNIPER_LIVE_ENABLED=false → 403 (실주문 비활성)
    - SNIPER_API_TOKEN 미설정 → 500 (서버 설정 오류)
    - X-API-Token 헤더 불일치 → 401
    - 성공 시 클라이언트 정보 로그 · 토큰 반환 (호출자가 필요 시 사용)
    """
    client_host = request.client.host if request.client else "-"
    user_agent = request.headers.get("User-Agent", "-")

    if not is_sniper_live_enabled():
        logger.warning(
            "sniper auth 차단 · LIVE 비활성 · path=%s · ip=%s", request.url.path, client_host
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sniper 실주문이 비활성화되어 있습니다 (SNIPER_LIVE_ENABLED=false).",
        )

    configured = _get_configured_token()
    if not configured:
        logger.error(
            "sniper auth 오류 · SNIPER_API_TOKEN 미설정 · path=%s", request.url.path
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버에 SNIPER_API_TOKEN 미설정. 관리자 문의.",
        )

    if not x_api_token or x_api_token != configured:
        logger.warning(
            "sniper auth 실패 · path=%s · ip=%s · UA=%s",
            request.url.path, client_host, user_agent[:80],
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 X-API-Token.",
            headers={"WWW-Authenticate": "X-API-Token"},
        )

    logger.info(
        "sniper auth 통과 · path=%s · ip=%s · UA=%s",
        request.url.path, client_host, user_agent[:80],
    )
    return x_api_token
