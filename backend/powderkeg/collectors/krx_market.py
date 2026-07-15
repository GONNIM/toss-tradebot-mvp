"""KRX 시장 데이터 수집기 · Phase 7-1c.

수집 (일 1회 · 저녁 배치):
  - 종가·시가총액·PBR·상장시장 (KOSPI/KOSDAQ)
  - 60일 평균 거래대금 (유동성 필터용)

전략:
  - FinanceDataReader (기존 KOSDAQ universe 에서 사용) 재활용
  - StockListing("KOSPI") + StockListing("KOSDAQ") 병합 · 오늘 스냅샷
  - 60일 ADV 는 DataReader(ticker, start_date) 로 개별 조회 · 부하 큼 → v1 은 배치 옵션
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import KrxMarketSnapshot

logger = logging.getLogger(__name__)


def _today_kst_str() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(tz=kst).date().isoformat()


async def collect_market_snapshot(
    tickers: Optional[Iterable[str]] = None,
    snapshot_date: Optional[str] = None,
    include_adv60: bool = False,
) -> dict[str, Any]:
    """KOSPI+KOSDAQ 시장 스냅샷 수집 · KrxMarketSnapshot upsert.

    Args:
        tickers: 대상 종목 (None = 전체 KOSPI+KOSDAQ)
        snapshot_date: 스냅샷 날짜 (None = 오늘 KST)
        include_adv60: True 이면 종목별 60일 평균 거래대금 조회 (개별 DataReader · 느림)

    Returns:
        {"total": N, "upserted": M, "adv60_computed": K, "errors": E}
    """
    import FinanceDataReader as fdr

    snapshot_date = snapshot_date or _today_kst_str()
    stats = {"total": 0, "upserted": 0, "adv60_computed": 0, "errors": 0, "snapshot_date": snapshot_date}

    # 1. 전체 listing (오늘 스냅샷 · 시총·PBR·종가 포함)
    rows: list[dict[str, Any]] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(market)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[krx] StockListing %s 실패 · %s", market, exc)
            stats["errors"] += 1
            continue
        for _, r in df.iterrows():
            code = str(r.get("Code") or "").strip()
            if not code:
                continue
            if tickers is not None and code not in tickers:
                continue
            rows.append({
                "ticker": code,
                "market": market,
                "close_price": _f(r.get("Close")),
                "market_cap": _f(r.get("Marcap")),
                "pbr": _f(r.get("PBR")),   # FDR 는 PBR 컬럼 제공 (일부 미제공 · None)
                "amount_today": _f(r.get("Amount")),
            })

    stats["total"] = len(rows)

    # 2. 60일 ADV 개별 조회 (선택 · 배치 옵션)
    adv60_map: dict[str, float] = {}
    if include_adv60:
        for row in rows:
            ticker = row["ticker"]
            try:
                # 최근 90 캘린더일 데이터 → 영업일 필터 후 60일 평균
                end = date.fromisoformat(snapshot_date)
                start = end - timedelta(days=90)
                df = fdr.DataReader(ticker, start, end)
                if df is None or df.empty:
                    continue
                # Amount = 거래대금 (Close * Volume 근사 · FDR 는 Volume 만 제공 시 계산)
                if "Amount" in df.columns:
                    amount = df["Amount"].tail(60)
                else:
                    amount = (df["Close"] * df["Volume"]).tail(60)
                if len(amount) == 0:
                    continue
                adv60_map[ticker] = float(amount.mean())
                stats["adv60_computed"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("[krx] adv60 %s 실패 · %s", ticker, exc)
                stats["errors"] += 1

    # 3. upsert
    async with get_session() as session:
        for row in rows:
            ticker = row["ticker"]
            stmt = select(KrxMarketSnapshot).where(
                KrxMarketSnapshot.ticker == ticker,
                KrxMarketSnapshot.snapshot_date == snapshot_date,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                existing = KrxMarketSnapshot(
                    ticker=ticker, snapshot_date=snapshot_date,
                )
                session.add(existing)
            existing.market = row["market"]
            existing.close_price = row["close_price"]
            existing.market_cap = row["market_cap"]
            existing.pbr = row["pbr"]
            if include_adv60 and ticker in adv60_map:
                existing.avg_daily_amount_60d = adv60_map[ticker]
            stats["upserted"] += 1

    logger.info("[krx.snapshot] %s", stats)
    return stats


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        # NaN 안전 처리
        if f != f:   # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


async def latest_market(ticker: str) -> Optional[KrxMarketSnapshot]:
    """지정 종목의 가장 최근 스냅샷."""
    async with get_session() as session:
        stmt = (
            select(KrxMarketSnapshot)
            .where(KrxMarketSnapshot.ticker == ticker)
            .order_by(KrxMarketSnapshot.snapshot_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()
