"""FastAPI 진입점.

기동:
    uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

활성 라우트 (Phase A 주 2 · 2026-07-30):
    /api/v1/powderkeg          — 화약고 스크리너 (L2)
    /api/v1/sector-leaders     — 섹터별 주도주 (L2)
    /api/v1/meme-watch         — Meme Watch (L3 실험장 · UI /lab)
    /api/v1/meme-watch/vip     — VIP 감시 (L2 · meme_watch 내 서브라우트)
    /api/v1/meme-watch/activist — Activist Radar (L2 · meme_watch 내 서브라우트)
    /api/v1/watchlist          — Watchlist (L1)
    /api/v1/sniper             — 급등주 스나이퍼 (L1)
    /api/v1/positions          — 보유 종목 (Phase K 후 · L1)
    /api/v1/dashboard          — 자동매매 요약 (Phase K 후 · L1)
    /api/v1/logs               — 감사 로그 (L1)
    /api/v1/settings           — 관리자 설정
    /health                    — 헬스체크

이월 dead 라우트 (파일 유지 · include 제외):
    crazy · moonshot · super_signals · backtest · execution
    UI 는 /lab 인덱스로 재편 (프론트 layout.tsx 참조).
    admin/read prefix 이원화는 Stage 2 Judgment Journal 신설 시 함께.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import (
    dashboard,
    insights,
    judgments,
    logs,
    meme_watch,
    positions,
    powderkeg,
    principles,
    rulebook,
    sector_leaders,
    serenity,
    serenity_hunter,
    session,
    settings,
    sniper,
    watchlist,
    webhooks,
)
from backend.services import config
from backend.services.db import init_db

# Root logger 설정 · Python default = WARNING · info 메시지 유실 방지 (2026-08-03)
# uvicorn 이 자체 logger 를 갖지만 앱 코드의 logger.info() 는 별도 · 여기서 명시 설정.
# force=True · uvicorn --log-config 등 기존 handler 있어도 덮어씀.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 관측성 초기화 (Phase D 주 8 · 2026-07-31 · DSN 미설정 시 no-op)
    from backend.services.observability import init_sentry
    init_sentry()

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

    # Serenity Influencer 크론 (Phase L8 · 2026-08-02)
    # crawler 06:00 · scorer 08:00 · backtest 월 00:00 (extractor 는 z.ai 비용 · env 명시)
    from backend.discovery.serenity.scheduler import register_serenity_jobs
    register_serenity_jobs(scheduler)

    # Principles v1.0.2 크론 (2026-08-17)
    # weekly_detect (Sun 21:00 KST · DART 감지) + daily_recompute (23:00 · 캐시+시세)
    from backend.principles.scheduler import register_principles_jobs
    register_principles_jobs(scheduler)

    # Rulebook · Blue-Chip 5단계 스크리너 (Phase E+ · 2026-08-02)
    # 매일 22:30 KST · Powderkeg 22:00 이후 · 존마 강의 원칙 1
    if _os.environ.get("RULEBOOK_BLUECHIP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        from backend.rulebook.screener import run_blue_chip_screener

        async def _blue_chip_cron():
            try:
                result = await run_blue_chip_screener(trigger="cron")
                logger.info(
                    "[BlueChip] nightly done · run=%s · passed=%d/%d · %.1fs",
                    result["run_id"], result["passed"], result["universe_size"], result["elapsed_sec"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("[BlueChip] nightly 실패 · %s", exc)

        scheduler.add_job(
            _blue_chip_cron,
            "cron",
            hour=22, minute=30,
            id="blue_chip_screener_nightly",
            max_instances=1,
            coalesce=True,
        )
        logger.info("[FastAPI] Blue-Chip 5단계 스크리너 · 매일 22:30 KST nightly")

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


# 라우트 등록 (Phase A 주 2 · 2026-07-30 · dead 5개 include 제외)
# ── L1 매일 여정
app.include_router(judgments.router, prefix="/api/v1/judgments", tags=["judgments"])
app.include_router(positions.router, prefix="/api/v1/positions", tags=["positions"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(logs.router, prefix="/api/v1/logs", tags=["logs"])
app.include_router(sniper.router, prefix="/api/v1/sniper", tags=["sniper"])
app.include_router(watchlist.router, prefix="/api/v1/watchlist", tags=["watchlist"])
# ── L2 심층 (주말 리서치)
app.include_router(powderkeg.router, prefix="/api/v1/powderkeg", tags=["powderkeg"])
app.include_router(
    sector_leaders.router,
    prefix="/api/v1/sector-leaders",
    tags=["sector-leaders"],
)
# ── Insights (자산화 공개 · Stage 2 sync 소비)
app.include_router(insights.router, prefix="/api/v1/insights", tags=["insights"])
# ── Rulebook (Phase E · 2026-08-02 · 존마 강의 3원칙 이식 · L2 첫 항목)
app.include_router(rulebook.router, prefix="/api/v1/rulebook", tags=["rulebook"])
# ── Principles (2026-08-17 · v1.0 · 저평가 우량주 5원칙 헌장 + screener + gate)
app.include_router(principles.router, prefix="/api/v1/principles", tags=["principles"])
# ── Serenity Influencer (Phase L6 · 2026-08-02 · public read)
app.include_router(serenity.router, prefix="/api/v1/serenity", tags=["serenity"])
# ── Serenity Hunter (Phase L14 v6 · 2026-08-04 · Step A: /verification + /health · Step C: /hunter)
app.include_router(serenity_hunter.router, prefix="/api/v1/serenity", tags=["serenity-hunter"])
# ── L3 실험장 (UI 는 /lab 이관 · API 는 데이터 유지)
app.include_router(
    meme_watch.router,
    prefix="/api/v1/meme-watch",
    tags=["meme-watch"],
)
# ── 관리
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
# ── 관리자 세션 (Phase D 주 7 · 2026-07-31 · httpOnly 쿠키 이관)
app.include_router(session.router, prefix="/api/v1/admin/session", tags=["session"])
# ── Webhooks (Phase D 주 8 · 2026-07-31 · 결제 훅 스텁)
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
# ── 이월 dead (include 제외 · Phase A 주 2)
#    crazy · moonshot · super_signals · backtest · execution
#    파일은 backend/api/routes/ 에 유지 (참조·재활성 대비) · main 등록만 제거


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
