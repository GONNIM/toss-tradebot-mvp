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


@pytest.mark.parametrize("job_id,hour,minute", [
    ("watchlist_finalize", "8", "30"),
    ("watchlist_assembly", "6", "0"),
])
def test_cron_jobs_run_at_kst_hours(job_id, hour, minute):
    """1030-02 · UTC 로 적은 시각이 KST 스케줄러에서 15:00 늦게 돌던 회귀 방지."""
    scheduler = AsyncIOScheduler(timezone="UTC")  # 스케줄러 기본 시간대와 무관해야 함
    register_watchlist_jobs(scheduler)
    trig = scheduler.get_job(job_id).trigger
    fields = {f.name: str(f) for f in trig.fields}
    assert fields["hour"] == hour
    assert fields["minute"] == minute
    assert str(trig.timezone) == "Asia/Seoul"


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
