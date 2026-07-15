"""P7-1f MajorShareholder 수집기 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DART_API_KEY", "test_key_stub")

from backend.discovery.data_sources.dart.client import (
    DartMajorShareholderRow,
    DartTreasuryStockRow,
)
from backend.powderkeg.collectors import dart_shareholders as ds
from backend.powderkeg.collectors.dart_shareholders import (
    _aggregate_shareholders,
    _aggregate_treasury,
    collect_batch,
    collect_shareholder_snapshot,
)
from backend.services.db import get_session, init_db
from backend.services.models import MajorShareholder


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(MajorShareholder))
    yield


def _row(nm, relate, pct, stock_knd="보통주"):
    return DartMajorShareholderRow(
        nm=nm, relate=relate, stock_knd=stock_knd,
        bsis_posesn_stock_co=None, bsis_posesn_stock_qota_rt=None,
        trmend_posesn_stock_co=None, trmend_posesn_stock_qota_rt=pct,
    )


def _tres(pct):
    return DartTreasuryStockRow(
        stock_knd="보통주", acqs_mth1="장내매수",
        stock_co=None, stock_pnc=pct,
    )


# ─── 집계 로직 단위 ─────────────────
def test_aggregate_본인_and_특수관계인():
    rows = [
        _row("영풍 회장", "본인", 35.0),           # 35%
        _row("배우자", "배우자", 5.0),
        _row("자녀", "자녀", 3.0),
        _row("계열사 A", "지주회사의 계열사", 4.0),
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.35)
    assert related == pytest.approx(0.12)   # 5+3+4=12%


def test_aggregate_보통주만_우선주_배제():
    """지주회사 · 오너 우선주 지분은 무시 (경영권 판단 표준)."""
    rows = [
        _row("회장", "본인", 20.0, stock_knd="보통주"),
        _row("회장", "본인", 25.0, stock_knd="우선주"),   # 무시
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.20)


def test_aggregate_holding_company_no_over_100():
    """지주회사 유형 시나리오 · 여러 특수관계인 · 우선주 중복 방지.

    이전 버그 · 우선주 중복 카운트 → 지분율 100%+.
    Fix · 보통주만 계산 → 정확.
    """
    rows = [
        _row("회장", "본인", 30.0, stock_knd="보통주"),
        _row("회장", "본인", 40.0, stock_knd="우선주"),   # 무시
        _row("배우자", "배우자", 5.0, stock_knd="보통주"),
        _row("배우자", "배우자", 8.0, stock_knd="우선주"),   # 무시
        _row("자녀A", "자녀", 3.0, stock_knd="보통주"),
        _row("자녀B", "자녀", 2.0, stock_knd="보통주"),
        _row("자녀A", "자녀", 5.0, stock_knd="우선주"),   # 무시
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.30)
    assert related == pytest.approx(0.10)   # 5+3+2=10% · 우선주 제외
    assert major + related <= 1.0            # 100% 이하 보장


def test_aggregate_missing_stock_knd_defaults_common():
    """오래된 보고서 · stock_knd 결측 시 보통주로 가정."""
    rows = [_row("회장", "본인", 40.0, stock_knd="")]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.40)


def test_aggregate_skips_summary_rows():
    """DART 응답의 "계" (합계) 행 skip · 중복 합산 방지 (효성 케이스 재현)."""
    rows = [
        _row("조현준", "본인", 41.02),
        _row("조현상", "친인척", 14.06),
        _row("(학)동양학원", "재단", 1.43),
        _row("계", "", 57.76),   # DART 합계 · skip 대상
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.4102)
    assert related == pytest.approx(0.1549, abs=0.001)   # 14.06 + 1.43 = 15.49
    assert major + related < 1.0    # 100% 이하 · "계" 중복 카운트 없음


def test_aggregate_skips_summary_row_변형():
    """"계" 외 · "합계" · "총계" · 공백 nm 도 skip."""
    for summary_nm in ("계", " 계 ", "합계", "총계", ""):
        rows = [
            _row("회장", "본인", 30.0),
            _row(summary_nm, "", 40.0),
        ]
        major, related = _aggregate_shareholders(rows)
        assert major == pytest.approx(0.30)
        assert related == pytest.approx(0.0), f"failed for nm={summary_nm!r}"


def test_aggregate_최대주주_relate_treated_as_major():
    """영풍 케이스 · relate="최대주주" 도 major 로 인정."""
    rows = [
        _row("장 세 준", "최대주주", 16.89),
        _row("장 세 환", "친인척", 11.83),
        _row("영풍개발㈜", "계열회사", 15.53),
        _row("영풍정밀㈜", "계열회사", 4.39),
        _row("계", "", 64.18),   # 합계 · skip
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.1689)
    assert related == pytest.approx(0.3175, abs=0.001)   # 11.83 + 15.53 + 4.39 = 31.75
    assert major + related < 1.0    # 정확한 개별 합


def test_aggregate_최대주주_본인_공백_포함():
    """삼성전자 · 알테오젠 케이스 · relate="최대주주 본인" (공백 있음)."""
    rows = [
        _row("삼성생명보험㈜", "최대주주 본인", 8.51),
        _row("홍라희", "최대주주의 특수관계인", 1.64),
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.0851)
    assert related == pytest.approx(0.0164)


def test_aggregate_의결권_있는_주식_공백():
    """SK하이닉스 케이스 · stock_knd="의결권 있는 주식" (공백 있음)."""
    rows = [
        _row("SK스퀘어㈜", "최대주주", 20.07, stock_knd="의결권 있는 주식"),
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.2007)


def test_aggregate_삼성전자_실_시나리오():
    """실 프로덕션 · 삼성전자 shareholders 재현."""
    rows = [
        _row("삼성생명보험㈜", "최대주주 본인", 8.51),
        _row("홍라희", "최대주주의 특수관계인", 1.64),
        _row("홍라희", "최대주주의 특수관계인", 0.03, stock_knd="우선주"),   # 배제
        _row("이재용", "최대주주의 특수관계인", 1.63),
        _row("이재용", "최대주주의 특수관계인", 0.02, stock_knd="우선주"),   # 배제
        _row("이부진", "계열회사 임원", 0.80),
        _row("이서현", "계열회사 임원", 0.79),
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.0851)
    # 관계인 합: 1.64 + 1.63 + 0.80 + 0.79 = 4.86%
    assert related == pytest.approx(0.0486, abs=0.001)


def test_aggregate_영풍_케이스_전체_시나리오():
    """실 프로덕션 데이터 재현 · 영풍 shareholders."""
    rows = [
        _row("장 세 준", "최대주주", 16.89),
        _row("최 윤 범", "계열회사 임원", 0.0),
        _row("유 중 근", "계열회사 임원", 0.21),
        _row("(재)경원문화재단", "공익법인", 0.76),
        _row("영풍개발㈜", "계열회사", 15.53),
        _row("영풍정밀㈜", "계열회사", 4.39),
        _row("씨케이(유)", "계열회사", 6.45),
        _row("에이치씨(유)", "계열회사", 1.38),
        _row("장 형 진", "친인척", 0.0),
        _row("장 세 환", "친인척", 11.83),
        _row("장 혜 선", "친인척", 0.52),
        _row("김 혜 경", "친인척", 0.05),
        _row("최 창 걸", "계열회사 임원", 0.27),
        _row("최 창 영", "계열회사 임원", 0.0),
        _row("최 창 근", "계열회사 임원", 3.04),
        _row("최 창 규", "계열회사 임원", 2.85),
        _row("계", "", 64.18),
    ]
    major, related = _aggregate_shareholders(rows)
    assert major == pytest.approx(0.1689)
    total = major + related
    # DART 합계 64.18% (미미한 반올림 허용)
    assert total == pytest.approx(0.6418, abs=0.005)


def test_aggregate_empty():
    assert _aggregate_shareholders([]) == (0.0, 0.0)


def test_aggregate_treasury():
    rows = [_tres(3.0), _tres(2.5)]
    assert _aggregate_treasury(rows) == pytest.approx(0.03)


def test_aggregate_treasury_empty():
    assert _aggregate_treasury([]) == 0.0


# ─── collect_shareholder_snapshot 통합 ───
@pytest.mark.asyncio
async def test_collect_stores_snapshot(monkeypatch):
    async def _stub_holders(corp_code, bsns_year, reprt_code):
        return [
            _row("회장", "본인", 40.0),
            _row("배우자", "배우자", 10.0),
        ]

    async def _stub_treasury(corp_code, bsns_year, reprt_code):
        return [_tres(3.0)]

    monkeypatch.setattr(ds, "fetch_major_shareholder_status", _stub_holders)
    monkeypatch.setattr(ds, "fetch_treasury_stock", _stub_treasury)

    r = await collect_shareholder_snapshot(
        "005930", "00126380", bsns_year=2025, reprt_code="11011",
        release_date=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )
    assert r is not None

    async with get_session() as session:
        row = (await session.execute(select(MajorShareholder))).scalar_one()
    assert row.ticker == "005930"
    assert row.reference_date == "2025-12-31"
    assert row.major_pct == pytest.approx(0.40)
    assert row.related_pct == pytest.approx(0.10)
    assert row.treasury_pct == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_collect_treasury_missing_ok(monkeypatch):
    """자기주식 API 실패 · major/related 만 저장."""
    async def _stub_holders(corp_code, bsns_year, reprt_code):
        return [_row("회장", "본인", 25.0)]

    async def _stub_treasury(corp_code, bsns_year, reprt_code):
        return []

    monkeypatch.setattr(ds, "fetch_major_shareholder_status", _stub_holders)
    monkeypatch.setattr(ds, "fetch_treasury_stock", _stub_treasury)

    r = await collect_shareholder_snapshot("005930", "00126380", bsns_year=2025)
    assert r is not None
    async with get_session() as session:
        row = (await session.execute(select(MajorShareholder))).scalar_one()
    assert row.major_pct == pytest.approx(0.25)
    assert row.treasury_pct is None


@pytest.mark.asyncio
async def test_collect_empty_returns_none(monkeypatch):
    async def _stub_holders(*a, **kw): return []
    async def _stub_treasury(*a, **kw): return []
    monkeypatch.setattr(ds, "fetch_major_shareholder_status", _stub_holders)
    monkeypatch.setattr(ds, "fetch_treasury_stock", _stub_treasury)

    r = await collect_shareholder_snapshot("999999", "00999999", bsns_year=2025)
    assert r is None


@pytest.mark.asyncio
async def test_collect_upsert_on_new_release(monkeypatch):
    async def _stub_holders(*a, **kw):
        return [_row("회장", "본인", 30.0)]
    async def _stub_treasury(*a, **kw): return []
    monkeypatch.setattr(ds, "fetch_major_shareholder_status", _stub_holders)
    monkeypatch.setattr(ds, "fetch_treasury_stock", _stub_treasury)

    r1 = await collect_shareholder_snapshot(
        "005930", "00126380", bsns_year=2025,
        release_date=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )
    r2 = await collect_shareholder_snapshot(
        "005930", "00126380", bsns_year=2025,
        release_date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert r1 == r2   # same row upserted

    async with get_session() as session:
        rows = (await session.execute(select(MajorShareholder))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_collect_batch_stats(monkeypatch):
    async def _stub_holders(corp_code, bsns_year, reprt_code):
        if corp_code == "A":
            return [_row("회장", "본인", 30.0)]
        if corp_code == "B":
            return []
        if corp_code == "C":
            return [_row("대표", "본인", 45.0)]
        return []
    async def _stub_treasury(*a, **kw): return []
    monkeypatch.setattr(ds, "fetch_major_shareholder_status", _stub_holders)
    monkeypatch.setattr(ds, "fetch_treasury_stock", _stub_treasury)

    stats = await collect_batch(
        [("111", "A"), ("222", "B"), ("333", "C")],
        bsns_year=2025,
    )
    assert stats["total"] == 3
    assert stats["collected"] == 2
    assert stats["empty"] == 1
    assert stats["failed"] == 0
