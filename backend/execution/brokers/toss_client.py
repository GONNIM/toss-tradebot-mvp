"""Toss Open API HTTP 클라이언트 — v2 트랙 C.

PaperAdapter (Phase 1 · 자본 sync + 시세) · TossAdapter (Phase 2 · 주문) 공용.

책임:
- Access Token 발급 · 캐시 · 5분 pre-emptive refresh
- 필수 헤더 자동 부착 (Authorization · X-Tossinvest-Account)
- 성공 응답 `{ result: ... }` 래퍼 자동 언랩 (2026-07-10 실측 계약)
- 에러 envelope 파싱 → 예외 계층 매핑 (Phase 2 확장)

참조: docs/plans/tradebot-mvp-v2/03-toss-openapi-integration.md
      메모리 reference_toss_open_api
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from backend.services import config

from ..exceptions import (
    BrokerCommunicationError,
    DuplicateOrderError,
    ExecutionError,
    InsufficientBalance,
    MarketClosed,
    OrderNotFound,
    OrderRejected,
    RateLimitExceeded,
)


@dataclass
class TossEnvelope:
    """Toss API 응답 · result + 메타(request_id · rate limit 헤더)."""
    result: Any
    request_id: Optional[str] = None
    rate_limit: dict[str, str] = field(default_factory=dict)
    status_code: int = 200


def _extract_rate_headers(resp: httpx.Response) -> dict[str, str]:
    return {
        k: v
        for k, v in resp.headers.items()
        if k.lower() in {"x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after"}
    }

logger = logging.getLogger(__name__)

_BASE_URL = "https://openapi.tossinvest.com"
_TIMEOUT_SEC = 10.0
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_TOKEN_CACHE = _PROJECT_ROOT / "backend" / "data" / "toss_token.json"

# HTTP → 예외 매핑 (03-toss-openapi-integration.md §7-2)
_INSUFFICIENT = {"insufficient-buying-power", "insufficient-sellable-quantity"}
_MARKET_CLOSED = {"order-hours-closed", "amount-order-outside-regular-hours"}
_ALREADY = {"already-filled", "already-canceled", "already-modified", "already-rejected"}
_NOT_FOUND = {"order-not-found", "stock-not-found"}


class TossClient:
    """Toss Open API 클라이언트 · 프로세스 lifetime 재사용 가능."""

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        account_seq: Optional[str] = None,
        token_cache_path: Optional[Path] = None,
    ):
        self._client_id = client_id or config.get("TOSS_CLIENT_ID")
        self._client_secret = client_secret or config.get("TOSS_CLIENT_SECRET")
        self._account_seq = account_seq or config.get("TOSS_ACCOUNT_SEQ")
        raw = token_cache_path or config.get("TOSS_TOKEN_CACHE_PATH")
        if raw is None:
            self._token_cache_path = _DEFAULT_TOKEN_CACHE
        else:
            p = Path(raw) if isinstance(raw, str) else raw
            self._token_cache_path = p if p.is_absolute() else _PROJECT_ROOT / p

    # ─── 인증 ───────────────────────────────
    def _refresh_token(self) -> str:
        if not self._client_id or not self._client_secret:
            raise ExecutionError("TOSS_CLIENT_ID/SECRET 미설정 (SOPS 복호화 확인)")
        logger.info("POST /oauth2/token")
        # AUTH 그룹 rate limit 준수
        from .rate_limiter import get_rate_limiter
        get_rate_limiter().acquire("/oauth2/token")
        with httpx.Client(timeout=_TIMEOUT_SEC) as client:
            resp = client.post(
                f"{_BASE_URL}/oauth2/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        if resp.status_code != 200:
            raise BrokerCommunicationError(
                f"토큰 발급 실패: {self._error_summary(resp)}",
                raw_response=self._safe_json(resp),
            )
        payload = resp.json()
        token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        now = time.time()
        self._token_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_cache_path.write_text(
            json.dumps(
                {
                    "access_token": token,
                    "token_type": payload.get("token_type", "Bearer"),
                    "expires_in": expires_in,
                    "expires_at": now + expires_in,
                    "issued_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return token

    def access_token(self) -> str:
        """캐시 재사용 · 만료 5분 전 pre-emptive refresh."""
        now = time.time()
        if self._token_cache_path.exists():
            try:
                cached = json.loads(self._token_cache_path.read_text(encoding="utf-8"))
                if cached.get("expires_at", 0) - now > 300:
                    return cached["access_token"]
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("토큰 캐시 무효 (%s) — 재발급", exc)
        return self._refresh_token()

    # ─── HTTP 헬퍼 ──────────────────────────
    def _headers(self, *, use_account_header: bool) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        if use_account_header:
            if not self._account_seq:
                raise ExecutionError("TOSS_ACCOUNT_SEQ 미설정 (사용자 액션 필요)")
            headers["X-Tossinvest-Account"] = str(self._account_seq)
        return headers

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Optional[dict]:
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _error_summary(resp: httpx.Response) -> str:
        request_id = resp.headers.get("X-Request-Id") or resp.headers.get("x-amz-cf-id") or "-"
        body = TossClient._safe_json(resp) or {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = err.get("code", "-")
        message = err.get("message", "-")
        return f"[{resp.status_code}] requestId={request_id} code={code} message={message}"

    def _raise_from_response(self, resp: httpx.Response) -> None:
        """HTTP 에러 → OMI 예외 매핑."""
        body = self._safe_json(resp) or {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = err.get("code", "")
        message = err.get("message", "")

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            raise RateLimitExceeded(retry_after=retry_after, message=message or code)
        if resp.status_code in {401} and code in {"invalid-token", "expired-token"}:
            # 자동 재발급 후 재시도는 상위 로직에서 (일단 예외)
            self._token_cache_path.unlink(missing_ok=True)
            raise BrokerCommunicationError(
                f"토큰 만료 — 재시도 필요: {self._error_summary(resp)}",
                raw_response=body,
            )
        if resp.status_code == 422 and code in _INSUFFICIENT:
            raise InsufficientBalance(code, message, raw_response=body)
        if resp.status_code == 422 and code in _MARKET_CLOSED:
            raise MarketClosed(code, message, raw_response=body)
        if resp.status_code == 422 and code == "idempotency-key-conflict":
            raise DuplicateOrderError(f"[{code}] {message}", raw_response=body)
        if resp.status_code == 404 and code in _NOT_FOUND:
            raise OrderNotFound(f"[{code}] {message}", raw_response=body)
        if 400 <= resp.status_code < 500:
            raise OrderRejected(code or f"http-{resp.status_code}", message or resp.text[:200], raw_response=body)
        if resp.status_code >= 500:
            raise BrokerCommunicationError(
                f"5xx 서버 오류: {self._error_summary(resp)}", raw_response=body
            )

    # ─── Public API ─────────────────────────
    def get(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        use_account_header: bool = True,
    ) -> Any:
        """인증된 GET · 성공 응답 result 언랩 후 반환."""
        from .rate_limiter import get_rate_limiter
        get_rate_limiter().acquire(path)
        with httpx.Client(timeout=_TIMEOUT_SEC) as client:
            resp = client.get(
                f"{_BASE_URL}{path}",
                headers=self._headers(use_account_header=use_account_header),
                params=params,
            )
        if resp.status_code != 200:
            self._raise_from_response(resp)
        body = self._safe_json(resp)
        if not isinstance(body, dict):
            return body
        # 응답 래퍼 자동 언랩 (2026-07-10 실측 · 03-toss §4-3)
        if "result" in body:
            return body["result"]
        return body

    def post(
        self,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
        use_account_header: bool = True,
    ) -> Any:
        """인증된 POST · 성공 응답 result 언랩 후 반환. (Phase 2 주문 API 대비)"""
        from .rate_limiter import get_rate_limiter
        get_rate_limiter().acquire(path)
        with httpx.Client(timeout=_TIMEOUT_SEC) as client:
            resp = client.post(
                f"{_BASE_URL}{path}",
                headers={
                    **self._headers(use_account_header=use_account_header),
                    "Content-Type": "application/json",
                },
                json=json_body,
            )
        if resp.status_code not in {200, 201}:
            self._raise_from_response(resp)
        body = self._safe_json(resp)
        if not isinstance(body, dict):
            return body
        if "result" in body:
            return body["result"]
        return body

    # ─── 편의 메서드 (자주 쓰는 조회) ────────
    def buying_power(self, currency: str = "KRW") -> dict:
        return self.get("/api/v1/buying-power", params={"currency": currency})

    def holdings(self, symbol: Optional[str] = None) -> Any:
        params = {"symbol": symbol} if symbol else None
        return self.get("/api/v1/holdings", params=params)

    def prices(self, symbols: list[str]) -> Any:
        """MARKET_DATA 그룹 · account 헤더 불필요."""
        return self.get(
            "/api/v1/prices",
            params={"symbols": ",".join(symbols)},
            use_account_header=False,
        )

    def accounts(self) -> list[dict]:
        return self.get("/api/v1/accounts", use_account_header=False) or []

    # ─── Envelope 반환 (주문 API · X-Request-Id 필수) ────
    def request_envelope(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        use_account_header: bool = True,
    ) -> TossEnvelope:
        """주문 API 등 감사 로깅이 필요한 호출용. X-Request-Id + Rate Limit 헤더 반환."""
        from .rate_limiter import get_rate_limiter
        get_rate_limiter().acquire(path)

        headers = self._headers(use_account_header=use_account_header)
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        with httpx.Client(timeout=_TIMEOUT_SEC) as client:
            if method.upper() == "GET":
                resp = client.get(f"{_BASE_URL}{path}", headers=headers, params=params)
            elif method.upper() == "POST":
                resp = client.post(f"{_BASE_URL}{path}", headers=headers, json=json_body, params=params)
            elif method.upper() == "DELETE":
                resp = client.delete(f"{_BASE_URL}{path}", headers=headers, params=params)
            else:
                raise ExecutionError(f"미지원 method: {method}")

        request_id = resp.headers.get("X-Request-Id") or resp.headers.get("x-amz-cf-id")
        rate_limit = _extract_rate_headers(resp)

        if resp.status_code not in {200, 201}:
            # 예외 발생 시에도 request_id 는 로그에 남기도록 재구성
            body = self._safe_json(resp) or {}
            err = body.get("error", {}) if isinstance(body, dict) else {}
            logger.warning(
                "Toss API 실패 · %s %s · code=%s requestId=%s",
                method, path, err.get("code", "-"), request_id or "-",
            )
            self._raise_from_response(resp)

        body = self._safe_json(resp)
        if isinstance(body, dict) and "result" in body:
            result = body["result"]
        else:
            result = body
        return TossEnvelope(result=result, request_id=request_id, rate_limit=rate_limit, status_code=resp.status_code)

    # ─── 주문 API (Phase 2 실전 어댑터 · TossAdapter 전용) ───
    def create_order(self, body: dict) -> TossEnvelope:
        """POST /api/v1/orders."""
        return self.request_envelope("POST", "/api/v1/orders", json_body=body)

    def cancel_order(self, order_id: str) -> TossEnvelope:
        """POST /api/v1/orders/{orderId}/cancel."""
        return self.request_envelope("POST", f"/api/v1/orders/{order_id}/cancel")

    def modify_order(self, order_id: str, body: dict) -> TossEnvelope:
        """POST /api/v1/orders/{orderId}/modify."""
        return self.request_envelope("POST", f"/api/v1/orders/{order_id}/modify", json_body=body)

    def get_order(self, order_id: str) -> TossEnvelope:
        """GET /api/v1/orders/{orderId}."""
        return self.request_envelope("GET", f"/api/v1/orders/{order_id}")

    def list_orders(self, status: str = "OPEN") -> TossEnvelope:
        """GET /api/v1/orders?status=OPEN|CLOSED.

        ⚠️ status 는 **그룹 라벨** (개별 orders[].status 와 값 체계 다름).
        - OPEN: {PENDING, PARTIAL_FILLED, PENDING_CANCEL, PENDING_REPLACE}
        - CLOSED: {FILLED, CANCELED, REJECTED, REPLACED, ...}
        """
        return self.request_envelope("GET", "/api/v1/orders", params={"status": status})

    def market_calendar(self, market: str) -> TossEnvelope:
        """GET /api/v1/market-calendar/{KR|US}."""
        return self.request_envelope(
            "GET", f"/api/v1/market-calendar/{market.upper()}", use_account_header=False
        )

    # ─── 조건주문 API (Phase 3 Super Signal OCO) ───
    def create_conditional_order(self, body: dict) -> TossEnvelope:
        """POST /api/v1/conditional-orders (SINGLE/OCO/OTO)."""
        return self.request_envelope(
            "POST", "/api/v1/conditional-orders", json_body=body
        )

    def cancel_conditional_order(self, conditional_order_id: str) -> TossEnvelope:
        """DELETE /api/v1/conditional-orders/{id}."""
        return self.request_envelope(
            "DELETE", f"/api/v1/conditional-orders/{conditional_order_id}"
        )

    def list_conditional_orders(self, status: str = "OPEN") -> TossEnvelope:
        """GET /api/v1/conditional-orders?status=OPEN|CLOSED."""
        return self.request_envelope(
            "GET", "/api/v1/conditional-orders", params={"status": status}
        )


_shared: Optional[TossClient] = None


def get_toss_client() -> TossClient:
    global _shared
    if _shared is None:
        _shared = TossClient()
    return _shared
