"""시세 저장소 · 토스 웹소켓 클라이언트 · 계획서 2절 (웹소켓 1개) · 6-1 「웹소켓 최근 체결」.

근거 (11/18 직접 읽음): https://openapi.tossinvest.com/openapi-docs/latest/asyncapi.json
                        https://openapi.tossinvest.com/openapi-docs/overview.md
- 접속: wss://openapi-ws.tossinvest.com/ws/v1 · 헤더 `Authorization: Bearer {토큰}` (REST 와 같은 토큰)
- 구독: 텍스트 프레임 1개 = JSON 배열 = 현재 구독 전체(덮어쓰기). 예 `[{"id":"r1"},{"type":"trade:us","codes":["TESTA"]}]`
  미국은 `trade:us` · 한국은 `trade:kr`. 빈 배열 `[]` 이면 전부 해제. 선언은 1초에 5번 · 연결당 100개.
- 응답: `{"type":"subscriptions","subscribed":[...],"rejected":[{target,code,message}]}` · 체결 `{"type":"message",
  "topic":"trade:us:SYM","data":{"price":"…","volume":"…","timestamp":"…","currency":"…"}}` (종목은 topic 3번째 칸)
- 유지: 평문 `PING` 을 60초마다. 서버는 클라이언트 수신이 180초 없으면 끊는다(서버 데이터는 시간을 되돌리지 않음).
- 오류 프레임 `{"type":"error","error":{"code":…}}`: `auth-revoked`(곧 끊김 · 새 토큰) · `server-shutdown`(다시 연결) ·
  `rate-limit-exceeded`(1초 뒤 다시 선언). 그 밖의 끊김은 1·2·4…초 지수 대기 + 흔들림으로 다시 연결 · 새로 선언.
- 연결은 계정당 2개 · 새 연결을 열기 전에 옛 연결을 먼저 닫는다.
웹소켓 값이 없거나 10초보다 낡으면 6-1 이 REST(GET /prices)로 읽는다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Awaitable, Callable, Optional

from .pricing import D

logger = logging.getLogger(__name__)

WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"
PING_EVERY_SEC = 60.0
IDLE_LIMIT_SEC = 180.0
MAX_TOPICS = 100
DECLARE_COOLDOWN_SEC = 1.0      # 선언은 1초에 5번까지 · 여유 있게 1초에 1번
BACKOFF_MAX_SEC = 60.0


@dataclass
class _Tick:
    price: Decimal
    at: float


class PriceStore:
    """종목별 최근 체결가와 받은 시각."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._d: dict[str, _Tick] = {}
        self._clock = clock

    def put(self, symbol: str, price) -> None:
        self._d[symbol] = _Tick(D(price), self._clock())

    def get(self, symbol: str) -> Optional[tuple[Decimal, float]]:
        """(가격, 나이 초) · 없으면 None."""
        t = self._d.get(symbol)
        return None if t is None else (t.price, self._clock() - t.at)

    def fresh(self, symbol: str, max_age: float = 10.0) -> Optional[Decimal]:
        got = self.get(symbol)
        if got is None or got[1] > max_age:
            return None
        return got[0]


def topic_for(symbol: str) -> tuple[str, str]:
    """(채널, 종목). 6자리 숫자는 한국 · 그 밖은 미국."""
    return ("trade:kr" if symbol.isdigit() and len(symbol) == 6 else "trade:us", symbol)


def build_declaration(symbols: list[str], req_id: Optional[str] = None) -> str:
    """구독 전체를 한 배열로 (덮어쓰기). 연결당 100개를 넘으면 앞에서 100개까지만."""
    items: list[dict] = [{"id": req_id}] if req_id else []
    by: dict[str, list[str]] = {}
    for sym in sorted(set(symbols))[:MAX_TOPICS]:
        ch, code = topic_for(sym)
        by.setdefault(ch, []).append(code)
    for ch in sorted(by):
        items.append({"type": ch, "codes": by[ch]})
    return json.dumps(items, ensure_ascii=False)


def parse_frame(raw) -> dict:
    """서버 프레임 → {'kind': tick|ack|pong|error|other, ...}. 깨진 프레임은 other."""
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return {"kind": "other"}
    if not isinstance(d, dict):
        return {"kind": "other"}
    t = d.get("type")
    if t == "message":
        topic = str(d.get("topic") or "")
        parts = topic.split(":")
        data = d.get("data") or {}
        if len(parts) >= 3 and data.get("price") is not None:
            return {"kind": "tick", "symbol": parts[2], "price": data["price"]}
        return {"kind": "other"}
    if t == "subscriptions":
        return {"kind": "ack", "subscribed": d.get("subscribed") or [], "rejected": d.get("rejected") or []}
    if t == "pong":
        return {"kind": "pong"}
    if t == "error":
        return {"kind": "error", "code": (d.get("error") or {}).get("code", "")}
    return {"kind": "other"}


def backoff_delay(attempt: int, rnd: Callable[[], float] = random.random) -> float:
    """1 · 2 · 4 … 초(최대 60) + 흔들림."""
    base = min(2 ** max(attempt, 0), BACKOFF_MAX_SEC)
    return base * (1 + 0.25 * rnd())


Connect = Callable[[str, dict], Awaitable]   # (url, headers) → 연결(async 컨텍스트가 아닌 연결 객체 · send/recv/close)


async def _default_connect(url: str, headers: dict):
    import websockets

    return await websockets.connect(url, additional_headers=headers, ping_interval=None, open_timeout=10)


class PlanWsClient:
    """토스 웹소켓 1연결 · 구독 · PING 60초 · 오류 프레임 처리 · 지수 대기 재연결."""

    status = "none"   # 하트비트에 적는 값: none | connected | down

    def __init__(self, store: PriceStore, *, token_fn: Optional[Callable[[], str]] = None,
                 symbols_fn: Optional[Callable[[], Awaitable[list[str]]]] = None,
                 connect: Optional[Connect] = None, url: str = WS_URL,
                 ping_every: float = PING_EVERY_SEC, poll_every: float = 5.0, sleep=asyncio.sleep,
                 rnd: Callable[[], float] = random.random):
        self.store = store
        self._token_fn = token_fn
        self._symbols_fn = symbols_fn
        self._connect = connect or _default_connect
        self.url = url
        self.ping_every, self.poll_every = ping_every, poll_every
        self._sleep = sleep
        self._rnd = rnd
        self.rejected: list[dict] = []
        self.reconnects = 0
        self._last_declared: Optional[list[str]] = None
        self._req = 0

    async def _declare(self, conn, symbols: list[str]) -> None:
        self._req += 1
        await conn.send(build_declaration(symbols, f"r{self._req}"))
        self._last_declared = sorted(set(symbols))

    async def _session(self, stop: asyncio.Event) -> str:
        """연결 한 번의 일생. 끝난 까닭('stop' | 'closed' | 'revoked' | 'shutdown')을 돌려준다."""
        token = await asyncio.to_thread(self._token_fn) if self._token_fn else ""
        conn = await self._connect(self.url, {"Authorization": f"Bearer {token}"})
        self.status = "connected"
        self._last_declared = None
        reason = "closed"
        try:
            symbols = await self._symbols_fn() if self._symbols_fn else []
            await self._declare(conn, symbols)
            last_ping = time.monotonic()
            last_poll = last_ping
            while not stop.is_set():
                now = time.monotonic()
                if now - last_ping >= self.ping_every:
                    await conn.send("PING")        # 서버 수신이 180초 없으면 끊기므로 데이터가 흘러도 보낸다
                    last_ping = now
                if now - last_poll >= self.poll_every:
                    last_poll = now
                    want = sorted(set(await self._symbols_fn())) if self._symbols_fn else []
                    if want != self._last_declared:
                        await self._declare(conn, want)
                try:
                    raw = await asyncio.wait_for(conn.recv(), timeout=min(1.0, self.ping_every, self.poll_every))
                except asyncio.TimeoutError:
                    continue
                f = parse_frame(raw)
                if f["kind"] == "tick":
                    self.store.put(f["symbol"], f["price"])
                elif f["kind"] == "ack":
                    self.rejected = f["rejected"]
                    if self.rejected:
                        logger.warning("[plan-ws] 구독 거절 %s건", len(self.rejected))
                elif f["kind"] == "error":
                    code = f["code"]
                    if code == "auth-revoked":
                        reason = "revoked"
                        break
                    if code == "server-shutdown":
                        reason = "shutdown"
                        break
                    if code == "rate-limit-exceeded":
                        await self._sleep(DECLARE_COOLDOWN_SEC)
                        self._last_declared = None   # 다음 확인에서 다시 선언
                    else:
                        logger.warning("[plan-ws] 오류 프레임 %s", code)
            else:
                reason = "stop"
        finally:
            self.status = "down"
            try:
                await conn.close()                  # 새 연결 전에 옛 연결을 먼저 닫는다
            except Exception:  # noqa: BLE001
                pass
        return reason

    async def run(self, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            started = time.monotonic()
            try:
                reason = await self._session(stop)
                if reason == "stop":
                    return
            except Exception as exc:  # noqa: BLE001 — 연결 · 인증 실패 · 끊김 모두 같은 길로 다시 시도
                logger.warning("[plan-ws] 연결 끊김 · %s", exc.__class__.__name__)
                self.status = "down"
            attempt = 0 if time.monotonic() - started > 30 else attempt + 1
            self.reconnects += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff_delay(attempt, self._rnd))
            except asyncio.TimeoutError:
                pass
