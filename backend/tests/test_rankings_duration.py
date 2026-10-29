"""1029-03 · 순위 폴러 duration (토스 명세: TOP_GAINERS 는 realtime 미지원)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self):
        self.calls = []

    def rankings(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(result={"rankings": []})


@pytest.mark.asyncio
async def test_top_gainers_uses_1d_others_realtime():
    from backend.discovery.live_tape.rankings import poll_rankings
    from backend.services.db import init_db

    await init_db()
    fake = _FakeClient()
    stats = await poll_rankings(toss_client=fake)

    by_type = {c["type"]: c["duration"] for c in fake.calls}
    assert by_type == {
        "MARKET_TRADING_AMOUNT": "realtime",
        "TOP_GAINERS": "1d",
        "MARKET_TRADING_VOLUME": "realtime",
    }
    assert stats["saved"] == 0
