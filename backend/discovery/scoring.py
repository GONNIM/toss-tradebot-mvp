"""9 인자 가중 스코어링 — Moonshot 결정 32 학술 검증 후 가중.

가중치 합 = 100%:
  - 카탈리스트 (F2)         30%   ← 어닝/FDA/M&A 등
  - 갭+거래량 (F2-b)        12%   ← gap-up + 거래량 surge
  - 변동성                  12%   ← intraday range / ATR
  - 뉴스 (LLM)              12%   ← Claude Haiku 분석
  - 인사이더 매수 (F6)      10%   ← SEC Form 4 cluster ≥3/15d
  - 소셜 (F4)                8%   ← WSB 멘션 카운트
  - 기술적                   8%   ← RSI/MACD/EMA
  - 스퀴즈 (F1)              6%   ← FINRA short ratio
  - 52w 저점                 2%   ← AZTR 패턴 (bounce hypothesis)

각 인자는 0~100 정규화 → 가중 합.

Crazy vs Moonshot:
  - Crazy: 시가총액 ≥ $1B (safe)
  - Moonshot: 모든 미국 주식 (페니스톡 포함)
  - 동일 스코어링 함수, universe 만 다름.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

WEIGHTS: dict[str, float] = {
    "catalyst":       0.30,
    "gap_volume":     0.12,
    "volatility":     0.12,
    "news_llm":       0.12,
    "insider":        0.10,
    "social":         0.08,
    "technical":      0.08,
    "squeeze":        0.06,
    "low_52w":        0.02,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-6, "Weights must sum to 1.0"


@dataclass
class FactorScores:
    """단일 종목의 9 인자 점수 (각 0~100)."""

    ticker: str
    catalyst: float = 0.0
    gap_volume: float = 0.0
    volatility: float = 0.0
    news_llm: float = 0.0
    insider: float = 0.0
    social: float = 0.0
    technical: float = 0.0
    squeeze: float = 0.0
    low_52w: float = 0.0

    raw_inputs: dict = field(default_factory=dict)  # 원본 측정값 (디버그)

    def total(self) -> float:
        """가중 합 (0~100)."""
        return (
            self.catalyst * WEIGHTS["catalyst"]
            + self.gap_volume * WEIGHTS["gap_volume"]
            + self.volatility * WEIGHTS["volatility"]
            + self.news_llm * WEIGHTS["news_llm"]
            + self.insider * WEIGHTS["insider"]
            + self.social * WEIGHTS["social"]
            + self.technical * WEIGHTS["technical"]
            + self.squeeze * WEIGHTS["squeeze"]
            + self.low_52w * WEIGHTS["low_52w"]
        )

    def breakdown(self) -> dict[str, float]:
        """가중 기여도 분해 (디버그용)."""
        return {
            "catalyst":   self.catalyst   * WEIGHTS["catalyst"],
            "gap_volume": self.gap_volume * WEIGHTS["gap_volume"],
            "volatility": self.volatility * WEIGHTS["volatility"],
            "news_llm":   self.news_llm   * WEIGHTS["news_llm"],
            "insider":    self.insider    * WEIGHTS["insider"],
            "social":     self.social     * WEIGHTS["social"],
            "technical":  self.technical  * WEIGHTS["technical"],
            "squeeze":    self.squeeze    * WEIGHTS["squeeze"],
            "low_52w":    self.low_52w    * WEIGHTS["low_52w"],
        }


# ─────────────────────────────────────────────
# 인자별 정규화 함수 (raw 측정값 → 0~100)
# ─────────────────────────────────────────────


def score_catalyst(
    earnings_days: Optional[int] = None,  # 어닝 D-day (음수=과거)
    fda_pdufa: bool = False,
    ma_announcement: bool = False,
    news_count_24h: int = 0,
) -> float:
    """카탈리스트 점수 (가중 30%)."""
    score = 0.0
    # 임박 어닝 (D-7 이내) → 60점
    if earnings_days is not None and 0 <= earnings_days <= 7:
        score += 60 - earnings_days * 5  # D-0=60, D-7=25
    # FDA PDUFA / M&A → 80점
    if fda_pdufa:
        score = max(score, 80)
    if ma_announcement:
        score = max(score, 90)
    # PR 뉴스 노출 (max 20점)
    score += min(news_count_24h * 4, 20)
    return min(score, 100.0)


def score_gap_volume(
    gap_pct: float = 0.0,
    volume_ratio: float = 1.0,  # 당일 / 평균 20일
) -> float:
    """갭업 + 거래량 점수 (가중 12%).

    EHGO 패턴: gap >+30% + volume >5x → 100점
    """
    gap_score = 0.0
    if gap_pct >= 30:
        gap_score = 100
    elif gap_pct >= 15:
        gap_score = 70
    elif gap_pct >= 7:
        gap_score = 40
    elif gap_pct >= 3:
        gap_score = 20

    vol_score = 0.0
    if volume_ratio >= 10:
        vol_score = 100
    elif volume_ratio >= 5:
        vol_score = 70
    elif volume_ratio >= 3:
        vol_score = 50
    elif volume_ratio >= 2:
        vol_score = 30

    return 0.6 * gap_score + 0.4 * vol_score


def score_volatility(intraday_range_pct: float = 0.0, atr_pct: float = 0.0) -> float:
    """변동성 점수 (가중 12%). intraday range + ATR (% of price)."""
    range_score = min(intraday_range_pct * 4, 100)  # 25% range → 100
    atr_score = min(atr_pct * 10, 100)              # 10% ATR → 100
    return 0.6 * range_score + 0.4 * atr_score


def score_news_llm(llm_manipulation_risk: int = 3, has_thesis: bool = True) -> float:
    """LLM 뉴스 분석 점수 (가중 12%).

    manipulation_risk 1~5 → 점수 80~0 (낮을수록 안전).
    thesis 없으면 0.
    """
    if not has_thesis:
        return 0.0
    base = max(0, 100 - llm_manipulation_risk * 20)  # 1→80, 5→0
    return base


def score_insider(distinct_buyers: int = 0, cluster_detected: bool = False) -> float:
    """SEC Form 4 인사이더 매수 (가중 10%).

    학술: 3+ cluster within 15d → strong signal
    """
    if cluster_detected:
        return min(100, 70 + (distinct_buyers - 3) * 10)  # 3=70, 4=80, ..., 6+=100
    # cluster 미달
    if distinct_buyers == 2:
        return 40
    if distinct_buyers == 1:
        return 20
    return 0


def score_social(mention_count: int = 0, distinct_authors: int = 0) -> float:
    """Reddit WSB 멘션 (가중 8%)."""
    if mention_count >= 50:
        return 100
    if mention_count >= 20:
        return 70
    if mention_count >= 10:
        return 50
    if mention_count >= 5:
        return 30
    if mention_count >= 1:
        return 10
    return 0


def score_technical(
    rsi: Optional[float] = None,
    above_ema_20: bool = False,
    macd_bullish: bool = False,
) -> float:
    """기술적 지표 (가중 8%). RSI 50~70 sweet spot."""
    score = 0.0
    if rsi is not None:
        if 50 <= rsi <= 70:
            score += 60
        elif 70 < rsi <= 80:
            score += 40
        elif 30 <= rsi < 50:
            score += 30
    if above_ema_20:
        score += 20
    if macd_bullish:
        score += 20
    return min(score, 100.0)


def score_squeeze(short_ratio: float = 0.0, trend_up: bool = False) -> float:
    """FINRA 단기매도 (가중 6%). 0.0~1.0 비율."""
    base = 0.0
    if short_ratio >= 0.5:
        base = 100
    elif short_ratio >= 0.3:
        base = 60
    elif short_ratio >= 0.2:
        base = 30
    return base + (10 if trend_up else 0)


def score_low_52w(distance_from_low_pct: float = 100.0) -> float:
    """52주 저점 근접도 (가중 2%). AZTR 패턴 — 저점 +10% 이내 강한 신호."""
    if distance_from_low_pct <= 5:
        return 100
    if distance_from_low_pct <= 10:
        return 70
    if distance_from_low_pct <= 20:
        return 40
    if distance_from_low_pct <= 50:
        return 10
    return 0


# ─────────────────────────────────────────────
# 통합 스코어링
# ─────────────────────────────────────────────


def compute_factor_scores(ticker: str, inputs: dict) -> FactorScores:
    """전체 인자 입력 dict → FactorScores.

    inputs 예시:
        {
            "earnings_days": 5,
            "fda_pdufa": False,
            "news_count_24h": 3,
            "gap_pct": 12.0,
            "volume_ratio": 4.5,
            "intraday_range_pct": 8.0,
            "atr_pct": 5.5,
            "llm_manipulation_risk": 2,
            "has_thesis": True,
            "distinct_insider_buyers": 4,
            "insider_cluster": True,
            "wsb_mention_count": 15,
            "wsb_distinct_authors": 8,
            "rsi": 62.0,
            "above_ema_20": True,
            "macd_bullish": True,
            "short_ratio": 0.35,
            "short_trend_up": True,
            "distance_from_52w_low_pct": 8.0,
        }
    """
    scores = FactorScores(
        ticker=ticker,
        catalyst=score_catalyst(
            earnings_days=inputs.get("earnings_days"),
            fda_pdufa=inputs.get("fda_pdufa", False),
            ma_announcement=inputs.get("ma_announcement", False),
            news_count_24h=inputs.get("news_count_24h", 0),
        ),
        gap_volume=score_gap_volume(
            gap_pct=inputs.get("gap_pct", 0.0),
            volume_ratio=inputs.get("volume_ratio", 1.0),
        ),
        volatility=score_volatility(
            intraday_range_pct=inputs.get("intraday_range_pct", 0.0),
            atr_pct=inputs.get("atr_pct", 0.0),
        ),
        news_llm=score_news_llm(
            llm_manipulation_risk=inputs.get("llm_manipulation_risk", 3),
            has_thesis=inputs.get("has_thesis", False),
        ),
        insider=score_insider(
            distinct_buyers=inputs.get("distinct_insider_buyers", 0),
            cluster_detected=inputs.get("insider_cluster", False),
        ),
        social=score_social(
            mention_count=inputs.get("wsb_mention_count", 0),
            distinct_authors=inputs.get("wsb_distinct_authors", 0),
        ),
        technical=score_technical(
            rsi=inputs.get("rsi"),
            above_ema_20=inputs.get("above_ema_20", False),
            macd_bullish=inputs.get("macd_bullish", False),
        ),
        squeeze=score_squeeze(
            short_ratio=inputs.get("short_ratio", 0.0),
            trend_up=inputs.get("short_trend_up", False),
        ),
        low_52w=score_low_52w(
            distance_from_low_pct=inputs.get("distance_from_52w_low_pct", 100.0),
        ),
        raw_inputs=dict(inputs),
    )
    return scores


def classify_risk(
    market_cap_usd: Optional[float],
    current_price: float,
) -> str:
    """Decision 40 위험 분류.

    HIGH: 시총 < $50M OR 가격 < $1 (페니스톡)
    MED:  시총 $50M ~ $500M
    LOW:  시총 ≥ $500M
    """
    if current_price < 1.0:
        return "HIGH"
    if market_cap_usd is None:
        return "MED"  # 미상은 보수적으로 MED
    if market_cap_usd < 50_000_000:
        return "HIGH"
    if market_cap_usd < 500_000_000:
        return "MED"
    return "LOW"
