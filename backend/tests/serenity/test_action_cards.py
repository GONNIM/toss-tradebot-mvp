"""action_cards.py · 필터 · 계산 · Shell 제외 · 가격 없음 분리."""
from __future__ import annotations

# ⚠ 실 파일 DB 오염 방지 · 반드시 in-memory sqlite 사용 (2026-08-05 사고 재발 방지)
# _clean_db fixture 가 실 tradebot.db 를 clear 하지 않도록 · 다른 import 전에 강제 지정.
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.discovery.serenity import action_cards as ac
from backend.discovery.serenity.constants import (
    BULL_PCT_MIN,
    MENTIONS_7D_MIN,
    MENTIONS_90D_MIN,
    POSITION_KRW,
    SLIPPAGE_LIMIT_PCT,
    SL_PCT,
    TP_TRIGGER_PCT,
    USDKRW_RATE,
)
from backend.services.db import get_session, init_db
from backend.services.models import (
    DiscoverySerenityScore,
    SerenitySignal,
    SerenityTickerPrice,
    SerenityTweet,
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        for model in (SerenitySignal, SerenityTweet, SerenityTickerPrice, DiscoverySerenityScore):
            await session.execute(delete(model))
    yield


# ─── 실행 계획 계산식 ───────────────────────────────────────────


def test_compute_execution_plan_basic():
    """last_close 100 → entry_limit 101 · sl 90.9 · tp 116.15."""
    p = ac._compute_execution_plan(100.0)
    assert p["entry_limit"] == pytest.approx(100.0 * (1 + SLIPPAGE_LIMIT_PCT / 100))
    assert p["sl_price"] == pytest.approx(p["entry_limit"] * (1 - SL_PCT / 100), rel=1e-3)
    assert p["tp_trigger_price"] == pytest.approx(p["entry_limit"] * (1 + TP_TRIGGER_PCT / 100), rel=1e-3)
    # min_rr = TP / SL = 15 / 10 = 1.5
    assert p["min_rr"] == 1.5
    assert p["min_rr_warning"] is True  # < MIN_RR_WARNING (2.0)


def test_compute_execution_plan_qty_floor():
    """POSITION_KRW / (entry_limit × USDKRW_RATE) floor."""
    p = ac._compute_execution_plan(100.0)
    expected_qty = int((POSITION_KRW) // (p["entry_limit"] * USDKRW_RATE))
    assert p["qty"] == expected_qty


# ─── 필터 유닛 (aggregate mock) ─────────────────────────────────


async def _seed_ticker_with_signals(ticker: str, m90: int, m7: int, bull_pct: float,
                                     price: float | None = 100.0,
                                     prior_close: float | None = None,
                                     industry: str | None = "Semiconductors",
                                     tier: str | None = "A",
                                     auto_avoid: bool = False,
                                     anti_flags: str = "",
                                     market_cap: float | None = None,
                                     shares_outstanding: float | None = None):
    """helper · signals/tweet/price/seed 각각 fixture 로 등록."""
    now = datetime.utcnow()
    async with get_session() as session:
        # tweets (m90 건 · 그중 m7 은 최근 7일 이내)
        tweet_ids: list[int] = []
        for i in range(m90):
            days_ago = 3 if i < m7 else 30
            tid = abs(hash((ticker, i))) & 0x7FFFFFFF
            tweet_ids.append(tid)
            tw = SerenityTweet(
                id=str(uuid.uuid4()),
                tweet_id=tid,
                text="dummy",
                url=f"http://x/{ticker}/{i}",
                posted_at=now - timedelta(days=days_ago),
            )
            session.add(tw)
        await session.commit()

        # signals · 처음 int(m90*bull_pct/100) 만 bullish
        bull_n = int(m90 * bull_pct / 100)
        for idx, tid in enumerate(tweet_ids):
            sig = SerenitySignal(
                id=f"{ticker}-sig-{idx}",
                tweet_id=tid,
                ticker=ticker,
                sentiment="bullish" if idx < bull_n else "neutral",
                confidence=0.8,
                extracted_at=now - timedelta(days=1),
            )
            session.add(sig)

        # price
        if price is not None:
            vs_prior = None
            if prior_close and prior_close > 0:
                vs_prior = round((price - prior_close) / prior_close * 100, 2)
            session.add(SerenityTickerPrice(
                ticker=ticker,
                snapshot_date=now.date().isoformat(),
                close=price,
                prior_close=prior_close,
                vs_prior_close_pct=vs_prior,
                industry=industry,
                sector="Technology",
                market_cap=market_cap,
                shares_outstanding=shares_outstanding,
            ))

        # seed score
        if tier:
            session.add(DiscoverySerenityScore(
                ticker=ticker,
                financing_tier="A",
                serenity_tier=tier,
                total_score=100,
                auto_avoid=auto_avoid,
                anti_pattern_flags=anti_flags,
                domain_tags="",
            ))
        await session.commit()


@pytest.mark.asyncio
async def test_passes_all_filters_creates_card():
    """m90=15 · m7=5 · bull=80 · price 존재 → 카드 발급."""
    await _seed_ticker_with_signals("NBIS", m90=15, m7=5, bull_pct=80.0)
    result = await ac.build_action_cards()
    tickers_passed = [c["ticker"] for c in result["cards"]]
    assert "NBIS" in tickers_passed
    card = next(c for c in result["cards"] if c["ticker"] == "NBIS")
    assert card["entry_limit"] > 100.0  # slippage 반영
    assert card["qty"] > 0


@pytest.mark.asyncio
async def test_below_bull_pct_excluded():
    """bull_pct 42 < 70 → excluded."""
    await _seed_ticker_with_signals("MSFT", m90=20, m7=5, bull_pct=42.0)
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "MSFT" for c in result["cards"])
    reason = next(e["reason"] for e in result["excluded"] if e["ticker"] == "MSFT")
    assert "bull_pct" in reason


@pytest.mark.asyncio
async def test_below_mentions_90d_excluded():
    """m90 8 < 10 → excluded."""
    await _seed_ticker_with_signals("BE", m90=8, m7=3, bull_pct=90.0)
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "BE" for c in result["cards"])
    reason = next(e["reason"] for e in result["excluded"] if e["ticker"] == "BE")
    assert "m90" in reason


@pytest.mark.asyncio
async def test_shell_company_excluded():
    """industry=Shell Companies → excluded."""
    await _seed_ticker_with_signals("CCXI", m90=20, m7=5, bull_pct=90.0, industry="Shell Companies")
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "CCXI" for c in result["cards"])
    reason = next(e["reason"] for e in result["excluded"] if e["ticker"] == "CCXI")
    assert "Shell Companies" in reason


@pytest.mark.asyncio
async def test_no_price_goes_to_watch_only():
    """price=None → watch_only (excluded 아님)."""
    await _seed_ticker_with_signals("SIVE", m90=20, m7=5, bull_pct=90.0, price=None)
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "SIVE" for c in result["cards"])
    assert any(w["ticker"] == "SIVE" for w in result["watch_only"])


@pytest.mark.asyncio
async def test_auto_avoid_excluded():
    """seed.auto_avoid=True → excluded."""
    await _seed_ticker_with_signals("AVOID", m90=20, m7=5, bull_pct=90.0, auto_avoid=True)
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "AVOID" for c in result["cards"])
    assert any("auto_avoid" in e["reason"] for e in result["excluded"] if e["ticker"] == "AVOID")


@pytest.mark.asyncio
async def test_anti_pattern_excluded():
    """anti_pattern_flags 있으면 excluded."""
    await _seed_ticker_with_signals("AAOI", m90=20, m7=5, bull_pct=90.0, anti_flags="no_cpo_design_win")
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "AAOI" for c in result["cards"])
    reason = next(e["reason"] for e in result["excluded"] if e["ticker"] == "AAOI")
    assert "anti_pattern" in reason


@pytest.mark.asyncio
async def test_sector_overlap_badge():
    """같은 industry 2+ 카드 → sector_overlap=True."""
    await _seed_ticker_with_signals("SNDK", m90=20, m7=5, bull_pct=80.0, industry="Semiconductors")
    await _seed_ticker_with_signals("MU", m90=20, m7=5, bull_pct=80.0, industry="Semiconductors")
    result = await ac.build_action_cards()
    for c in result["cards"]:
        if c["ticker"] in ("SNDK", "MU"):
            assert c["sector_overlap"] is True


@pytest.mark.asyncio
async def test_fx_rate_and_filters_in_response():
    """response 에 fx_rate·filters·risk 포함."""
    result = await ac.build_action_cards()
    assert result["fx_rate"] == USDKRW_RATE
    assert result["fx_source"] == "hardcoded"
    assert result["filters"]["bull_pct_min"] == BULL_PCT_MIN
    assert result["filters"]["mentions_90d_min"] == MENTIONS_90D_MIN
    assert result["filters"]["mentions_7d_min"] == MENTIONS_7D_MIN
    assert "Shell Companies" in result["filters"]["shell_industries"]


# ─── 가격 검증 게이트 (2026-08-13 MU 사고 대응) ─────────────────────


@pytest.mark.asyncio
async def test_qty_zero_excluded_with_reason():
    """예산 미달 (qty=0) → excluded 로 이동 · 사유 명시 (Fable 5 · 탈락 명단 투명성)."""
    # MU 시나리오 · $911 · 20만원 예산 · qty = floor(200000 / (911×1.01×1330)) = 0
    await _seed_ticker_with_signals("MU", m90=45, m7=3, bull_pct=78.0, price=911.29, tier=None)
    result = await ac.build_action_cards()
    assert all(c["ticker"] != "MU" for c in result["cards"]), "qty=0 카드 노출 X"
    reason = next(e["reason"] for e in result["excluded"] if e["ticker"] == "MU")
    assert "예산 미달" in reason and "₩200,000" in reason


@pytest.mark.asyncio
async def test_price_verification_failed_badge_on_abnormal_move():
    """prior_close 대비 |pct| > 30% → 카드에 배지 (배제 X · Fable 5 리뷰)."""
    # +40% 이동 (예 실적 발표 급등)
    await _seed_ticker_with_signals(
        "NBIS", m90=15, m7=5, bull_pct=85.0,
        price=140.0, prior_close=100.0,
    )
    result = await ac.build_action_cards()
    card = next(c for c in result["cards"] if c["ticker"] == "NBIS")
    assert card["price_verification_failed"] is True, "±30% 초과 → 배지 표시"
    assert card["vs_prior_pct"] == 40.0


@pytest.mark.asyncio
async def test_price_verification_ok_on_normal_move():
    """정상 변동 (±30% 이내) → 배지 없음."""
    await _seed_ticker_with_signals(
        "COHR", m90=37, m7=7, bull_pct=72.0,
        price=105.0, prior_close=100.0, tier=None,
    )
    result = await ac.build_action_cards()
    card = next(c for c in result["cards"] if c["ticker"] == "COHR")
    assert card["price_verification_failed"] is False
    assert card["vs_prior_pct"] == 5.0


@pytest.mark.asyncio
async def test_market_cap_sanity_warning_on_inconsistency():
    """|market_cap − shares × close| / market_cap > 10% → sanity warning."""
    # 편차 20% · yf market_cap 이 shares × close 보다 20% 큼
    # shares × close = 100M × $100 = $10B · yf market_cap 은 $12B 로 저장
    await _seed_ticker_with_signals(
        "AXTI", m90=65, m7=9, bull_pct=83.0,
        price=100.0, market_cap=12_000_000_000, shares_outstanding=100_000_000,
    )
    result = await ac.build_action_cards()
    card = next(c for c in result["cards"] if c["ticker"] == "AXTI")
    assert card["market_cap_sanity_warning"] is True


@pytest.mark.asyncio
async def test_market_cap_sanity_ok_when_consistent():
    """market_cap 과 shares × close 편차 ≤ 10% → warning 없음."""
    # 편차 5% · 통과
    await _seed_ticker_with_signals(
        "AXTI", m90=65, m7=9, bull_pct=83.0,
        price=100.0, market_cap=10_500_000_000, shares_outstanding=100_000_000,
    )
    result = await ac.build_action_cards()
    card = next(c for c in result["cards"] if c["ticker"] == "AXTI")
    assert card["market_cap_sanity_warning"] is False


@pytest.mark.asyncio
async def test_market_cap_sanity_skipped_when_shares_missing():
    """shares_outstanding 미저장 (기존 스냅샷) → sanity skip · warning False."""
    # market_cap 만 있음 · shares_outstanding 없음
    await _seed_ticker_with_signals(
        "AXTI", m90=65, m7=9, bull_pct=83.0,
        price=100.0, market_cap=10_000_000_000, shares_outstanding=None,
    )
    result = await ac.build_action_cards()
    card = next(c for c in result["cards"] if c["ticker"] == "AXTI")
    assert card["market_cap_sanity_warning"] is False
