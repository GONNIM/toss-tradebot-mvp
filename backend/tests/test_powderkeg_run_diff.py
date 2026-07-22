"""P4-1 · Run/RunDiff 모델·diff 계산·API 통합 테스트."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.screener import (
    _compute_diffs,
    _encode_value,
    _numeric_equal,
    _status_of,
)
from backend.services.db import get_session, init_db
from backend.services.models import (
    PowderKegList,
    PowderKegRun,
    PowderKegRunDiff,
)


TICKER = "999999"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegRunDiff))
        await session.execute(delete(PowderKegRun))
        await session.execute(delete(PowderKegList))
    yield


def _make_screen_result(**overrides):
    """ScreenResult-like namespace (typed 아님 · 필드만 매칭)."""
    base = dict(
        ticker=TICKER,
        status="passed",
        conditions={
            "1_pbr": True, "2_net_cash_ratio": True,
            "3_owner_pct": True, "4_not_big_biz": True,
            "5_audit_opinion": True, "6_cash_reality": True,
            "7_operating_profit": True, "8_fscore": True,
            "9_adv60": True, "10_no_bad_history": True,
        },
        pbr=0.4,
        net_cash_ratio=0.5,
        owner_pct=0.6,
        piotroski_f_score=8,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ────────────────────────────────────────────────────────────────
# 순수 함수 · _status_of · _numeric_equal · _encode_value
# ────────────────────────────────────────────────────────────────


def test_status_of_mapping():
    assert _status_of(True) == "pass"
    assert _status_of(False) == "fail"
    assert _status_of(None) == "na"
    assert _status_of("passed") is None


def test_numeric_equal_precision():
    assert _numeric_equal(None, None) is True
    assert _numeric_equal(None, 0.1) is False
    assert _numeric_equal(0.123456, 0.123457) is True     # 5자리 반올림
    assert _numeric_equal(0.4, 0.45) is False


def test_encode_value_json_or_str():
    assert _encode_value(None) is None
    assert _encode_value(True) == "true"
    assert _encode_value(0.4) == "0.4"
    assert _encode_value("passed") == '"passed"'


# ────────────────────────────────────────────────────────────────
# _compute_diffs · 조합 케이스
# ────────────────────────────────────────────────────────────────


def test_diff_baseline_no_prev():
    """이전 스냅샷 없음 → 모든 조건이 신규 (prev=None, curr=현재 값)."""
    curr = _make_screen_result()
    diffs = _compute_diffs(prev=None, curr=curr)
    keys = {d["condition_key"] for d in diffs}
    # 조건 10개 + 서브스코어 4개 + tier 1개 = 15
    assert len(diffs) == 15
    assert "1_pbr" in keys
    assert "pbr" in keys
    assert "tier" in keys


def test_diff_no_change_skips():
    """이전 · 현재 완전 동일 → diff 없음."""
    curr = _make_screen_result()
    prev = SimpleNamespace(
        conditions_json=json.dumps({k: v for k, v in curr.conditions.items()}),
        pbr=curr.pbr,
        net_cash_ratio=curr.net_cash_ratio,
        owner_pct=curr.owner_pct,
        piotroski_f_score=curr.piotroski_f_score,
        status=curr.status,
    )
    diffs = _compute_diffs(prev=prev, curr=curr)
    assert diffs == []


def test_diff_condition_status_change():
    """1_pbr True → False 만 변경 → 1_pbr 하나만 감지."""
    curr = _make_screen_result()
    curr.conditions = dict(curr.conditions)
    curr.conditions["1_pbr"] = False
    curr.status = "rejected"       # 통합 판정도 바뀜
    curr.pbr = 0.6                 # PBR 값도 바뀜 (임계 초과)

    prev_conds = {k: True for k in curr.conditions}
    prev = SimpleNamespace(
        conditions_json=json.dumps(prev_conds),
        pbr=0.4,
        net_cash_ratio=curr.net_cash_ratio,
        owner_pct=curr.owner_pct,
        piotroski_f_score=curr.piotroski_f_score,
        status="passed",
    )
    diffs = _compute_diffs(prev=prev, curr=curr)
    keys = [d["condition_key"] for d in diffs]
    # 1_pbr (조건 상태) + pbr (스코어) + tier
    assert "1_pbr" in keys
    assert "pbr" in keys
    assert "tier" in keys
    assert len(diffs) == 3

    pbr_cond_diff = next(d for d in diffs if d["condition_key"] == "1_pbr")
    assert pbr_cond_diff["prev_status"] == "pass"
    assert pbr_cond_diff["curr_status"] == "fail"

    tier_diff = next(d for d in diffs if d["condition_key"] == "tier")
    assert tier_diff["prev_value"] == "passed"
    assert tier_diff["curr_value"] == "rejected"


def test_diff_ignores_micro_numeric():
    """서브스코어 소수점 6자리 이하 미세 변화는 skip."""
    curr = _make_screen_result()
    curr.pbr = 0.4000001            # 6자리 · 반올림 5자리 → 동일
    prev = SimpleNamespace(
        conditions_json=json.dumps(curr.conditions),
        pbr=0.4,
        net_cash_ratio=curr.net_cash_ratio,
        owner_pct=curr.owner_pct,
        piotroski_f_score=curr.piotroski_f_score,
        status=curr.status,
    )
    diffs = _compute_diffs(prev=prev, curr=curr)
    assert diffs == []


# ────────────────────────────────────────────────────────────────
# DB · PowderKegRun / PowderKegRunDiff 삽입·조회
# ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_and_diff_persist_and_query():
    async with get_session() as session:
        session.add(PowderKegRun(
            run_id="20260722-120000K",
            ticker_count=5,
            trigger="manual",
            git_sha="abc1234",
        ))
        session.add(PowderKegRunDiff(
            run_id="20260722-120000K",
            ticker=TICKER,
            condition_key="tier",
            prev_value=_encode_value("rejected"),
            curr_value=_encode_value("passed"),
            prev_status="rejected",
            curr_status="passed",
        ))
        session.add(PowderKegRunDiff(
            run_id="20260722-120000K",
            ticker=TICKER,
            condition_key="1_pbr",
            prev_value=_encode_value(False),
            curr_value=_encode_value(True),
            prev_status="fail",
            curr_status="pass",
        ))

    async with get_session() as session:
        runs = (await session.execute(select(PowderKegRun))).scalars().all()
        assert len(runs) == 1
        assert runs[0].trigger == "manual"

        diffs = (await session.execute(
            select(PowderKegRunDiff).where(PowderKegRunDiff.ticker == TICKER)
        )).scalars().all()
        assert len(diffs) == 2
        keys = {d.condition_key for d in diffs}
        assert keys == {"tier", "1_pbr"}


# ────────────────────────────────────────────────────────────────
# API · FastAPI TestClient (경량 · 스키마 검증만)
# ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_diff_latest_and_summary_api():
    from fastapi.testclient import TestClient
    from backend.api.main import app

    async with get_session() as session:
        session.add(PowderKegList(
            run_id="20260722-120000K",
            ticker=TICKER,
            name="테스트종목",
            status="passed",
            conditions_json=json.dumps({"1_pbr": True}),
        ))
        session.add(PowderKegRun(
            run_id="20260722-120000K",
            ticker_count=1,
            trigger="manual",
        ))
        session.add(PowderKegRunDiff(
            run_id="20260722-120000K",
            ticker=TICKER,
            condition_key="tier",
            prev_value=_encode_value("rejected"),
            curr_value=_encode_value("passed"),
            prev_status="rejected",
            curr_status="passed",
        ))

    with TestClient(app) as client:
        r = client.get(f"/api/v1/powderkeg/run-diff/latest?ticker={TICKER}")
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == TICKER
        assert len(body["items"]) == 1
        assert body["items"][0]["condition_key"] == "tier"

        r2 = client.get("/api/v1/powderkeg/run-diff/summary")
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["run_id"] == "20260722-120000K"
        assert body2["total_changed_tickers"] == 1
        assert body2["tier_moved_count"] == 1
        assert body2["items"][0]["ticker"] == TICKER
        assert body2["items"][0]["tier_moved"] is True
