"""진입가 산출 v2.0 — 52W 위치 + ATR14 + 과열 판정.

기획: docs/plans/sector-leaders-top10-entry-refinement/plan.md §5

기존 로직 (top10.py:279-290) 은 `min(현재가, 점추정×0.9)` 로 대부분 현재가를 반환 →
낙관적 예측이면 최고점에서도 "지금 매수" 표시. 본 모듈은 그것을 대체한다.

핵심 원칙:
1. **과열 판정 우선**: 52W 위치 ≥ 85% OR 200MA 이격 ≥ +25% → 진입가 None + 관망
2. **변동성 조정 진입가**: 현재가 − 1.0 × ATR14 (표준 스케일)
3. **데이터 부족 fallback**: 시계열 짧으면 조건 완화 (진입가 산출은 가능)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────────

TRADING_DAYS_52W = 252            # 약 1년 거래일
TRADING_DAYS_200MA = 200
ATR_PERIOD = 14
OVERHEAT_52W_THRESHOLD = 0.85     # 52W 상위 15%
OVERHEAT_MA200_THRESHOLD = 0.25   # 200MA 대비 +25% 이상
ATR_ENTRY_MULTIPLIER = 1.0        # 표준 스케일 (v2.1에서 0.5/1.0/1.5 3단계)
NEAR_ENTRY_TOLERANCE_PCT = 0.5    # 진입가 대비 ±0.5% 이내면 "지금 매수"
ATR_FALLBACK_PCT = 0.02           # ATR 계산 실패 시 현재가의 2%


@dataclass(frozen=True)
class EntryPriceResult:
    """진입가 산출 결과."""

    entry_price: Optional[float]       # 과열 시 None
    entry_status: str                  # 🟢/🟡/🔴 + 설명
    entry_gap_pct: Optional[float]     # 현재가 대비 %, 과열 시 None

    high_52w: float
    low_52w: float
    pos_52w: float                     # 0.0 ~ 1.0

    atr14: float
    ma200: Optional[float]             # 데이터 부족 시 None
    ma200_deviation: Optional[float]   # 200MA 이격도 (소수, 0.25 = +25%)

    overheat: bool
    entry_method: str = "v2.0-atr"


# ─────────────────────────────────────────────────────────────────
# 개별 지표 계산
# ─────────────────────────────────────────────────────────────────


def compute_52w_position(
    closes: list[float],
    current: float,
    window: int = TRADING_DAYS_52W,
) -> tuple[float, float, float]:
    """52주 위치 산출.

    Returns
    -------
    (high_52w, low_52w, pos_52w)
        pos_52w: 0.0 (52W 저점) ~ 1.0 (52W 고점).
        데이터 부족 시 사용 가능한 전 구간 사용.
        high == low 이면 pos = 0.5 (중립).
    """
    recent = closes[-window:] if len(closes) >= window else closes
    if not recent:
        return current, current, 0.5
    high = max(recent + [current])
    low = min(recent + [current])
    if high <= low:
        return high, low, 0.5
    pos = (current - low) / (high - low)
    return high, low, max(0.0, min(1.0, pos))


def compute_atr14(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = ATR_PERIOD,
) -> Optional[float]:
    """Wilder ATR14.

    첫 TR = high[0] - low[0] (이전 close 없음).
    이후 TR = max(high-low, |high-prev_close|, |low-prev_close|).
    ATR = 최근 period 개 TR 의 단순평균 (Wilder smoothing 대신 SMA — v2.0 단순화).

    데이터가 period+1 미만이면 None (호출측에서 fallback 결정).
    """
    n = len(closes)
    if n < 2 or len(highs) != n or len(lows) != n:
        return None
    trs: list[float] = []
    trs.append(highs[0] - lows[0])
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    recent = trs[-period:]
    return sum(recent) / period


def compute_ma200(closes: list[float], window: int = TRADING_DAYS_200MA) -> Optional[float]:
    """200일 이동평균. 데이터 부족(<200) 시 None."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


# ─────────────────────────────────────────────────────────────────
# 통합 진입가 산출
# ─────────────────────────────────────────────────────────────────


def compute_entry_price(
    current_price: float,
    ohlc: list[tuple[float, float, float]],  # [(high, low, close), ...] 오래된→최근 순
) -> EntryPriceResult:
    """v2.0 진입가 산출 — 52W 위치 + ATR14 완충 + 과열 판정.

    Parameters
    ----------
    current_price : float
        실시간 우선, 없으면 last_close.
    ohlc : list[tuple[float, float, float]]
        (high, low, close) 시계열 (오래된→최근). 260일 정도 권장.

    Returns
    -------
    EntryPriceResult
    """
    if current_price <= 0:
        # 현재가 없으면 아무 것도 못 함 — 방어적 return
        return EntryPriceResult(
            entry_price=None,
            entry_status="⚠️ 현재가 없음",
            entry_gap_pct=None,
            high_52w=0.0,
            low_52w=0.0,
            pos_52w=0.5,
            atr14=0.0,
            ma200=None,
            ma200_deviation=None,
            overheat=False,
        )

    highs = [h for h, _, _ in ohlc]
    lows = [l for _, l, _ in ohlc]
    closes = [c for _, _, c in ohlc]

    # 1. 52W 위치
    high_52w, low_52w, pos_52w = compute_52w_position(closes, current_price)

    # 2. ATR14
    atr14 = compute_atr14(highs, lows, closes)
    if atr14 is None or atr14 <= 0:
        atr14 = current_price * ATR_FALLBACK_PCT   # 현재가의 2% fallback

    # 3. 200MA
    ma200 = compute_ma200(closes)
    ma200_deviation: Optional[float] = None
    if ma200 is not None and ma200 > 0:
        ma200_deviation = current_price / ma200 - 1

    # 4. 과열 판정 — 두 조건 중 하나라도 참
    overheat_by_52w = pos_52w >= OVERHEAT_52W_THRESHOLD
    overheat_by_ma200 = (
        ma200_deviation is not None
        and ma200_deviation >= OVERHEAT_MA200_THRESHOLD
    )
    overheat = overheat_by_52w or overheat_by_ma200

    # 5. 진입가 산출
    if overheat:
        reasons: list[str] = []
        if overheat_by_52w:
            reasons.append(f"52W {pos_52w * 100:.0f}%")
        if overheat_by_ma200:
            reasons.append(f"MA200 +{ma200_deviation * 100:.1f}%")
        return EntryPriceResult(
            entry_price=None,
            entry_status=f"🔴 과열 관망 ({' · '.join(reasons)})",
            entry_gap_pct=None,
            high_52w=high_52w,
            low_52w=low_52w,
            pos_52w=pos_52w,
            atr14=atr14,
            ma200=ma200,
            ma200_deviation=ma200_deviation,
            overheat=True,
        )

    # 정상: 진입가 = 현재가 − 1.0 × ATR14
    entry_price = max(current_price - ATR_ENTRY_MULTIPLIER * atr14, 0.0)
    entry_gap_pct = (entry_price / current_price - 1) * 100  # 음수

    if entry_gap_pct >= -NEAR_ENTRY_TOLERANCE_PCT:
        entry_status = "🟢 지금 매수 가능 (ATR 완충 흡수)"
    else:
        entry_status = f"🟡 {abs(entry_gap_pct):.1f}% 조정 대기"

    return EntryPriceResult(
        entry_price=entry_price,
        entry_status=entry_status,
        entry_gap_pct=entry_gap_pct,
        high_52w=high_52w,
        low_52w=low_52w,
        pos_52w=pos_52w,
        atr14=atr14,
        ma200=ma200,
        ma200_deviation=ma200_deviation,
        overheat=False,
    )
