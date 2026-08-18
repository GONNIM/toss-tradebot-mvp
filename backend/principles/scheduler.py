"""Principles v1.0.2 스케줄러.

2 잡:
  1. weekly_detect_and_fetch (일요일 21:00 KST)
     - 각 KOSPI 종목의 최신 공시 분기 vs financial_cache 보유 분기 비교
     - 미수집 분기만 DART 호출 (호출 최소화)
     - rate limit 200ms sleep · 실패 → retry_queue upsert
  2. daily_recompute (매일 23:00 KST)
     - 캐시된 재무 + FDR 시가총액 + 산업분류 → 5원칙 재계산
     - DART 호출 없음
     - PrinciplesRun + PrinciplesResult upsert
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

import FinanceDataReader as fdr
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.dart.client import fetch_financial_statement
from backend.principles.charter import load_charter
from backend.principles.financials import (
    _REPRT_CODE_BY_Q,
    PrinciplesFinancials,
    cumulative_to_quarter,
    fetch_dividend_matter,
    parse_principles_financials,
    ttm_sum,
)
from backend.principles.screener import ScreenerInput, screen
from backend.principles.sector_detector import detect_financial
from backend.services.db import get_session
from backend.services.models import (
    PrinciplesDartRetryQueue,
    PrinciplesFinancialCache,
    PrinciplesResult,
    PrinciplesRun,
)

logger = logging.getLogger(__name__)

DART_RATE_LIMIT_SLEEP_SEC = 0.2  # 5 req/sec 이하
DART_MAX_RETRY = 3


# ─── KOSPI universe (FDR 캐시) ────────────────────────────────

_universe_cache: Optional[pd.DataFrame] = None
_universe_cached_at: Optional[datetime] = None
_UNIVERSE_TTL_SEC = 3600  # 1시간


async def get_kospi_universe() -> pd.DataFrame:
    """KOSPI 전종목 메타 (FDR StockListing) · 1시간 캐시."""
    global _universe_cache, _universe_cached_at
    now = datetime.now()
    if (
        _universe_cache is not None
        and _universe_cached_at is not None
        and (now - _universe_cached_at).total_seconds() < _UNIVERSE_TTL_SEC
    ):
        return _universe_cache
    df = await asyncio.to_thread(fdr.StockListing, "KOSPI")
    _universe_cache = df
    _universe_cached_at = now
    return df


# ─── corp_code 매핑 ──────────────────────────────────────────

_corp_code_map: Optional[dict[str, str]] = None


async def get_corp_code_map() -> dict[str, str]:
    """DART corp_code 매핑 (프로세스 lifetime 캐시)."""
    global _corp_code_map
    if _corp_code_map is not None:
        return _corp_code_map
    from backend.powderkeg.collectors.corp_codes import resolve_many

    df = await get_kospi_universe()
    tickers = df["Code"].astype(str).tolist()
    result = await resolve_many(tickers)
    _corp_code_map = {k: v for k, v in result.items() if v}
    logger.info(f"[principles] corp_code 매핑 완료 · {len(_corp_code_map)} / {len(tickers)}")
    return _corp_code_map


# ─── 감지 배치 · 미수집 분기만 DART ─────────────────────────

def _quarters_needed(today: date) -> list[tuple[int, int]]:
    """오늘 기준 · 수집 대상 분기 (fiscal_year, fiscal_quarter) 리스트.

    포함 범위 (2026-08-18 확장):
      - 최근 8개 분기 (TTM 계산 · 최근 2년 Q1~Q4)
      - 최근 5개 회계연도 사업보고서 (P3 배당 지속성 5년 · Q4=11011)
    """
    quarters: list[tuple[int, int]] = []
    y, m = today.year, today.month
    # (1) 최근 8분기 · TTM 용
    for i in range(8):
        q = ((m - 1) // 3)  # 0-indexed
        if i == 0:
            q -= 1  # 현재 진행 분기는 아직 공시 안 됨
        else:
            q -= 1
        yy = y
        while q < 0:
            q += 4
            yy -= 1
        quarters.append((yy, q + 1))
        m -= 3
        while m <= 0:
            m += 12
            y -= 1

    # (2) P3 · 최근 5개 회계연도 Q4 (사업보고서 · DPS 5년 필요)
    latest_year = today.year - 1 if today.month < 4 else today.year - 1
    # 사업보고서는 익년 3/31까지 공시 · 오늘 기준 안전하게 최근 5년 (직전 회계연도부터)
    for i in range(1, 6):
        quarters.append((today.year - i, 4))

    # dedup · 최신순 (year desc → quarter desc)
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for q in sorted(quarters, reverse=True):
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


async def weekly_detect_and_fetch() -> dict:
    """주 1회 감지 배치 · 미수집 분기만 DART 호출.

    호출 최소화: 종목당 캐시된 (fiscal_year, fiscal_quarter) 집합 조회 → diff.
    """
    started = datetime.now()
    stats = {"tickers": 0, "dart_calls": 0, "cache_upserts": 0, "retries": 0, "skipped": 0}

    df = await get_kospi_universe()
    tickers = df["Code"].astype(str).tolist()
    corp_map = await get_corp_code_map()
    quarters_target = _quarters_needed(date.today())

    async with get_session() as session:
        # 캐시된 (ticker, year, quarter) 세트 조회
        cached_rows = (
            await session.execute(
                select(
                    PrinciplesFinancialCache.ticker,
                    PrinciplesFinancialCache.fiscal_year,
                    PrinciplesFinancialCache.fiscal_quarter,
                )
            )
        ).all()
        cached: dict[str, set[tuple[int, int]]] = {}
        for t, y, q in cached_rows:
            cached.setdefault(t, set()).add((y, q))

        for ticker in tickers:
            stats["tickers"] += 1
            corp_code = corp_map.get(ticker)
            if not corp_code:
                stats["skipped"] += 1
                continue
            have = cached.get(ticker, set())
            missing = [q for q in quarters_target if q not in have]
            for (yy, qq) in missing:
                reprt = _REPRT_CODE_BY_Q[qq]
                try:
                    items = await fetch_financial_statement(corp_code, yy, reprt)
                    stats["dart_calls"] += 1
                    await asyncio.sleep(DART_RATE_LIMIT_SLEEP_SEC)
                except Exception as e:
                    logger.warning(f"[principles.detect] {ticker} {yy}Q{qq} fail: {e}")
                    await _enqueue_retry(session, ticker, yy, qq, str(e))
                    stats["retries"] += 1
                    continue
                if not items:
                    # 미공시 (013) · retry 안 함 · 다음 주 재시도
                    continue
                parsed = parse_principles_financials(items)
                # 배당 (Q4=사업보고서에만)
                dps = None
                dtotal = None
                if qq == 4:
                    try:
                        dm = await fetch_dividend_matter(corp_code, yy)
                        stats["dart_calls"] += 1
                        await asyncio.sleep(DART_RATE_LIMIT_SLEEP_SEC)
                        if dm:
                            dps = dm.dividend_per_share_common
                    except Exception as e:
                        logger.warning(f"[principles.dividend] {ticker} {yy} fail: {e}")
                await _upsert_cache(session, ticker, yy, qq, corp_code, parsed, dps, dtotal)
                stats["cache_upserts"] += 1
        await session.commit()

    stats["elapsed_sec"] = (datetime.now() - started).total_seconds()
    logger.info(f"[principles.weekly_detect] done · {stats}")
    return stats


async def _enqueue_retry(
    session: AsyncSession, ticker: str, yy: int, qq: int, err: str
) -> None:
    existing = (
        await session.execute(
            select(PrinciplesDartRetryQueue).where(
                PrinciplesDartRetryQueue.ticker == ticker,
                PrinciplesDartRetryQueue.fiscal_year == yy,
                PrinciplesDartRetryQueue.fiscal_quarter == qq,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            PrinciplesDartRetryQueue(
                ticker=ticker,
                fiscal_year=yy,
                fiscal_quarter=qq,
                attempt=1,
                last_error=err[:290],
                retry_after=datetime.now() + timedelta(hours=1),
            )
        )
    else:
        existing.attempt = min(existing.attempt + 1, DART_MAX_RETRY)
        existing.last_error = err[:290]
        existing.retry_after = datetime.now() + timedelta(
            hours=2 ** existing.attempt
        )


async def _upsert_cache(
    session: AsyncSession,
    ticker: str,
    yy: int,
    qq: int,
    corp_code: str,
    parsed: PrinciplesFinancials,
    dps: Optional[float],
    dtotal: Optional[float],
) -> None:
    existing = (
        await session.execute(
            select(PrinciplesFinancialCache).where(
                PrinciplesFinancialCache.ticker == ticker,
                PrinciplesFinancialCache.fiscal_year == yy,
                PrinciplesFinancialCache.fiscal_quarter == qq,
            )
        )
    ).scalar_one_or_none()
    # v1.0.2 · buyback 절대값 저장
    buy_abs = abs(parsed.buyback_cashflow) if parsed.buyback_cashflow else None
    fields = dict(
        corp_code=corp_code,
        revenue_cum=parsed.revenue,
        operating_income_cum=parsed.operating_income,
        net_income_owner_cum=parsed.net_income_owner or parsed.net_income,
        interest_expense_cum=parsed.interest_expense,
        total_assets=parsed.total_assets,
        total_liabilities=parsed.total_liabilities,
        total_equity=parsed.total_equity,
        buyback_cashflow_cum=buy_abs,
        dividend_per_share=dps,
        dividend_total=dtotal,
    )
    if existing is None:
        session.add(
            PrinciplesFinancialCache(
                ticker=ticker, fiscal_year=yy, fiscal_quarter=qq, **fields
            )
        )
    else:
        for k, v in fields.items():
            setattr(existing, k, v)


# ─── 일일 재계산 · DART 호출 없음 ────────────────────────────


async def daily_recompute() -> dict:
    """캐시된 재무 + FDR 시세 → 5원칙 재계산 · PrinciplesRun/Result upsert.

    가드 (2026-08-18 신설 · reset 직후 빈 캐시로 돌지 않도록):
      principles_financial_cache 가 완전히 비어 있으면 run 생성 없이 skip.
      "cache_empty_skip" 반환 · 로그 · 향후 유사 상황 재발 방지.
    """
    started = datetime.now()
    charter = load_charter()

    # 가드 · 캐시 empty check
    async with get_session() as session:
        cache_count = (
            await session.execute(select(PrinciplesFinancialCache).limit(1))
        ).scalars().first()
    if cache_count is None:
        logger.warning(
            "[principles.daily_recompute] cache_empty_skip · "
            "principles_financial_cache 비어있음 · run 생성 없이 종료"
        )
        return {"skipped": True, "reason": "cache_empty_skip"}

    df = await get_kospi_universe()

    stats = {"universe": 0, "pass": 0, "fail": 0, "insufficient": 0}
    async with get_session() as session:
        run = PrinciplesRun(
            started_at=started,
            trigger="cron",
            charter_version=charter["version"],
            universe_size=len(df),
            dart_call_count=0,
        )
        session.add(run)
        await session.flush()
        run_id = run.id

        # 캐시 로드 · 종목별로 그룹
        cache_rows = (
            await session.execute(select(PrinciplesFinancialCache))
        ).scalars().all()
        by_ticker: dict[str, list[PrinciplesFinancialCache]] = {}
        for r in cache_rows:
            by_ticker.setdefault(r.ticker, []).append(r)

        for _, row in df.iterrows():
            ticker = str(row["Code"])
            name = str(row.get("Name") or "")
            industry_name = str(row.get("Sector") or row.get("Industry") or "")
            market_cap = None
            marcap = row.get("Marcap")
            if marcap is not None and not pd.isna(marcap):
                try:
                    market_cap = float(marcap)
                except (ValueError, TypeError):
                    pass

            sector = detect_financial(ticker, industry_name)
            fin_rows = by_ticker.get(ticker, [])

            inp = _build_screener_input(
                ticker=ticker,
                name=name,
                market_cap=market_cap,
                fin_rows=fin_rows,
                is_financial_sector=sector.is_financial_sector,
            )
            verdict = screen(inp)
            stats["universe"] += 1
            if verdict.verdict == "PASS":
                stats["pass"] += 1
            elif verdict.verdict == "FAIL":
                stats["fail"] += 1
            else:
                stats["insufficient"] += 1

            session.add(
                PrinciplesResult(
                    run_id=run_id,
                    ticker=ticker,
                    name=name,
                    verdict=verdict.verdict,
                    industry_code=sector.industry_code,
                    is_financial_sector=sector.is_financial_sector,
                    per_ttm=verdict.per_ttm,
                    per_operating=verdict.per_operating,
                    payout_ratio_3y_avg=verdict.payout_ratio_3y_avg,
                    dividend_years=verdict.dividend_years,
                    dividend_cut=verdict.dividend_cut,
                    debt_ratio=verdict.debt_ratio,
                    interest_coverage=verdict.interest_coverage,
                    reasons_json=json.dumps(
                        [
                            {
                                "code": r.code,
                                "status": r.status,
                                "value": r.value,
                                "threshold": r.threshold,
                                "note": r.note,
                            }
                            for r in verdict.reasons
                        ],
                        ensure_ascii=False,
                    ),
                    missing_fields_json=json.dumps(
                        verdict.missing_fields, ensure_ascii=False
                    ),
                )
            )
        run.finished_at = datetime.now()
        run.pass_count = stats["pass"]
        run.fail_count = stats["fail"]
        run.insufficient_count = stats["insufficient"]
        run.elapsed_sec = (run.finished_at - run.started_at).total_seconds()
        await session.commit()

    stats["run_id"] = run_id
    stats["elapsed_sec"] = (datetime.now() - started).total_seconds()
    logger.info(f"[principles.daily_recompute] done · run_id={run_id} · {stats}")
    return stats


def _build_screener_input(
    *,
    ticker: str,
    name: str,
    market_cap: Optional[float],
    fin_rows: list[PrinciplesFinancialCache],
    is_financial_sector: bool,
) -> ScreenerInput:
    """캐시 rows → ScreenerInput · TTM 누적 분해 + 3년 · 5년 시계열 조립."""
    # (year, quarter) → row
    by_yq: dict[tuple[int, int], PrinciplesFinancialCache] = {
        (r.fiscal_year, r.fiscal_quarter): r for r in fin_rows
    }
    # 최근 회계연도 (Q4 있는 연도 기준)
    years_desc = sorted({y for y, q in by_yq if q == 4}, reverse=True)

    # ─── TTM (최근 4개 분기 단독) ─────
    ni_owner_ttm = None
    op_ttm = None
    ie_ttm = None
    if years_desc:
        # 각 필드의 누적 값 시계열 · Q1~Q4 각 연도별
        def _quarter_flow(attr: str) -> list[Optional[float]]:
            """8개 분기 단독 시계열 (오래된 순)."""
            series: list[Optional[float]] = []
            for y in reversed(years_desc[:2]):  # 최근 2년
                cum = {
                    q: getattr(by_yq[(y, q)], attr) if (y, q) in by_yq else None
                    for q in (1, 2, 3, 4)
                }
                q_flow = cumulative_to_quarter(cum)
                for q in (1, 2, 3, 4):
                    series.append(q_flow[q])
            return series

        ni_owner_ttm = ttm_sum(_quarter_flow("net_income_owner_cum"))
        op_ttm = ttm_sum(_quarter_flow("operating_income_cum"))
        ie_ttm = ttm_sum(_quarter_flow("interest_expense_cum"))

    # ─── 3년 연간값 (Q4 = 사업보고서) ─
    ni_3y: list[Optional[float]] = []
    div_3y: list[Optional[float]] = []
    buy_3y: list[Optional[float]] = []
    for y in reversed(years_desc[:3]):  # 최근 3년 (오래된 순)
        row = by_yq.get((y, 4))
        if row:
            ni_3y.append(row.net_income_owner_cum)
            div_3y.append(row.dividend_total)
            buy_3y.append(row.buyback_cashflow_cum)
        else:
            ni_3y.append(None)
            div_3y.append(None)
            buy_3y.append(None)
    # 3년 부족 시 None 채움
    while len(ni_3y) < 3:
        ni_3y.insert(0, None)
        div_3y.insert(0, None)
        buy_3y.insert(0, None)

    # ─── 5년 DPS (Q4 dividend_per_share) ─
    dps_5y: list[Optional[float]] = []
    for y in reversed(years_desc[:5]):
        row = by_yq.get((y, 4))
        dps_5y.append(row.dividend_per_share if row else None)

    # 최신 분기 · 재무건전성 (총 최근 Q1~4 아무거나 latest)
    latest = None
    for y in years_desc:
        for q in (4, 3, 2, 1):
            if (y, q) in by_yq:
                latest = by_yq[(y, q)]
                break
        if latest:
            break

    total_liab = latest.total_liabilities if latest else None
    total_eq = latest.total_equity if latest else None

    # v1.0.2 · TTM sanity check 참조값 (최근 사업보고서 연간 순이익)
    latest_annual_ni = None
    if years_desc:
        r_fy = by_yq.get((years_desc[0], 4))
        if r_fy:
            latest_annual_ni = r_fy.net_income_owner_cum

    return ScreenerInput(
        ticker=ticker,
        name=name,
        market_cap=market_cap,
        net_income_owner_ttm=ni_owner_ttm,
        operating_income_ttm=op_ttm,
        net_income_owner_3y=ni_3y,
        dividend_total_3y=div_3y,
        buyback_cashflow_3y=buy_3y,
        dividend_per_share_5y=dps_5y,
        total_liabilities=total_liab,
        total_equity=total_eq,
        interest_expense_ttm=ie_ttm,
        is_financial_sector=is_financial_sector,
        latest_annual_net_income_owner=latest_annual_ni,
    )


# ─── APScheduler 등록 ─────────────────────────────────────────


def register_principles_jobs(scheduler: AsyncIOScheduler) -> None:
    """주 1회 감지 배치 + 매일 23:00 재계산."""
    scheduler.add_job(
        weekly_detect_and_fetch,
        trigger=CronTrigger(day_of_week="sun", hour=21, minute=0, timezone="Asia/Seoul"),
        id="principles_weekly_detect",
        name="주 1회 DART 감지 배치 (일요일 21:00)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        daily_recompute,
        trigger=CronTrigger(hour=23, minute=0, timezone="Asia/Seoul"),
        id="principles_daily_recompute",
        name="매일 23:00 principles 재계산 (캐시+시세)",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        "[principles] jobs registered · weekly_detect (Sun 21:00) + daily_recompute (23:00) KST"
    )
