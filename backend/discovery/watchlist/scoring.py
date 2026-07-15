"""Watchlist Composite Score · Sprint 2 Week 2 T60.

공식:
    composite_score = 0.35 · news_z
                    + 0.25 · board_z
                    + 0.15 · youtube_signal
                    + 0.15 · event_proximity
                    + 0.10 · prev_day_derivative   (v1 · placeholder 0)

계획서: docs/plans/sniper/02-strategic-pivot-as-is-to-be.md §2-3
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─── 가중치 (기본값 · UI 튜닝 가능 Week 3+) ───────────────
W_NEWS = 0.35
W_BOARD = 0.25
W_YOUTUBE = 0.15
W_EVENT = 0.15
W_PREV_DAY = 0.10


# ─── source 분류 ─────────────────────────────────────
_NEWS_SOURCES = {
    "news_yhap", "news_edaily", "news_fnnews", "news_hankyung", "news_yonhap",
}
_BOARD_SOURCES = {"board_naver"}
_YOUTUBE_SOURCES = {
    "youtube_shuka", "youtube_sampro", "youtube_hantoo", "youtube_jungpro",
}
_EVENT_SOURCES = {
    "assembly", "moef_rss", "motie_rss", "msit_rss", "molit_rss",
}
_PREV_DAY_SOURCES = {"prev_day_derivative"}


@dataclass
class TickerScore:
    ticker: str
    composite_score: float
    news_score: float = 0.0
    board_score: float = 0.0
    youtube_score: float = 0.0
    event_score: float = 0.0
    prev_day_score: float = 0.0
    # source_breakdown[source] = {"count": N, "intensity_sum": X}
    source_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


def score_signals(signals: list[dict[str, Any]]) -> list[TickerScore]:
    """signals (WatchlistSignal 딕셔너리 리스트) → 티커별 TickerScore 리스트.

    Args:
        signals: store.signals_for_date() 반환값 · [{ticker, source, intensity, ...}]

    Returns:
        composite_score 내림차순 정렬된 TickerScore 리스트.

    로직:
        · 뉴스 · 티커별 뉴스 언급 count · fallback z = count / 5 (5회=z1)
        · 종토방 · intensity 최대값 (이미 z-score · T55)
        · 유튜브 · upload count · scaled: min(count, 3) / 3
        · 이벤트 · assembly/gov 신호 존재 시 1.0
        · 전일 파생 · placeholder 0.0
    """
    if not signals:
        return []

    # 티커별 · source별 집계
    per_ticker: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for s in signals:
        ticker = s.get("ticker")
        source = s.get("source")
        intensity = float(s.get("intensity") or 0.0)
        if not ticker or not source:
            continue
        per_ticker[ticker][source].append(intensity)

    results: list[TickerScore] = []
    for ticker, by_source in per_ticker.items():
        news_count = sum(len(by_source[s]) for s in by_source if s in _NEWS_SOURCES)
        board_intensity_max = max(
            (max(by_source[s]) for s in by_source if s in _BOARD_SOURCES and by_source[s]),
            default=0.0,
        )
        youtube_count = sum(len(by_source[s]) for s in by_source if s in _YOUTUBE_SOURCES)
        event_present = any(s in _EVENT_SOURCES for s in by_source)
        prev_day_val = max(
            (max(by_source[s]) for s in by_source if s in _PREV_DAY_SOURCES and by_source[s]),
            default=0.0,
        )

        news_score = news_count / 5.0            # 5 mentions = 1.0
        board_score = board_intensity_max        # 이미 z-score
        youtube_score = min(youtube_count, 3) / 3.0
        event_score = 1.0 if event_present else 0.0
        prev_day_score = prev_day_val

        composite = (
            W_NEWS * news_score
            + W_BOARD * board_score
            + W_YOUTUBE * youtube_score
            + W_EVENT * event_score
            + W_PREV_DAY * prev_day_score
        )

        # breakdown (감사용)
        breakdown = {
            s: {"count": len(vals), "intensity_sum": round(sum(vals), 3)}
            for s, vals in by_source.items()
        }

        results.append(TickerScore(
            ticker=ticker,
            composite_score=round(composite, 4),
            news_score=round(news_score, 4),
            board_score=round(board_score, 4),
            youtube_score=round(youtube_score, 4),
            event_score=round(event_score, 4),
            prev_day_score=round(prev_day_score, 4),
            source_breakdown=breakdown,
        ))

    results.sort(key=lambda x: -x.composite_score)
    return results
