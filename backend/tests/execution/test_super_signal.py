"""Super Signal Contract Test — v2 트랙 C Phase 3.

- record_hit 삽입
- 30일 window 히트 병합
- 2+ source · intensity 임계 승격
- cooldown 24h 재승격 방지
- OCO body 조립 검증
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from backend.discovery.super_signal import (
    SOURCE_WEIGHTS,
    compute_intensity,
    promote_recent,
    record_hit,
)
from backend.services.db import get_session, init_db
from backend.services.models import SignalHit, SuperSignal


@pytest.fixture(autouse=True)
async def _clean_tables():
    """각 테스트 시작 전 signal_hit / super_signal 비움."""
    await init_db()
    async with get_session() as session:
        await session.execute(delete(SuperSignal))
        await session.execute(delete(SignalHit))
    yield
    async with get_session() as session:
        await session.execute(delete(SuperSignal))
        await session.execute(delete(SignalHit))


# ═══════════════════════════════════════════════════════════════
def test_source_weights_defined():
    assert SOURCE_WEIGHTS["activist"] == 3.0
    assert SOURCE_WEIGHTS["vip"] == 2.0
    assert SOURCE_WEIGHTS["meme_stock"] == 1.0


def test_compute_intensity_multi_source():
    hits = [
        {"source": "meme_stock", "score": 0.8},
        {"source": "vip", "score": 0.9},
        {"source": "activist", "score": 1.0},
    ]
    # 0.8×1 + 0.9×2 + 1.0×3 = 5.6
    assert compute_intensity(hits) == 5.6


def test_compute_intensity_unknown_source_weight_1():
    assert compute_intensity([{"source": "other", "score": 0.5}]) == 0.5


async def test_record_hit_persists():
    ok = await record_hit(
        ticker="WEN",
        source="meme_stock",
        signal_id="m-1",
        strength=80,
        action="buy",
    )
    assert ok is True
    async with get_session() as session:
        from sqlalchemy import select
        rows = (await session.execute(select(SignalHit))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ticker == "WEN"
    assert rows[0].score == 0.8


async def test_promote_single_source_no_promotion():
    await record_hit(ticker="WEN", source="meme_stock", signal_id="m-1", strength=80)
    promoted = await promote_recent()
    assert promoted == []


async def test_promote_two_sources_meets_threshold():
    await record_hit(ticker="WEN", source="meme_stock", signal_id="m-1", strength=80)
    await record_hit(ticker="WEN", source="activist", signal_id="a-1", strength=90)
    promoted = await promote_recent()
    assert len(promoted) == 1
    s = promoted[0]
    assert s.ticker == "WEN"
    # 0.8×1 + 0.9×3 = 3.5
    assert s.intensity == 3.5
    assert "meme_stock" in s.sources
    assert "activist" in s.sources


async def test_promote_two_sources_below_threshold():
    # 매우 낮은 강도 · intensity < 1.5 임계
    await record_hit(ticker="XYZ", source="meme_stock", signal_id="m-1", strength=10)
    await record_hit(ticker="XYZ", source="vip", signal_id="v-1", strength=20)
    promoted = await promote_recent()
    # 0.1×1 + 0.2×2 = 0.5 < 1.5 → 승격 안 됨
    assert promoted == []


async def test_promote_cooldown_prevents_duplicate():
    await record_hit(ticker="WEN", source="meme_stock", signal_id="m-1", strength=80)
    await record_hit(ticker="WEN", source="activist", signal_id="a-1", strength=90)

    p1 = await promote_recent()
    assert len(p1) == 1

    # 신규 히트 추가 후 재시도 — 24h cooldown 유효
    await record_hit(ticker="WEN", source="vip", signal_id="v-1", strength=70)
    p2 = await promote_recent()
    assert p2 == []


async def test_promote_only_buy_action():
    # sell 히트는 승격 대상 아님
    await record_hit(ticker="WEN", source="meme_stock", signal_id="m-1", strength=80, action="sell")
    await record_hit(ticker="WEN", source="activist", signal_id="a-1", strength=90, action="sell")
    promoted = await promote_recent()
    assert promoted == []


async def test_promote_metadata_contains_hits():
    import json as _json
    await record_hit(ticker="WEN", source="meme_stock", signal_id="m-1", strength=50)
    await record_hit(ticker="WEN", source="vip", signal_id="v-1", strength=90)
    promoted = await promote_recent()
    assert len(promoted) == 1
    meta = _json.loads(promoted[0].metadata_json)
    assert len(meta["hits"]) == 2
    assert set(h["source"] for h in meta["hits"]) == {"meme_stock", "vip"}


# ═══════════════════════════════════════════════════════════════
# Executor OCO body 조립 검증 (실 API 호출 없음)
# ═══════════════════════════════════════════════════════════════
def test_oco_price_rounding_kr():
    from backend.discovery.super_signal.executor import _round_price
    assert _round_price("005930", 286500.7) == "286501"
    assert _round_price("005930", 286500.0) == "286500"


def test_oco_price_rounding_us():
    from backend.discovery.super_signal.executor import _round_price
    assert _round_price("WEN", 7.5567) == "7.56"
    assert _round_price("WEN", 8.1) == "8.10"


def test_client_order_id_regex_compliance():
    import re
    from backend.discovery.super_signal.executor import _client_oco_id
    for _ in range(10):
        cid = _client_oco_id("WEN")
        assert re.match(r"^[a-zA-Z0-9_-]{1,36}$", cid)
