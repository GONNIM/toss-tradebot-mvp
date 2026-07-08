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
    crazy,
    dashboard,
    logs,
    meme_watch,
    moonshot,
    positions,
    sector_leaders,
    settings,
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
