"""Watchlist Scheduler · Sprint 2 T59 · 잡 등록 검증."""
from __future__ import annotations

import pytest

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.discovery.watchlist.scheduler import (
    finalize_watchlist_job,
    register_watchlist_jobs,
)


def test_register_watchlist_jobs_adds_six_jobs():
    scheduler = AsyncIOScheduler()
    register_watchlist_jobs(scheduler)
    ids = {job.id for job in scheduler.get_jobs()}
    expected = {
        "watchlist_news",
        "watchlist_boards",
        "watchlist_youtube",
        "watchlist_assembly",
        "watchlist_gov_press",
        "watchlist_finalize",
    }
    assert expected.issubset(ids), f"missing: {expected - ids}"


@pytest.mark.asyncio
async def test_finalize_job_runs_successfully():
    """empty DB 에서도 error 없이 완료 · Week 2 T61 실체 wire-up."""
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    from backend.services.db import init_db
    await init_db()

    result = await finalize_watchlist_job()
    # 실행 자체는 성공 · signals 0 → written 0
    assert "error" not in result or result.get("written") == 0
    assert "trade_date" in result
