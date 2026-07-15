"""FastAPI 진입점.

기동:
    uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

라우트:
    /api/v1/crazy       — Crazy Picks Top 10
    /api/v1/moonshot    — Moonshot Picks Top 3
    /api/v1/positions   — 보유 종목 (Phase K 후)
    /api/v1/dashboard   — 자동매매 요약 (Phase K 후)
    /api/v1/settings    — 파라미터
    /api/v1/logs        — 감사 로그
    /health             — 헬스체크
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import (
    backtest,
    crazy,
    dashboard,
    execution,
    logs,
    meme_watch,
    moonshot,
    positions,
    powderkeg,
    sector_leaders,
    settings,
    sniper,
    super_signals,
    watchlist,
)
from backend.services import config
from backend.services.db import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 시작 시
    logger.info("[FastAPI] starting — init DB")
    await init_db()

    # APScheduler (B-2l) — sector_leaders 매월 잡 + meme_watch 주간 잡
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from backend.discovery.meme_watch.scheduler import register_meme_jobs
    from backend.discovery.sector_leaders.scheduler import register_monthly_jobs

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    register_monthly_jobs(scheduler)
    register_meme_jobs(scheduler)

    # Execution Layer — TossAdapter 사용 시 미체결 주문 30초 주기 reconcile (Phase 2)
    import os as _os
    if (
        _os.environ.get("EXECUTION_ENABLED", "").lower() in {"1", "true", "yes", "on"}
        and _os.environ.get("EXECUTION_BROKER", "paper").lower() == "toss"
    ):
        from backend.execution.reconciler import reconcile_pending_orders

        scheduler.add_job(
            reconcile_pending_orders,
            "interval",
            seconds=30,
            id="execution_reconcile",
            max_instances=1,
            coalesce=True,
        )
        logger.info("[FastAPI] Execution reconciler 30초 주기 · Toss 미체결 주문 폴링")

    # Super Signal — 5분 주기 승격 + OCO 실행 (Phase 3)
    if _os.environ.get("SUPER_SIGNAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        from backend.discovery.super_signal import promote_and_execute

        scheduler.add_job(
            promote_and_execute,
            "interval",
            minutes=5,
            id="super_signal_orchestration",
            max_instances=1,
            coalesce=True,
        )
        logger.info("[FastAPI] Super Signal 오케스트레이션 5분 주기 · 승격+OCO")

    # 급등주 스나이퍼 (Sprint 1) — 5단계 loop
    #   scan_and_enter 30초 · manage_positions 5초 · universe nightly 22:00 KST
    if _os.environ.get("SNIPER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        from backend.discovery.live_tape.sniper import register_sniper_jobs
        from backend.discovery.live_tape.universe import refresh_universe

        register_sniper_jobs(scheduler)
        scheduler.add_job(
            refresh_universe,
            "cron",
            hour=22, minute=0,
            id="sniper_universe_refresh",
            max_instances=1,
        )
        logger.info("[FastAPI] Sniper jobs 등록 완료 (기본 sniper.enabled=False · UI로 활성화)")

    # Watchlist 야간 신호 수집 (Sprint 2) — 뉴스·종토방·유튜브·국회·정부
    if _os.environ.get("WATCHLIST_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        from backend.discovery.watchlist.scheduler import register_watchlist_jobs

        register_watchlist_jobs(scheduler)
        logger.info("[FastAPI] Watchlist 야간 신호 수집 잡 등록 완료 (Sprint 2 Week 1)")

    # Powder Keg 이벤트 자동 감시 (Phase 7-3) — DART 폴링 30m + 액션 처리 5m
    if _os.environ.get("POWDERKEG_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        from backend.powderkeg.scheduler import register_powderkeg_jobs

        register_powderkeg_jobs(scheduler)
        logger.info("[FastAPI] Powder Keg 이벤트 자동 감시 잡 등록 완료 (Phase 7-3)")

    # WATCH 프로파일 배치 · 30분 요약 발송 (Phase 3 §6-2)
    if _os.environ.get("TELEGRAM_PROFILE", "SCOUT").upper() == "WATCH":
        from backend.services.notifier import Level, TelegramNotifier
        from backend.services.notifier_profile import flush_watch_batch

        _watch_notifier = TelegramNotifier()

        async def _flush_watch():
            # WATCH 배치는 profile 필터 우회 · force=True 로 직접 발송
            return await flush_watch_batch(
                lambda title, body: _watch_notifier.send(Level.INFO, title, body, force=True)
            )

        scheduler.add_job(
            _flush_watch,
            "interval",
            minutes=30,
            id="watch_batch_flush",
            max_instances=1,
            coalesce=True,
        )
        logger.info("[FastAPI] WATCH 프로파일 30분 배치 요약 잡 등록")

    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("[FastAPI] APScheduler started — sector_leaders(3) + meme_watch(1) jobs registered")

    yield
    # 종료 시
    scheduler.shutdown(wait=False)
    logger.info("[FastAPI] shutdown")


app = FastAPI(
    title="Toss Tradebot MVP API",
    version="0.1.0",
    description="자동매매 + Crazy + Moonshot Discovery API",
    lifespan=lifespan,
)

# CORS — Next.js 프론트엔드
# 허용 origin 은 CORS_ORIGINS 환경변수(쉼표 구분) 로 제어. 미설정 시 기본값 사용.
# 프론트 포트 변경 시 코드 수정 없이 .env 만 갱신 → 재기동으로 반영.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 라우트 등록
app.include_router(crazy.router, prefix="/api/v1/crazy", tags=["crazy"])
app.include_router(moonshot.router, prefix="/api/v1/moonshot", tags=["moonshot"])
app.include_router(positions.router, prefix="/api/v1/positions", tags=["positions"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(logs.router, prefix="/api/v1/logs", tags=["logs"])
app.include_router(
    sector_leaders.router,
    prefix="/api/v1/sector-leaders",
    tags=["sector-leaders"],
)
app.include_router(
    meme_watch.router,
    prefix="/api/v1/meme-watch",
    tags=["meme-watch"],
)
app.include_router(
    execution.router,
    prefix="/api/v1/execution",
    tags=["execution"],
)
app.include_router(
    super_signals.router,
    prefix="/api/v1/super-signals",
    tags=["super-signals"],
)
app.include_router(
    backtest.router,
    prefix="/api/v1/backtest",
    tags=["backtest"],
)
app.include_router(
    sniper.router,
    prefix="/api/v1/sniper",
    tags=["sniper"],
)
app.include_router(
    watchlist.router,
    prefix="/api/v1/watchlist",
    tags=["watchlist"],
)
app.include_router(
    powderkeg.router,
    prefix="/api/v1/powderkeg",
    tags=["powderkeg"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "toss-tradebot-mvp"}


@app.get("/")
async def root():
    return {
        "service": "Toss Tradebot MVP API",
        "version": "0.1.0",
        "docs": "/docs",
    }
