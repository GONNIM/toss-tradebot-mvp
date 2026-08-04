"""Serenity 언급 티커 종가 스냅샷 · vs prior close 배치 · Phase L9 · 2026-08-03.

목적: Ticker Card 상단 "vs prior close · +X.X%" 표시.

파이프라인:
    active_tickers(days=180) → yfinance 5d ohlc → 최근 2 종가 → upsert SerenityTickerPrice

특징:
    - to_yfinance_symbol 로 심볼 매핑 (SIVE→SIVE.ST · .KQ→.KS)
    - concurrency 제한 (yfinance rate limit · 배치 4)
    - 실패 티커는 error 필드에 기록 · 재실행 시 재시도

Cron: 매일 09:30 KST (Powderkeg 22:30 이후 오전 · Serenity scorer 08:00 이후)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.discovery.serenity.aggregators import active_tickers, first_mention_map
from backend.services.db import get_session
from backend.services.models import DiscoverySerenityScore, SerenityTickerPrice
from backend.services.ticker_map import is_private_or_brand, to_yfinance_symbol

logger = logging.getLogger(__name__)

CONCURRENCY = 4
_HISTORY_DAYS = 7
_MAX_LOOKBACK_DAYS = 400  # first_mention_at 최대 커버 범위 (yfinance range 상한 방어)


def _fetch_price_bundle(
    yahoo_symbol: str,
    *,
    first_mention_date: Optional[str] = None,
    ticker_client=None,
) -> dict:
    """close · prior_close · first_mention_price 한 번의 yfinance 호출로 취득.

    반환:
      {close, prior, snapshot_date, first_mention_price, first_mention_used_date, error}
      실패 시 close/prior=None · error 채움.
    """
    result: dict = {
        "close": None,
        "prior": None,
        "snapshot_date": None,
        "first_mention_price": None,
        "first_mention_used_date": None,
        "sector": None,
        "industry": None,
        # Phase L14 · 시총 + 유동성 (RISK-PRINCIPLES §3)
        "market_cap": None,
        "market_cap_source": None,
        "avg_dollar_volume_20d": None,
        "error": None,
    }

    # start 결정 · first_mention_date 있으면 그 이전 1 거래일 · 최대 400 일
    today = datetime.utcnow().date()
    if first_mention_date:
        try:
            fm_dt = datetime.strptime(first_mention_date, "%Y-%m-%d").date()
            start_dt = fm_dt - timedelta(days=3)
        except ValueError:
            fm_dt = None
            start_dt = today - timedelta(days=_HISTORY_DAYS)
    else:
        fm_dt = None
        start_dt = today - timedelta(days=_HISTORY_DAYS)

    # 상한 방어 · 400 일 초과 시 잘라냄
    earliest = today - timedelta(days=_MAX_LOOKBACK_DAYS)
    if start_dt < earliest:
        start_dt = earliest

    try:
        if ticker_client is None:
            import yfinance as yf
            stock = yf.Ticker(yahoo_symbol)
        else:
            stock = ticker_client(yahoo_symbol)
        hist = stock.history(
            start=start_dt.isoformat(),
            end=(today + timedelta(days=1)).isoformat(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[serenity_price] yfinance 실패 · %s · %s", yahoo_symbol, exc)
        result["error"] = str(exc)[:180]
        return result

    if hist is None or getattr(hist, "empty", True) or len(hist) < 2:
        result["error"] = "history 부족"
        return result

    try:
        result["close"] = float(hist.iloc[-1]["Close"])
        result["prior"] = float(hist.iloc[-2]["Close"])
        result["snapshot_date"] = hist.index[-1].date().isoformat()
    except (KeyError, IndexError, ValueError) as exc:
        result["error"] = f"parse: {exc}"
        return result

    # first_mention_price · fm_dt 이상 첫 거래일 종가
    if fm_dt is not None:
        try:
            idx_dates = [ts.date() for ts in hist.index]
            for i, d in enumerate(idx_dates):
                if d >= fm_dt:
                    result["first_mention_price"] = float(hist.iloc[i]["Close"])
                    result["first_mention_used_date"] = d.isoformat()
                    break
        except (KeyError, IndexError, ValueError, AttributeError) as exc:
            logger.warning("[serenity_price] first_mention parse 실패 · %s · %s", yahoo_symbol, exc)

    # yfinance info · sector · industry · market_cap (Phase L13 · L14)
    # info 는 별도 HTTP 요청 · 실패해도 price 결과는 유지
    try:
        info = getattr(stock, "info", None) or {}
        sec = info.get("sector")
        ind = info.get("industry")
        if isinstance(sec, str) and sec.strip():
            result["sector"] = sec.strip()[:80]
        if isinstance(ind, str) and ind.strip():
            result["industry"] = ind.strip()[:120]
        # Phase L14 · market_cap · info 우선 · fallback sharesOutstanding × close
        mc = info.get("marketCap")
        if isinstance(mc, (int, float)) and mc > 0:
            result["market_cap"] = float(mc)
            result["market_cap_source"] = "yf"
        else:
            shares = info.get("sharesOutstanding")
            if isinstance(shares, (int, float)) and shares > 0 and result["close"]:
                result["market_cap"] = float(shares) * result["close"]
                result["market_cap_source"] = "computed"
    except Exception as exc:  # noqa: BLE001
        logger.debug("[serenity_price] info 실패 · %s · %s", yahoo_symbol, exc)

    # Phase L14 · avg_dollar_volume_20d · 이미 fetch 한 hist 재사용
    try:
        from backend.discovery.serenity.liquidity import compute_avg_dollar_volume
        adv = compute_avg_dollar_volume(hist, window=20)
        if adv is not None:
            result["avg_dollar_volume_20d"] = adv
    except Exception as exc:  # noqa: BLE001
        logger.debug("[serenity_price] adv 계산 실패 · %s · %s", yahoo_symbol, exc)

    return result


async def _load_all_tickers(days: int = 180) -> list[str]:
    """언급 티커 (signals) + seed 티커 union."""
    async with get_session() as session:
        seed_rows = (await session.execute(select(DiscoverySerenityScore.ticker))).scalars().all()
    seed_set = set(seed_rows)
    signal_set = set(await active_tickers(days=days))
    return sorted(seed_set | signal_set)


async def _upsert_price(
    ticker: str,
    yahoo_symbol: str,
    close,
    prior,
    snapshot_date,
    first_mention_price,
    first_mention_used_date,
    sector: Optional[str],
    industry: Optional[str],
    market_cap: Optional[float],
    market_cap_source: Optional[str],
    avg_dollar_volume_20d: Optional[float],
    error: Optional[str],
) -> None:
    pct = None
    if close is not None and prior is not None and prior > 0:
        pct = round((close - prior) / prior * 100, 2)
    gain_pct = None
    if close is not None and first_mention_price is not None and first_mention_price > 0:
        gain_pct = round((close - first_mention_price) / first_mention_price * 100, 2)
    async with get_session() as session:
        existing = (await session.execute(
            select(SerenityTickerPrice).where(SerenityTickerPrice.ticker == ticker)
        )).scalar_one_or_none()
        if existing:
            existing.snapshot_date = snapshot_date or existing.snapshot_date
            existing.close = close
            existing.prior_close = prior
            existing.vs_prior_close_pct = pct
            existing.first_mention_date = first_mention_used_date or existing.first_mention_date
            existing.first_mention_price = first_mention_price or existing.first_mention_price
            existing.gain_since_first_mention_pct = gain_pct if gain_pct is not None else existing.gain_since_first_mention_pct
            # sector · industry · market_cap · adv · 새 값 있으면 갱신 · 없으면 기존 유지
            if sector:
                existing.sector = sector
            if industry:
                existing.industry = industry
            if market_cap is not None:
                existing.market_cap = market_cap
                existing.market_cap_source = market_cap_source
            if avg_dollar_volume_20d is not None:
                existing.avg_dollar_volume_20d = avg_dollar_volume_20d
            existing.yahoo_symbol = yahoo_symbol
            existing.error = error
            existing.fetched_at = datetime.utcnow()
            await session.commit()
            return
        row = SerenityTickerPrice(
            ticker=ticker,
            snapshot_date=snapshot_date or datetime.utcnow().date().isoformat(),
            close=close,
            prior_close=prior,
            vs_prior_close_pct=pct,
            first_mention_date=first_mention_used_date,
            first_mention_price=first_mention_price,
            gain_since_first_mention_pct=gain_pct,
            sector=sector,
            industry=industry,
            market_cap=market_cap,
            market_cap_source=market_cap_source,
            avg_dollar_volume_20d=avg_dollar_volume_20d,
            yahoo_symbol=yahoo_symbol,
            error=error,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()


async def refresh_prices(
    *,
    days: int = 180,
    limit: Optional[int] = None,
    ticker_client=None,
) -> dict:
    """언급 티커 전체 종가 스냅샷 upsert.

    반환: {"targets": N, "ok": M, "failed": K}
    """
    tickers = await _load_all_tickers(days=days)
    if limit:
        tickers = tickers[:limit]
    if not tickers:
        return {"targets": 0, "ok": 0, "failed": 0}

    # first_mention_at 배치 조회 (Gain 계산용 · Phase L10)
    fm_map = await first_mention_map(tickers)

    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"targets": len(tickers), "ok": 0, "failed": 0, "skipped": 0}

    async def _one(tk: str) -> None:
        async with sem:
            # Private / 브랜드명 · yfinance 호출 스킵 (rate limit 소모 방지)
            if is_private_or_brand(tk):
                await _upsert_price(
                    tk, tk, None, None, None, None, None,
                    None, None, None, None, None,
                    "private/브랜드",
                )
                stats["skipped"] = stats.get("skipped", 0) + 1
                return

            symbol = to_yfinance_symbol(tk)
            fm_dt = fm_map.get(tk)
            fm_date_str = fm_dt.strftime("%Y-%m-%d") if fm_dt else None
            bundle = await asyncio.to_thread(
                _fetch_price_bundle,
                symbol,
                first_mention_date=fm_date_str,
                ticker_client=ticker_client,
            )
            if bundle["close"] is None:
                stats["failed"] += 1
            else:
                stats["ok"] += 1
            await _upsert_price(
                tk,
                symbol,
                bundle["close"],
                bundle["prior"],
                bundle["snapshot_date"],
                bundle["first_mention_price"],
                bundle["first_mention_used_date"],
                bundle["sector"],
                bundle["industry"],
                bundle["market_cap"],
                bundle["market_cap_source"],
                bundle["avg_dollar_volume_20d"],
                bundle["error"],
            )

    await asyncio.gather(*[_one(t) for t in tickers])
    return stats
