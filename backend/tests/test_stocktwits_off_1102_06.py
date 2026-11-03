"""1102-06: stocktwits 수집 기본 꺼짐 · 상태 "off" · 켜면 다시 등록."""
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.discovery.meme_watch import scheduler as ms


def _ids(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("MEME_STOCKTWITS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("MEME_STOCKTWITS_ENABLED", value)
    s = AsyncIOScheduler()
    ms.register_meme_jobs(s)
    return {j.id for j in s.get_jobs()}


def test_stocktwits_job_off_by_default(monkeypatch):
    ids = _ids(monkeypatch, None)
    assert "meme_social_stocktwits_5min" not in ids
    assert "meme_social_apewisdom_5min" in ids and "meme_social_trends_hourly" in ids


def test_stocktwits_job_back_on_with_env(monkeypatch):
    assert "meme_social_stocktwits_5min" in _ids(monkeypatch, "1")


@pytest.mark.asyncio
async def test_sources_status_reports_off(monkeypatch):
    monkeypatch.delenv("MEME_STOCKTWITS_ENABLED", raising=False)
    from backend.api.routes.meme_watch import _sources_status
    from backend.services.db import init_db

    await init_db()

    st = await _sources_status()
    assert st["stocktwits"] == "off"
    assert st["apewisdom"] in ("ok", "blocked")
