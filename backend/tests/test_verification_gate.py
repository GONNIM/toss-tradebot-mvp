"""VerificationChecker 게이트 테스트 (gate-design-v1 §3-3 · 세션 B).

핵심 검증:
  - tags 없음 → 즉시 통과
  - tags 있음 + 확인 없음 → verification_required 차단
  - tags 있음 + 매치 확인 있음 → 통과
  - tags 구성 변경 (신 배치) → hash 불일치 자동 실효 (재확인 요구)
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services import config  # noqa: F401
from backend.services.db import engine, get_session
from backend.services.models import (
    Base,
    PrinciplesVerificationConfirm,
)
from backend.execution.principles_gate import VerificationChecker
from backend.principles.verification_tagger import tags_hash


@pytest.fixture(autouse=True)
async def _setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_no_tags_passes_immediately():
    """태그 없음 → 즉시 통과."""
    r = await VerificationChecker().check(ticker="033530", tags=[])
    assert r.passed is True


@pytest.mark.asyncio
async def test_tags_present_no_confirm_blocks():
    """태그 있음 + 확인 없음 → verification_required 차단."""
    r = await VerificationChecker().check(
        ticker="033530",
        tags=["single_quarter_outlier"],
    )
    assert r.passed is False
    assert r.reason == "verification_required"
    assert r.tags_hash == tags_hash(["single_quarter_outlier"])


@pytest.mark.asyncio
async def test_tags_matched_confirm_allows():
    """태그 있음 + 매치 확인 저장 → 통과."""
    tags = ["single_quarter_outlier"]
    h = tags_hash(tags)
    async with get_session() as s:
        s.add(PrinciplesVerificationConfirm(
            ticker="033530",
            tags_hash=h,
            tags_json='["single_quarter_outlier"]',
            confirmed_by="test",
            run_id_at_confirm=1,
        ))
        await s.commit()
    r = await VerificationChecker().check(ticker="033530", tags=tags)
    assert r.passed is True


@pytest.mark.asyncio
async def test_tags_composition_changed_auto_invalidates():
    """CRITICAL · 태그 구성 변경 (신 배치) → hash 불일치 자동 실효.

    시나리오:
    1. 이전 배치: ticker 033530 · tags=[single_quarter_outlier] · 사용자 확인 완료
    2. 신 배치: ticker 033530 · tags=[single_quarter_outlier, ttm_concentration] (구성 변경)
    3. VerificationChecker(신 tags) → hash 불일치 → verification_required 차단
    """
    old_tags = ["single_quarter_outlier"]
    old_hash = tags_hash(old_tags)
    async with get_session() as s:
        # 이전 배치 확인 저장
        s.add(PrinciplesVerificationConfirm(
            ticker="033530",
            tags_hash=old_hash,
            tags_json='["single_quarter_outlier"]',
            confirmed_by="test-old-batch",
            run_id_at_confirm=13,
        ))
        await s.commit()
    # 신 배치 · 태그 구성 변경 (2개)
    new_tags = ["single_quarter_outlier", "ttm_concentration"]
    r = await VerificationChecker().check(ticker="033530", tags=new_tags)
    assert r.passed is False
    assert r.reason == "verification_required"
    assert r.tags_hash != old_hash
    assert r.tags_hash == tags_hash(new_tags)


@pytest.mark.asyncio
async def test_tags_same_composition_across_batches_stays_confirmed():
    """동일 구성 태그 · 여러 배치 (recompute) 걸쳐 확인 유지 (재확인 피로 방지).

    사용자 지시 (2026-08-23) · 이중키 (ticker, tags_hash) 로 run_id 무관.
    """
    tags = ["single_quarter_outlier"]
    h = tags_hash(tags)
    async with get_session() as s:
        s.add(PrinciplesVerificationConfirm(
            ticker="033530",
            tags_hash=h,
            tags_json='["single_quarter_outlier"]',
            confirmed_by="test-run-13",
            run_id_at_confirm=13,
        ))
        await s.commit()
    # run 14·15·16 시뮬레이션 · 태그 동일 · 확인 유지
    for _sim_run in range(14, 17):
        r = await VerificationChecker().check(ticker="033530", tags=tags)
        assert r.passed is True, f"run 시뮬레이션 {_sim_run} · 확인 실효 (버그)"


@pytest.mark.asyncio
async def test_different_ticker_same_tags_no_bypass():
    """다른 티커 · 동일 태그 구성 · 별건 확인 필요 (ticker 스코프 격리)."""
    tags = ["single_quarter_outlier"]
    h = tags_hash(tags)
    async with get_session() as s:
        s.add(PrinciplesVerificationConfirm(
            ticker="033530", tags_hash=h,
            tags_json='["single_quarter_outlier"]',
            confirmed_by="t", run_id_at_confirm=13,
        ))
        await s.commit()
    r = await VerificationChecker().check(ticker="016740", tags=tags)
    assert r.passed is False  # 다른 ticker · 확인 없음
