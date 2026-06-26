"""Meme Watch universe 빌드 (Phase 1a / 1a-bonus / 1b 네이버 전환).

US: NASDAQ + NYSE 시총 ≤ 5B USD (네이버 금융 marketValue 페이지네이션).
KRX: KOSDAQ 시총 ≤ 1조원 (FDR).

매주 일요일 03:00 KST 자동 갱신 (APScheduler).

데이터 소스:
- 네이버 금융 (api.stock.naver.com) — 미국 시총·종목 리스트 (yfinance 차단 우회)
- FDR StockListing("KOSDAQ") — 한국 KOSDAQ 리스트 + 시총
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import FinanceDataReader as fdr
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.naver_quote import fetch_us_listings
from backend.services.db import get_session
from backend.services.models import MemeUniverse

logger = logging.getLogger(__name__)

US_MARKET_CAP_MAX = 5_000_000_000       # 5B USD
KRX_MARKET_CAP_MAX = 1_000_000_000_000  # 1조원


def _pick_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


async def _fetch_listing(market: str) -> pd.DataFrame:
    """FDR StockListing — 시장명 (KOSDAQ 등) 별 호출."""
    return await asyncio.to_thread(fdr.StockListing, market)


async def fetch_us_candidates() -> pd.DataFrame:
    """NASDAQ + NYSE 시총 ≤ 5B USD (네이버 금융 marketValue 페이지네이션).

    네이버 응답의 reutersCode 를 ticker 로 사용 (.O / .K suffix 포함) —
    일봉 fetch 시 그대로 호출 가능.
    """
    logger.info("[meme_universe] fetching US via Naver (NASDAQ + NYSE)")
    nasdaq, nyse = await asyncio.gather(
        fetch_us_listings("NASDAQ", US_MARKET_CAP_MAX),
        fetch_us_listings("NYSE", US_MARKET_CAP_MAX),
    )

    rows = []
    for listing in [*nasdaq, *nyse]:
        rows.append(
            {
                "Ticker": listing.reuters_code,
                "Symbol": listing.symbol,
                "Name": listing.name_eng or listing.name_kor,
                "Sector": listing.industry_kor,
                "_cap": listing.market_value_usd,
            }
        )
    df = pd.DataFrame(rows)
    logger.info(
        f"[meme_universe] US (Naver): NASDAQ {len(nasdaq)} + NYSE {len(nyse)} "
        f"= {len(df)} total (cap ≤ ${US_MARKET_CAP_MAX:,})"
    )
    return df


async def fetch_krx_candidates() -> pd.DataFrame:
    """KOSDAQ 시총 ≤ KRX_MARKET_CAP_MAX 종목."""
    logger.info("[meme_universe] fetching KOSDAQ")
    kosdaq = await _fetch_listing("KOSDAQ")

    cap_col = _pick_col(kosdaq, "Marcap", "MarketCap", "market_cap")
    if cap_col is None:
        logger.warning("[meme_universe] KOSDAQ: Marcap 컬럼 없음 — 필터 skip")
        kosdaq["_cap"] = 0.0
    else:
        kosdaq["_cap"] = pd.to_numeric(kosdaq[cap_col], errors="coerce").fillna(0.0)
        kosdaq = kosdaq[(kosdaq["_cap"] > 0) & (kosdaq["_cap"] <= KRX_MARKET_CAP_MAX)]

    logger.info(f"[meme_universe] KOSDAQ after filter: {len(kosdaq)} rows")
    return kosdaq


async def upsert_universe(
    session: AsyncSession, df: pd.DataFrame, market: str
) -> dict:
    """DataFrame → MemeUniverse 테이블 UPSERT + 미출현 종목 deactivate."""
    stats = {"inserted": 0, "updated": 0, "deactivated": 0, "total_input": len(df)}

    ticker_col = _pick_col(df, "Symbol", "Code", "Ticker", "ticker")
    name_col = _pick_col(df, "Name", "name")
    sector_col = _pick_col(df, "Sector", "Industry", "sector")

    if ticker_col is None or name_col is None:
        logger.error(
            f"[meme_universe] {market}: ticker/name 컬럼 누락 "
            f"(ticker={ticker_col}, name={name_col})"
        )
        return stats

    existing_tickers = set(
        (
            await session.execute(
                select(MemeUniverse.ticker).where(MemeUniverse.market == market)
            )
        ).scalars().all()
    )
    seen: set[str] = set()

    for _, row in df.iterrows():
        ticker = str(row[ticker_col]).strip()
        if not ticker:
            continue
        name = str(row[name_col]).strip()[:100]
        sector_raw = row.get(sector_col) if sector_col else None
        sector = str(sector_raw).strip()[:50] if pd.notna(sector_raw) else None
        cap = float(row.get("_cap", 0)) or None

        existing = (
            await session.execute(
                select(MemeUniverse).where(
                    MemeUniverse.market == market,
                    MemeUniverse.ticker == ticker,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                MemeUniverse(
                    market=market,
                    ticker=ticker,
                    name=name,
                    sector=sector,
                    market_cap=cap,
                    is_active=True,
                )
            )
            stats["inserted"] += 1
        else:
            existing.name = name
            existing.sector = sector
            existing.market_cap = cap
            existing.is_active = True
            stats["updated"] += 1
        seen.add(ticker)

    # 이번 빌드에 안 나온 종목 deactivate
    for ticker in existing_tickers - seen:
        existing = (
            await session.execute(
                select(MemeUniverse).where(
                    MemeUniverse.market == market,
                    MemeUniverse.ticker == ticker,
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.is_active:
            existing.is_active = False
            stats["deactivated"] += 1

    await session.commit()
    return stats


async def build_universe() -> dict:
    """전체 universe 재빌드 — US + KRX, 부분 실패 격리."""
    stats: dict = {}
    async with get_session() as session:
        try:
            us_df = await fetch_us_candidates()
            stats["us"] = await upsert_universe(session, us_df, "US")
        except Exception as e:
            logger.exception(f"[meme_universe] US build failed: {e}")
            stats["us"] = {"error": str(e)}
        try:
            krx_df = await fetch_krx_candidates()
            stats["krx"] = await upsert_universe(session, krx_df, "KRX")
        except Exception as e:
            logger.exception(f"[meme_universe] KRX build failed: {e}")
            stats["krx"] = {"error": str(e)}
    logger.info(f"[meme_universe] done stats={stats}")
    return stats
