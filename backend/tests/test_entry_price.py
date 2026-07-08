"""진입가 v2.0 단위 테스트.

대상: backend/discovery/sector_leaders/entry_price.py
기획: docs/plans/sector-leaders-top10-entry-refinement/plan.md §5

SK하이닉스 최고점 사례(3M) / 정상 구간 사례(2M) / 저점 사례 검증.
"""
from __future__ import annotations

import pytest

from backend.discovery.sector_leaders.entry_price import (
    ATR_ENTRY_MULTIPLIER,
    ATR_FALLBACK_PCT,
    NEAR_ENTRY_TOLERANCE_PCT,
    OVERHEAT_52W_THRESHOLD,
    OVERHEAT_MA200_THRESHOLD,
    compute_52w_position,
    compute_atr14,
    compute_entry_price,
    compute_ma200,
)


# ─────────────────────────────────────────────────────────────────
# 개별 지표 테스트
# ─────────────────────────────────────────────────────────────────


class TestFiftyTwoWeekPosition:
    def test_at_high(self):
        closes = [100.0 + i for i in range(252)]  # 100~351
        high, low, pos = compute_52w_position(closes, current=351.0)
        assert high == 351.0
        assert low == 100.0
        assert pos == pytest.approx(1.0)

    def test_at_low(self):
        closes = [100.0 + i for i in range(252)]
        high, low, pos = compute_52w_position(closes, current=100.0)
        assert pos == pytest.approx(0.0)

    def test_at_middle(self):
        closes = [100.0 + i for i in range(252)]
        high, low, pos = compute_52w_position(closes, current=225.5)
        assert pos == pytest.approx(0.5)

    def test_current_exceeds_history(self):
        """현재가가 과거 최고보다 높으면 pos = 1.0."""
        closes = [100.0] * 252
        high, low, pos = compute_52w_position(closes, current=200.0)
        assert high == 200.0
        assert pos == pytest.approx(1.0)

    def test_flat_series(self):
        """평평한 시계열: high == low → 중립 0.5."""
        closes = [100.0] * 252
        high, low, pos = compute_52w_position(closes, current=100.0)
        assert pos == pytest.approx(0.5)

    def test_shorter_than_window(self):
        """250일 미만이어도 사용 가능한 구간으로 계산."""
        closes = [100.0, 200.0, 150.0]
        high, low, pos = compute_52w_position(closes, current=175.0)
        assert high == 200.0
        assert low == 100.0
        assert pos == pytest.approx(0.75)

    def test_empty_series(self):
        """빈 시계열 방어."""
        high, low, pos = compute_52w_position([], current=100.0)
        assert pos == pytest.approx(0.5)


class TestATR14:
    def test_known_atr(self):
        """일정한 range (high-low = 10) 시계열 → ATR14 = 10."""
        n = 20
        highs = [110.0] * n
        lows = [100.0] * n
        closes = [105.0] * n
        atr = compute_atr14(highs, lows, closes)
        assert atr == pytest.approx(10.0)

    def test_insufficient_data(self):
        """14일 미만 → None."""
        highs = [110.0] * 5
        lows = [100.0] * 5
        closes = [105.0] * 5
        assert compute_atr14(highs, lows, closes) is None

    def test_length_mismatch(self):
        """길이 불일치 → None."""
        assert compute_atr14([1.0, 2.0], [1.0], [1.0]) is None

    def test_uses_true_range_with_gap(self):
        """전일 close 대비 갭 있으면 TR 확장."""
        # 첫 봉 range=1, 이후 상승 갭 5 발생
        n = 20
        highs = [101.0] + [106.0] * (n - 1)
        lows = [100.0] + [105.0] * (n - 1)
        closes = [100.5] + [105.5] * (n - 1)
        atr = compute_atr14(highs, lows, closes)
        # 최근 14봉의 TR: max(1, |106-105.5|, |105-105.5|) = 1 (전일 close 105.5)
        assert atr is not None
        assert atr == pytest.approx(1.0)


class TestMA200:
    def test_known_ma(self):
        closes = [100.0] * 200
        assert compute_ma200(closes) == pytest.approx(100.0)

    def test_insufficient_data(self):
        closes = [100.0] * 199
        assert compute_ma200(closes) is None


# ─────────────────────────────────────────────────────────────────
# 통합 진입가 테스트 — 시나리오 기반
# ─────────────────────────────────────────────────────────────────


def _make_ohlc(closes: list[float], range_pct: float = 0.02) -> list[tuple[float, float, float]]:
    """(close 시계열) → (high, low, close) OHLC 시계열 생성."""
    result = []
    for c in closes:
        h = c * (1 + range_pct / 2)
        l = c * (1 - range_pct / 2)
        result.append((h, l, c))
    return result


class TestOverheatDetection:
    def test_sk_hynix_peak_scenario(self):
        """SK하이닉스 300만원 최고점 시나리오 — 반드시 과열 판정."""
        # 100만~300만원 상승 후 현재 300만원 (52W 위치 100%)
        closes = [1_000_000 + (2_000_000 * i / 251) for i in range(252)]
        ohlc = _make_ohlc(closes)
        result = compute_entry_price(current_price=3_000_000, ohlc=ohlc)

        assert result.overheat is True
        assert result.entry_price is None
        assert result.entry_gap_pct is None
        assert result.entry_status.startswith("🔴")
        assert result.pos_52w >= OVERHEAT_52W_THRESHOLD

    def test_ma200_deviation_triggers_overheat(self):
        """52W 위치는 낮아도 200MA 이격 크면 과열."""
        # 200MA 근방에서 완만한 시계열 (10만) 유지 후 최근 급등 (13만)
        closes = [100_000.0] * 250 + [130_000.0] * 2
        ohlc = _make_ohlc(closes)
        result = compute_entry_price(current_price=130_000, ohlc=ohlc)

        assert result.ma200 is not None
        assert result.ma200_deviation >= OVERHEAT_MA200_THRESHOLD
        assert result.overheat is True
        assert result.entry_price is None

    def test_normal_range_no_overheat(self):
        """SK하이닉스 정상 200만원 (밴드 중단) → 과열 아님."""
        # 100만~300만 범위 시계열, 현재 200만 (52W 위치 50%)
        closes = [1_000_000 + (2_000_000 * i / 251) for i in range(252)]
        ohlc = _make_ohlc(closes)
        result = compute_entry_price(current_price=2_000_000, ohlc=ohlc)

        assert result.pos_52w == pytest.approx(0.5, abs=0.05)
        # 200MA는 시계열 평균 2M 근방 → 이격도 0에 가까움
        if result.ma200 is not None:
            assert abs(result.ma200_deviation) < OVERHEAT_MA200_THRESHOLD
        assert result.overheat is False
        assert result.entry_price is not None
        assert result.entry_price < 2_000_000  # ATR 완충으로 현재가보다 낮음


class TestEntryPriceCalculation:
    def test_atr_buffer_applied(self):
        """정상 구간 진입가 = 현재가 − 1×ATR14."""
        n = 252
        # 안정적 시계열, range = 2000원 고정
        closes = [100_000.0] * n
        highs = [101_000.0] * n
        lows = [99_000.0] * n
        ohlc = list(zip(highs, lows, closes))
        result = compute_entry_price(current_price=100_000, ohlc=ohlc)

        assert result.overheat is False
        assert result.atr14 == pytest.approx(2000.0)
        expected_entry = 100_000 - ATR_ENTRY_MULTIPLIER * 2000
        assert result.entry_price == pytest.approx(expected_entry)

    def test_status_ready_when_gap_small(self):
        """진입가 gap이 -0.5% 이내면 '지금 매수'."""
        # 매우 낮은 변동성 → ATR도 작음 → gap 작음
        n = 252
        closes = [100_000.0] * n
        highs = [100_100.0] * n  # range 200원 (0.2%)
        lows = [99_900.0] * n
        ohlc = list(zip(highs, lows, closes))
        result = compute_entry_price(current_price=100_000, ohlc=ohlc)

        assert result.entry_gap_pct == pytest.approx(-0.2, abs=0.01)
        assert result.entry_status.startswith("🟢")

    def test_status_wait_when_gap_large(self):
        """진입가 gap이 -0.5% 초과면 '조정 대기'."""
        n = 252
        closes = [100_000.0] * n
        highs = [103_000.0] * n  # range 6000원 (6%) → 큰 gap
        lows = [97_000.0] * n
        ohlc = list(zip(highs, lows, closes))
        result = compute_entry_price(current_price=100_000, ohlc=ohlc)

        assert result.entry_gap_pct < -NEAR_ENTRY_TOLERANCE_PCT
        assert result.entry_status.startswith("🟡")

    def test_atr_fallback_when_data_insufficient(self):
        """ATR 계산 실패 시 현재가의 2% fallback."""
        result = compute_entry_price(current_price=100_000, ohlc=[])
        # 시계열 없음 → ATR = 100000 * 0.02 = 2000
        assert result.atr14 == pytest.approx(100_000 * ATR_FALLBACK_PCT)

    def test_zero_current_price_defensive(self):
        """현재가 0 방어."""
        result = compute_entry_price(current_price=0, ohlc=[])
        assert result.entry_price is None
        assert "현재가" in result.entry_status


class TestBoundaryConditions:
    def test_52w_position_exactly_at_threshold(self):
        """52W 위치가 정확히 임계값(0.85)이면 과열 판정."""
        closes = [0.0, 100.0]  # low=0, high=100
        ohlc = _make_ohlc(closes)
        # pos_52w = 0.85 → 현재가 = 85
        result = compute_entry_price(current_price=85.0, ohlc=ohlc)
        assert result.pos_52w == pytest.approx(OVERHEAT_52W_THRESHOLD, abs=0.01)
        assert result.overheat is True

    def test_below_threshold_not_overheat(self):
        """52W 84%는 과열 아님 (200MA 조건 미충족 가정)."""
        closes = [0.0, 100.0]  # low=0, high=100
        ohlc = _make_ohlc(closes)
        result = compute_entry_price(current_price=84.0, ohlc=ohlc)
        assert result.pos_52w == pytest.approx(0.84, abs=0.01)
        # 데이터 부족으로 MA200 None → 52W 조건만 평가
        assert result.overheat is False
