"""P7-1e 이벤트 수집기 · classifier + poller."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DART_API_KEY", "test_key_stub")

from backend.discovery.data_sources.dart.client import DartDisclosure
from backend.powderkeg.collectors import events as ev_mod
from backend.powderkeg.collectors.events import (
    classify_disclosure,
    poll_powderkeg_events,
)
from backend.services.db import get_session, init_db
from backend.services.models import PowderKegEvent


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(PowderKegEvent))
    yield


# ─── classifier 단위 테스트 ────────────────────
def test_classify_type_b_takes_precedence():
    """Type B 는 우선 · 횡령 감지 시 A 무시."""
    # 만약 제목에 A 와 B 키워드가 함께 있으면 B 반환
    result = classify_disclosure("최대주주 변경 및 횡령 혐의")
    assert result is not None
    event_type, kw = result
    assert event_type.startswith("B1")
    assert "횡령" in kw


def test_classify_type_a_stock_pledge():
    result = classify_disclosure("최대주주 등의 주식담보제공 계약 체결")
    assert result is not None
    event_type, _ = result
    assert event_type == "A3_stock_pledge"


def test_classify_type_a_inheritance():
    result = classify_disclosure("최대주주 별세에 따른 지분 상속")
    assert result is not None
    event_type, _ = result
    # 상속·별세 둘 다 A2 · 어떤 것이든 A2 로 매칭
    assert event_type.startswith("A2")


def test_classify_type_b_audit_negative():
    result = classify_disclosure("감사의견 부적정 · 상장적격성 실질심사 대상")
    assert result is not None
    event_type, _ = result
    # 감사의견·거래정지 두 B · 어느 하나 매칭
    assert event_type.startswith("B")


def test_classify_no_match():
    assert classify_disclosure("일반 실적 공시") is None
    assert classify_disclosure("") is None
    assert classify_disclosure("사업보고서 제출") is None


def test_classify_capital_return():
    result = classify_disclosure("자기주식 소각 결정 공시")
    assert result is not None
    event_type, _ = result
    assert event_type == "A5_capital_return"


# ─── poll_powderkeg_events 통합 테스트 ─────────
def _mk_disclosure(stock_code, rcept_no, title, rcept_dt="20260715"):
    return DartDisclosure(
        corp_code="00000001", corp_name="테스트",
        stock_code=stock_code, rcept_no=rcept_no,
        rcept_dt=rcept_dt, report_nm=title,
        pblntf_ty="B", corp_cls="Y",
    )


@pytest.mark.asyncio
async def test_poll_classifies_and_saves(monkeypatch):
    fake_list = [
        _mk_disclosure("005930", "20260715001", "최대주주 등의 주식담보제공 계약"),   # A3
        _mk_disclosure("000660", "20260715002", "횡령·배임 혐의발생"),                   # B1
        _mk_disclosure("035420", "20260715003", "일반 실적 공시"),                        # 무매칭
        _mk_disclosure("068270", "20260715004", "자기주식 소각 결정"),                   # A5
    ]

    async def _stub_fetch(bgn_de, end_de, pblntf_ty, only_listed=True):
        # 모든 타입 폴링에 같은 결과 반환 · 중복 dedup 검증
        return fake_list

    monkeypatch.setattr(ev_mod, "fetch_recent_disclosures", _stub_fetch)

    stats = await poll_powderkeg_events(lookback_days=1)
    # 4 타입 폴링 × 4 공시 = 16 fetched · 매칭 3 (A3+B1+A5) × 4 = 12 matched
    #   그러나 dedup (rcept_no) 으로 inserted 는 3
    assert stats["fetched"] == 16
    assert stats["matched"] == 12
    assert stats["inserted"] == 3
    assert stats["type_a"] == 2   # A3 + A5
    assert stats["type_b"] == 1

    async with get_session() as session:
        rows = (await session.execute(select(PowderKegEvent))).scalars().all()
    types = sorted([r.event_type for r in rows])
    assert types == ["A3", "A5", "B1"]


@pytest.mark.asyncio
async def test_poll_watched_tickers_filter(monkeypatch):
    fake_list = [
        _mk_disclosure("005930", "id1", "횡령·배임 혐의발생"),
        _mk_disclosure("000660", "id2", "횡령·배임 혐의발생"),
    ]

    async def _stub_fetch(bgn_de, end_de, pblntf_ty, only_listed=True):
        return fake_list

    monkeypatch.setattr(ev_mod, "fetch_recent_disclosures", _stub_fetch)

    stats = await poll_powderkeg_events(
        lookback_days=1, watched_tickers={"005930"},   # 000660 제외
    )
    async with get_session() as session:
        rows = (await session.execute(select(PowderKegEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].ticker == "005930"
    assert stats["inserted"] == 1


@pytest.mark.asyncio
async def test_poll_dedup_on_rerun(monkeypatch):
    """동일 rcept_no 재실행 · 두 번 저장 안됨."""
    fake_list = [_mk_disclosure("005930", "id-dup", "횡령·배임 혐의발생")]

    async def _stub_fetch(*a, **kw):
        return fake_list

    monkeypatch.setattr(ev_mod, "fetch_recent_disclosures", _stub_fetch)

    r1 = await poll_powderkeg_events(lookback_days=1)
    r2 = await poll_powderkeg_events(lookback_days=1)

    async with get_session() as session:
        rows = (await session.execute(select(PowderKegEvent))).scalars().all()
    assert len(rows) == 1        # 두 번째 poll 은 dedup
    assert r1["inserted"] == 1
    assert r2["inserted"] == 0


@pytest.mark.asyncio
async def test_poll_url_generated(monkeypatch):
    fake_list = [_mk_disclosure("005930", "20260715001", "횡령·배임 혐의발생")]

    async def _stub_fetch(*a, **kw):
        return fake_list

    monkeypatch.setattr(ev_mod, "fetch_recent_disclosures", _stub_fetch)
    await poll_powderkeg_events(lookback_days=1)

    async with get_session() as session:
        row = (await session.execute(select(PowderKegEvent))).scalar_one()
    assert "dart.fss.or.kr" in row.url
    assert "20260715001" in row.url
    assert row.release_date is not None
