"""Watchlist Composite Score v2 · 1030-04.

공식 버전: SCORE_VERSION = "watchlist-v2-2026-10-30"

칸 5개를 각각 0~1 로 만든 뒤, **수집 중인 칸끼리** 가중을 다시 맞춰 합친다 (합성도 0~1).

    composite = Σ(w_i · score_i) / Σ(w_i)        i ∈ 수집 중인 칸

    칸        기본 가중   칸 점수 (0~1)
    news      0.35       0.6 · min(1, Σintensity / 3) + 0.4 · min(1, 서로 다른 언론사 수 / 3)
                         (intensity = 기사 한 건의 종목 가중 · 4종목 이상 기사는 1/n · 요약에서만이면 ×0.5)
                         같은 언론의 피드 둘은 한 곳으로 센다 (source_groups.NEWS_PUBLISHER)
    interest  0.25       개인 관심 = 순위 신호(개인 순매수·토스증권 체결 거래대금·거래량) 중
                         가장 강한 intensity + 0.15 × (겹친 종류 수 − 1) · 상한 1
    youtube   0.15       min(영상 수, 3) / 3
    event     0.15       dart_disclosure·assembly·정부 보도자료가 하나라도 있으면 1.0
                         (dart_caution 주의 공시는 점수 0 — 화면에 「주의 공시」로만 표시)
    prev_day  0.10       시장 거래대금·거래량 새 진입/상승 신호 중 가장 강한 intensity
                         + 0.15 × (겹친 종류 수 − 1) · 상한 1

수집 여부 판정은 collecting.collecting_categories() 한 곳이다 (화면 /watchlist/sources 와 공유).
DB 컬럼은 기존 이름을 재사용한다: news_score · board_score(= 개인 관심) · youtube_score · event_score · prev_day_score.

이전 공식(v1, 2026-07)은 종토방 z-score 를 0~1 로 못 맞춰 합이 1 을 넘었다. 옛 board_naver 신호는 점수에 넣지 않는다.

계획서: docs/plans/sniper/2026-10-30-watchlist-data-rework.md
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from . import source_groups as sg

logger = logging.getLogger(__name__)

SCORE_VERSION = "watchlist-v2-2026-10-30"

# ─── 가중치 (기본값 · 수집 중인 칸끼리 재정규화) ───────────
W_NEWS = 0.35
W_INTEREST = 0.25
W_YOUTUBE = 0.15
W_EVENT = 0.15
W_PREV_DAY = 0.10
WEIGHTS: dict[str, float] = {
    "news": W_NEWS, "interest": W_INTEREST, "youtube": W_YOUTUBE,
    "event": W_EVENT, "prev_day": W_PREV_DAY,
}

# 뉴스: 기사 가중 합 3.0 이면 만점(3건 단독 보도 수준) · 언론사 3곳이면 만점. 한 곳이 도배해도 0.6 을 못 넘는다.
_NEWS_SUM_CAP = 3.0
_NEWS_PUBLISHER_CAP = 3
_NEWS_W_SUM = 0.6
_NEWS_W_PUBLISHERS = 0.4
# 순위: 서로 다른 순위가 겹치면 (예: 개인 순매수 + 토스 거래대금) 한쪽만일 때보다 확실하다
_RANK_OVERLAP_BONUS = 0.15
_YOUTUBE_CAP = 3


@dataclass
class TickerScore:
    ticker: str
    composite_score: float
    news_score: float = 0.0
    board_score: float = 0.0          # = 개인 관심 (옛 종토방 컬럼 재사용)
    youtube_score: float = 0.0
    event_score: float = 0.0
    prev_day_score: float = 0.0
    # source_breakdown[source] = {"count": N, "intensity_sum": X}
    source_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    used_weights: dict[str, float] = field(default_factory=dict)


def _rank_score(by_source: dict[str, list[float]], sources: set[str]) -> float:
    vals = [max(by_source[s]) for s in by_source if s in sources and by_source[s]]
    if not vals:
        return 0.0
    return min(1.0, max(vals) + _RANK_OVERLAP_BONUS * (len(vals) - 1))


def normalized_weights(collecting: dict[str, bool]) -> dict[str, float]:
    """수집 중인 칸끼리 합이 1 이 되게 다시 맞춘 가중 · 수집 중인 칸이 없으면 빈 dict."""
    active = {k: w for k, w in WEIGHTS.items() if collecting.get(k)}
    total = sum(active.values())
    if total <= 0:
        return {}
    return {k: round(w / total, 6) for k, w in active.items()}


def score_signals(
    signals: list[dict[str, Any]],
    collecting: Optional[dict[str, bool]] = None,
) -> list[TickerScore]:
    """signals (WatchlistSignal 딕셔너리 리스트) → 티커별 TickerScore 리스트.

    Args:
        signals: store.signals_for_date() 반환값 · [{ticker, source, intensity, ...}]
        collecting: 칸별 수집 여부 · None 이면 collecting.collecting_categories() (환경 조회)

    Returns:
        composite_score 내림차순 정렬된 TickerScore 리스트.
    """
    if not signals:
        return []
    if collecting is None:
        from .collecting import collecting_categories

        collecting = collecting_categories()
    weights = normalized_weights(collecting)

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
        news_sum = sum(sum(v) for s, v in by_source.items() if s in sg.NEWS_SOURCES)
        publishers = {sg.NEWS_PUBLISHER[s] for s in by_source if s in sg.NEWS_SOURCES}
        news_score = (
            _NEWS_W_SUM * min(1.0, news_sum / _NEWS_SUM_CAP)
            + _NEWS_W_PUBLISHERS * min(1.0, len(publishers) / _NEWS_PUBLISHER_CAP)
        ) if publishers else 0.0
        interest_score = _rank_score(by_source, sg.INTEREST_SOURCES)
        youtube_count = sum(len(v) for s, v in by_source.items() if s in sg.YOUTUBE_SOURCES)
        youtube_score = min(youtube_count, _YOUTUBE_CAP) / _YOUTUBE_CAP
        event_score = 1.0 if any(s in sg.EVENT_SOURCES for s in by_source) else 0.0
        prev_day_score = _rank_score(by_source, sg.PREV_DAY_SOURCES)

        cells = {
            "news": news_score, "interest": interest_score, "youtube": youtube_score,
            "event": event_score, "prev_day": prev_day_score,
        }
        composite = sum(weights[k] * cells[k] for k in weights)

        # breakdown (감사용)
        breakdown = {
            s: {"count": len(vals), "intensity_sum": round(sum(vals), 3)}
            for s, vals in by_source.items()
        }

        results.append(TickerScore(
            ticker=ticker,
            composite_score=round(composite, 4),
            news_score=round(news_score, 4),
            board_score=round(interest_score, 4),
            youtube_score=round(youtube_score, 4),
            event_score=round(event_score, 4),
            prev_day_score=round(prev_day_score, 4),
            source_breakdown=breakdown,
            used_weights=weights,
        ))

    results.sort(key=lambda x: -x.composite_score)
    return results
