"""P7-1d 공정위 대기업집단 테스트."""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.collectors import ftc_big_biz as ftc
from backend.powderkeg.collectors.big_biz_seed import BIG_BIZ_GROUPS_2026
from backend.services.db import get_session, init_db
from backend.services.models import BigBusinessGroup


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(BigBusinessGroup))
    yield


@pytest.mark.asyncio
async def test_refresh_from_seed_loads_2026_groups():
    stats = await ftc.refresh_from_seed(2026)
    assert stats["year"] == 2026
    # seed 에 20+ 그룹 · 각 그룹 대표 계열사 최소 1개
    total_expected = sum(len(affiliates) for _, affiliates in BIG_BIZ_GROUPS_2026)
    assert stats["inserted"] == total_expected


@pytest.mark.asyncio
async def test_refresh_from_seed_replaces_previous_year_data():
    """같은 year 두 번 호출 · 기존 삭제 후 재적재."""
    await ftc.refresh_from_seed(2026)
    stats2 = await ftc.refresh_from_seed(2026)
    assert stats2["deleted"] > 0
    total_expected = sum(len(affiliates) for _, affiliates in BIG_BIZ_GROUPS_2026)
    assert stats2["inserted"] == total_expected


@pytest.mark.asyncio
async def test_is_big_biz_group_true_for_seeded_ticker():
    await ftc.refresh_from_seed(2026)
    # 삼성전자 · 삼성 소속
    assert await ftc.is_big_biz_group("005930", 2026) is True
    # SK하이닉스 · SK 소속
    assert await ftc.is_big_biz_group("000660", 2026) is True


@pytest.mark.asyncio
async def test_is_big_biz_group_false_for_non_seeded_ticker():
    await ftc.refresh_from_seed(2026)
    # 알테오젠 · 대기업집단 아님 (예상)
    assert await ftc.is_big_biz_group("196170", 2026) is False


@pytest.mark.asyncio
async def test_resolve_group_returns_group_name():
    await ftc.refresh_from_seed(2026)
    assert await ftc.resolve_group("005930", 2026) == "삼성"
    assert await ftc.resolve_group("005380", 2026) == "현대자동차"


@pytest.mark.asyncio
async def test_resolve_group_returns_none_for_unaffiliated():
    await ftc.refresh_from_seed(2026)
    assert await ftc.resolve_group("196170", 2026) is None


@pytest.mark.asyncio
async def test_list_all_returns_sorted():
    await ftc.refresh_from_seed(2026)
    lst = await ftc.list_all(2026)
    assert len(lst) > 20
    # 정렬 확인 · group_name asc
    groups = [x["group_name"] for x in lst]
    assert groups == sorted(groups)
