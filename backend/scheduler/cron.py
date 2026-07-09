"""APScheduler cron — Discovery 실행기 (Phase J dry-run 활성).

스케줄 (KST):
  - 06:00 universe 갱신 (Finnhub profile + Stooq quote)
  - 06:30 Crazy Picks (시총 ≥ $1B)
  - 16:50 Moonshot Picks (모든 미국 주식, 페니/마이크로 포함)

기동:
    python -m backend.scheduler.cron                # 데몬 (systemd)
    python -m backend.scheduler.cron --once crazy   # 1회 즉시 실행 (수동 검증)
    python -m backend.scheduler.cron --once moonshot
    python -m backend.scheduler.cron --once universe

Phase J dry-run watchlist (50 ticker) — 운영 안정화 후 확장 가능.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Phase J 초기 watchlist (~50 ticker)
# 운영 안정화 후 SEC company_tickers.json 전체로 확장.
# ─────────────────────────────────────────────

WATCHLIST = [
    # Big 7
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    # 사용자 영구 보유 + 인접
    "SPCX", "ASTS", "NBIS",
    # 반도체·하드웨어
    "MU", "AVGO", "AMD", "INTC", "QCOM", "TSM", "ASML", "ARM",
    # 클라우드·소프트웨어
    "ORCL", "CRM", "PLTR", "NET", "SNOW", "IBM",
    # 핀테크·암호
    "COIN", "MSTR", "RIOT", "MARA",
    # 게임·메타
    "RBLX",
    # 금융·결제
    "V", "MA", "JPM", "BAC",
    # 컨슈머
    "WMT", "COST", "KO", "PEP",
    # 헬스케어
    "JNJ", "PFE", "MRK",
    # ETF (지수)
    "SPY", "QQQ",
    # 미친 상승 후보 (역사적 화제 / 백테스트 검증)
    "EHGO", "AZTR", "AMC", "GME", "CARV",
    # 마이크로캡 / 페니 추가 (Moonshot HIGH 위험 후보 — 결정 2026-06-20)
    "BBAI",     # BigBear.ai — AI 정부 계약 마이크로캡
    "SOFI",     # SoFi Tech — 핀테크 소형주
    "RIVN",     # Rivian — EV 손실 누적 후보
    "LCID",     # Lucid Motors — EV 단가 변동성
    "MNTS",     # Momentus — 우주 마이크로캡
    "IPDN",     # Professional Diversity — 페니스톡
    "ZAPP",     # Zapp Electric Vehicles — EV 페니
    "BURU",     # Nuburu — 레이저 페니
    "HCDI",     # Harbor Custom Dev — 주택 페니
    "NUKK",     # Nukkleus — 핀테크 페니
    "BREA",     # Brera Holdings — 스포츠 마이크로캡
    "WAVE",     # Eco Wave Power — 청정에너지 마이크로
]

# Top N 설정
CRAZY_TOP_N = int(os.environ.get("CRAZY_TOP_N", "10"))
MOONSHOT_TOP_N = int(os.environ.get("MOONSHOT_TOP_N", "3"))
SECTOR_LEADERS_TOP_N = int(os.environ.get("SECTOR_LEADERS_TOP_N", "3"))


# ─────────────────────────────────────────────
# 클라이언트 builder
# ─────────────────────────────────────────────


def _build_clients() -> dict:
    """Discovery 클라이언트 dict. 호출 측이 async with 로 진입.

    Stooq 가 JS PoW 봇 차단 도입 (2026-06-20) → Yahoo 우선, Stooq 보존 (대체).
    crazy_picks.py 는 clients['stooq'] 키 호환 위해 Yahoo 도 'stooq' 키로 등록.
    """
    from backend.discovery.data_sources.apewisdom import ApewisdomClient
    from backend.discovery.data_sources.finnhub import FinnhubClient
    from backend.discovery.data_sources.finra import FINRAClient
    from backend.discovery.data_sources.rss import RSSClient
    from backend.discovery.data_sources.sec_edgar import SECEdgarClient
    from backend.discovery.data_sources.yahoo import YahooClient
    from backend.services.llm import get_llm_client

    return {
        "stooq": YahooClient(),   # Yahoo 가 stooq 키 점유 — crazy_picks.py 호환
        "finnhub": FinnhubClient(),
        "sec": SECEdgarClient(),
        "apewisdom": ApewisdomClient(),
        "finra": FINRAClient(),
        "rss": RSSClient(),
        "llm": get_llm_client(),
    }


async def _enter_clients(clients: dict) -> dict:
    """모든 async-context 클라이언트 동시 진입.

    예외: 'llm' 키는 진입하지 않는다. Z.ai GLM 은 undocumented concurrent=1
    제한이 있어 cron 에서 client A 만들고 crazy_picks 가 또 만들면 A 연결이
    z.ai 서버에 남아 B 호출이 "두 번째 동시 호출" 로 분류돼 hang.
    → LLM 은 호출 측 (run_crazy_picks/run_moonshot_picks) 내부 `async with`
       으로만 lifecycle 관리.
    """
    for name, c in list(clients.items()):
        if name == "llm":
            continue
        if hasattr(c, "__aenter__"):
            await c.__aenter__()
    return clients


async def _fill_missing_prices(picks):
    """current_price=0 인 pick 에 대해 단독 Yahoo fetch — fallback.

    factor 수집 단계에서 Yahoo 가 fd 누수/timeout 등으로 fail 했더라도 DB 에는
    실 가격이 들어가도록 보장.
    """
    from backend.discovery.data_sources.yahoo import YahooClient
    missing = [p for p in picks if not p.current_price or p.current_price == 0]
    if not missing:
        return picks
    logger.info(f"[fill_prices] {len(missing)} picks missing close_price → Yahoo fetch")
    async with YahooClient() as yh:
        for p in missing:
            try:
                price = await asyncio.wait_for(yh.get_current_price(p.ticker), timeout=10.0)
                # dataclass replace
                from dataclasses import replace as _replace
                idx = picks.index(p)
                picks[idx] = _replace(p, current_price=price)
                logger.debug(f"[fill_prices] {p.ticker} = ${price:.2f}")
            except Exception as e:
                logger.warning(f"[fill_prices] {p.ticker} fail: {e}")
    return picks


async def _exit_clients(clients: dict) -> None:
    """모든 클라이언트 graceful close (LLM 은 호출 측이 이미 close).

    crazy_picks/moonshot_picks 내부에서 factor 단계 끝나고 이미 close 했을 수
    있음 — _aexit__ 이중 호출 안전 (httpx AsyncClient 는 idempotent).
    """
    for name, c in clients.items():
        if name == "llm":
            continue
        if hasattr(c, "__aexit__"):
            try:
                await c.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"close failed: {e}")


# ─────────────────────────────────────────────
# Universe 갱신
# ─────────────────────────────────────────────


async def run_universe_refresh():
    """Watchlist 기반 ticker_universe 테이블 갱신."""
    from sqlalchemy import select
    from backend.discovery.scoring import classify_risk
    from backend.discovery.universe import (
        CRAZY_MIN_MARKET_CAP,
        MOONSHOT_MIN_AVG_VOLUME,
        MOONSHOT_MIN_PRICE,
    )
    from backend.services.db import get_session
    from backend.services.models import TickerUniverse

    logger.info(f"[universe] start — {len(WATCHLIST)} tickers")
    clients = await _enter_clients(_build_clients())

    updated = 0
    try:
        for ticker in WATCHLIST:
            try:
                profile = await clients["finnhub"].get_company_profile(ticker)
                # clients['stooq'] 는 실제로 YahooClient (호환 키)
                candles = await clients["stooq"].get_daily_candles(ticker, count=25)
                if not candles:
                    logger.debug(f"[universe] {ticker} no candles")
                    continue
                latest = candles[-1]
                avg_vol = sum(c.volume for c in candles) / len(candles)
                mcap_usd = (profile.market_cap or 0) * 1_000_000  # Finnhub 은 millions 단위

                async with get_session() as session:
                    stmt = select(TickerUniverse).where(TickerUniverse.symbol == ticker)
                    row = (await session.execute(stmt)).scalar_one_or_none()
                    if not row:
                        row = TickerUniverse(
                            symbol=ticker,
                            market=profile.exchange or "UNKNOWN",
                            category="dry_run",
                            sector=profile.sector,
                            company_name=profile.name,
                            market_cap=mcap_usd if mcap_usd > 0 else None,
                        )
                        session.add(row)
                    else:
                        row.market = profile.exchange or row.market
                        row.sector = profile.sector or row.sector
                        row.company_name = profile.name or row.company_name
                        row.market_cap = mcap_usd if mcap_usd > 0 else row.market_cap
                    await session.commit()

                updated += 1
            except Exception as e:
                logger.warning(f"[universe] {ticker} enrich fail: {e}")
    finally:
        await _exit_clients(clients)

    logger.info(f"[universe] refresh complete — {updated}/{len(WATCHLIST)} enriched")
    return updated


async def _load_dry_run_universe():
    """WATCHLIST 기반 TickerInfo 리스트 — DB enrich 데이터 반영."""
    from sqlalchemy import select
    from backend.discovery.scoring import classify_risk
    from backend.discovery.universe import (
        TickerInfo,
        passes_crazy_filter,
        passes_moonshot_filter,
    )
    from backend.services.db import get_session
    from backend.services.models import TickerUniverse

    universe: list = []
    async with get_session() as session:
        rows = (await session.execute(select(TickerUniverse))).scalars().all()
        # WATCHLIST 우선 + DB에 있는 ticker
        targets = {r.symbol: r for r in rows}
        for ticker in WATCHLIST:
            row = targets.get(ticker)
            if not row:
                # universe 갱신 전이면 metadata 없이 ticker 만으로 진입
                universe.append(TickerInfo(
                    ticker=ticker, name="", exchange="UNKNOWN", sector=None,
                    market_cap_usd=None, avg_daily_volume_20d=None,
                    current_price=None, listing_date=None,
                    risk_level="MED", is_crazy=True, is_moonshot=True,
                ))
                continue
            risk = classify_risk(row.market_cap, 0)  # 가격 0 → MED 기본
            info = TickerInfo(
                ticker=row.symbol, name=row.company_name or "",
                exchange=row.market, sector=row.sector,
                market_cap_usd=row.market_cap,
                avg_daily_volume_20d=None,
                current_price=None,
                listing_date=None,
                risk_level=risk,
                # dry-run watchlist 전체 강제 통과 — 데모·디버그 목적.
                # 운영 universe 확장 시 passes_*_filter 활성화 필요.
                is_crazy=True, is_moonshot=True,
            )
            universe.append(info)
    return universe


# ─────────────────────────────────────────────
# Crazy / Moonshot 실행
# ─────────────────────────────────────────────


async def run_crazy_picks_job():
    """Crazy Picks 일일 실행 — Top N + DB + Telegram.

    env:
      CRAZY_SKIP_SLOW=1     SEC/FINRA skip (dry-run 빠른 모드)
      WATCHLIST_LIMIT=N     universe 상위 N 개만 (수동 트리거 데모 용)
    """
    from backend.discovery.crazy_picks import run_crazy_picks
    from backend.services.db import get_session
    from backend.services.models import CrazyPick
    from backend.services.notifier import TelegramNotifier, format_crazy_alert

    skip_slow = os.environ.get("CRAZY_SKIP_SLOW", "0") == "1"
    limit = int(os.environ.get("WATCHLIST_LIMIT", "0"))
    logger.info(f"[crazy] start skip_slow={skip_slow} limit={limit or 'all'}")
    today = datetime.now().strftime("%Y-%m-%d")
    universe = await _load_dry_run_universe()
    if limit:
        universe = universe[:limit]
        logger.info(f"[crazy] universe truncated to {len(universe)}")
    clients = await _enter_clients(_build_clients())

    try:
        picks = await run_crazy_picks(
            universe, clients, top_n=CRAZY_TOP_N, generate_thesis=True, skip_slow=skip_slow,
        )
    finally:
        await _exit_clients(clients)

    # close_price=0 인 pick 에 한해 별도 Yahoo fetch (factor 단계 Yahoo timeout 회복)
    picks = await _fill_missing_prices(picks)

    # DB 저장 — 같은 pick_date 의 이전 row 모두 삭제 후 insert (중복 방지)
    from sqlalchemy import delete as _delete
    async with get_session() as session:
        await session.execute(_delete(CrazyPick).where(CrazyPick.pick_date == today))
        for p in picks:
            row = CrazyPick(
                pick_date=today,
                rank=p.rank,
                ticker=p.ticker,
                company_name=p.company_name,
                sector=p.sector,
                market_cap=p.market_cap_usd,
                close_price=p.current_price,
                composite_score=p.total_score,
                factor_breakdown=json.dumps(p.factor_scores.breakdown()),
                thesis=p.thesis,
                catalysts=json.dumps(p.catalysts, ensure_ascii=False),
                risks=json.dumps(p.risks, ensure_ascii=False),
                news_summary=p.news_summary,
            )
            session.add(row)
        await session.commit()
    logger.info(f"[crazy] saved {len(picks)} picks to DB (이전 동일 날짜 삭제)")

    # Telegram
    if picks:
        title, body = format_crazy_alert(picks)
        notifier = TelegramNotifier()
        await notifier.send_info(title, body)
    return len(picks)


async def run_moonshot_picks_job():
    """Moonshot Picks 일일 실행 — Top N + DB + Telegram.

    env: MOONSHOT_SKIP_SLOW / WATCHLIST_LIMIT
    """
    from backend.discovery.moonshot_picks import run_moonshot_picks
    from backend.services.db import get_session
    from backend.services.models import MoonshotPick
    from backend.services.notifier import TelegramNotifier, format_moonshot_alert

    skip_slow = os.environ.get("MOONSHOT_SKIP_SLOW", "0") == "1"
    limit = int(os.environ.get("WATCHLIST_LIMIT", "0"))
    logger.info(f"[moonshot] start skip_slow={skip_slow} limit={limit or 'all'}")
    today = datetime.now().strftime("%Y-%m-%d")
    universe = await _load_dry_run_universe()
    if limit:
        universe = universe[:limit]
    clients = await _enter_clients(_build_clients())

    try:
        picks = await run_moonshot_picks(
            universe, clients, top_n=MOONSHOT_TOP_N, skip_slow=skip_slow,
        )
    finally:
        await _exit_clients(clients)

    # close_price=0 fallback fetch
    picks = await _fill_missing_prices(picks)

    # 3 가격대도 fallback 후 재계산 (current_price 가 업데이트됐으므로)
    from dataclasses import replace as _replace
    for i, p in enumerate(picks):
        if p.buy_price_market == 0 and p.current_price > 0:
            picks[i] = _replace(
                p,
                buy_price_market=p.current_price,
                buy_price_limit_3pct=round(p.current_price * 0.97, 4),
                buy_price_limit_7pct=round(p.current_price * 0.93, 4),
            )

    # DB 저장 — 같은 pick_date 이전 row 삭제 후 insert (중복 방지)
    from sqlalchemy import delete as _delete
    async with get_session() as session:
        await session.execute(_delete(MoonshotPick).where(MoonshotPick.pick_date == today))
        for p in picks:
            fs = p.factor_scores
            row = MoonshotPick(
                pick_date=today,
                rank=p.rank,
                ticker=p.ticker,
                company_name=p.company_name,
                sector=p.sector,
                market_cap=p.market_cap_usd,
                current_price=p.current_price,
                score_volatility=fs.volatility,
                score_catalyst=fs.catalyst,
                score_squeeze=fs.squeeze,
                score_social=fs.social,
                score_news=fs.news_llm,
                score_technical=fs.technical,
                score_gap_volume=fs.gap_volume,
                score_low_rebound=fs.low_52w,
                score_insider=fs.insider,
                composite_score=p.total_score,
                buy_price_a=p.buy_price_market,
                buy_price_b=p.buy_price_limit_3pct,
                buy_price_c=p.buy_price_limit_7pct,
                target_sell_multiplier=2.0,
                stop_loss_multiplier=0.5,
                time_stop_days=5,
                market_cap_category=p.risk_level,  # HIGH/MED/LOW
                risk_level=p.risk_level,
                manipulation_risk=p.manipulation_risk,
                thesis=p.thesis,
                catalysts=json.dumps(p.catalysts, ensure_ascii=False),
                risks=json.dumps(p.risks, ensure_ascii=False),
                news_summary=p.news_summary,
            )
            session.add(row)
        await session.commit()
    logger.info(f"[moonshot] saved {len(picks)} picks to DB")

    # Telegram
    if picks:
        title, body = format_moonshot_alert(picks)
        notifier = TelegramNotifier()
        await notifier.send_info(title, body)
    return len(picks)


# ─────────────────────────────────────────────
# Cron job wrappers (exception swallow)
# ─────────────────────────────────────────────


async def job_universe_refresh():
    try:
        await run_universe_refresh()
    except Exception as e:
        logger.error(f"[cron] universe refresh failed: {e}", exc_info=True)


async def job_crazy_picks():
    try:
        await run_crazy_picks_job()
    except Exception as e:
        logger.error(f"[cron] crazy picks failed: {e}", exc_info=True)


async def job_moonshot_picks():
    try:
        await run_moonshot_picks_job()
    except Exception as e:
        logger.error(f"[cron] moonshot picks failed: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Sector Leaders Top 매력도 알림 (KRX, 일 2회)
# ─────────────────────────────────────────────


async def run_sector_leaders_alert_job(slot: str = "default") -> int:
    """Sector Leaders Top 매력도 알림 — Top N 발송.

    Logic:
        1) compute_top10(session, top_n=10) — 매력도 정렬 Top 10
        2) ≥0.6 항목 추출 — 6개 이상이면 그대로, 5개 이하면 ≥0.5 까지 확장
        3) 매력도 상위 SECTOR_LEADERS_TOP_N (=3) 컷 + rank 재계산
        4) format_sector_leaders_alert → Telegram send_info
    """
    from dataclasses import replace as _replace

    from backend.discovery.sector_leaders.top10 import compute_top10
    from backend.services.db import get_session
    from backend.services.notifier import (
        TelegramNotifier,
        format_sector_leaders_alert,
    )

    logger.info(f"[sector_leaders_alert] start slot={slot}")

    async with get_session() as session:
        items = await compute_top10(session, top_n=10)

    high = [i for i in items if i.attractiveness >= 0.6]
    if len(high) >= 6:
        candidates = high
        bucket = "0.6"
        expanded = False
    else:
        candidates = [i for i in items if i.attractiveness >= 0.5]
        bucket = "0.5"
        expanded = True

    picks = candidates[:SECTOR_LEADERS_TOP_N]
    picks = [_replace(p, rank=i + 1) for i, p in enumerate(picks)]

    if not picks:
        bucket = "empty"

    title, body = format_sector_leaders_alert(picks, bucket, expanded=expanded)
    notifier = TelegramNotifier()
    await notifier.send_info(title, body)

    logger.info(
        f"[sector_leaders_alert] slot={slot} sent={len(picks)} bucket={bucket}"
    )
    return len(picks)


async def job_sector_leaders_alert_0905():
    try:
        await run_sector_leaders_alert_job(slot="09:05")
    except Exception as e:
        logger.error(f"[cron] sector_leaders 09:05 failed: {e}", exc_info=True)


async def job_sector_leaders_alert_1705():
    try:
        await run_sector_leaders_alert_job(slot="17:05")
    except Exception as e:
        logger.error(f"[cron] sector_leaders 17:05 failed: {e}", exc_info=True)


# ─────────────────────────────────────────────
# VIP 감시 (밈주 워치 P-A · 종목 파라미터화 · 2026-07-08)
# 상세: docs/plans/meme-stock-discovery/05-wen-vip-watch.md
# ─────────────────────────────────────────────


async def job_vip_price_regular():
    """미 정규장 30초 폴러. 정규장 아니면 skip (AH job 담당)."""
    from backend.discovery.vip.vip_watch import (
        is_us_regular_hours,
        run_price_tick,
    )

    if not is_us_regular_hours():
        return
    try:
        result = await run_price_tick()
        if not result.get("skipped"):
            sent = result.get("sent") or []
            if sent:
                logger.info(
                    f"[cron.vip.price.regular] sent={sent} "
                    f"pnl={result.get('pnl'):+.4f}"
                )
    except Exception as e:
        logger.error(f"[cron.vip.price.regular] failed: {e}", exc_info=True)


async def job_vip_price_after():
    """정규장 외(AH·PM·주말·마감) 300초 폴러. 정규장이면 skip."""
    from backend.discovery.vip.vip_watch import (
        is_us_regular_hours,
        run_price_tick,
    )

    if is_us_regular_hours():
        return
    try:
        result = await run_price_tick()
        if not result.get("skipped"):
            sent = result.get("sent") or []
            if sent:
                logger.info(
                    f"[cron.vip.price.after] sent={sent} "
                    f"pnl={result.get('pnl'):+.4f}"
                )
    except Exception as e:
        logger.error(f"[cron.vip.price.after] failed: {e}", exc_info=True)


async def job_vip_activist():
    """SEC EDGAR activist 필링 폴러 — 5분 간격. env 미설정 시 tick 내부에서 skip."""
    from backend.discovery.vip.vip_watch import run_activist_tick

    try:
        result = await run_activist_tick()
        if not result.get("skipped") and result.get("sent"):
            logger.info(
                f"[cron.vip.activist] sent acc={result.get('accession')} "
                f"form={result.get('form')}"
            )
    except Exception as e:
        logger.error(f"[cron.vip.activist] failed: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Activist Radar (2026-07-09~) — 헤지펀드 경영권 매수 초기 신호
# 기획: docs/plans/activist-radar/
# ─────────────────────────────────────────────


async def job_activist_us():
    """미국 SC 13D/G 폴러 (Phase A) — 5분 간격. Universe 22 CIK 순회."""
    from backend.discovery.activist.radar import run_us_tick

    try:
        result = await run_us_tick()
        if result.get("backfill"):
            logger.info(f"[cron.activist.us] baseline set · detected={result.get('detected')}")
            return
        recent = result.get("recent_processed", 0)
        sent = result.get("sent", 0)
        if recent or sent:
            logger.info(
                f"[cron.activist.us] recent={recent} sent={sent} "
                f"stale_marked={result.get('stale_marked', 0)}"
            )
    except Exception as e:
        logger.error(f"[cron.activist.us] failed: {e}", exc_info=True)


# ─────────────────────────────────────────────
# Scheduler + entry
# ─────────────────────────────────────────────


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(job_universe_refresh, CronTrigger(hour=6, minute=0),
                      id="universe_refresh", name="Universe 갱신", replace_existing=True)
    scheduler.add_job(job_crazy_picks, CronTrigger(hour=6, minute=30),
                      id="crazy_picks", name="Crazy Picks 06:30 KST", replace_existing=True)
    scheduler.add_job(job_moonshot_picks, CronTrigger(hour=16, minute=50),
                      id="moonshot_picks", name="Moonshot Picks 16:50 KST", replace_existing=True)
    scheduler.add_job(job_sector_leaders_alert_0905, CronTrigger(hour=9, minute=5),
                      id="sector_leaders_alert_0905",
                      name="Sector Leaders Top — 09:05 KST (개장 안정)",
                      replace_existing=True)
    scheduler.add_job(job_sector_leaders_alert_1705, CronTrigger(hour=17, minute=5),
                      id="sector_leaders_alert_1705",
                      name="Sector Leaders Top — 17:05 KST (정규장 마감 후)",
                      replace_existing=True)
    # VIP 감시 (env VIP_ENABLED=true 일 때만 실효 — tick 내부에서 skip)
    scheduler.add_job(
        job_vip_price_regular,
        IntervalTrigger(seconds=30),
        id="vip_price_regular",
        name="VIP 정규장 30s 폴러",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_vip_price_after,
        IntervalTrigger(seconds=300),
        id="vip_price_after",
        name="VIP AH/PM 300s 폴러",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_vip_activist,
        IntervalTrigger(seconds=300),
        id="vip_activist",
        name="VIP Activist SEC 필링 폴러 (300s)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Activist Radar — 22 CIK 순회 (5분)
    scheduler.add_job(
        job_activist_us,
        IntervalTrigger(seconds=300),
        id="activist_us",
        name="Activist Radar US SC 13D/G 폴러 (300s)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


async def main_daemon():
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("[cron] Scheduler 시작 — 등록 job:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.id}: {job.name} → next {job.next_run_time}")

    stop = asyncio.Event()
    def _shutdown(*_):
        logger.info("[cron] Shutdown signal received")
        stop.set()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)
    await stop.wait()
    scheduler.shutdown(wait=True)
    logger.info("[cron] Shutdown complete")


async def main_once(target: str):
    if target == "universe":
        n = await run_universe_refresh()
        print(f"✅ Universe 갱신: {n}/{len(WATCHLIST)} 종목")
    elif target == "crazy":
        n = await run_crazy_picks_job()
        print(f"✅ Crazy Picks: Top {n} 저장 + Telegram 알림")
    elif target == "moonshot":
        n = await run_moonshot_picks_job()
        print(f"✅ Moonshot Picks: Top {n} 저장 + Telegram 알림")
    elif target == "sector_leaders":
        n = await run_sector_leaders_alert_job(slot="manual")
        print(f"✅ Sector Leaders Alert: Top {n} 발송")
    elif target == "vip_price":
        from backend.discovery.vip.vip_watch import run_price_tick

        result = await run_price_tick()
        print(f"✅ VIP price tick: {result}")
    elif target == "vip_activist":
        from backend.discovery.vip.vip_watch import run_activist_tick

        result = await run_activist_tick()
        print(f"✅ VIP activist tick: {result}")
    elif target == "vip_status":
        from backend.discovery.vip.vip_watch import get_status

        result = await get_status()
        print(f"✅ VIP status: {result}")
    elif target == "vip_config":
        from backend.discovery.vip.vip_watch import get_config

        result = get_config()
        print(f"✅ VIP config: {result}")
    elif target == "activist_us":
        from backend.discovery.activist.radar import run_us_tick

        result = await run_us_tick()
        print(f"✅ activist US tick: {result}")
    elif target == "activist_status":
        from backend.discovery.activist.radar import get_status

        result = await get_status()
        print(f"✅ activist status: universe={result.get('universe_size')}, events={result.get('events_total')}, buckets={ {k: len(v) for k,v in result['buckets'].items()} }")
    else:
        print(f"❌ unknown target: {target}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        choices=[
            "universe", "crazy", "moonshot", "sector_leaders",
            "vip_price", "vip_activist", "vip_status", "vip_config",
            "activist_us", "activist_status",
        ],
        help="1회 즉시 실행 (수동 검증). 미지정 시 데몬 모드.",
    )
    args = parser.parse_args()

    if args.once:
        asyncio.run(main_once(args.once))
    else:
        asyncio.run(main_daemon())
