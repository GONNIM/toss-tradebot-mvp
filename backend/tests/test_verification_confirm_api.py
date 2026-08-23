"""confirm API 선승인 방지 검증 (gate-design-v1 §3-3 · 세션 B · 2026-08-23 보완).

핵심 검증:
  (a) pending 과 일치하는 태그 조합 제출 → 저장 성공
  (b) 불일치 조합 제출 → 400 · 미저장 (백지 승인 차단)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services import config  # noqa: F401
from backend.services.db import engine, get_session
from backend.services.models import (
    Base,
    PrinciplesResult,
    PrinciplesRun,
    PrinciplesVerificationConfirm,
)


@pytest.fixture(autouse=True)
async def _setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_pass_with_tags(ticker: str, tags: list[str]) -> int:
    """최신 run + PASS ticker + tags 시드. run_id 반환."""
    async with get_session() as s:
        now = datetime.now()
        run = PrinciplesRun(
            started_at=now - timedelta(minutes=5),
            finished_at=now - timedelta(minutes=1),
            trigger="test",
            charter_version="1.0.9",
            universe_size=832,
            pass_count=1,
        )
        s.add(run)
        await s.flush()
        s.add(PrinciplesResult(
            run_id=run.id,
            ticker=ticker,
            name="테스트",
            verdict="PASS",
            verification_tags=json.dumps(sorted(tags), ensure_ascii=False),
        ))
        await s.commit()
        return run.id


async def _client() -> AsyncClient:
    from backend.api.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_confirm_success_when_tags_match_pending():
    """(a) pending 과 일치 → 저장 성공."""
    run_id = await _seed_pass_with_tags("033530", ["single_quarter_outlier"])
    client = await _client()
    async with client:
        res = await client.post(
            "/api/v1/principles/verification/confirm",
            json={
                "ticker": "033530",
                "tags": ["single_quarter_outlier"],
                "confirmed_by": "test-user",
            },
        )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "confirmed"
    assert body["ticker"] == "033530"
    assert body["run_id_at_confirm"] == run_id
    # DB 저장 확인
    async with get_session() as s:
        from sqlalchemy import select
        rows = (await s.execute(
            select(PrinciplesVerificationConfirm)
            .where(PrinciplesVerificationConfirm.ticker == "033530")
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].confirmed_by == "test-user"


@pytest.mark.asyncio
async def test_confirm_rejects_when_tags_mismatch_and_no_save():
    """(b) 불일치 조합 제출 → 400 · 미저장 (백지 승인 차단)."""
    # 최신 run 에는 single_quarter_outlier 만 태깅
    await _seed_pass_with_tags("033530", ["single_quarter_outlier"])
    client = await _client()
    async with client:
        # 임의 조합 (2 태그) 선승인 시도 · 백지 승인 구멍 재현
        res = await client.post(
            "/api/v1/principles/verification/confirm",
            json={
                "ticker": "033530",
                "tags": ["single_quarter_outlier", "ttm_concentration"],
                "confirmed_by": "attacker",
            },
        )
    assert res.status_code == 400
    body = res.json()
    detail = body.get("detail", {})
    assert detail.get("error") == "tags_mismatch"
    # 현재 실제 태그 반환 (프론트 최신 재표시)
    assert detail.get("current_tags") == ["single_quarter_outlier"]
    # 미저장 확인
    async with get_session() as s:
        from sqlalchemy import select
        rows = (await s.execute(
            select(PrinciplesVerificationConfirm)
            .where(PrinciplesVerificationConfirm.ticker == "033530")
        )).scalars().all()
        assert len(rows) == 0, "불일치 조합인데 저장됨 · 백지 승인 구멍 · 심각"


@pytest.mark.asyncio
async def test_confirm_rejects_when_ticker_not_tagged_in_latest_run():
    """부차 · 최신 run 에서 미태깅 ticker 는 확인 불필요 · 400."""
    # ticker 없이 run 만 생성
    async with get_session() as s:
        s.add(PrinciplesRun(
            started_at=datetime.now() - timedelta(minutes=5),
            finished_at=datetime.now() - timedelta(minutes=1),
            trigger="test", charter_version="1.0.9",
            universe_size=832,
        ))
        await s.commit()
    client = await _client()
    async with client:
        res = await client.post(
            "/api/v1/principles/verification/confirm",
            json={"ticker": "005930", "tags": ["single_quarter_outlier"]},
        )
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "not_tagged"
