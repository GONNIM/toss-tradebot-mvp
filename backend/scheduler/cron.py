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
    """모든 async-context 클라이언트 동시 진입."""
    for name, c in list(clients.items()):
        if hasattr(c, "__aenter__"):
            await c.__aenter__()
    return clients


async def _exit_clients(clients: dict) -> None:
    """모든 클라이언트 graceful close."""
    for c in clients.values():
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

    # DB 저장
    async with get_session() as session:
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
    logger.info(f"[crazy] saved {len(picks)} picks to DB")

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

    # DB 저장 — Decision 33 (3 가격대) + Decision 34 (target/stop/time) + Decision 40 (위험)
    async with get_session() as session:
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
    else:
        print(f"❌ unknown target: {target}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", choices=["universe", "crazy", "moonshot"],
                        help="1회 즉시 실행 (수동 검증). 미지정 시 데몬 모드.")
    args = parser.parse_args()

    if args.once:
        asyncio.run(main_once(args.once))
    else:
        asyncio.run(main_daemon())
