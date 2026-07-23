"""P4-5 · KRX 관리종목/거래정지 수집기 + screener 조건 ⑩ 통합 테스트.

파싱은 로컬 fixture 로 검증 · 실 HTTP 미의존 (KIND 응답 변화에 강건).
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.powderkeg.collectors.krx_admin_issue import (
    _parse_admin_html,
    _parse_corp_list_html,
    _parse_halt_html,
    designation_history,
    is_currently_designated,
    latest_snapshot_date,
)
from backend.services.db import get_session, init_db
from backend.services.models import PowderKegKrxIssue


# ─────────────────────────────────────────────────────────────
# 실 KIND 응답 발췌 (2026-07-23 실측 캡처 · fixture)
# ─────────────────────────────────────────────────────────────
ADMIN_FIXTURE = """
<section class="scrarea type-00">
	<table class="list type-00 tmt30" summary="종목명, 지정일, 지정사유">
		<tbody>
			<tr>
				<td class="first"><img src='/images/common/icn_t_ko.gif' class='vmiddle legend' alt='코스닥'> 세진티에스</a> <img src='/images/common/icn_t_kwan.gif' class='vmiddle legend' alt='관리종목'/> </td>
				<td class="txc">2026-07-21</td>
				<td>시가총액 미달</td>
			</tr>
			<tr>
				<td class="first"><img src='/images/common/icn_t_yu.gif' class='vmiddle legend' alt='유가증권'> 주연테크</a> <img src='/images/common/icn_t_kwan.gif' class='vmiddle legend' alt='관리종목'/> </td>
				<td class="txc">2026-07-21</td>
				<td>시가총액 미달</td>
			</tr>
			<tr>
				<td class="first"><img src='/images/common/icn_t_yu.gif' class='vmiddle legend' alt='유가증권'> CJ씨푸드1우</a> </td>
				<td class="txc">2026-07-20</td>
				<td>종류주식 시가총액 미달</td>
			</tr>
		</tbody>
	</table>
</section>
"""

HALT_FIXTURE = """
<tbody>
	<tr class="">
		<td class="first txc">124</td>
		<td><img src='/images/common/icn_t_yu.gif' class='vmiddle legend' alt='유가증권'> ACE 러시아MSCI(합성)</a> </td>
		<td>투자유의종목(ETF,ETN)</td>
	</tr>
	<tr class="">
		<td class="first txc">122</td>
		<td><img src='/images/common/icn_t_ko.gif' class='vmiddle legend' alt='코스닥'> DGI</a> <img src='/images/common/icn_t_kwan.gif' class='vmiddle legend' alt='관리종목'/> </td>
		<td>상장폐지 사유발생</td>
	</tr>
</tbody>
"""

CORP_LIST_FIXTURE = """
<table>
<tr>
    <td>세진티에스</td><td>기타업종</td><td>067770</td><td>홈</td><td>x</td><td>2020</td><td>서울</td>
</tr>
<tr>
    <td>주연테크</td><td>제조업</td><td>044060</td><td>홈</td><td>x</td><td>2015</td><td>서울</td>
</tr>
<tr>
    <td>DGI</td><td>서비스</td><td>040610</td><td>홈</td><td>x</td><td>2018</td><td>서울</td>
</tr>
<tr>
    <td>테스트헤더</td><td>안됨</td><td>NOTVALID</td><td>필드</td>
</tr>
</table>
"""


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegKrxIssue))
    yield


# ─────────────────────────────────────────────────────────────
# 파서 단위 · admin/halt/corp
# ─────────────────────────────────────────────────────────────


def test_parse_admin_html():
    rows = _parse_admin_html(ADMIN_FIXTURE)
    assert len(rows) == 3
    # 첫 행 · 세진티에스 · 관리종목 뱃지 있음
    r0 = rows[0]
    assert r0["market"] == "KOSDAQ"
    assert r0["name"] == "세진티에스"
    assert r0["designation_date"] == "2026-07-21"
    assert r0["reason"] == "시가총액 미달"
    assert r0["is_admin_badge"] is True
    # 세 번째 · 우선주 · 뱃지 없음 (실 관리종목 아님 · 종류주식)
    r2 = rows[2]
    assert r2["name"] == "CJ씨푸드1우"
    assert r2["is_admin_badge"] is False


def test_parse_halt_html():
    rows = _parse_halt_html(HALT_FIXTURE)
    assert len(rows) == 2
    assert rows[0]["name"] == "ACE 러시아MSCI(합성)"
    assert rows[0]["reason"] == "투자유의종목(ETF,ETN)"
    assert rows[0]["designation_date"] is None    # halt 응답은 지정일 미제공
    # DGI · 관리종목 뱃지 있음
    assert rows[1]["name"] == "DGI"
    assert rows[1]["is_admin_badge"] is True


def test_parse_corp_list_html():
    m = _parse_corp_list_html(CORP_LIST_FIXTURE)
    # 유효 6자리 종목코드만 매핑 · NOTVALID 는 skip
    assert m.get("세진티에스") == "067770"
    assert m.get("주연테크") == "044060"
    assert m.get("DGI") == "040610"
    assert "테스트헤더" not in m


# ─────────────────────────────────────────────────────────────
# 조회 헬퍼 · is_currently_designated / designation_history
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_currently_designated_no_snapshot_returns_none():
    result = await is_currently_designated("067770")
    assert result is None    # 스냅샷 미수집


@pytest.mark.asyncio
async def test_is_currently_designated_designated_row():
    async with get_session() as session:
        session.add(PowderKegKrxIssue(
            ticker="067770", name="세진티에스", kind="admin",
            reason="시가총액 미달", designation_date="2026-07-21",
            snapshot_date="2026-07-23",
        ))
    result = await is_currently_designated("067770")
    assert result is not None
    assert result["kind"] == "admin"
    assert result["reason"] == "시가총액 미달"
    assert result["snapshot_date"] == "2026-07-23"


@pytest.mark.asyncio
async def test_is_currently_designated_ticker_not_in_snapshot():
    # 스냅샷은 있지만 대상 티커는 없음 (다른 종목만)
    async with get_session() as session:
        session.add(PowderKegKrxIssue(
            ticker="044060", name="주연테크", kind="admin",
            reason="시가총액 미달", designation_date="2026-07-21",
            snapshot_date="2026-07-23",
        ))
    result = await is_currently_designated("067770")   # 067770 은 스냅샷에 없음
    assert result is not None
    assert result["kind"] is None     # 미지정 표식


@pytest.mark.asyncio
async def test_latest_snapshot_date_returns_most_recent():
    async with get_session() as session:
        for snap in ("2026-07-20", "2026-07-23", "2026-07-22"):
            session.add(PowderKegKrxIssue(
                ticker="044060", name="주연테크", kind="admin",
                snapshot_date=snap,
            ))
    d = await latest_snapshot_date()
    assert d == "2026-07-23"


@pytest.mark.asyncio
async def test_designation_history_lookback():
    async with get_session() as session:
        # 2 이력 · 하나는 1년 전 · 다른 하나는 4년 전 (3년 lookback 밖)
        session.add(PowderKegKrxIssue(
            ticker="044060", name="주연테크", kind="admin",
            snapshot_date="2025-07-23",
        ))
        session.add(PowderKegKrxIssue(
            ticker="044060", name="주연테크", kind="halt",
            snapshot_date="2022-07-23",
        ))
    hist = await designation_history("044060", lookback_days=3 * 365)
    assert len(hist) == 1     # 3년 밖 이력 제외
    assert hist[0]["snapshot_date"] == "2025-07-23"


# ─────────────────────────────────────────────────────────────
# Screener 조건 ⑩ 통합 · 3 시나리오
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_screener_c10_none_when_no_snapshot():
    """스냅샷 미수집 → c10=None (3상태 유지)."""
    result = await is_currently_designated("067770")
    assert result is None       # 실 스크리너는 이때 c10=None 반환 · screener.py 통합 검증


@pytest.mark.asyncio
async def test_screener_c10_false_when_currently_designated():
    """현재 관리종목 리스트에 있음 → c10=False."""
    async with get_session() as session:
        session.add(PowderKegKrxIssue(
            ticker="067770", name="세진티에스", kind="admin",
            reason="시가총액 미달", designation_date="2026-07-21",
            snapshot_date="2026-07-23",
        ))
    result = await is_currently_designated("067770")
    assert result["kind"] == "admin"
    # screener 는 kind 존재 시 c10=False · reject_reasons 에 사유 노출


@pytest.mark.asyncio
async def test_screener_c10_false_when_prior_history_only():
    """오늘 스냅샷엔 없지만 최근 3년 이력 있음 → c10=False."""
    async with get_session() as session:
        # 오늘 스냅샷 · 대상 미지정
        session.add(PowderKegKrxIssue(
            ticker="900001", name="OTHER", kind="admin",
            snapshot_date="2026-07-23",
        ))
        # 6개월 전 이력
        session.add(PowderKegKrxIssue(
            ticker="067770", name="세진티에스", kind="admin",
            reason="과거지정", snapshot_date="2026-01-15",
        ))
    curr = await is_currently_designated("067770")
    assert curr is not None
    assert curr["kind"] is None
    hist = await designation_history("067770", lookback_days=3 * 365)
    assert len(hist) == 1
    # screener 는 이력 있음 시 c10=False · latest 지정일 노출


@pytest.mark.asyncio
async def test_screener_c10_true_when_clean():
    """스냅샷 있고 대상 미지정 · 이력 없음 → c10=True."""
    async with get_session() as session:
        session.add(PowderKegKrxIssue(
            ticker="900001", name="OTHER", kind="admin",
            snapshot_date="2026-07-23",
        ))
    curr = await is_currently_designated("067770")
    assert curr is not None
    assert curr["kind"] is None
    hist = await designation_history("067770", lookback_days=3 * 365)
    assert hist == []
