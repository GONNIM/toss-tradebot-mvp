"""가격 규칙 · 계획서 6절.

- 가격 단위: $1 미만 0.0001 · $1 이상 0.01.
- 매수: 감시가 · 주문가 모두 내림.
- 매도(손절 · 추적): 감시가 올림(먼저 발동) · 주문가 내림(체결 쉬움).
- 매도(TP1 · 시간 손절 지정가): 주문가 내림.
- 수량: 예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림.
금액 상한은 코드 기본값 0(= 주문 불가) · 실제 값은 SOPS 환경 설정(PLAN_MAX_ORDER_USD 등).
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Optional, Union

Num = Union[int, float, str, Decimal]

ONE = Decimal("1")


def D(x: Num) -> Decimal:
    """float 잡음을 막기 위해 문자열을 거쳐 Decimal 로."""
    return x if isinstance(x, Decimal) else Decimal(str(x))


def tick(price: Num) -> Decimal:
    return Decimal("0.0001") if D(price) < ONE else Decimal("0.01")


def floor_tick(price: Num) -> Decimal:
    t = tick(price)
    return (D(price) / t).to_integral_value(ROUND_FLOOR) * t


def ceil_tick(price: Num) -> Decimal:
    t = tick(price)
    return (D(price) / t).to_integral_value(ROUND_CEILING) * t


def buy_watch(p: Num) -> Decimal:
    return floor_tick(p)


def buy_order(p: Num) -> Decimal:
    return floor_tick(p)


def sell_watch(p: Num) -> Decimal:
    return ceil_tick(p)


def sell_order(p: Num) -> Decimal:
    return floor_tick(p)


def order_price_from_watch(watch: Num, factor: Num) -> Decimal:
    """감시가 × factor 를 내림한 주문가."""
    return floor_tick(D(watch) * D(factor))


def below_by_tick(watch: Num, cur: Num, ticks: int = 1) -> bool:
    """6-1 「아래에 있음」 = 감시가 ≤ 현재가 − n틱 (틱은 현재가 기준)."""
    return D(watch) <= D(cur) - tick(cur) * ticks


def above_by_tick(watch: Num, cur: Num, ticks: int = 1) -> bool:
    """6-1 「위에 있음」 = 감시가 ≥ 현재가 + n틱."""
    return D(watch) >= D(cur) + tick(cur) * ticks


def cap_sell_watch(computed: Num, cur: Num) -> Decimal:
    """끌어올리기 · 추적 상향의 매도 감시가 = min(계산값 올림, 현재가 − 2틱) (6-1 비교 기준)."""
    return min(ceil_tick(computed), D(cur) - tick(cur) * 2)


def qty_for_budget(budget: Num, buy_price: Num) -> int:
    """예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림. 가격 · 예산이 0 이하면 0."""
    b, p = D(budget), D(buy_price)
    if b <= 0 or p <= 0:
        return 0
    raw = int((b / (p * Decimal("1.001"))).to_integral_value(ROUND_FLOOR))
    return (raw // 6) * 6


def fmt(p: Num) -> str:
    """토스 요청용 문자열 (지수 표기 없음)."""
    d = D(p)
    return "0" if d == 0 else format(d.normalize(), "f")


# ─── 금액 상한 (SOPS 환경 설정 · 없으면 0 = 주문 불가) ─────────────────────

def _cfg_decimal(name: str) -> Decimal:
    from backend.services import config

    raw = config.get(name)
    try:
        v = Decimal(str(raw)) if raw not in (None, "") else Decimal(0)
    except Exception:  # noqa: BLE001 — 깨진 값 = 0 = 주문 불가
        return Decimal(0)
    return v if v > 0 else Decimal(0)


def max_order_usd() -> Decimal:
    return _cfg_decimal("PLAN_MAX_ORDER_USD")


def total_cap_usd() -> Decimal:
    return _cfg_decimal("PLAN_TOTAL_CAP_USD")


def test_max_usd() -> Decimal:
    return _cfg_decimal("PLAN_TEST_MAX_USD")


def check_caps(*, mode: str, order_usd: Num, open_total_usd: Num) -> Optional[str]:
    """거부 사유 문장(통과면 None). 모의는 돈이 움직이지 않아 상한을 보지 않는다."""
    if mode == "paper":
        return None
    order = D(order_usd)
    if mode == "test":
        cap = test_max_usd()
        if cap <= 0:
            return "시험 계획 금액 상한이 설정되지 않았습니다 · 주문 불가"
        if order > cap:
            return "시험 계획 금액 상한을 넘습니다"
        return None
    one = max_order_usd()
    total = total_cap_usd()
    if one <= 0 or total <= 0:
        return "계획 금액 상한이 설정되지 않았습니다 · 주문 불가"
    if order > one:
        return "한 주문 금액 상한을 넘습니다"
    if D(open_total_usd) + order > total:
        return "열린 계획 합계 상한을 넘습니다"
    return None
