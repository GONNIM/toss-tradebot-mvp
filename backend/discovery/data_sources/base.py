"""데이터 소스 클라이언트 공통 base class.

httpx 비동기 + tenacity 지수 백오프 + rate limit 회피.
모든 외부 소스 (Stooq·Finnhub·SEC·FINRA·Reddit·RSS) 가 본 base 를 상속.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class DataSourceError(Exception):
    """외부 데이터 소스 호출 실패."""


class DataSourceClient:
    """모든 외부 데이터 소스 클라이언트의 base.

    사용:
        async with StooqClient() as client:
            candles = await client.get_daily_candles("AAPL", count=252)
    """

    DEFAULT_TIMEOUT: float = 15.0
    DEFAULT_MAX_RETRIES: int = 3

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ):
        self.base_url = base_url
        self.headers = headers or {}
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.max_retries = max_retries or self.DEFAULT_MAX_RETRIES
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "DataSourceClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """HTTP 요청 + 지수 백오프 재시도.

        Raises:
            DataSourceError: max_retries 초과
        """
        if self._client is None:
            raise RuntimeError(
                f"{type(self).__name__} not entered. Use `async with {type(self).__name__}() as client:`"
            )

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type(
                    (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.request(method, path, **kwargs)
                    # 5xx 만 재시도. 4xx 는 즉시 raise (rate limit 제외)
                    if 500 <= response.status_code < 600:
                        response.raise_for_status()
                    if response.status_code == 429:
                        response.raise_for_status()  # rate limit → 재시도
                    return response
        except RetryError as e:
            logger.error(f"[{type(self).__name__}] retry exhausted: {e}")
            raise DataSourceError(f"All {self.max_retries} retries failed: {e}") from e

        # Unreachable
        raise DataSourceError("Unexpected fall-through")

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._request("POST", path, **kwargs)
