"""관리자 세션 라우트 · Phase D 주 7 · 2026-07-31.

목적: localStorage → httpOnly 쿠키 세션 이관.
프론트는 이 라우트에 관리자 토큰(SNIPER_API_TOKEN)을 POST하여 세션 쿠키를
발급받는다. 이후 모든 관리·편집·실주문 라우트는 쿠키 기반 인증으로 통과.

엔드포인트:
    POST   /api/v1/admin/session   — 로그인 (토큰 검증 → Set-Cookie)
    DELETE /api/v1/admin/session   — 로그아웃 (쿠키 삭제)
    GET    /api/v1/admin/session   — whoami (role 반환 · 예외 없음)

참조: docs/plans/toss-tradebot-tobe/roadmap-12week.md Phase D 주 7
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.api.auth import (
    _get_configured_token,
    _record_access,
    clear_session_cookie,
    get_current_role,
    is_sniper_live_enabled,
    set_session_cookie,
)

router = APIRouter()


class SessionLoginPayload(BaseModel):
    token: str = Field(..., min_length=1, max_length=200)


class SessionInfo(BaseModel):
    role: str            # admin | subscriber | anon
    live_enabled: bool   # SNIPER_LIVE_ENABLED 상태 (UI 배지용)


@router.post("", response_model=SessionInfo)
async def login(payload: SessionLoginPayload, request: Request, response: Response) -> SessionInfo:
    """관리자 로그인 · 토큰 검증 성공 시 httpOnly 쿠키 발급."""
    configured = _get_configured_token()
    if not configured:
        await _record_access(
            request, event="server_misconfig", role="anon",
            token_source="body", detail="SNIPER_API_TOKEN 미설정",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버에 SNIPER_API_TOKEN 미설정. 관리자 문의.",
        )

    if payload.token != configured:
        await _record_access(request, event="login_fail", role="anon", token_source="body")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 관리자 토큰.",
        )

    set_session_cookie(response, configured)
    await _record_access(request, event="login_ok", role="admin", token_source="body")
    return SessionInfo(role="admin", live_enabled=is_sniper_live_enabled())


@router.delete("", response_model=SessionInfo)
async def logout(request: Request, response: Response) -> SessionInfo:
    """관리자 로그아웃 · 쿠키 삭제 (idempotent · 세션 없어도 200)."""
    clear_session_cookie(response)
    await _record_access(request, event="logout", role="anon", token_source="cookie")
    return SessionInfo(role="anon", live_enabled=is_sniper_live_enabled())


@router.get("", response_model=SessionInfo)
async def whoami(request: Request) -> SessionInfo:
    """현재 세션 상태 조회 · 예외 없음.

    프론트 부팅 시 role 확인용 (login form vs admin nav 분기).
    """
    role = await get_current_role(
        x_api_token=request.headers.get("X-API-Token"),
        sniper_session=request.cookies.get("sniper_session"),
    )
    return SessionInfo(role=role, live_enabled=is_sniper_live_enabled())
