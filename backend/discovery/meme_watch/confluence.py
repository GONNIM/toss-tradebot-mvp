"""Meme Confluence Score — 02 plan 공식 구현 (Phase 1e MVP).

5요소 중 Phase 1 가용:
  ② 소셜 모멘텀 (apewisdom mentions/upvotes/24h 비교) — 가중치 0.30
  ③ 유동성 폭주 (meme_volume_snapshot.volume_z_20d)          — 가중치 0.25
  ④ Oversold + 반전 (rsi_14 + return_1d_pct)                — 가중치 0.15

Phase 2 추가 예정:
  ① 공매도 — KRX/FINRA — 가중치 0.30
  ⑤ Catalyst — VI/halt/공시 — 가중치 0.15

동적 가중치 재정규화 (소스 결손 시 자동 보정 — [[partner_accountability]]).
Phase 1e MVP 가용 가중치 합 = 0.70 → 재정규화 시 social 0.43 / volume 0.36 /
oversold 0.21 (합 1.0).

라벨 (정규화된 score 0~1.5):
  ≥ 1.00 → 🔥🔥 BLAZING / ≥ 0.75 → 🔥 HOT / ≥ 0.50 → ⚠️ WATCH /
  ≥ 0.25 → 👀 OBSERVE / < 0.25 → 💤 SLEEP
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SignalContribution:
    name: str            # "social" / "volume" / "oversold" / "short" / "catalyst"
    label: str           # 한국어 라벨
    raw_value: Optional[float]
    raw_label: str       # 사람 가독 (예: "+8σ", "23%", "RSI 22")
    normalized: float    # [0, 1.5]
    weight: float        # 재정규화된 가중치
    contribution: float  # normalized × weight
    detail: str          # 사용자 설명


@dataclass(frozen=True)
class MemeScore:
    ticker: str
    score: float
    label: str
    emoji: str
    active_signals: int          # normalized ≥ 0.5 인 시그널 개수
    strongest_signal: str        # 최대 contribution 시그널 이름
    confidence_label: str        # "strong" / "medium" / "weak"
    sample_warning: bool
    contributions: list[SignalContribution]


# Phase 1 base 가중치 (catalyst 후속 — 가중치 0.15 reserve)
_BASE_WEIGHTS = {
    "short": 0.30,
    "social": 0.30,
    "volume": 0.25,
    "oversold": 0.15,
}
_CATALYST_WEIGHT = 0.15


def normalize_weights(available: set[str]) -> dict[str, float]:
    """가용 시그널 집합 → 합 1.0 으로 재정규화."""
    base = dict(_BASE_WEIGHTS)
    if "catalyst" in available:
        base = {k: v * (1 - _CATALYST_WEIGHT) for k, v in base.items()}
        base["catalyst"] = _CATALYST_WEIGHT
    active = {k: v for k, v in base.items() if k in available}
    s = sum(active.values())
    if s <= 0:
        return {}
    return {k: v / s for k, v in active.items()}


# ─────────────────────────────────────────────────────────────────
# 시그널별 정규화 [0, 1.5]
# ─────────────────────────────────────────────────────────────────


def _normalize_apewisdom(
    mentions: int, mentions_24h_ago: Optional[int], upvotes: int
) -> tuple[float, str, float]:
    """apewisdom mentions 24h vs 전일 비율 + upvote 강도."""
    if not mentions:
        return 0.0, "0 mentions", 0.0
    if not mentions_24h_ago:
        ratio = mentions / 100.0
    else:
        ratio = mentions / max(1, mentions_24h_ago)

    if ratio >= 5.0:
        n = 1.5
    elif ratio >= 3.0:
        n = 1.0 + (ratio - 3.0) * 0.25
    elif ratio >= 2.0:
        n = 0.7 + (ratio - 2.0) * 0.3
    elif ratio >= 1.5:
        n = 0.4 + (ratio - 1.5) * 0.6
    elif ratio >= 1.0:
        n = 0.2 + (ratio - 1.0) * 0.4
    else:
        n = 0.0

    if mentions > 0 and (upvotes / mentions) >= 5.0:
        n = min(1.5, n + 0.1)

    raw_label = f"{mentions:,}↑/{mentions_24h_ago or 0:,} ({ratio:.1f}×)"
    return n, raw_label, ratio


def _normalize_trends(score_24h: Optional[int]) -> tuple[float, str]:
    """Google Trends 검색량 0~100 → normalized [0, 1.5]."""
    if score_24h is None or score_24h <= 0:
        return 0.0, ""
    # 100 = 최대 (검색량 폭증) → 1.5
    # 80+ → 1.0
    # 50+ → 0.7
    # 30+ → 0.4
    # 15+ → 0.2
    if score_24h >= 90:
        n = 1.5
    elif score_24h >= 70:
        n = 1.0 + (score_24h - 70) / 20 * 0.5
    elif score_24h >= 50:
        n = 0.7 + (score_24h - 50) / 20 * 0.3
    elif score_24h >= 30:
        n = 0.4 + (score_24h - 30) / 20 * 0.3
    elif score_24h >= 15:
        n = 0.2 + (score_24h - 15) / 15 * 0.2
    else:
        n = 0.0
    return n, f"Trends {score_24h}"


def normalize_social(
    mentions: int,
    mentions_24h_ago: Optional[int],
    upvotes: int,
    trends_score_24h: Optional[int] = None,
) -> tuple[float, str, float]:
    """apewisdom + Google Trends 통합 소셜 시그널.

    두 sub-source 다 가용 시 max(apewisdom, trends) 사용 —
    한쪽만 강해도 시그널 인식. trends 만 가용 시 그 값 사용.

    Returns: (normalized, raw_label, raw_value)
    """
    ape_n, ape_label, ape_ratio = _normalize_apewisdom(
        mentions, mentions_24h_ago, upvotes
    )
    trends_n, trends_label = _normalize_trends(trends_score_24h)

    # 두 sub-source max — 하나가 강하면 그 시그널 인정
    n = max(ape_n, trends_n)

    if ape_n > 0 and trends_n > 0:
        raw_label = f"{ape_label} · {trends_label}"
    elif trends_n > 0:
        raw_label = trends_label
    else:
        raw_label = ape_label

    return n, raw_label, ape_ratio


def normalize_volume(
    volume_ratio_20d: Optional[float],
    volume_z_20d: Optional[float] = None,
) -> tuple[float, str, float]:
    """거래량 정규화 (Phase 2 튜닝).

    배수 우선 사용 — 1배 미만 0, 2배 0.5, 5배 1.0, 10배+ 1.5.
    배수 없으면 z-score (구식) fallback.
    """
    if volume_ratio_20d is not None and volume_ratio_20d > 0:
        r = volume_ratio_20d
        if r < 1.0:
            n = 0.0
        elif r <= 2.0:
            n = (r - 1.0) * 0.5
        elif r <= 5.0:
            n = 0.5 + (r - 2.0) / 3.0 * 0.5
        elif r <= 10.0:
            n = 1.0 + (r - 5.0) / 5.0 * 0.5
        else:
            n = 1.5
        return n, f"{r:.1f}× (20D 평균 대비)", r

    if volume_z_20d is not None:
        n = max(0.0, min(1.5, volume_z_20d / 10.0))
        return n, f"+{volume_z_20d:.1f}σ", float(volume_z_20d)

    return 0.0, "—", 0.0


def normalize_momentum(
    rsi_14: Optional[float], return_1d_pct: Optional[float]
) -> tuple[float, str, float]:
    """Momentum / Breakout — 02 plan 의 Oversold 재정의 (Phase 2 튜닝).

    백테스트에서 밈주 폭등이 RSI > 70 상태에서 추가 폭발임을 확인.
    "Oversold + 반등" 은 별개 케이스로 보존 (시그널 강도 0.6).

    Returns: (normalized, raw_label, raw_value=rsi)
    """
    if rsi_14 is None or return_1d_pct is None:
        return 0.0, "—", 0.0

    # Breakout — 강한 폭등 + 강세 RSI
    if return_1d_pct >= 10 and rsi_14 >= 70:
        n = 1.0
    # Breakout 후보 — 폭등 + 중강 RSI
    elif return_1d_pct >= 5 and rsi_14 >= 65:
        n = 0.7
    # 약한 폭등
    elif return_1d_pct >= 3:
        n = 0.4
    # Oversold 반전 (별개 — 하락 후 반등)
    elif rsi_14 <= 30 and return_1d_pct >= 5:
        n = 0.6
    else:
        n = 0.0
    return n, f"RSI {rsi_14:.0f} · 1D {return_1d_pct:+.1f}%", float(rsi_14)


# 하위 호환 — 기존 코드 (이전 normalize_oversold 호출처) 보존
normalize_oversold = normalize_momentum


# ─────────────────────────────────────────────────────────────────
# 시그널 종합
# ─────────────────────────────────────────────────────────────────


def _label_and_emoji(score: float) -> tuple[str, str]:
    if score >= 1.00:
        return "BLAZING", "🔥🔥"
    if score >= 0.75:
        return "HOT", "🔥"
    if score >= 0.50:
        return "WATCH", "⚠️"
    if score >= 0.25:
        return "OBSERVE", "👀"
    return "SLEEP", "💤"


def normalize_catalyst(return_1d_pct: Optional[float]) -> tuple[float, str, float]:
    """Catalyst 시그널 (Phase 2-D) — 1D gap up 자동 검출.

    KRX VI 발동 / FINRA halt / DART 공시 등 외부 트리거는 후속 phase.
    1차 MVP: 일봉 return 자체로 trigger event 추정.

    +30%+ → 1.0 (확실한 catalyst)
    +20%+ → 0.7
    +15%+ → 0.5
    +10%+ → 0.3
    그 외 → 0.0
    """
    if return_1d_pct is None:
        return 0.0, "—", 0.0
    if return_1d_pct >= 30:
        n = 1.0
    elif return_1d_pct >= 20:
        n = 0.7
    elif return_1d_pct >= 15:
        n = 0.5
    elif return_1d_pct >= 10:
        n = 0.3
    else:
        n = 0.0
    return n, f"1D {return_1d_pct:+.1f}% (gap)", float(return_1d_pct)


def compute_meme_score(
    *,
    ticker: str,
    social_inputs: Optional[dict] = None,  # {mentions, mentions_24h_ago, upvotes}
    volume_z_20d: Optional[float] = None,
    volume_ratio_20d: Optional[float] = None,    # Phase 2 튜닝 — 우선
    rsi_14: Optional[float] = None,
    return_1d_pct: Optional[float] = None,
    short_pct_of_float: Optional[float] = None,  # Phase 2
    catalyst_score: Optional[float] = None,      # 외부 catalyst (VI/halt 등)
) -> MemeScore:
    """5요소 confluence — 가용 시그널만으로 가중치 재정규화."""
    contributions: list[SignalContribution] = []
    available: set[str] = set()

    # ② Social — apewisdom + Google Trends (Phase 3-C)
    if social_inputs is not None:
        n, label, raw = normalize_social(
            social_inputs.get("mentions") or 0,
            social_inputs.get("mentions_24h_ago"),
            social_inputs.get("upvotes") or 0,
            social_inputs.get("trends_score_24h"),
        )
        has_any_signal = (
            social_inputs.get("mentions")
            or social_inputs.get("trends_score_24h")
        )
        if n > 0 or has_any_signal:
            available.add("social")
            contributions.append(
                SignalContribution(
                    name="social",
                    label="소셜 모멘텀",
                    raw_value=raw,
                    raw_label=label,
                    normalized=n,
                    weight=0.0,
                    contribution=0.0,
                    detail="apewisdom 24h 언급 + Google Trends 검색량 (max)",
                )
            )

    # ③ Volume — Phase 2 튜닝: 배수 우선, z fallback
    if volume_ratio_20d is not None or volume_z_20d is not None:
        n, label, raw = normalize_volume(volume_ratio_20d, volume_z_20d)
        available.add("volume")
        contributions.append(
            SignalContribution(
                name="volume",
                label="유동성 폭주",
                raw_value=raw,
                raw_label=label,
                normalized=n,
                weight=0.0,
                contribution=0.0,
                detail="20D 평균 대비 거래량 배수 (또는 z-score fallback)",
            )
        )

    # ④ Momentum / Breakout (Phase 2 재정의 — 기존 Oversold 명칭 유지하되 의미 확장)
    if rsi_14 is not None and return_1d_pct is not None:
        n, label, raw = normalize_momentum(rsi_14, return_1d_pct)
        available.add("oversold")  # weight key 그대로 — backward compat
        contributions.append(
            SignalContribution(
                name="oversold",
                label="Momentum / Breakout",
                raw_value=raw,
                raw_label=label,
                normalized=n,
                weight=0.0,
                contribution=0.0,
                detail="RSI ≥ 70 + 1D ≥ +10% (강한 폭등) 또는 RSI ≤ 30 + 반등 (Oversold)",
            )
        )

    # ① Short (Phase 2 — 보유 시 추가)
    if short_pct_of_float is not None:
        # US 트랙 — 5% 임계 (한국 5%, 미국 15% 차이는 추후 시장별 분기)
        n = min(1.5, max(0.0, short_pct_of_float / 15.0))
        available.add("short")
        contributions.append(
            SignalContribution(
                name="short",
                label="공매도 잔고",
                raw_value=short_pct_of_float,
                raw_label=f"{short_pct_of_float:.1f}%",
                normalized=n,
                weight=0.0,
                contribution=0.0,
                detail="유동주식 대비 공매도 잔고 비율",
            )
        )

    # ⑤ Catalyst (Phase 2-D)
    # 외부 catalyst 미명시 시 1D return 으로 자동 gap up 검출 (10%↑ 부터)
    if catalyst_score is not None:
        n = max(0.0, min(1.5, catalyst_score))
        raw_label = f"{catalyst_score:.2f}"
        raw_val = catalyst_score
        detail = "VI/halt/공시 등 외부 트리거"
    elif return_1d_pct is not None and return_1d_pct >= 10:
        n, raw_label, raw_val = normalize_catalyst(return_1d_pct)
        detail = "1D gap up ≥ +10% (외부 catalyst 부재 시 자동 추정)"
    else:
        n = None

    if n is not None:
        available.add("catalyst")
        contributions.append(
            SignalContribution(
                name="catalyst",
                label="Catalyst",
                raw_value=raw_val,
                raw_label=raw_label,
                normalized=n,
                weight=0.0,
                contribution=0.0,
                detail=detail,
            )
        )

    # 가중치 재정규화
    weights = normalize_weights(available)
    score = 0.0
    new_contributions: list[SignalContribution] = []
    for c in contributions:
        w = weights.get(c.name, 0.0)
        contrib = c.normalized * w
        score += contrib
        new_contributions.append(
            SignalContribution(
                name=c.name,
                label=c.label,
                raw_value=c.raw_value,
                raw_label=c.raw_label,
                normalized=c.normalized,
                weight=w,
                contribution=contrib,
                detail=c.detail,
            )
        )

    label, emoji = _label_and_emoji(score)
    active = sum(1 for c in new_contributions if c.normalized >= 0.5)
    strongest = (
        max(new_contributions, key=lambda c: c.contribution).name
        if new_contributions
        else "—"
    )
    if len(new_contributions) >= 4:
        conf_label = "strong"
    elif len(new_contributions) == 3:
        conf_label = "medium"
    else:
        conf_label = "weak"
    sample_warning = len(new_contributions) < 3

    return MemeScore(
        ticker=ticker,
        score=score,
        label=label,
        emoji=emoji,
        active_signals=active,
        strongest_signal=strongest,
        confidence_label=conf_label,
        sample_warning=sample_warning,
        contributions=new_contributions,
    )
