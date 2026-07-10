"""SignalRouter — v2 트랙 C Phase 1.

시그널 엔진(meme_stock · vip · activist · sector_leaders · super_signal) → OrderManager 라우팅.

책임:
1. EXECUTION_ENABLED=false → 즉시 return None (기존 알림 흐름만)
2. Kill Switch 발동 → 로그·알림 후 return None
3. Risk Budget 통과 여부 확인 → 실패 시 로그·알림 후 return None
4. SignalEvent → OrderRequest 변환 (강도·자본 → 수량 매핑)
5. order_manager.submit_order(req) 호출
6. 결과 감사 로그 + 텔레그램 요약 알림

시그널 감지 직후 동기 호출 (사용자 승인 · 2026-07-10).
텔레그램 알림과 병행 · 알림 흐름 무영향.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §7
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

from .audit import record_order_result
from .exceptions import (
    ExecutionError,
    InsufficientBalance,
    KillSwitchActive,
    OrderRejected,
    RiskBudgetViolation,
)
from .kill_switch import KillSwitch, get_kill_switch
from .models import (
    BrokerKind,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)
from .order_manager import OrderManager
from .params import ExecutionParamsStore, get_params_store
from .risk_budget import RiskBudgetChecker

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class SignalEvent:
    """discovery 4채널 → Router 입력.

    각 시그널 서브패키지에서 emit 시점에 생성.
    """
    ticker: str
    action: str                          # "buy" | "sell" | "hold"
    strength: int                        # 0~100 (시그널 강도)
    source: str                          # meme_stock | vip | activist | sector_leaders | super_signal
    signal_id: str
    order_type: str = "market"           # market | limit
    price: Optional[float] = None        # LIMIT 만 사용
    metadata: dict = field(default_factory=dict)


class SignalRouter:
    """시그널 → 리스크 검증 → OMI 라우팅."""

    # 강도 → 수량 매핑 시 최대 주문 금액 (env `EXECUTION_MAX_ORDER_AMOUNT`)
    # Phase 2 실계좌 진입 시 10만 원 하드 상한

    def __init__(
        self,
        order_manager: OrderManager,
        *,
        risk_checker: Optional[RiskBudgetChecker] = None,
        kill_switch: Optional[KillSwitch] = None,
        params_store: Optional[ExecutionParamsStore] = None,
    ):
        self._om = order_manager
        self._risk = risk_checker or RiskBudgetChecker(params_store)
        self._ks = kill_switch or get_kill_switch()
        self._params = params_store or get_params_store()

    # ─── 전역 스위치 ───
    @staticmethod
    def enabled() -> bool:
        return _env_bool("EXECUTION_ENABLED", default=False)

    # ─── 강도 → 수량 매핑 (Phase 1 단순) ───
    def _resolve_qty(self, event: SignalEvent, ref_price: float) -> int:
        """시그널 강도(0~100) × 종목 상한 자본 → 정수 주."""
        max_order = _env_float("EXECUTION_MAX_ORDER_AMOUNT", 100_000.0)
        # 강도 비례 배분 · 최소 1주
        weight = max(0.1, min(1.0, event.strength / 100.0))
        budget = max_order * weight
        qty = max(1, int(budget // max(ref_price, 1.0)))
        return qty

    # ─── SignalEvent → OrderRequest 변환 ───
    def _to_order_request(
        self, event: SignalEvent, ref_price: float
    ) -> Optional[OrderRequest]:
        if event.action == "hold":
            return None
        try:
            side = OrderSide(event.action)
        except ValueError:
            logger.warning("알 수 없는 action=%r · skip", event.action)
            return None
        try:
            order_type = OrderType(event.order_type)
        except ValueError:
            order_type = OrderType.MARKET

        qty = self._resolve_qty(event, ref_price)
        return OrderRequest(
            ticker=event.ticker,
            side=side,
            order_type=order_type,
            qty=qty,
            price=event.price if order_type == OrderType.LIMIT else None,
            signal_source=event.source,
            signal_id=event.signal_id,
        )

    # ─── Public entry ───
    async def route(self, event: SignalEvent) -> Optional[OrderResult]:
        """시그널 → 주문 라우팅.

        None 반환 케이스: 비활성/Kill Switch/Risk Budget 위반/hold 시그널/변환 실패.
        """
        # ① 전역 스위치
        if not self.enabled():
            return None

        # ② Kill Switch
        if self._ks.is_active():
            logger.warning(
                "[Router] Kill Switch 발동 상태 · 시그널 스킵 · ticker=%s · source=%s",
                event.ticker,
                event.source,
            )
            return None

        # ③ 시세 확보 (수량 매핑 근거)
        market_info = self._om.get_market_info(event.ticker)
        if market_info.last_price is None:
            logger.warning(
                "[Router] 시세 조회 실패 · 스킵 · ticker=%s", event.ticker
            )
            return None

        # ④ Request 변환
        req = self._to_order_request(event, market_info.last_price)
        if req is None:
            return None

        # ⑤ Risk Budget
        balance = self._om.get_balance()
        check = await self._risk.check(req, balance, self._om.broker_kind)
        if not check.passed:
            logger.warning(
                "[Router] 리스크 예산 위반 · %s · %s", check.rule, check.detail
            )
            # 감사 로그: 위반으로 rejected 기록
            rejected = OrderResult(
                order_uuid=req.order_uuid,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                error_code=f"risk-budget-{check.rule}",
                error_message=check.detail,
            )
            try:
                await record_order_result(self._om.broker_kind, req, rejected)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Router] 감사 로그 실패 — %s", exc)
            return rejected

        # ⑥ 실 주문 · 예외 정규화
        try:
            result = self._om.submit_order(req)
        except KillSwitchActive as exc:
            logger.warning("[Router] Kill Switch (제출 시점) · %s", exc)
            return None
        except InsufficientBalance as exc:
            result = OrderResult(
                order_uuid=req.order_uuid,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                error_code=exc.code,
                error_message=exc.message,
            )
        except OrderRejected as exc:
            result = OrderResult(
                order_uuid=req.order_uuid,
                broker_order_id=None,
                status=OrderStatus.REJECTED,
                error_code=exc.code,
                error_message=exc.message,
            )
        except ExecutionError as exc:
            result = OrderResult(
                order_uuid=req.order_uuid,
                broker_order_id=None,
                status=OrderStatus.ERROR,
                error_code="execution-error",
                error_message=str(exc),
            )

        # ⑦ 감사 로그
        try:
            await record_order_result(self._om.broker_kind, req, result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Router] 감사 로그 실패 — %s", exc)

        return result


# 프로세스 lifetime 싱글턴 (OrderManager 주입 필요)
_router: Optional[SignalRouter] = None


def get_signal_router() -> Optional[SignalRouter]:
    """전역 Router 조회. discovery 통합 지점에서 호출.

    미초기화 시 EXECUTION_ENABLED 여부 확인 후 지연 초기화.
    """
    global _router
    if _router is not None:
        return _router
    if not _env_bool("EXECUTION_ENABLED", default=False):
        # 비활성 시 초기화 자체 스킵 (Toss API 호출 방지)
        return None
    # 지연 초기화: 기본 어댑터 = PaperAdapter (Phase 1)
    # Phase 2에서 EXECUTION_BROKER 로 분기
    broker = os.environ.get("EXECUTION_BROKER", "paper").lower()
    if broker == "paper":
        from .brokers.paper_adapter import PaperAdapter

        om: OrderManager = PaperAdapter()
    else:
        logger.warning("EXECUTION_BROKER=%s 미지원 (Phase 2 예정) · Paper 대체", broker)
        from .brokers.paper_adapter import PaperAdapter

        om = PaperAdapter()
    _router = SignalRouter(om)
    return _router


def reset_signal_router() -> None:
    """테스트·재구성용."""
    global _router
    _router = None
