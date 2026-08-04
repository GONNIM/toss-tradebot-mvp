"""Serenity 알파 검증 · Phase L14 v6 (2026-08-04 · Fable 5 6차 GO).

이 페이지의 존재 이유 · "인플루언서 1인 소스에 알파가 존재하는가" 를 데이터로 답한다.

핵심 함수:
    first_mention_events()     · 각 티커 최초 signal + backtest tuple
    build_buckets()            · sentiment/seed/시총/confidence 3분위 4개 bucket · n<30 masking
    confidence_predictive_check() · 3상태 (insufficient_n / fail / pass · Fable 5 3차 (3b))
    verification_hero()        · 요약 카드 데이터 (히트율·평균 수익률·초과수익·gate 상태)

v6 D1 원칙:
    · 저장은 raw · 조정은 표시/판정 계층에서 각 1회만
    · raw hit_rate + slippage-adjusted + cost-adjusted 세 버전 병기
    · excess_return_primary_raw + adjusted 병기
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func, select

from backend.discovery.serenity.constants import (
    COST_ROUND_TRIP_PCT,
    GATE_EVENTS_MIN,
    SLIPPAGE_PCT,
)
from backend.services.db import get_session
from backend.services.models import (
    DiscoverySerenityScore,
    SerenityBacktest,
    SerenityBenchmarkPrice,
    SerenitySignal,
    SerenityTickerPrice,
    SerenityTweet,
)

logger = logging.getLogger(__name__)

HIT_THRESHOLD_PCT = 10.0  # Fable 5 3차 · +1d/+3d ≥10% (급등 정의)
BUCKET_MIN_N = 30         # Fable 5 3차 · n<30 회색 · "판정 불가"


async def first_mention_events() -> list[dict]:
    """각 티커의 first signal (SerenityTweet.posted_at 최소) 이벤트 + backtest join.

    v6 hotfix2 (2026-08-04): first mention 기준 = SerenityTweet.posted_at (트윗 발행일).
    aggregators.first_mention_map · backtest.load_pending_signals 와 통일.
    이전 (extracted_at) 은 z.ai 배치 최근으로 밀림 · 잘못된 first 판정.

    반환 각 dict:
        {ticker, signal_id, posted_at, extracted_at, sentiment, confidence,
         backtest: SerenityBacktest or None}
    """
    async with get_session() as session:
        # 티커별 first posted_at (트윗 발행) subquery
        subq = (
            select(
                SerenitySignal.ticker,
                func.min(SerenityTweet.posted_at).label("first_posted_at"),
            )
            .join(SerenityTweet, SerenityTweet.tweet_id == SerenitySignal.tweet_id)
            .group_by(SerenitySignal.ticker)
            .subquery()
        )
        stmt = (
            select(SerenitySignal, SerenityTweet.posted_at)
            .join(SerenityTweet, SerenityTweet.tweet_id == SerenitySignal.tweet_id)
            .join(
                subq,
                (SerenitySignal.ticker == subq.c.ticker)
                & (SerenityTweet.posted_at == subq.c.first_posted_at),
            )
        )
        rows = list((await session.execute(stmt)).all())

        # backtest 조회 (signal_id 매핑)
        signal_ids = [r[0].id for r in rows]
        if not signal_ids:
            return []
        bt_rows = list((await session.execute(
            select(SerenityBacktest).where(SerenityBacktest.signal_id.in_(signal_ids))
        )).scalars().all())
        bt_by_signal = {b.signal_id: b for b in bt_rows}

    events: list[dict] = []
    for sig, posted_at in rows:
        bt = bt_by_signal.get(sig.id)
        events.append({
            "ticker": sig.ticker,
            "signal_id": sig.id,
            "posted_at": posted_at,
            "extracted_at": sig.extracted_at,
            "sentiment": sig.sentiment,
            "confidence": sig.confidence,
            "backtest": bt,
        })
    return events


def _is_valid_event(bt: Optional[SerenityBacktest]) -> bool:
    """v6 §2.7 valid = 성과 판정 가능 (상폐 포함).

    · price_at_signal not null AND (return_3d not null OR delisting_flag=True)
    """
    if bt is None:
        return False
    if bt.price_at_signal is None:
        return False
    return bt.return_3d is not None or bt.delisting_flag


def _hit_rate(events: list[dict], attr: str, threshold: float) -> Optional[float]:
    """valid 이벤트 중 attr (return_1d/3d) ≥ threshold 비율 (%)."""
    valid = [e for e in events if _is_valid_event(e["backtest"])]
    if not valid:
        return None
    hits = 0
    for e in valid:
        bt = e["backtest"]
        val = getattr(bt, attr, None)
        if val is not None and val >= threshold:
            hits += 1
    return round(hits * 100 / len(valid), 2)


def _hit_rate_delisting_as_minus100(events: list[dict], attr: str, threshold: float) -> Optional[float]:
    """상폐 이벤트를 -100% 로 처리한 히트율 · 동일 분모 (Fable 5 3차 (1b) 병렬 노출)."""
    valid = [e for e in events if _is_valid_event(e["backtest"])]
    if not valid:
        return None
    hits = 0
    for e in valid:
        bt = e["backtest"]
        if bt.delisting_flag:
            # -100% 는 threshold 미달 · hit 아님
            continue
        val = getattr(bt, attr, None)
        if val is not None and val >= threshold:
            hits += 1
    return round(hits * 100 / len(valid), 2)


def _avg(events: list[dict], attr: str) -> Optional[float]:
    """valid 이벤트 attr 평균 (%)."""
    vals = [
        getattr(e["backtest"], attr, None)
        for e in events
        if _is_valid_event(e["backtest"])
    ]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _excess(events: list[dict], sig_attr: str, bench_attr: str) -> Optional[float]:
    """평균 초과수익 raw · avg(sig − bench). v6 D1: bench 만 차감 · slippage/cost 는 판정/표시 계층."""
    diffs: list[float] = []
    for e in events:
        if not _is_valid_event(e["backtest"]):
            continue
        bt = e["backtest"]
        sig_val = getattr(bt, sig_attr, None)
        bench_val = getattr(bt, bench_attr, None)
        if sig_val is not None and bench_val is not None:
            diffs.append(sig_val - bench_val)
    if not diffs:
        return None
    return round(sum(diffs) / len(diffs), 2)


def _confidence_tertile(events: list[dict]) -> dict:
    """confidence 3분위 예측력 검증 (Fable 5 4차 (D2) · 3상태 리턴).

    반환: {top_hit_rate, bottom_hit_rate, diff_pp, top_n, bottom_n, min_n_ok,
           predictive_status: "insufficient_n" | "fail" | "pass"}
    """
    valid = [e for e in events if _is_valid_event(e["backtest"])]
    if len(valid) < 3:
        return {
            "top_hit_rate": None, "bottom_hit_rate": None, "diff_pp": None,
            "top_n": 0, "bottom_n": 0, "min_n_ok": False,
            "predictive_status": "insufficient_n",
        }
    # confidence 정렬 · 3분위
    sorted_events = sorted(valid, key=lambda e: e["confidence"] or 0)
    n = len(sorted_events)
    tercile_size = n // 3
    bottom = sorted_events[:tercile_size]
    top = sorted_events[-tercile_size:] if tercile_size > 0 else []

    def _hr(subset):
        if not subset:
            return None
        hits = sum(
            1 for e in subset
            if (getattr(e["backtest"], "return_3d", None) or -999) >= HIT_THRESHOLD_PCT
        )
        return round(hits * 100 / len(subset), 2)

    top_hr = _hr(top)
    bot_hr = _hr(bottom)
    diff = None
    if top_hr is not None and bot_hr is not None:
        diff = round(top_hr - bot_hr, 2)
    min_n_ok = len(top) >= BUCKET_MIN_N and len(bottom) >= BUCKET_MIN_N

    if not min_n_ok:
        status = "insufficient_n"
    elif diff is None or diff < 15:
        status = "fail"
    else:
        status = "pass"

    return {
        "top_hit_rate": top_hr,
        "bottom_hit_rate": bot_hr,
        "diff_pp": diff,
        "top_n": len(top),
        "bottom_n": len(bottom),
        "min_n_ok": min_n_ok,
        "predictive_status": status,
    }


async def _bucket_by_sentiment(events: list[dict]) -> list[dict]:
    from collections import defaultdict
    groups = defaultdict(list)
    for e in events:
        if _is_valid_event(e["backtest"]):
            groups[e["sentiment"] or "unknown"].append(e)
    rows = []
    for key, subset in sorted(groups.items()):
        n = len(subset)
        rows.append({
            "key": key,
            "n": n,
            "hit_rate_10pct_3d": _hit_rate(subset, "return_3d", HIT_THRESHOLD_PCT),
            "avg_return_3d": _avg(subset, "return_3d"),
            "excess_iwm_3d": _excess(subset, "return_3d", "benchmark_iwm_return_3d"),
            "is_masked": n < BUCKET_MIN_N,
        })
    return rows


async def _bucket_by_seed(events: list[dict]) -> list[dict]:
    async with get_session() as session:
        seed_tickers = set((await session.execute(
            select(DiscoverySerenityScore.ticker)
        )).scalars().all())
    valid = [e for e in events if _is_valid_event(e["backtest"])]
    seed_events = [e for e in valid if e["ticker"] in seed_tickers]
    unscored_events = [e for e in valid if e["ticker"] not in seed_tickers]
    rows = []
    for key, subset in (("seed", seed_events), ("unscored", unscored_events)):
        n = len(subset)
        rows.append({
            "key": key,
            "n": n,
            "hit_rate_10pct_3d": _hit_rate(subset, "return_3d", HIT_THRESHOLD_PCT),
            "avg_return_3d": _avg(subset, "return_3d"),
            "excess_iwm_3d": _excess(subset, "return_3d", "benchmark_iwm_return_3d"),
            "is_masked": n < BUCKET_MIN_N,
        })
    return rows


async def _bucket_by_market_cap(events: list[dict]) -> list[dict]:
    async with get_session() as session:
        cap_rows = list((await session.execute(
            select(SerenityTickerPrice.ticker, SerenityTickerPrice.market_cap)
        )).all())
    cap_map = {t: c for t, c in cap_rows if c is not None}

    def _tier(cap: Optional[float]) -> str:
        if cap is None:
            return "unknown"
        if cap < 1e9:
            return "micro (<1B)"
        if cap < 1e10:
            return "small (1-10B)"
        return "mid+"

    from collections import defaultdict
    groups = defaultdict(list)
    for e in events:
        if not _is_valid_event(e["backtest"]):
            continue
        tier = _tier(cap_map.get(e["ticker"]))
        groups[tier].append(e)
    rows = []
    for key in ("micro (<1B)", "small (1-10B)", "mid+", "unknown"):
        subset = groups.get(key, [])
        n = len(subset)
        rows.append({
            "key": key,
            "n": n,
            "hit_rate_10pct_3d": _hit_rate(subset, "return_3d", HIT_THRESHOLD_PCT),
            "avg_return_3d": _avg(subset, "return_3d"),
            "excess_iwm_3d": _excess(subset, "return_3d", "benchmark_iwm_return_3d"),
            "is_masked": n < BUCKET_MIN_N,
        })
    return rows


def _bucket_by_confidence_tertile(events: list[dict]) -> list[dict]:
    """confidence 3분위 bucket (bottom / mid / top)."""
    valid = [e for e in events if _is_valid_event(e["backtest"])]
    if len(valid) < 3:
        return [
            {"key": "bottom", "n": 0, "hit_rate_10pct_3d": None, "avg_return_3d": None, "excess_iwm_3d": None, "is_masked": True},
            {"key": "mid", "n": 0, "hit_rate_10pct_3d": None, "avg_return_3d": None, "excess_iwm_3d": None, "is_masked": True},
            {"key": "top", "n": 0, "hit_rate_10pct_3d": None, "avg_return_3d": None, "excess_iwm_3d": None, "is_masked": True},
        ]
    sorted_events = sorted(valid, key=lambda e: e["confidence"] or 0)
    n = len(sorted_events)
    ts = n // 3
    bottom = sorted_events[:ts]
    mid = sorted_events[ts:-ts] if ts > 0 else []
    top = sorted_events[-ts:] if ts > 0 else []
    rows = []
    for key, subset in (("bottom", bottom), ("mid", mid), ("top", top)):
        nn = len(subset)
        rows.append({
            "key": key,
            "n": nn,
            "hit_rate_10pct_3d": _hit_rate(subset, "return_3d", HIT_THRESHOLD_PCT),
            "avg_return_3d": _avg(subset, "return_3d"),
            "excess_iwm_3d": _excess(subset, "return_3d", "benchmark_iwm_return_3d"),
            "is_masked": nn < BUCKET_MIN_N,
        })
    return rows


async def build_buckets(events: list[dict]) -> list[dict]:
    """4개 bucket · sentiment · seed · 시총 · confidence 3분위 (v6 D2)."""
    return [
        {"name": "sentiment", "rows": await _bucket_by_sentiment(events)},
        {"name": "seed", "rows": await _bucket_by_seed(events)},
        {"name": "market_cap_tier", "rows": await _bucket_by_market_cap(events)},
        {"name": "confidence_tertile", "rows": _bucket_by_confidence_tertile(events)},
    ]


async def _benchmark_row_count(symbol: str) -> int:
    async with get_session() as session:
        return int((await session.execute(
            select(func.count()).select_from(SerenityBenchmarkPrice).where(SerenityBenchmarkPrice.symbol == symbol)
        )).scalar_one())


async def build_hero(events: list[dict]) -> dict:
    """검증 요약 카드 데이터 (v6 §2.6 API 계약)."""
    valid_count = sum(1 for e in events if _is_valid_event(e["backtest"]))
    iwm_rows = await _benchmark_row_count("IWM")

    # raw 히트율 (v6 D1 원칙)
    hit_1d = _hit_rate(events, "return_1d", HIT_THRESHOLD_PCT)
    hit_3d = _hit_rate(events, "return_3d", HIT_THRESHOLD_PCT)
    hit_1d_del = _hit_rate_delisting_as_minus100(events, "return_1d", HIT_THRESHOLD_PCT)
    hit_3d_del = _hit_rate_delisting_as_minus100(events, "return_3d", HIT_THRESHOLD_PCT)

    # raw 평균 수익률
    avg_by_window = {
        w: _avg(events, f"return_{w}d") for w in (1, 3, 5, 10, 30)
    }
    avg_gap = _avg(events, "gap_next_open_pct")

    # 표시 계층 조정 (v6 D1 원칙 · 각 1회 차감)
    def _adjusted(raw: Optional[float], adj_pct: float) -> Optional[float]:
        if raw is None:
            return None
        return round(raw - adj_pct, 2)

    avg_slippage_adj_1d = _adjusted(avg_by_window[1], SLIPPAGE_PCT)
    avg_cost_adj_1d = _adjusted(avg_by_window[1], SLIPPAGE_PCT + COST_ROUND_TRIP_PCT)
    avg_slippage_adj_3d = _adjusted(avg_by_window[3], SLIPPAGE_PCT)
    avg_cost_adj_3d = _adjusted(avg_by_window[3], SLIPPAGE_PCT + COST_ROUND_TRIP_PCT)

    # 벤치마크 raw
    bench_iwm_avg = {w: _avg(events, f"benchmark_iwm_return_{w}d") for w in (1, 3, 5, 10, 30)}
    bench_spy_avg = {w: _avg(events, f"benchmark_spy_return_{w}d") for w in (1, 3, 5, 10, 30)}

    # 초과수익 raw (bench 만 차감 · v6 D1)
    excess_iwm_raw = {
        1: _excess(events, "return_1d", "benchmark_iwm_return_1d"),
        3: _excess(events, "return_3d", "benchmark_iwm_return_3d"),
        5: _excess(events, "return_5d", "benchmark_iwm_return_5d"),
    }
    excess_spy_raw = {
        1: _excess(events, "return_1d", "benchmark_spy_return_1d"),
        3: _excess(events, "return_3d", "benchmark_spy_return_3d"),
        5: _excess(events, "return_5d", "benchmark_spy_return_5d"),
    }
    # 초과수익 adjusted (표시 계층 · slippage + cost 1회 차감)
    excess_iwm_adj = {
        k: _adjusted(v, SLIPPAGE_PCT + COST_ROUND_TRIP_PCT) for k, v in excess_iwm_raw.items()
    }
    excess_spy_adj = {
        k: _adjusted(v, SLIPPAGE_PCT + COST_ROUND_TRIP_PCT) for k, v in excess_spy_raw.items()
    }

    # 게이트 상태 (Step A 시점 · deprecation 판정은 Step C hunter.py 소관)
    gate_reasons = []
    if valid_count < GATE_EVENTS_MIN:
        gate_reasons.append(f"insufficient_valid_events ({valid_count}/{GATE_EVENTS_MIN})")
    if iwm_rows < GATE_EVENTS_MIN:
        gate_reasons.append(f"insufficient_benchmark_rows ({iwm_rows}/{GATE_EVENTS_MIN})")
    gate_open = len(gate_reasons) == 0

    warning_text = None
    if valid_count < GATE_EVENTS_MIN:
        warning_text = f"검증 데이터 축적 중 (N={valid_count}/{GATE_EVENTS_MIN}). 매매 판단 불가."

    return {
        "total_events": len(events),
        "valid_events": valid_count,
        "benchmark_rows_iwm": iwm_rows,  # Fable 5 6차 비차단 권고 · 정확 판정 필드
        "benchmark_rows_spy": await _benchmark_row_count("SPY"),
        "hit_rate_10pct_1d": hit_1d,
        "hit_rate_10pct_3d": hit_3d,
        "hit_rate_10pct_1d_delisting_as_minus100": hit_1d_del,
        "hit_rate_10pct_3d_delisting_as_minus100": hit_3d_del,
        "avg_raw_return_1d": avg_by_window[1],
        "avg_raw_return_3d": avg_by_window[3],
        "avg_return_by_window": avg_by_window,
        "avg_gap_next_open_pct": avg_gap,
        "avg_slippage_adjusted_return_1d": avg_slippage_adj_1d,
        "avg_slippage_adjusted_return_3d": avg_slippage_adj_3d,
        "avg_cost_adjusted_return_1d": avg_cost_adj_1d,
        "avg_cost_adjusted_return_3d": avg_cost_adj_3d,
        "benchmark_iwm_avg": bench_iwm_avg,
        "benchmark_spy_avg": bench_spy_avg,
        "excess_return_primary_raw": excess_iwm_raw,     # IWM 단독 primary
        "excess_return_primary_adjusted": excess_iwm_adj,
        "excess_return_reference_raw": excess_spy_raw,   # SPY 참고
        "excess_return_reference_adjusted": excess_spy_adj,
        "gate_open": gate_open,
        "gate_events_needed": GATE_EVENTS_MIN,
        "gate_events_have": valid_count,
        "gate_close_reasons": gate_reasons,
        "warning_text": warning_text,
    }


async def confidence_predictive_check() -> dict:
    """API 스크립트에서 호출용 · 3상태 판정."""
    events = await first_mention_events()
    return _confidence_tertile(events)
