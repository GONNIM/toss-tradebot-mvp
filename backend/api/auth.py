"""실주문 API 인증 계층 · Sprint 1 T44 · Phase D 주 7 확장.

Phase D (2026-07-31~): localStorage 기반 X-API-Token 헤더 방식을
httpOnly 쿠키 세션으로 이관. XSS 방어선 완결.

토큰:
- 환경변수 `SNIPER_API_TOKEN` (SOPS 저장 · 최소 32자 랜덤)
- 미설정 시 인증 자체가 항상 실패 (안전측)

토큰 수신 우선순위 (하위 호환):
1. httpOnly 쿠키 `sniper_session` (Phase D 정식 경로)
2. `X-API-Token` 헤더 (기존 · 서버 to 서버 · 크론 스크립트 유지)

활성화 스위치:
- `SNIPER_LIVE_ENABLED=true` env 명시 시에만 실주문 라우트 활성
- 기본 false · Paper 모드로 fallback

Role (Phase D):
- admin: 세션 쿠키/헤더로 SNIPER_API_TOKEN 검증 통과
- subscriber: (Stage 3 예약 · 현재 미구현)
- anon: 그 외 (읽기 전용 공개 라우트만 접근 가능)

감사 로그:
- Phase D 이전: 표준 logging 만 사용
- Phase D 이후: `sniper_api_access` 테이블 append (login·logout·auth 성공/실패)

참조:
- feedback_sniper_security_and_flexibility
- docs/plans/toss-tradebot-tobe/roadmap-12week.md Phase D 주 7
"""
from __future__ import annotations

import logging
import os
from typing import Literal, Optional

from fastapi import Cookie, Header, HTTPException, Request, Response, status

logger = logging.getLogger(__name__)


SESSION_COOKIE_NAME = "sniper_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12h · 관리자 세션 · 재로그인 부담 최소

Role = Literal["admin", "subscriber", "anon"]


def is_sniper_live_enabled() -> bool:
    """실주문 활성 스위치 · 기본 false."""
    raw = os.environ.get("SNIPER_LIVE_ENABLED", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _get_configured_token() -> Optional[str]:
    token = os.environ.get("SNIPER_API_TOKEN", "").strip()
    return token or None


def _cookie_secure() -> bool:
    """Set-Cookie Secure 플래그 · 프로덕션(HTTPS) 강제."""
    raw = os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # 기본: 프로덕션 도메인이면 True, 그 외 False (로컬 HTTP)
    return os.environ.get("APP_ENV", "").strip().lower() == "production"


def _pick_token(cookie_value: Optional[str], header_value: Optional[str]) -> tuple[Optional[str], str]:
    """토큰 후보와 출처 라벨 반환.

    쿠키 우선 · 헤더 fallback · 없으면 (None, "none").
    """
    if cookie_value:
        return cookie_value, "cookie"
    if header_value:
        return header_value, "header"
    return None, "none"


async def _record_access(
    request: Request,
    *,
    event: str,
    role: Role,
    token_source: str,
    detail: Optional[str] = None,
) -> None:
    """sniper_api_access 테이블 append · 실패는 요청을 막지 않음.

    Phase D 승격: 표준 로그와 병존 · 감사 DB write.
    """
    from backend.services.db import AsyncSessionLocal
    from backend.services.models import SniperApiAccess

    client_host = request.client.host if request.client else None
    ua = request.headers.get("User-Agent", "-")

    try:
        async with AsyncSessionLocal() as session:
            row = SniperApiAccess(
                event=event,
                role=role,
                path=str(request.url.path)[:200],
                method=request.method[:10],
                ip=client_host[:45] if client_host else None,
                user_agent=ua[:255],
                token_source=token_source,
                detail=detail,
            )
            session.add(row)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 · 감사 실패로 요청 흐름 막지 않음
        logger.warning("sniper_api_access DB write 실패 · %s · %s", event, exc)


def _verify_token(request: Request, candidate: Optional[str], source: str) -> str:
    """공통 토큰 검증 · 실행 스위치 검사와 분리."""
    client_host = request.client.host if request.client else "-"
    user_agent = request.headers.get("User-Agent", "-")

    configured = _get_configured_token()
    if not configured:
        logger.error("sniper auth 오류 · SNIPER_API_TOKEN 미설정 · path=%s", request.url.path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버에 SNIPER_API_TOKEN 미설정. 관리자 문의.",
        )

    if not candidate or candidate != configured:
        logger.warning(
            "sniper auth 실패 · path=%s · ip=%s · UA=%s · src=%s",
            request.url.path, client_host, user_agent[:80], source,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 필요. 관리자 로그인 후 다시 시도.",
            headers={"WWW-Authenticate": "Cookie"},
        )

    logger.info(
        "sniper auth 통과 · path=%s · ip=%s · UA=%s · src=%s",
        request.url.path, client_host, user_agent[:80], source,
    )
    return candidate


async def require_sniper_token(
    request: Request,
    x_api_token: Optional[str] = Header(None, alias="X-API-Token"),
    sniper_session: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> str:
    """관리·편집 라우트 · 토큰만 검증 · 쿠키 우선 헤더 fallback.

    실주문 아닌 관리 작업(파라미터 편집·유니버스 재싱크·상태 조회)에서 사용.
    SNIPER_LIVE_ENABLED 는 무관 · 실행 스위치와 독립.

    - SNIPER_API_TOKEN 미설정 → 500
    - 쿠키/헤더 모두 미일치 → 401
    """
    candidate, source = _pick_token(sniper_session, x_api_token)
    try:
        token = _verify_token(request, candidate, source)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            await _record_access(request, event="auth_fail", role="anon", token_source=source)
        elif exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            await _record_access(
                request, event="server_misconfig", role="anon",
                token_source=source, detail="SNIPER_API_TOKEN 미설정",
            )
        raise
    await _record_access(request, event="auth_ok", role="admin", token_source=source)
    return token


async def require_sniper_live_token(
    request: Request,
    x_api_token: Optional[str] = Header(None, alias="X-API-Token"),
    sniper_session: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> str:
    """실주문 라우트 · 토큰 + LIVE_ENABLED 이중 검증 · 쿠키 우선.

    실 자금이 움직이는 라우트(실 매수/매도 트리거)에서만 사용.
    SNIPER_LIVE_ENABLED=false 이면 토큰이 맞아도 403.
    """
    candidate, source = _pick_token(sniper_session, x_api_token)
    if not is_sniper_live_enabled():
        client_host = request.client.host if request.client else "-"
        logger.warning(
            "sniper live 차단 · LIVE 비활성 · path=%s · ip=%s",
            request.url.path, client_host,
        )
        await _record_access(
            request, event="live_block", role="admin" if candidate else "anon",
            token_source=source, detail="SNIPER_LIVE_ENABLED=false",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "실주문 라우트가 비활성 상태입니다 (SNIPER_LIVE_ENABLED=false). "
                "관리·편집은 정상 사용 가능 · 실 매매 승격은 forward test 통과 후 관리자 승인 필요."
            ),
        )
    try:
        token = _verify_token(request, candidate, source)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            await _record_access(request, event="auth_fail", role="anon", token_source=source)
        raise
    await _record_access(request, event="auth_ok", role="admin", token_source=source)
    return token


async def get_current_role(
    x_api_token: Optional[str] = Header(None, alias="X-API-Token"),
    sniper_session: Optional[str] = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> Role:
    """현재 요청의 role 계산 · 예외 발생 없음.

    공개 GET 라우트에서 열람자 구분 시 사용.
    Stage 3에서 subscriber 계층 확장 예정.
    """
    configured = _get_configured_token()
    if not configured:
        return "anon"
    candidate = sniper_session or x_api_token
    if candidate and candidate == configured:
        return "admin"
    return "anon"


def set_session_cookie(response: Response, token: str) -> None:
    """로그인 성공 시 httpOnly 쿠키 세팅."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """로그아웃 시 쿠키 삭제."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )
