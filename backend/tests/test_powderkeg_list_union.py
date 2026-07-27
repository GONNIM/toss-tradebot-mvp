"""P2-3 · GET /list union_last_n_runs + run_screener 원자성/universe_type 정합 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import (
    PowderKegList,
    PowderKegRun,
    PowderKegRunDiff,
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegRunDiff))
        await session.execute(delete(PowderKegRun))
        await session.execute(delete(PowderKegList))
    yield


async def _seed_list_row(run_id: str, ticker: str, created_at: datetime, status: str = "passed",
                         nc: float = 0.5):
    import json as _json
    async with get_session() as session:
        session.add(PowderKegList(
            run_id=run_id, ticker=ticker,
            name=f"NAME-{ticker}", status=status,
            net_cash_ratio=nc,
            piotroski_f_score=6, owner_pct=0.5, pbr=0.3,
            conditions_json=_json.dumps({"1_pbr": True}),
            created_at=created_at,
        ))


# ─────────────────────────────────────────────────────────────
# GET /list · union_last_n_runs
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_union_last_n_default_1_backward_compat():
    """union_last_n_runs 미지정 · 기본 1 · 최신 run 만 반환."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    t0 = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_list_row("RUN-A", "111111", t0)
    await _seed_list_row("RUN-B", "222222", t0 + timedelta(seconds=25))

    with TestClient(app) as client:
        r = client.get("/api/v1/powderkeg/list")
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == "RUN-B"
        assert len(body["items"]) == 1
        assert body["items"][0]["ticker"] == "222222"
        assert body["union_last_n_runs"] == 1
        assert body["source_run_ids"] == ["RUN-B"]


@pytest.mark.asyncio
async def test_union_last_n_5_merges_multiple_runs():
    """union=5 · 최근 5 run 병합 · 서로 다른 ticker 모두 포함."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    t0 = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_list_row("RUN-A", "111111", t0, nc=0.9)
    await _seed_list_row("RUN-B", "222222", t0 + timedelta(seconds=25), nc=0.7)

    with TestClient(app) as client:
        r = client.get("/api/v1/powderkeg/list?union_last_n_runs=5")
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == "RUN-B"
        assert body["count"] == 2
        tickers = {i["ticker"] for i in body["items"]}
        assert tickers == {"111111", "222222"}
        assert set(body["source_run_ids"]) == {"RUN-A", "RUN-B"}


@pytest.mark.asyncio
async def test_union_duplicate_ticker_picks_latest():
    """동일 ticker 가 두 run 에 있으면 최신 run 채택."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    t0 = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_list_row("RUN-A", "111111", t0, status="rejected", nc=0.3)
    await _seed_list_row("RUN-B", "111111", t0 + timedelta(seconds=25), status="passed", nc=0.8)

    with TestClient(app) as client:
        r = client.get("/api/v1/powderkeg/list?union_last_n_runs=5")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        it = body["items"][0]
        assert it["ticker"] == "111111"
        assert it["status"] == "passed"
        assert it["net_cash_ratio"] == 0.8


@pytest.mark.asyncio
async def test_union_respects_explicit_run_id():
    """run_id 명시 시 · union 무시 · 그 run 만 조회."""
    from fastapi.testclient import TestClient
    from backend.api.main import app
    t0 = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    await _seed_list_row("RUN-A", "111111", t0)
    await _seed_list_row("RUN-B", "222222", t0 + timedelta(seconds=25))

    with TestClient(app) as client:
        r = client.get("/api/v1/powderkeg/list?run_id=RUN-A&union_last_n_runs=5")
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == "RUN-A"
        assert body["count"] == 1
        assert body["items"][0]["ticker"] == "111111"
        assert body["source_run_ids"] == ["RUN-A"]


@pytest.mark.asyncio
async def test_empty_returns_stable_shape():
    """DB 비어있어도 source_run_ids · union_last_n_runs 필드 존재."""
    from fastapi.testclient import TestClient
    from backend.api.main import app

    with TestClient(app) as client:
        r = client.get("/api/v1/powderkeg/list?union_last_n_runs=3")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["source_run_ids"] == []
        assert body["union_last_n_runs"] == 3


# ─────────────────────────────────────────────────────────────
# run_screener 원자성 · run_id 초 충돌 방어
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_screener_run_id_suffix_on_collision():
    """이미 존재하는 base run_id · -2 suffix 로 재시도 · IntegrityError 없음."""
    from backend.powderkeg.screener import run_screener
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _kst = _tz(_td(hours=9))
    base = _dt.now(tz=_kst).strftime("%Y%m%d-%H%M%SK")

    async with get_session() as session:
        session.add(PowderKegRun(run_id=base, trigger="test", ticker_count=0))
        await session.commit()

    stats = await run_screener([], universe_type="custom")
    assert stats["run_id"] != base
    assert stats["run_id"].startswith(base + "-")
    assert stats["universe_type"] == "custom"
    assert "universe_size" in stats
