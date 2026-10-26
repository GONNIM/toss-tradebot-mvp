"""1025-05 · 판정·후보 결과 자동 계산 (docs/plans/judgment-outcomes/README.md · 사용자 승인 10/26).

가격은 토스 일봉 (GET /api/v1/candles 1d) 하나로 양끝을 맞춘다 · 토스에 없으면 계산 불가 (다른 소스로 채우지 않음).
기준 시각 = 만들어진 시각 (UTC naive) → 현지 · 현지 정규장 마감 (KR 15:30 · US 16:00) 뒤면 그날 봉, 앞이면 그 전 봉.
- 저널: 기준가 = 적은 진입가 → 없으면 기준 봉 종가 (result_base_price) · horizon_days 달력일 · 손절 도달.
  대체된 판정 · 청산 행 (page_source=close) 은 계산하지 않는다.
- Crazy: perf_1w · perf_1m (기준 봉 + 7·30 달력일과 같거나 뒤인 첫 봉).
- Moonshot: perf_1d·3d·5d (기준 봉 뒤 1·3·5번째 봉) · max_price_after (그 5봉 고가 최대).
이미 값이 있는 칸은 건드리지 않는다 (수동 PATCH 보존). 토스 호출은 서버 cron 에서만 · 종목당 1회.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.services.broker_links import is_kr_code
from backend.services.db import ensure_columns, get_session
from backend.services.models import CrazyPick, MoonshotPick, UserJudgment

logger = logging.getLogger(__name__)

_TZ = {"KR": ZoneInfo("Asia/Seoul"), "US": ZoneInfo("America/New_York")}
_CLOSE = {"KR": time(15, 30), "US": time(16, 0)}


@dataclass(frozen=True)
class Bar:
    d: date
    close: float
    low: float
    high: float


def _f(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def market_of(symbol: str) -> str:
    return "KR" if is_kr_code(symbol.upper()) else "US"


def base_date(created_utc: datetime, market: str) -> date:
    """만들어진 시각에 이미 마감된 마지막 현지 거래일 후보 (주말·휴장은 bar_on_or_before 가 처리)."""
    if created_utc.tzinfo is None:
        created_utc = created_utc.replace(tzinfo=timezone.utc)
    local = created_utc.astimezone(_TZ[market])
    return local.date() if local.time() >= _CLOSE[market] else local.date() - timedelta(days=1)


def parse_bars(resp) -> list[Bar]:
    out = []
    for c in (resp or {}).get("candles") or [] if isinstance(resp, dict) else []:
        try:
            d = date.fromisoformat(str(c.get("timestamp"))[:10])  # 1d 봉 = 현지 거래일 자정
        except ValueError:
            continue
        close = _f(c.get("closePrice"))
        if not close:
            continue
        out.append(Bar(d, close, _f(c.get("lowPrice")) or close, _f(c.get("highPrice")) or close))
    return sorted(out, key=lambda b: b.d)


def bar_on_or_before(bars: list[Bar], d: date) -> Optional[Bar]:
    prior = [b for b in bars if b.d <= d]
    return prior[-1] if prior else None


def _first_on_or_after(bars: list[Bar], d: date) -> Optional[Bar]:
    return next((b for b in bars if b.d >= d), None)


def calendar_return(bars: list[Bar], base: Bar, days: int, base_price: float) -> Optional[float]:
    end = _first_on_or_after(bars, base.d + timedelta(days=days))
    return end.close / base_price - 1 if end and base_price else None


def _after(bars: list[Bar], base: Bar) -> list[Bar]:
    return [b for b in bars if b.d > base.d]


def nth_bar_return(bars: list[Bar], base: Bar, n: int) -> Optional[float]:
    after = _after(bars, base)
    return after[n - 1].close / base.close - 1 if len(after) >= n else None


def max_high_after(bars: list[Bar], base: Bar, n: int) -> Optional[float]:
    after = _after(bars, base)
    return max(b.high for b in after[:n]) if len(after) >= n else None


def invalidation_hit(bars: list[Bar], base_bar: Bar, end: date, *, base_price: float, invalidation: float,
                     target: Optional[float]) -> Optional[tuple[date, float]]:
    """기준 봉 다음 날 ~ end 사이 손절가에 닿은 첫 날과 그 저가(고가). 공매도형 = 목표 < 기준 < 손절."""
    short = invalidation > base_price and (target is None or target < base_price)
    for b in bars:
        if not (base_bar.d < b.d <= end):
            continue
        if short and b.high >= invalidation:
            return b.d, b.high
        if not short and b.low <= invalidation:
            return b.d, b.low
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _judgment_due(j: UserJudgment) -> bool:
    return j.superseded_by_id is None and j.page_source != "close" and j.result_at_horizon is None


async def _fetch(client, symbols: set[str]) -> tuple[dict[str, list[Bar]], set[str]]:
    got: dict[str, list[Bar]] = {}
    missing: set[str] = set()
    for sym in sorted(symbols):
        try:
            bars = parse_bars(await asyncio.to_thread(client.candles, sym, 200))
        except Exception as exc:  # noqa: BLE001 — 토스에 없는 종목 등 · 계산 불가
            logger.warning("[outcomes] 일봉 없음 %s · %s", sym, type(exc).__name__)
            bars = []
        if bars:
            got[sym] = bars
        else:
            missing.add(sym)
    return got, missing


def _score_judgment(j: UserJudgment, bars: list[Bar], now: datetime) -> str:
    """computed | pending | unavailable — 기준가는 만기와 무관하게 먼저 고정."""
    if j.result_base_price is None:
        if j.entry_price:
            j.result_base_price, j.result_base_source = j.entry_price, "entry"
        else:
            b0 = bar_on_or_before(bars, base_date(j.ts, market_of(j.ticker)))
            if b0 is None:
                return "unavailable"
            j.result_base_price, j.result_base_source = b0.close, "t0_close"
    base_bar = bar_on_or_before(bars, base_date(j.ts, market_of(j.ticker)))
    if base_bar is None:
        return "unavailable"
    end = _first_on_or_after(bars, base_bar.d + timedelta(days=j.horizon_days))
    if end is None:
        return "pending"
    j.result_at_horizon = end.close / j.result_base_price - 1
    j.result_computed_at = now
    if j.invalidation_price and j.invalidation_hit_ts is None:
        hit = invalidation_hit(bars, base_bar, end.d, base_price=j.result_base_price,
                               invalidation=j.invalidation_price, target=j.target_price)
        if hit:
            j.invalidation_hit_ts = datetime.combine(hit[0], time())
            j.invalidation_hit_low = hit[1]
    return "computed"


async def run_outcomes(client=None, now: Optional[datetime] = None) -> dict:
    """만기가 된 판정·후보의 결과를 채운다 · 실행 요약 (건수만) 을 돌려준다."""
    if client is None:
        from backend.execution.brokers.toss_client import get_toss_client

        client = get_toss_client()
    now = now or _utcnow()
    await ensure_columns()
    summary = {k: {"computed": 0, "pending": 0, "unavailable": 0} for k in ("judgments", "crazy", "moonshot")}
    async with get_session() as session:
        judgments = [j for j in (await session.execute(select(UserJudgment))).scalars().all() if _judgment_due(j)]
        crazy = (await session.execute(select(CrazyPick).where(
            (CrazyPick.perf_1w.is_(None)) | (CrazyPick.perf_1m.is_(None))))).scalars().all()
        moon = (await session.execute(select(MoonshotPick).where(
            (MoonshotPick.perf_1d.is_(None)) | (MoonshotPick.perf_3d.is_(None)) | (MoonshotPick.perf_5d.is_(None))
            | (MoonshotPick.max_price_after.is_(None))))).scalars().all()
        symbols = {j.ticker.upper() for j in judgments} | {p.ticker.upper() for p in crazy} | {p.ticker.upper() for p in moon}
        bars_by, missing = await _fetch(client, symbols)

        for j in judgments:
            bars = bars_by.get(j.ticker.upper())
            summary["judgments"]["unavailable" if bars is None else _score_judgment(j, bars, now)] += 1

        for p in crazy:
            bars = bars_by.get(p.ticker.upper())
            b0 = bar_on_or_before(bars, base_date(p.created_at, market_of(p.ticker))) if bars else None
            if b0 is None:
                summary["crazy"]["unavailable"] += 1
                continue
            if p.perf_1w is None:
                p.perf_1w = calendar_return(bars, b0, 7, b0.close)
            if p.perf_1m is None:
                p.perf_1m = calendar_return(bars, b0, 30, b0.close)
            summary["crazy"]["computed" if p.perf_1w is not None else "pending"] += 1

        for p in moon:
            bars = bars_by.get(p.ticker.upper())
            b0 = bar_on_or_before(bars, base_date(p.created_at, market_of(p.ticker))) if bars else None
            if b0 is None:
                summary["moonshot"]["unavailable"] += 1
                continue
            for attr, n in (("perf_1d", 1), ("perf_3d", 3), ("perf_5d", 5)):
                if getattr(p, attr) is None:
                    setattr(p, attr, nth_bar_return(bars, b0, n))
            if p.max_price_after is None:
                p.max_price_after = max_high_after(bars, b0, 5)
            summary["moonshot"]["computed" if p.perf_1d is not None else "pending"] += 1

    summary["symbols"] = len(symbols)
    summary["missing_symbols"] = len(missing)
    logger.info("[outcomes] %s", summary)
    return summary
