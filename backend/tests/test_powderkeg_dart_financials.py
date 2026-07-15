"""P7-1b DART 재무제표 수집기 단위 테스트.

- account_id 매칭 (K-IFRS 표준)
- account_nm 키워드 fallback
- 총차입금 합산 로직
- BS vs IS 항목 분리
- CFS → OFS fallback
- 정정 재보고 (release_date 최신 우선)
- 감사의견 통합
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DART_API_KEY", "test_key_stub")

from backend.discovery.data_sources.dart.client import (
    DartAuditOpinion,
    DartFinancialItem,
)
from backend.powderkeg.collectors import dart_financials as df
from backend.powderkeg.collectors.dart_financials import (
    ParsedFinancials,
    collect_financial_snapshot,
    parse_financial_items,
)
from backend.services.db import get_session, init_db
from backend.services.models import FinancialSnapshot


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(FinancialSnapshot))
    yield


def _mk(account_id, account_nm, sj_div, amount, fs_div="CFS"):
    return DartFinancialItem(
        account_id=account_id, account_nm=account_nm,
        sj_div=sj_div, fs_div=fs_div, fs_nm="연결재무제표",
        thstrm_amount=amount, frmtrm_amount=None, ord=1,
    )


# ─── parser 단위 테스트 ────────────────────────
def test_parse_by_account_id():
    items = [
        _mk("ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "BS", 100),
        _mk("ifrs-full_Equity", "자본총계", "BS", 500),
        _mk("ifrs-full_ProfitLoss", "당기순이익", "IS", 30),
    ]
    p = parse_financial_items(items)
    assert p.cash_and_equivalents == 100
    assert p.total_equity == 500
    assert p.net_income == 30


def test_parse_by_name_keyword_fallback():
    """account_id 비어있어도 한글명 매칭."""
    items = [
        _mk("", "현금및현금성자산", "BS", 100),
        _mk("", "단기금융상품", "BS", 50),
        _mk("", "이익잉여금", "BS", 200),
        _mk("", "영업이익", "IS", 20),
        _mk("", "이자수익", "IS", 5),
    ]
    p = parse_financial_items(items)
    assert p.cash_and_equivalents == 100
    assert p.short_term_investments == 50
    assert p.retained_earnings == 200
    assert p.operating_income == 20
    assert p.interest_income == 5


def test_parse_debt_sum():
    """총차입금 · 여러 계정 합산."""
    items = [
        _mk("", "단기차입금", "BS", 30),
        _mk("", "유동성장기차입금", "BS", 20),
        _mk("", "장기차입금", "BS", 50),
        _mk("", "매입채무", "BS", 100),   # 차입금 아님 · 제외
    ]
    p = parse_financial_items(items)
    assert p.total_debt == 100    # 30 + 20 + 50


def test_parse_bs_is_separation():
    """BS 항목이 IS 로 오분류되지 않아야."""
    items = [
        _mk("ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "IS", 999),   # IS 로 잘못 · 무시
        _mk("ifrs-full_CashAndCashEquivalents", "현금및현금성자산", "BS", 100),
    ]
    p = parse_financial_items(items)
    assert p.cash_and_equivalents == 100


def test_parse_empty():
    p = parse_financial_items([])
    assert p.total_equity is None
    assert p.matched_items == {}


# ─── collect_financial_snapshot 통합 ───────────
@pytest.mark.asyncio
async def test_collect_stores_and_upserts_on_recorrection(monkeypatch):
    """정정 재보고 · release_date 최신 값으로 갱신."""
    call_count = {"n": 0}

    async def _stub_fs(corp_code, bsns_year, reprt_code, fs_div="CFS"):
        call_count["n"] += 1
        if fs_div == "CFS":
            return [
                _mk("", "현금및현금성자산", "BS", 1000),
                _mk("", "자본총계", "BS", 5000),
                _mk("", "당기순이익", "IS", 300),
                _mk("", "이자수익", "IS", 20),
            ]
        return []

    async def _stub_op(corp_code, bsns_year, reprt_code="11011"):
        return DartAuditOpinion(bsns_year="2026", adtor="XX회계법인",
                                adt_reprt_opinion="적정",
                                emphs_matter=None, core_report_matter=None)

    monkeypatch.setattr(df, "fetch_financial_statement", _stub_fs)
    monkeypatch.setattr(df, "fetch_audit_opinion", _stub_op)

    r1 = await collect_financial_snapshot(
        ticker="005930", corp_code="00126380",
        bsns_year=2026, reprt_code="11011",
        release_date=datetime(2026, 3, 15, tzinfo=timezone.utc),
    )
    assert r1 is not None

    # 정정 재보고 · 더 최신 release_date
    r2 = await collect_financial_snapshot(
        ticker="005930", corp_code="00126380",
        bsns_year=2026, reprt_code="11011",
        release_date=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    assert r2 == r1   # 같은 row · UPDATE

    async with get_session() as session:
        stmt = select(FinancialSnapshot).where(FinancialSnapshot.ticker == "005930")
        rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1                        # unique 유지
    row = rows[0]
    # SQLite 저장 시 tzinfo 유실 · naive 비교
    assert row.release_date.replace(tzinfo=None) == datetime(2026, 5, 20)
    assert row.cash_and_equivalents == 1000
    assert row.audit_opinion == "적정"
    assert row.reference_date == "2026-12-31"
    assert row.report_code == "11011"


@pytest.mark.asyncio
async def test_collect_stale_release_ignored(monkeypatch):
    """오래된 release_date · 기존 값 유지."""
    async def _stub_fs(corp_code, bsns_year, reprt_code, fs_div="CFS"):
        return [
            _mk("", "자본총계", "BS", 5000),
            _mk("", "당기순이익", "IS", 300),
        ]

    async def _stub_op(*a, **kw):
        return None

    monkeypatch.setattr(df, "fetch_financial_statement", _stub_fs)
    monkeypatch.setattr(df, "fetch_audit_opinion", _stub_op)

    await collect_financial_snapshot(
        ticker="005930", corp_code="00126380",
        bsns_year=2026, reprt_code="11012",
        release_date=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )
    await collect_financial_snapshot(
        ticker="005930", corp_code="00126380",
        bsns_year=2026, reprt_code="11012",
        release_date=datetime(2026, 8, 1, tzinfo=timezone.utc),   # 이전 날짜
    )
    async with get_session() as session:
        rows = (await session.execute(select(FinancialSnapshot))).scalars().all()
    assert len(rows) == 1
    assert rows[0].release_date.replace(tzinfo=None) == datetime(2026, 8, 20)


@pytest.mark.asyncio
async def test_collect_cfs_fallback_to_ofs(monkeypatch):
    """CFS 미제출 → OFS 로 fallback."""
    async def _stub_fs(corp_code, bsns_year, reprt_code, fs_div="CFS"):
        if fs_div == "CFS":
            return []    # 연결 미제출
        return [
            _mk("", "자본총계", "BS", 200, fs_div="OFS"),
        ]

    async def _stub_op(*a, **kw):
        return None

    monkeypatch.setattr(df, "fetch_financial_statement", _stub_fs)
    monkeypatch.setattr(df, "fetch_audit_opinion", _stub_op)

    r = await collect_financial_snapshot(
        ticker="123456", corp_code="00999999",
        bsns_year=2026, reprt_code="11013",
    )
    assert r is not None
    async with get_session() as session:
        row = (await session.execute(select(FinancialSnapshot))).scalar_one()
    assert row.total_equity == 200
    assert row.reference_date == "2026-03-31"


@pytest.mark.asyncio
async def test_collect_returns_none_when_no_data(monkeypatch):
    async def _stub_fs(*a, **kw):
        return []
    async def _stub_op(*a, **kw):
        return None
    monkeypatch.setattr(df, "fetch_financial_statement", _stub_fs)
    monkeypatch.setattr(df, "fetch_audit_opinion", _stub_op)

    r = await collect_financial_snapshot(
        ticker="000001", corp_code="00000001",
        bsns_year=2026, reprt_code="11011",
    )
    assert r is None


@pytest.mark.asyncio
async def test_collect_batch_aggregates(monkeypatch):
    async def _stub_fs(corp_code, bsns_year, reprt_code, fs_div="CFS"):
        # A: 정상 · B: 빈 데이터 · C: 정상
        if corp_code == "A":
            return [_mk("", "자본총계", "BS", 100)]
        if corp_code == "B":
            return []
        if corp_code == "C":
            return [_mk("", "자본총계", "BS", 200)]
        return []

    async def _stub_op(*a, **kw):
        return None

    monkeypatch.setattr(df, "fetch_financial_statement", _stub_fs)
    monkeypatch.setattr(df, "fetch_audit_opinion", _stub_op)

    stats = await df.collect_batch(
        [("111", "A"), ("222", "B"), ("333", "C")],
        bsns_year=2026, reprt_code="11011",
    )
    assert stats["total"] == 3
    assert stats["collected"] == 2
    assert stats["empty"] == 1
    assert stats["failed"] == 0
