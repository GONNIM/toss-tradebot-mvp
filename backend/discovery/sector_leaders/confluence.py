"""Multi-signal Confluence — 4종 시그널 통합 강도 산출 (B-2i-a).

단변량 회귀의 R² 한계를 다중 시그널 일치(confluence)로 보강.

4종 시그널 (이미 가용한 데이터로 산출):
  ① 수출 YoY (회귀 입력값, base)
  ② 지역 일관성 (MotirRegionExport 평균)
  ③ 종목 3M 모멘텀 (KrxDailyCandle)
  ④ 잠정→확정 갱신 추세 (MotirExportHistory)

각 시그널을 -1 ~ +1 로 정규화 → 가중합 → 종합 강도/방향 산출.
음의 상관 종목 (correlation_sign = -1) 은 수출 YoY 부호만 반전.

향후 확장 (B-2i-b):
  ⑤ 원자재 가격 추세 (DDR/NAND, 두바이유 등)
  ⑥ 5.1~25일 사전 데이터
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 데이터 모델
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalContribution:
    name: str            # 'export_yoy' / 'region_consistency' / 'stock_momentum' / 'revision_trend'
    label: str           # 한국어 라벨
    raw_value: Optional[float]
    raw_label: str       # raw_value 표기 (예: '+169.4%')
    normalized: float    # -1 ~ +1
    weight: float
    contribution: float  # normalized × weight
    detail: str          # 자연어 설명
    direction: str       # 'bullish' / 'bearish' / 'neutral'


@dataclass(frozen=True)
class ConfluenceResult:
    score: float                  # -1.0 ~ +1.0 (가중합)
    score_pct: float              # 0~100 (강도 시각화)
    direction: str                # 'bullish' / 'bearish' / 'neutral'
    agreement_count: int          # 같은 방향 시그널 개수
    disagreement_count: int       # 반대 방향 시그널 개수
    total_signals: int            # 0이 아닌 시그널 개수
    contributions: list[SignalContribution]
    grade: str                    # 'strong_bullish'/'moderate_bullish'/'mixed'/'moderate_bearish'/'strong_bearish'
    grade_label: str              # 한국어 등급
    grade_color: str              # 'green' / 'amber' / 'red'
    interpretation: str           # 자연어 종합 해석


# ─────────────────────────────────────────────────────────────────
# 시그널 산출 헬퍼
# ─────────────────────────────────────────────────────────────────


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _sign_direction(v: float, eps: float = 0.05) -> str:
    if v > eps:
        return "bullish"
    if v < -eps:
        return "bearish"
    return "neutral"


# ─────────────────────────────────────────────────────────────────
# 시그널 ① 수출 YoY (base)
# ─────────────────────────────────────────────────────────────────


def signal_export_yoy(yoy_pct: float, correlation_sign: int) -> SignalContribution:
    """수출 YoY → ±50% 를 ±1 로 정규화. 음의 상관 종목은 부호 반전."""
    raw_label = f"{yoy_pct:+.1f}%"
    normalized = _clamp(yoy_pct / 50.0)
    if correlation_sign < 0:
        # 음의 상관: 수출 ↑ 시 주가 ↓ 기대 → 부호 반전
        normalized = -normalized
    weight = 0.35
    contribution = normalized * weight
    direction = _sign_direction(normalized)
    detail = (
        f"수출 YoY {yoy_pct:+.1f}% — "
        + ("강한 상승 시그널" if normalized > 0.5 else
           "완만한 상승" if normalized > 0.1 else
           "강한 하락 시그널" if normalized < -0.5 else
           "완만한 하락" if normalized < -0.1 else
           "중립")
    )
    if correlation_sign < 0:
        detail += " (음의 상관 — 부호 반전 적용)"
    return SignalContribution(
        name="export_yoy",
        label="수출 YoY (메인 시그널)",
        raw_value=yoy_pct,
        raw_label=raw_label,
        normalized=normalized,
        weight=weight,
        contribution=contribution,
        detail=detail,
        direction=direction,
    )


# ─────────────────────────────────────────────────────────────────
# 시그널 ② 지역 일관성
# ─────────────────────────────────────────────────────────────────


def signal_region_consistency(
    region_latest_yoys: dict[str, float],
    correlation_sign: int,
) -> SignalContribution:
    """매핑된 종목의 품목 수출에 대한 지역별 최신 yoy 평균.

    모든 10개 지역(미국·중국·일본·아세안·EU·중동·중남미·CIS·베트남·인도)을
    평균. 향후 매핑 YAML 에 종목별 주력 지역 추가 시 가중 평균으로 확장.
    """
    if not region_latest_yoys:
        return _empty_signal(
            "region_consistency", "지역 일관성", weight=0.25,
            detail="지역 데이터 부재"
        )
    yoys = list(region_latest_yoys.values())
    mean_yoy = sum(yoys) / len(yoys)
    positive_ratio = sum(1 for y in yoys if y > 0) / len(yoys)
    # ±50% 를 ±1 로
    normalized = _clamp(mean_yoy / 50.0)
    if correlation_sign < 0:
        normalized = -normalized
    weight = 0.20
    contribution = normalized * weight
    direction = _sign_direction(normalized)
    pos_pct = positive_ratio * 100
    detail = (
        f"10개 지역 평균 yoy {mean_yoy:+.1f}% · "
        f"양의 yoy {pos_pct:.0f}% ({sum(1 for y in yoys if y > 0)}/{len(yoys)})"
    )
    return SignalContribution(
        name="region_consistency",
        label="지역 일관성",
        raw_value=mean_yoy,
        raw_label=f"평균 {mean_yoy:+.1f}%",
        normalized=normalized,
        weight=weight,
        contribution=contribution,
        detail=detail,
        direction=direction,
    )


# ─────────────────────────────────────────────────────────────────
# 시그널 ③ 종목 3M 모멘텀
# ─────────────────────────────────────────────────────────────────


def signal_stock_momentum(
    monthly_close_by_month: dict[str, float],
    horizon_months: int = 3,
) -> SignalContribution:
    """최근 3M 누적 수익률. ±20% 를 ±1 로 정규화.

    주가 모멘텀은 종목 자체 추세를 반영 — 회귀 입력과 독립.
    """
    if not monthly_close_by_month or len(monthly_close_by_month) < horizon_months + 1:
        return _empty_signal(
            "stock_momentum", "종목 3M 모멘텀", weight=0.20,
            detail="월말 종가 부족"
        )
    sorted_months = sorted(monthly_close_by_month.keys())
    end_close = monthly_close_by_month[sorted_months[-1]]
    start_close = monthly_close_by_month[sorted_months[-1 - horizon_months]]
    if start_close <= 0:
        return _empty_signal(
            "stock_momentum", "종목 3M 모멘텀", weight=0.20,
            detail="시작 종가 비정상"
        )
    momentum_pct = (end_close / start_close - 1) * 100.0
    normalized = _clamp(momentum_pct / 20.0)
    weight = 0.20
    contribution = normalized * weight
    direction = _sign_direction(normalized)
    detail = (
        f"최근 {horizon_months}개월 누적 수익률 {momentum_pct:+.1f}% — "
        + ("강한 상승 추세" if momentum_pct > 15 else
           "완만한 상승" if momentum_pct > 3 else
           "강한 하락" if momentum_pct < -15 else
           "완만한 하락" if momentum_pct < -3 else
           "횡보")
    )
    return SignalContribution(
        name="stock_momentum",
        label="종목 3M 모멘텀",
        raw_value=momentum_pct,
        raw_label=f"{momentum_pct:+.1f}%",
        normalized=normalized,
        weight=weight,
        contribution=contribution,
        detail=detail,
        direction=direction,
    )


# ─────────────────────────────────────────────────────────────────
# 시그널 ④ 잠정→확정 갱신 추세
# ─────────────────────────────────────────────────────────────────


def signal_revision_trend(
    history_revisions: list[tuple[float, float]],
    correlation_sign: int,
) -> SignalContribution:
    """MotirExportHistory 의 (이전 yoy, 현재 final yoy) 페어들의 평균 변화.

    history_revisions: 각 (item, month) 변경 이력의 (이전 yoy, 현재 yoy) 페어.
    양의 변화 (잠정 → 상향 갱신) 평균이 크면 강세.
    """
    if not history_revisions:
        return _empty_signal(
            "revision_trend", "잠정→확정 갱신 추세", weight=0.15,
            detail="갱신 이력 부재 (충돌 0건)"
        )
    deltas = [(curr - prev) for prev, curr in history_revisions]
    mean_delta = sum(deltas) / len(deltas)
    # 평균 변화 ±5%p 를 ±1 로
    normalized = _clamp(mean_delta / 5.0)
    if correlation_sign < 0:
        normalized = -normalized
    weight = 0.10
    contribution = normalized * weight
    direction = _sign_direction(normalized)
    upward = sum(1 for d in deltas if d > 0)
    detail = (
        f"갱신 {len(deltas)}건 중 상향 {upward}건 · "
        f"평균 변화 {mean_delta:+.2f}%p"
    )
    return SignalContribution(
        name="revision_trend",
        label="잠정→확정 갱신 추세",
        raw_value=mean_delta,
        raw_label=f"평균 {mean_delta:+.2f}%p",
        normalized=normalized,
        weight=weight,
        contribution=contribution,
        detail=detail,
        direction=direction,
    )


# ─────────────────────────────────────────────────────────────────
# 시그널 ⑤ 관세청 10일 잠정 (B-2k) — 매크로 사전 시그널
# ─────────────────────────────────────────────────────────────────


def signal_customs_interim(
    interim_yoy_pct: Optional[float],
    period_label: Optional[str],
    correlation_sign: int,
) -> SignalContribution:
    """관세청 10일 단위 잠정 TOTAL YoY → 매크로 사전 시그널.

    매월 11일경 1~10일 / 21일경 1~20일 / 익월 1일 1~말일 발표.
    가장 빠른 전체 시장 시그널 (motir PDF 보다 5~10일 빠름).

    가중치 0.10 — 종합 매크로지만 품목별 시그널이 아니라 작게 적용.
    """
    if interim_yoy_pct is None:
        return _empty_signal(
            "customs_interim",
            "관세청 잠정 (매크로)",
            weight=0.10,
            detail="관세청 잠정 YoY 데이터 부재",
        )
    raw_label = f"{interim_yoy_pct:+.1f}%"
    normalized = _clamp(interim_yoy_pct / 50.0)
    if correlation_sign < 0:
        normalized = -normalized
    weight = 0.10
    contribution = normalized * weight
    direction = _sign_direction(normalized)
    detail = (
        f"전체 시장 {period_label or '잠정'} YoY {interim_yoy_pct:+.1f}% — "
        + ("강한 매크로 상승" if normalized > 0.5 else
           "완만한 상승" if normalized > 0.1 else
           "강한 매크로 하락" if normalized < -0.5 else
           "완만한 하락" if normalized < -0.1 else
           "횡보")
        + " · 매월 11일/21일 발표"
    )
    return SignalContribution(
        name="customs_interim",
        label=f"관세청 잠정 ({period_label or 'TOTAL'})",
        raw_value=interim_yoy_pct,
        raw_label=raw_label,
        normalized=normalized,
        weight=weight,
        contribution=contribution,
        detail=detail,
        direction=direction,
    )


def _empty_signal(
    name: str, label: str, weight: float, detail: str,
) -> SignalContribution:
    return SignalContribution(
        name=name, label=label,
        raw_value=None, raw_label="—",
        normalized=0.0, weight=weight, contribution=0.0,
        detail=detail, direction="neutral",
    )


# ─────────────────────────────────────────────────────────────────
# Confluence 통합
# ─────────────────────────────────────────────────────────────────


def compute_confluence(
    yoy_pct: float,
    region_latest_yoys: dict[str, float],
    monthly_close_by_month: dict[str, float],
    history_revisions: list[tuple[float, float]],
    correlation_sign: int = 1,
    customs_interim_yoy: Optional[float] = None,
    customs_interim_period: Optional[str] = None,
) -> ConfluenceResult:
    """5종 시그널 통합 → ConfluenceResult.

    가중치:
      ① 수출 YoY (메인 품목): 0.35
      ② 지역 일관성: 0.20
      ③ 종목 3M 모멘텀: 0.20
      ④ 잠정→확정 갱신: 0.10
      ⑤ 관세청 잠정 (매크로): 0.10
      합 = 0.95 (모멘텀이 항상 가용)
    """
    contribs: list[SignalContribution] = [
        signal_export_yoy(yoy_pct, correlation_sign),
        signal_region_consistency(region_latest_yoys, correlation_sign),
        signal_stock_momentum(monthly_close_by_month),
        signal_revision_trend(history_revisions, correlation_sign),
        signal_customs_interim(customs_interim_yoy, customs_interim_period, correlation_sign),
    ]
    score = sum(c.contribution for c in contribs)
    # 가용한 시그널만 카운트 (raw_value=None 인 시그널은 데이터 부족)
    active = [c for c in contribs if c.raw_value is not None]
    bullish = sum(1 for c in active if c.direction == "bullish")
    bearish = sum(1 for c in active if c.direction == "bearish")

    if score >= 0.7:
        grade = "strong_bullish"
        grade_label = "강한 매수 동의"
        grade_color = "green"
    elif score >= 0.4:
        grade = "moderate_bullish"
        grade_label = "중간 매수 시그널"
        grade_color = "green"
    elif score >= -0.4:
        grade = "mixed"
        grade_label = "혼재 (단독 판단 금지)"
        grade_color = "amber"
    elif score >= -0.7:
        grade = "moderate_bearish"
        grade_label = "중간 매도 시그널"
        grade_color = "red"
    else:
        grade = "strong_bearish"
        grade_label = "강한 매도 동의"
        grade_color = "red"

    direction = _sign_direction(score, eps=0.05)

    interpretation = _build_interpretation(
        score, bullish, bearish, len(active), correlation_sign,
    )

    return ConfluenceResult(
        score=score,
        score_pct=abs(score) * 100,
        direction=direction,
        agreement_count=max(bullish, bearish),
        disagreement_count=min(bullish, bearish),
        total_signals=len(active),
        contributions=contribs,
        grade=grade,
        grade_label=grade_label,
        grade_color=grade_color,
        interpretation=interpretation,
    )


def _build_interpretation(
    score: float, bullish: int, bearish: int, total: int, correlation_sign: int,
) -> str:
    """종합 자연어 해석."""
    if total == 0:
        return "데이터 부족 — 시그널 산출 불가."
    parts = []
    if score >= 0.7:
        parts.append(f"{bullish}/{total} 시그널이 강세 동의 — 매우 강한 매수 시그널.")
    elif score >= 0.4:
        parts.append(f"{bullish}/{total} 시그널이 상승 — 중간 강도 매수 시그널.")
    elif score >= -0.4:
        parts.append(
            f"시그널 혼재 (강세 {bullish} · 약세 {bearish}) — 단변량 회귀만 으로 단독 판단 위험."
        )
    elif score >= -0.7:
        parts.append(f"{bearish}/{total} 시그널이 하락 — 중간 강도 매도 시그널.")
    else:
        parts.append(f"{bearish}/{total} 시그널이 강세 동의 매도 — 매우 강한 약세.")

    if correlation_sign < 0:
        parts.append("(음의 상관 종목 — 부호 반전 적용)")
    return " ".join(parts)
