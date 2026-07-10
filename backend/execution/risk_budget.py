"""Risk Budget — v2 트랙 C Phase 1.

Phase 1 룰 (단순):
- 종목당 최대 자본 할당: `per_ticker_max_pct` (기본 10%)
- 전체 일일 손실 캡: `daily_loss_limit` (기본 -3%) → 신규 매수 차단
- 종목별 Max DD: `ticker_dd_limit` (기본 -5%) → 자동 청산 신호

Phase 3 확장: Kelly Criterion · Vol Targeting.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §8-2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from .audit import daily_realized_pnl
from .models import Balance, BrokerKind, OrderRequest, OrderSide
from .params import ExecutionParamsStore, get_params_store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    rule: Optional[str] = None       # 위반된 룰 이름
    detail: Optional[str] = None     # 사유 (텔레그램·로그용)


class RiskBudgetChecker:
    """OrderRequest + Balance → 리스크 예산 룰 검증."""

    def __init__(self, params_store: Optional[ExecutionParamsStore] = None):
        self._params = params_store or get_params_store()

    async def check(
        self,
        req: OrderRequest,
        balance: Balance,
        broker_kind: BrokerKind,
    ) -> RiskCheckResult:
        rb = self._params.risk_budget()

        # ─── 매도는 리스크 예산 룰과 무관 (오히려 리스크 축소) ───
        if req.side == OrderSide.SELL:
            return RiskCheckResult(passed=True)

        # ─── ① 종목당 상한 (per_ticker_max_pct) ───
        # 신규 주문액 = qty * (price 또는 현재가 근사)
        if req.price is None:
            # MARKET 은 사전 검증 어려움 · 어댑터 측에서 최종 확인
            new_order_krw = 0.0
        else:
            new_order_krw = float(req.qty) * float(req.price)

        cur_position_krw = 0.0
        for pos in balance.positions:
            if pos.ticker == req.ticker:
                cur_position_krw = pos.qty * pos.current_price
                if pos.currency == "USD":
                    cur_position_krw *= balance.fx_usd_krw
                break

        if balance.total_equity_krw > 0 and new_order_krw > 0:
            projected = cur_position_krw + new_order_krw
            allowed = balance.total_equity_krw * rb.per_ticker_max_pct
            if projected > allowed:
                return RiskCheckResult(
                    passed=False,
                    rule="per_ticker_max_pct",
                    detail=(
                        f"종목 상한 초과: {req.ticker} · 신규+기존={projected:,.0f}KRW · "
                        f"허용={allowed:,.0f}KRW ({rb.per_ticker_max_pct*100:.1f}%)"
                    ),
                )

        # ─── ② 일일 손실 캡 (daily_loss_limit) ───
        # daily_realized_pnl 은 감사 로그 기반 근사치 (Phase 3 정교화)
        try:
            since = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            realized = await daily_realized_pnl(broker_kind, since)
        except Exception as exc:  # noqa: BLE001
            logger.warning("일일 손익 조회 실패 — %s · 통과 처리", exc)
            realized = 0.0

        if balance.total_equity_krw > 0:
            realized_pct = realized / balance.total_equity_krw
            # 70% 초과 진입 시부터 신규 매수 차단 (여유 30%)
            trigger = rb.daily_loss_limit * 0.7
            if realized_pct < trigger:
                return RiskCheckResult(
                    passed=False,
                    rule="daily_loss_limit",
                    detail=(
                        f"일일 손실 캡 근접: 실현손실 {realized_pct*100:.2f}% · "
                        f"차단 트리거 {trigger*100:.2f}% (한계 {rb.daily_loss_limit*100:.1f}%)"
                    ),
                )

        return RiskCheckResult(passed=True)

    def check_ticker_dd(self, ticker: str, unrealized_pnl_pct: float) -> RiskCheckResult:
        """종목별 Max DD 룰 — 보유 종목 상시 감시 (매수 전과 독립)."""
        rb = self._params.risk_budget()
        if unrealized_pnl_pct <= rb.ticker_dd_limit:
            return RiskCheckResult(
                passed=False,
                rule="ticker_dd_limit",
                detail=(
                    f"종목 Max DD 도달: {ticker} · unrealized {unrealized_pnl_pct*100:.2f}% "
                    f"<= 한계 {rb.ticker_dd_limit*100:.1f}%"
                ),
            )
        return RiskCheckResult(passed=True)
