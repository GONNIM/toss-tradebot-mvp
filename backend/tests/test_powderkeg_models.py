"""Phase 7-1a · 모델 스캐폴드 · init_db 확인."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.services.db import get_session, init_db
from backend.services.models import (
    BigBusinessGroup,
    FinancialSnapshot,
    KrxMarketSnapshot,
    MajorShareholder,
    PowderKegEvent,
    PowderKegList,
    PowderKegOrderTicket,
)


@pytest.mark.asyncio
async def test_powderkeg_tables_create_and_ping():
    """전 6 테이블 create_all + 단건 insert/select."""
    await init_db()
    async with get_session() as session:
        session.add(FinancialSnapshot(
            ticker="005930", corp_code="00126380",
            reference_date="2026-06-30", release_date=__import__("datetime").datetime(2026, 8, 14),
            report_code="11012",
            cash_and_equivalents=100_000_000_000,
            short_term_investments=50_000_000_000,
            total_debt=30_000_000_000,
            total_equity=500_000_000_000,
            retained_earnings=400_000_000_000,
            operating_income=20_000_000_000,
            net_income=15_000_000_000,
            interest_income=1_500_000_000,
            audit_opinion="적정",
        ))
        session.add(KrxMarketSnapshot(
            ticker="005930", snapshot_date="2026-07-15",
            market="KOSPI", close_price=72700, market_cap=430_000_000_000_000,
            pbr=0.45, avg_daily_amount_60d=1_000_000_000_000,
        ))
        session.add(BigBusinessGroup(
            year=2026, group_name="삼성", corp_name="삼성전자", ticker="005930",
        ))
        session.add(MajorShareholder(
            ticker="005930", reference_date="2026-06-30",
            release_date=__import__("datetime").datetime(2026, 8, 14),
            major_pct=0.20, related_pct=0.15, treasury_pct=0.10,
        ))
        session.add(PowderKegList(
            run_id="20260715-100000", ticker="005930", name="삼성전자",
            status="rejected", net_cash_ratio=0.05, piotroski_f_score=7,
            owner_pct=0.35, pbr=0.45,
            reject_reasons="major_pct<0.4,big_biz_group",
        ))
        session.add(PowderKegEvent(
            ticker="005930", event_type="A3", source="dart",
            source_id="20260715001", title="최대주주 주식담보제공 계약",
            confidence=0.9,
        ))
        session.add(PowderKegOrderTicket(
            event_id=1, ticker="005930", proposed_qty=10,
            invalidation_price=70000.0,
            invalidation_logic="무혐의 확정",
        ))

    # readback
    from sqlalchemy import select
    async with get_session() as session:
        rows = (await session.execute(select(FinancialSnapshot))).scalars().all()
        assert len(rows) == 1 and rows[0].audit_opinion == "적정"

        rows = (await session.execute(select(PowderKegList))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "rejected"

        rows = (await session.execute(select(PowderKegOrderTicket))).scalars().all()
        assert len(rows) == 1 and rows[0].invalidation_logic == "무혐의 확정"


def test_config_thresholds_defaults():
    from backend.powderkeg.config import ScreenerThresholds, get_thresholds
    t = get_thresholds()
    assert isinstance(t, ScreenerThresholds)
    assert t.pbr_max == 0.5
    assert t.net_cash_ratio_min == 0.40
    assert t.piotroski_f_score_min == 6


def test_config_thresholds_env_override(monkeypatch):
    monkeypatch.setenv("POWDERKEG_PBR_MAX", "0.7")
    monkeypatch.setenv("POWDERKEG_FSCORE_MIN", "5")
    from backend.powderkeg.config import get_thresholds
    t = get_thresholds()
    assert t.pbr_max == 0.7
    assert t.piotroski_f_score_min == 5


def test_config_keywords_type_a_and_b_present():
    from backend.powderkeg.config import KEYWORDS_TYPE_A, KEYWORDS_TYPE_B
    assert "A1_owner_legal_risk" in KEYWORDS_TYPE_A
    assert "A3_stock_pledge" in KEYWORDS_TYPE_A
    assert "B1_embezzlement" in KEYWORDS_TYPE_B
    assert any("횡령" in k for kw in KEYWORDS_TYPE_B.values() for k in kw)
