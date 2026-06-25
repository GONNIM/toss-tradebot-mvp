"""Meme Watch universe 빌드 (Phase 1a / 1a-bonus).

US: Russell 2000 (iShares IWM ETF holdings) — small/mid cap 표준 지수.
KRX: KOSDAQ 시총 ≤ 1조원.

매주 일요일 03:00 KST 자동 갱신 (APScheduler).

데이터 소스:
- FDR (이미 sector_leaders 에서 사용 중) — KOSDAQ 리스트
- iShares IWM holdings CSV (공식) — Russell 2000 small/mid cap
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Optional

import FinanceDataReader as fdr
import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_session
from backend.services.models import MemeUniverse

logger = logging.getLogger(__name__)

KRX_MARKET_CAP_MAX = 1_000_000_000_000  # 1조원

# iShares IWM (Russell 2000 ETF) 공식 holdings CSV. 매일 갱신.
IWM_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"
)
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")


def _pick_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


async def _fetch_listing(market: str) -> pd.DataFrame:
    """FDR StockListing — 시장명 (KOSDAQ 등) 별 호출."""
    return await asyncio.to_thread(fdr.StockListing, market)


async def fetch_us_candidates() -> pd.DataFrame:
    """Russell 2000 ETF (IWM) holdings — small/mid cap 표준."""
    logger.info("[meme_universe] fetching Russell 2000 (iShares IWM holdings)")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(IWM_HOLDINGS_URL, timeout=30.0)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig", errors="replace")

    # iShares CSV 는 상단에 메타 행, 본 데이터의 헤더는 "Ticker," 로 시작
    lines = text.split("\n")
    header_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or line.startswith('"Ticker"'):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("iShares IWM CSV: 'Ticker' header line not found")

    df = pd.read_csv(
        io.StringIO("\n".join(lines[header_idx:])), on_bad_lines="skip"
    )
    df.columns = [c.strip() for c in df.columns]
    if "Ticker" not in df.columns:
        raise ValueError(f"IWM CSV: Ticker column missing — {df.columns.tolist()}")

    # 시총 (Market Value) — 쉼표 제거 후 numeric
    cap_col = _pick_col(df, "Market Value", "Marcap", "MarketCap")
    if cap_col:
        df["_cap"] = pd.to_numeric(
            df[cap_col].astype(str).str.replace(",", "").str.replace('"', ""),
            errors="coerce",
        ).fillna(0.0)
    else:
        df["_cap"] = 0.0

    # ticker 유효성 (대문자 영문 1~6자, '.', '-' 허용)
    df = df[df["Ticker"].astype(str).str.match(_TICKER_RE, na=False)]

    logger.info(f"[meme_universe] Russell 2000 IWM holdings: {len(df)} rows")
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
