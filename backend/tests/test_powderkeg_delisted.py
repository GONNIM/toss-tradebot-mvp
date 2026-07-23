"""P2-1 · KIND 상장폐지 collector + 재무 백필 스토어 테스트.

파싱은 로컬 fixture 로 검증 · 실 HTTP 미의존.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.collectors.krx_delisted import (
    EXCLUDE_KEYWORDS,
    _is_transitional,
    _parse_delisted_html,
    list_backfill_candidates,
)
from backend.services.db import get_session, init_db
from backend.services.models import (
    PowderKegDelistedBackfillProgress,
    PowderKegDelistedIssue,
)


# 실 KIND delcompany.do 응답 발췌 (2026-07-23 실측)
DELISTED_FIXTURE = """
<table cellpadding="0" cellspacing="1" class="bbs_tb" border=1>
<tr>
    <th>번호</th><th>회사명</th><th>종목코드</th><th>폐지일자</th><th>폐지사유</th><th>비고</th>
</tr>
<tr>
    <td style="text-align:center;">393</td>
    <td>이엠네트웍스</td>
    <td style="mso-number-format:'@';text-align:center;">087730</td>
    <td style="text-align:center;">2021-10-08</td>
    <td>기업의 계속성 및 경영의 투명성 등 상장폐지기준 해당</td>
    <td></td>
</tr>
<tr>
    <td style="text-align:center;">392</td>
    <td>엠피씨플러스</td>
    <td style="mso-number-format:'@';text-align:center;">050540</td>
    <td style="text-align:center;">2023-05-08</td>
    <td>감사의견 거절(감사범위 제한)</td>
    <td></td>
</tr>
<tr>
    <td style="text-align:center;">391</td>
    <td>SK오션플랜트</td>
    <td style="mso-number-format:'@';text-align:center;">100090</td>
    <td style="text-align:center;">2023-04-19</td>
    <td>유가증권시장 상장</td>
    <td>SK오션플랜트</td>
</tr>
</table>
"""


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegDelistedIssue))
        await session.execute(delete(PowderKegDelistedBackfillProgress))
    yield


# ─────────────────────────────────────────────────────────────
# 파싱 · is_transitional 분류
# ─────────────────────────────────────────────────────────────


def test_parse_delisted_html_returns_all_rows():
    rows = _parse_delisted_html(DELISTED_FIXTURE)
    assert len(rows) == 3
    r0 = rows[0]
    assert r0["ticker"] == "087730"
    assert r0["corp_name"] == "이엠네트웍스"
    assert r0["delisted_date"] == "2021-10-08"
    assert r0["is_transitional"] is False
    # 이관성 (SK오션플랜트 · 유가증권시장 상장 이전)
    r_transitional = rows[2]
    assert r_transitional["ticker"] == "100090"
    assert r_transitional["is_transitional"] is True


def test_is_transitional_keywords_cover_edge_cases():
    for kw in EXCLUDE_KEYWORDS:
        assert _is_transitional(f"XXX {kw} YYY", None) is True
    assert _is_transitional("감사의견 거절", None) is False
    assert _is_transitional(None, None) is False


# ─────────────────────────────────────────────────────────────
# DB 스토어 · list_backfill_candidates 필터
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_candidates_excludes_transitional():
    async with get_session() as session:
        # 3 종목 · 2개 부실 · 1개 이관성
        session.add(PowderKegDelistedIssue(
            ticker="087730", corp_name="이엠네트웍스", market="KOSDAQ",
            delisted_date="2021-10-08", reason="상장폐지기준", is_transitional=False,
            snapshot_date="2026-07-23",
        ))
        session.add(PowderKegDelistedIssue(
            ticker="050540", corp_name="엠피씨플러스", market="KOSDAQ",
            delisted_date="2023-05-08", reason="감사의견 거절", is_transitional=False,
            snapshot_date="2026-07-23",
        ))
        session.add(PowderKegDelistedIssue(
            ticker="100090", corp_name="SK오션플랜트", market="KOSPI",
            delisted_date="2023-04-19", reason="유가증권시장 상장", is_transitional=True,
            snapshot_date="2026-07-23",
        ))
    candidates = await list_backfill_candidates()
    tickers = [c["ticker"] for c in candidates]
    assert "087730" in tickers
    assert "050540" in tickers
    assert "100090" not in tickers, "이관성 제외 필요"
    assert len(candidates) == 2


@pytest.mark.asyncio
async def test_backfill_candidates_returns_empty_when_no_snapshot():
    candidates = await list_backfill_candidates()
    assert candidates == []


@pytest.mark.asyncio
async def test_backfill_candidates_uses_latest_snapshot():
    async with get_session() as session:
        session.add(PowderKegDelistedIssue(
            ticker="AAA111", corp_name="OLD", market="KOSDAQ",
            snapshot_date="2026-01-01", is_transitional=False,
        ))
        session.add(PowderKegDelistedIssue(
            ticker="BBB222", corp_name="NEW", market="KOSDAQ",
            snapshot_date="2026-07-23", is_transitional=False,
        ))
    candidates = await list_backfill_candidates()
    tickers = [c["ticker"] for c in candidates]
    assert "BBB222" in tickers
    assert "AAA111" not in tickers, "최신 스냅샷만 선택되어야 함"


# ─────────────────────────────────────────────────────────────
# Progress 저장 · upsert 로직
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_progress_row_persist_and_resume():
    async with get_session() as session:
        session.add(PowderKegDelistedBackfillProgress(
            run_id="20260723-100000K",
            last_offset=0, total_candidates=236,
            inserted=0, errors=0, status="running",
        ))
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegDelistedBackfillProgress).where(
                PowderKegDelistedBackfillProgress.run_id == "20260723-100000K"
            )
        )).scalar_one()
        assert row.total_candidates == 236
        assert row.status == "running"
        # 재개 시 offset 갱신
        row.last_offset = 50
        row.inserted = 45
        row.status = "paused"
    async with get_session() as session:
        row2 = (await session.execute(
            select(PowderKegDelistedBackfillProgress).where(
                PowderKegDelistedBackfillProgress.run_id == "20260723-100000K"
            )
        )).scalar_one()
        assert row2.last_offset == 50
        assert row2.inserted == 45
        assert row2.status == "paused"
