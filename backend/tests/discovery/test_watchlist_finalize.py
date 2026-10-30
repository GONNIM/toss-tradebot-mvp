"""Watchlist finalize · Sprint 2 Week 2 T60·T61."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.watchlist.finalize import finalize_watchlist, list_watchlist
from backend.discovery.watchlist.scoring import normalized_weights, score_signals
from backend.discovery.watchlist.store import upsert_signal
from backend.services.db import get_session, init_db
from backend.services.models import LiveTapeUniverse, Watchlist, WatchlistSignal


_KST = timezone(timedelta(hours=9))
TRADE_DATE = "2026-07-14"


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(WatchlistSignal))
        await session.execute(delete(Watchlist))
        await session.execute(delete(LiveTapeUniverse))
    yield


async def _seed_universe(items: list[tuple[str, str]]):
    async with get_session() as session:
        for code, name in items:
            session.add(LiveTapeUniverse(
                ticker=code, name=name, market="KOSDAQ",
                dept=None, close_price=1000.0, market_cap_krw=100_000_000_000,
                shares=1_000_000, amount_today=1_000_000_000,
                amount_20d_avg=None, is_squeeze_candidate=False,
                refreshed_at=datetime.now(tz=timezone.utc),
            ))


# ─── scoring 단위 테스트 (v2 · 1030-04) ───────────────
_ALL_ON = {"news": True, "interest": True, "youtube": True, "event": True, "prev_day": True}


def test_score_signals_weights_and_ordering():
    """티커별 · source별 조합 점수 계산 (칸마다 0~1 · 합성 0~1)."""
    signals = [
        # 삼성전자 · 서로 다른 언론 3곳 + 개인 순매수 새 진입 + 유튜브 1건
        {"ticker": "005930", "source": "news_yhap", "intensity": 1.0},
        {"ticker": "005930", "source": "news_mk", "intensity": 1.0},
        {"ticker": "005930", "source": "news_fnnews", "intensity": 1.0},
        {"ticker": "005930", "source": "rank_individual_netbuy", "intensity": 0.9},
        {"ticker": "005930", "source": "youtube_shuka", "intensity": 1.0},
        # SK하이닉스 · 뉴스 1건만 · 낮은 점수
        {"ticker": "000660", "source": "news_yhap", "intensity": 1.0},
    ]
    scores = score_signals(signals, _ALL_ON)
    assert len(scores) == 2
    top = scores[0]
    assert top.ticker == "005930"
    # news = 0.6*min(1,3/3) + 0.4*min(1,3/3) = 1.0 · interest 0.9 · youtube 1/3
    assert top.news_score == 1.0
    assert top.board_score == 0.9
    assert top.youtube_score == pytest.approx(0.3333, abs=1e-3)
    # composite = 0.35*1 + 0.25*0.9 + 0.15*(1/3) = 0.625
    assert top.composite_score == pytest.approx(0.625, abs=1e-3)
    assert 0.0 <= top.composite_score <= 1.0
    assert scores[1].ticker == "000660"
    assert scores[1].composite_score < top.composite_score


def test_score_signals_empty():
    assert score_signals([], _ALL_ON) == []


def test_score_renormalizes_over_collecting_cells_only():
    """수집 안 하는 칸은 빼고 가중을 다시 맞춘다 · 뉴스만 수집하면 뉴스 점수가 곧 합성."""
    sig = [{"ticker": "005930", "source": "news_yhap", "intensity": 1.0}]
    only_news = {"news": True, "interest": False, "youtube": False, "event": False, "prev_day": False}
    s = score_signals(sig, only_news)[0]
    assert s.composite_score == pytest.approx(s.news_score, abs=1e-4)
    assert s.used_weights == {"news": 1.0}
    assert normalized_weights(_ALL_ON) == pytest.approx(
        {"news": 0.35, "interest": 0.25, "youtube": 0.15, "event": 0.15, "prev_day": 0.10})


def test_news_score_is_capped_and_counts_publishers_once():
    """한 언론의 두 피드(인포맥스 증권·전체)는 한 곳 · 한 곳이 도배해도 0.6 을 못 넘는다."""
    sigs = [{"ticker": "005930", "source": "news_yhap", "intensity": 1.0} for _ in range(10)]
    sigs += [{"ticker": "005930", "source": "news_einfomax_all", "intensity": 1.0} for _ in range(10)]
    s = score_signals(sigs, _ALL_ON)[0]
    assert s.news_score == pytest.approx(0.6 + 0.4 * (1 / 3), abs=1e-3)


def test_event_cell_and_caution_scores_zero():
    sigs = [
        {"ticker": "005930", "source": "dart_disclosure", "intensity": 1.0},
        {"ticker": "000660", "source": "dart_caution", "intensity": 0.0},
    ]
    by = {s.ticker: s for s in score_signals(sigs, _ALL_ON)}
    assert by["005930"].event_score == 1.0
    assert by["000660"].event_score == 0.0 and by["000660"].composite_score == 0.0


def test_legacy_board_signal_not_scored():
    s = score_signals([{"ticker": "005930", "source": "board_naver", "intensity": 3.0}], _ALL_ON)[0]
    assert s.composite_score == 0.0 and s.board_score == 0.0


def test_rank_overlap_bonus_capped_at_one():
    sigs = [
        {"ticker": "005930", "source": "rank_individual_netbuy", "intensity": 0.95},
        {"ticker": "005930", "source": "rank_toss_amount", "intensity": 0.9},
        {"ticker": "005930", "source": "rank_market_amount", "intensity": 0.6},
        {"ticker": "005930", "source": "rank_market_volume", "intensity": 0.5},
    ]
    s = score_signals(sigs, _ALL_ON)[0]
    assert s.board_score == pytest.approx(min(1.0, 0.95 + 0.15), abs=1e-4)
    assert s.prev_day_score == pytest.approx(0.6 + 0.15, abs=1e-4)


# ─── finalize 통합 테스트 ───────────────────────────
@pytest.mark.asyncio
async def test_finalize_writes_top_n():
    """5 종목 signal → Top 3 승격."""
    await _seed_universe([
        ("005930", "삼성전자"), ("000660", "SK하이닉스"),
        ("373220", "LG에너지솔루션"), ("035420", "NAVER"),
        ("068270", "셀트리온"),
    ])
    # 종목별 signal 유입
    tickers_scores = [
        ("005930", 5),   # 뉴스 5건
        ("373220", 4),
        ("000660", 3),
        ("035420", 2),
        ("068270", 1),
    ]
    for ticker, cnt in tickers_scores:
        for i in range(cnt):
            await upsert_signal(
                ticker=ticker, source=f"news_yhap",
                signal_type="headline", intensity=1.0,
                trade_date=TRADE_DATE,
                detected_at=datetime.now(tz=timezone.utc) - timedelta(minutes=i * 6),
            )

    stats = await finalize_watchlist(trade_date=TRADE_DATE, top_n=3)
    assert stats["written"] == 3
    assert stats["candidates_scored"] == 5

    watchlist = await list_watchlist(TRADE_DATE)
    assert [w["ticker"] for w in watchlist] == ["005930", "373220", "000660"]
    assert watchlist[0]["rank"] == 1
    assert watchlist[0]["name"] == "삼성전자"
    assert watchlist[0]["added_by"] == "auto"
    assert not watchlist[0]["locked"]


@pytest.mark.asyncio
async def test_finalize_keeps_locked_entries():
    """locked=True 는 finalize 후에도 유지."""
    await _seed_universe([
        ("005930", "삼성전자"), ("000660", "SK하이닉스"),
        ("373220", "LG에너지솔루션"),
    ])

    # locked 사전 삽입 (사용자 수동 add 시뮬)
    async with get_session() as session:
        session.add(Watchlist(
            trade_date=TRADE_DATE, ticker="068270", name="셀트리온",
            rank=99, composite_score=0.0,
            news_score=0.0, board_score=0.0, youtube_score=0.0,
            event_score=0.0, prev_day_score=0.0,
            source_breakdown=None, locked=True, added_by="user",
        ))
        # non-locked 사전 삽입 → 삭제되어야 함
        session.add(Watchlist(
            trade_date=TRADE_DATE, ticker="AAA000", name="테스트",
            rank=100, composite_score=0.0,
            news_score=0.0, board_score=0.0, youtube_score=0.0,
            event_score=0.0, prev_day_score=0.0,
            source_breakdown=None, locked=False, added_by="auto",
        ))

    # 새 signal
    for ticker in ("005930", "373220"):
        for _ in range(3):
            await upsert_signal(
                ticker=ticker, source="news_yhap",
                signal_type="headline", intensity=1.0,
                trade_date=TRADE_DATE,
                detected_at=datetime.now(tz=timezone.utc),
            )

    stats = await finalize_watchlist(trade_date=TRADE_DATE, top_n=3)
    assert stats["locked_kept"] == 1
    assert stats["auto_picked"] == 2  # top_n=3 - 1 locked = 2
    assert stats["written"] == 3

    watchlist = await list_watchlist(TRADE_DATE)
    assert len(watchlist) == 3
    tickers = {w["ticker"] for w in watchlist}
    assert "068270" in tickers  # locked 유지
    assert "AAA000" not in tickers  # non-locked 삭제됨
    # locked=True 인 셀트리온은 여전히 locked
    celltrion = [w for w in watchlist if w["ticker"] == "068270"][0]
    assert celltrion["locked"] is True
    assert celltrion["added_by"] == "user"


@pytest.mark.asyncio
async def test_finalize_empty_signals():
    stats = await finalize_watchlist(trade_date=TRADE_DATE, top_n=30)
    assert stats["written"] == 0
    assert stats["signals_read"] == 0


@pytest.mark.asyncio
async def test_finalize_fills_name_from_dart_db_table():
    """matcher·유니버스에 없는 종목은 화약고 DART 표 이름으로 빈칸만 채움 (1030-04)."""
    from backend.services.models import DartCorpCodeMap

    async with get_session() as session:
        await session.execute(delete(DartCorpCodeMap))
        session.add(DartCorpCodeMap(corp_code="99999991", corp_name="테스트상장사", stock_code="999991"))
    detected = datetime(2026, 7, 13, 20, 0, tzinfo=_KST).astimezone(timezone.utc)
    await upsert_signal(ticker="999991", source="news_mk", signal_type="headline",
                        intensity=1.0, trade_date=TRADE_DATE, detected_at=detected)
    await finalize_watchlist(trade_date=TRADE_DATE, top_n=5)
    rows = await list_watchlist(TRADE_DATE)
    assert [r["name"] for r in rows if r["ticker"] == "999991"] == ["테스트상장사"]
