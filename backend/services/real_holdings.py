"""1025-08 · 토스 실계좌 보유 — 정리 · 하루 기록 · 매도 판단 재료 (보유 일수 · 최고가 대비).

사실만 낸다 (권유·예상 없음). 토스 호출은 서버에서만 (토큰 1개 규칙 · 1025-06).
보유 줄 (종목·수량·금액) 은 INFO 로그에 남기지 않는다 — 건수만.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.services.db import get_session
from backend.services.models import HoldingSnapshot, UserJudgment

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_LOCAL_TZ = {"KR": KST, "US": ZoneInfo("America/New_York")}
FIRST_CANDLES = 200  # 토스 일봉 최대 · 처음 한 번 과거를 채움 (국내 약 10달)
DAILY_CANDLES = 5    # 그 뒤로는 최근 며칠만 (빠진 날 메움)


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


@dataclass
class HoldingRow:
    symbol: str
    name: Optional[str]
    market: str  # KR | US
    currency: str
    qty: float
    avg_price: float
    last_price: Optional[float]
    market_value: Optional[float]  # 거래 통화 기준
    purchase_amount: float
    pnl: Optional[float]
    pnl_pct: Optional[float]
    pnl_source: str  # api | computed


def parse_items(holdings_dict) -> list[HoldingRow]:
    """토스 holdings 응답 → 보유 줄 · 토스 원본 값 우선 · 없으면 계산 (dashboard 와 같은 규칙)."""
    out: list[HoldingRow] = []
    items = (holdings_dict or {}).get("items") or [] if isinstance(holdings_dict, dict) else []
    for it in items:
        if not isinstance(it, dict):
            continue
        sym = str(it.get("symbol") or "").strip().upper()
        qty = _f(it.get("quantity")) or 0
        if not sym or qty <= 0:
            continue
        currency = (it.get("currency") or "").upper() or ("KRW" if sym[:1].isdigit() else "USD")
        market = (it.get("marketCountry") or "").upper()
        if market not in ("KR", "US"):
            market = "KR" if currency == "KRW" else "US"
        avg = _f(it.get("averagePurchasePrice")) or 0
        last = _f(it.get("lastPrice"))
        mv_obj = it.get("marketValue") or {}
        pl_obj = it.get("profitLoss") or {}
        mv = _f(mv_obj.get("amount"))
        if mv is None and last is not None:
            mv = round(qty * last, 4)
        cost = _f(mv_obj.get("purchaseAmount")) or round(qty * avg, 4)
        pnl = _f(pl_obj.get("amount"))
        pnl_source = "api"
        if pnl is None:
            pnl_source = "computed"
            pnl = round(mv - cost, 4) if mv is not None else None
        # % 는 자체 계산 (dashboard.py 2026-08-13 사고 · 화면끼리 같은 값)
        pnl_pct = round(pnl / cost * 100, 2) if (pnl is not None and cost > 0) else None
        out.append(HoldingRow(sym, it.get("name"), market, currency, qty, avg, last, mv, cost, pnl, pnl_pct, pnl_source))
    return out


def _candle_bars(resp) -> list[tuple[date, float]]:
    bars = []
    for c in (resp or {}).get("candles") or [] if isinstance(resp, dict) else []:
        try:
            d = date.fromisoformat(str(c.get("timestamp"))[:10])  # 1d 봉 = 현지 거래일 자정
        except ValueError:
            continue
        close = _f(c.get("closePrice"))
        if close:
            bars.append((d, close))
    return bars


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # DB 는 UTC naive


async def _upsert(session, *, symbol, market, trade_date, kind, **cols) -> None:
    row = (await session.execute(select(HoldingSnapshot).where(
        HoldingSnapshot.symbol == symbol, HoldingSnapshot.market == market,
        HoldingSnapshot.trade_date == trade_date, HoldingSnapshot.kind == kind,
    ))).scalar_one_or_none()
    if row is None:
        session.add(HoldingSnapshot(symbol=symbol, market=market, trade_date=trade_date, kind=kind,
                                    saved_at=_utcnow(), **cols))
        return
    for k, v in cols.items():
        setattr(row, k, v)
    row.saved_at = _utcnow()


async def snapshot_market(market: str, client=None, now: Optional[datetime] = None) -> dict:
    """한 시장의 보유를 그 시장 거래일로 저장 · 팔린 종목은 수량 0 · 일봉 종가를 채움."""
    from backend.services import fx

    if market not in ("KR", "US"):
        raise ValueError("market 은 KR 또는 US")
    if client is None:
        from backend.execution.brokers.toss_client import get_toss_client

        client = get_toss_client()
    now = now or datetime.now(timezone.utc)
    local_today = now.astimezone(_LOCAL_TZ[market]).date()
    raw = await asyncio.to_thread(client.holdings)
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        # 응답 이상을 「다 팔림」으로 적지 않는다
        raise RuntimeError("토스 보유 응답에 items 가 없음")
    rows = [r for r in parse_items(raw) if r.market == market]
    quote = await asyncio.to_thread(fx.usd_krw, client) if market == "US" else None

    n_candles = 0
    held_dates: list[date] = []
    async with get_session() as session:
        for r in rows:
            has_candles = (await session.execute(select(func.count()).select_from(HoldingSnapshot).where(
                HoldingSnapshot.symbol == r.symbol, HoldingSnapshot.market == market, HoldingSnapshot.kind == "candle",
            ))).scalar_one() > 0
            bars: list[tuple[date, float]] = []
            try:
                bars = _candle_bars(await asyncio.to_thread(
                    client.candles, r.symbol, DAILY_CANDLES if has_candles else FIRST_CANDLES))
            except Exception as exc:  # noqa: BLE001 — 일봉이 없어도 보유 기록은 남긴다
                logger.warning("[holdings] 일봉 조회 실패 (%s) · %s", market, type(exc).__name__)
            for d, close in bars:
                await _upsert(session, symbol=r.symbol, market=market, trade_date=d, kind="candle",
                              close=close, currency=r.currency)
            n_candles += len(bars)
            trade_date = max((d for d, _ in bars), default=local_today)
            held_dates.append(trade_date)
            await _upsert(
                session, symbol=r.symbol, market=market, trade_date=trade_date, kind="holding",
                name=r.name, currency=r.currency, qty=r.qty, avg_price=r.avg_price, close=r.last_price,
                market_value=r.market_value, purchase_amount=r.purchase_amount,
                fx_rate=quote.rate if quote else None, fx_source=quote.source if quote else None,
            )

        # 지난 기록에서 들고 있던 종목이 지금 없으면 → 팔림 (수량 0)
        held = {r.symbol for r in rows}
        sold_date = max(held_dates, default=local_today)
        sold = 0
        last_dates = (await session.execute(
            select(HoldingSnapshot.symbol, func.max(HoldingSnapshot.trade_date))
            .where(HoldingSnapshot.market == market, HoldingSnapshot.kind == "holding")
            .group_by(HoldingSnapshot.symbol)
        )).all()
        for sym, last_d in last_dates:
            if sym in held:
                continue
            last = (await session.execute(select(HoldingSnapshot).where(
                HoldingSnapshot.symbol == sym, HoldingSnapshot.market == market,
                HoldingSnapshot.kind == "holding", HoldingSnapshot.trade_date == last_d,
            ))).scalar_one()
            if (last.qty or 0) > 0:
                await _upsert(session, symbol=sym, market=market, trade_date=max(sold_date, last_d + timedelta(days=1)),
                              kind="holding", qty=0.0, currency=last.currency, name=last.name)
                sold += 1
    out = {"market": market, "held": len(rows), "sold": sold, "candles": n_candles}
    logger.info("[holdings] 기록 %s · 보유 %d · 팔림 %d · 일봉 %d", market, len(rows), sold, n_candles)
    return out


def _kst_date(ts: datetime) -> date:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)  # DB 시각은 UTC
    return ts.astimezone(KST).date()


async def holding_facts(session, row: HoldingRow, today: date) -> dict:
    """보유 일수 · 기준일 · 기준일 뒤 최고 종가 · 그 대비 % (사실만)."""
    snaps = (await session.execute(select(HoldingSnapshot).where(
        HoldingSnapshot.symbol == row.symbol, HoldingSnapshot.market == row.market,
    ).order_by(HoldingSnapshot.trade_date))).scalars().all()
    holds = [s for s in snaps if s.kind == "holding"]
    candles = [s for s in snaps if s.kind == "candle"]
    sold_dates = [s.trade_date for s in holds if (s.qty or 0) <= 0]
    last_sold = max(sold_dates) if sold_dates else None
    streak = [s.trade_date for s in holds if (s.qty or 0) > 0 and (last_sold is None or s.trade_date > last_sold)]

    jq = select(func.min(UserJudgment.ts)).where(UserJudgment.ticker == row.symbol)
    if last_sold is not None:
        jq = jq.where(UserJudgment.ts > datetime.combine(last_sold, datetime.max.time()))
    first_j = (await session.execute(jq)).scalar_one_or_none()

    if first_j is not None:
        basis, basis_source = _kst_date(first_j), "journal"
    elif streak:
        basis, basis_source = streak[0], "record"
    else:
        basis, basis_source = None, None

    closes = [(s.trade_date, s.close) for s in snaps if s.close and (basis is None or s.trade_date >= basis)]
    if row.last_price:
        closes.append((today, row.last_price))
    peak_date, peak = max(closes, key=lambda x: (x[1], x[0])) if closes else (None, None)
    from_peak = round((row.last_price / peak - 1) * 100, 2) if (peak and row.last_price) else None
    peak_complete = bool(basis and candles and candles[0].trade_date <= basis)
    return {
        "basis_date": basis,
        "basis_source": basis_source,
        "days_held": (today - basis).days if basis else None,
        "peak_close": peak,
        "peak_date": peak_date,
        "from_peak_pct": from_peak,
        "peak_complete": peak_complete,
        "record_started": holds[0].trade_date if holds else None,
    }
