"""1114-02: 스냅샷 bar_date 저장 · 열 추가 멱등."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from backend.discovery.meme_watch.volume_snapshot import _last_bar_date


def test_last_bar_date_from_index():
    df = pd.DataFrame({"Close": [1, 2]}, index=pd.to_datetime(["2026-11-12", "2026-11-13"]))
    assert _last_bar_date(df) == date(2026, 11, 13)


def test_last_bar_date_unknown():
    assert _last_bar_date(pd.DataFrame()) is None


@pytest.mark.asyncio
async def test_ensure_columns_idempotent_bar_date():
    from backend.services.db import engine, ensure_columns, init_db

    await init_db()
    await ensure_columns()
    await ensure_columns()
    async with engine.begin() as conn:
        cols = {r[1] for r in (await conn.execute(text("PRAGMA table_info(meme_volume_snapshot)"))).all()}
    assert "bar_date" in cols
