"""Phase 2 Smoke Test — 사용자 협업용 CLI (6단계).

스펙: docs/plans/tradebot-mvp-v2/03-toss-openapi-integration.md §8-2

⚠️ 실계좌 · 실 자금 사용. **정규장 시간에만 실행 권장.**
각 단계별 사용자 확인 (yes/no) 대기 · 언제든 중단 가능.

실행:
    python -m scripts.toss.smoke_test

단계:
1. 최소 지정가 매수 — 1주 · 현재가 -5% (미체결로 남을 가격)
2. 주문 상태 조회 정확도
3. 미체결 주문 취소
4. 정정 (가격 변경) 후 재취소
5. 시장가 매도 — 실 보유 종목 1주 (선택)
6. 429 유발 — 초당 7회 시도 · Retry-After 파싱 검증

각 단계 X-Request-Id 로깅 · 사용자가 종목 지정 (기본 005930).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.execution.brokers.toss_client import TossClient, get_toss_client  # noqa: E402
from backend.execution.exceptions import (  # noqa: E402
    ExecutionError,
    OrderNotFound,
    OrderRejected,
    RateLimitExceeded,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("toss-smoke")


def _confirm(msg: str) -> bool:
    answer = input(f"{msg} (yes/no): ").strip().lower()
    return answer in {"y", "yes"}


def _get_current_price(client: TossClient, ticker: str) -> Optional[float]:
    data = client.prices([ticker])
    if isinstance(data, list) and data:
        p = data[0].get("price") or data[0].get("lastPrice")
        try:
            return float(p) if p is not None else None
        except (TypeError, ValueError):
            return None
    return None


def _make_client_order_id() -> str:
    return f"smoke-{uuid.uuid4().hex[:8]}"


# ═══════════════════════════════════════════════════════════════
def step_1_limit_buy_offmarket(client: TossClient, ticker: str) -> Optional[str]:
    print("\n═════ 1/6 · 최소 지정가 매수 (미체결로 남을 가격) ═════")
    price = _get_current_price(client, ticker)
    if price is None:
        logger.error("현재가 조회 실패 · 종목 확인")
        return None
    target = round(price * 0.95, 2 if not ticker.isdigit() else 0)  # -5%
    print(f"  현재가: {price} → 지정가 매수 {target} (1주)")
    if not _confirm("실행할까요?"):
        return None
    body = {
        "clientOrderId": _make_client_order_id(),
        "symbol": ticker,
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "quantity": "1",
        "price": str(target),
    }
    try:
        env = client.create_order(body)
    except OrderRejected as exc:
        logger.error("거절 · %s", exc)
        return None
    print(f"  ✅ 접수 · orderId={env.result.get('orderId')} · requestId={env.request_id}")
    print(f"     status={env.result.get('status')} · rate_limit={env.rate_limit}")
    return env.result.get("orderId")


def step_2_status_query(client: TossClient, order_id: str) -> None:
    print("\n═════ 2/6 · 주문 상태 조회 정확도 ═════")
    env = client.get_order(order_id)
    print(f"  status={env.result.get('status')} · requestId={env.request_id}")


def step_3_cancel(client: TossClient, order_id: str) -> bool:
    print("\n═════ 3/6 · 미체결 주문 취소 ═════")
    if not _confirm("취소 실행할까요?"):
        return False
    env = client.cancel_order(order_id)
    status = env.result.get("status") if isinstance(env.result, dict) else "?"
    print(f"  status={status} · requestId={env.request_id}")
    return status in {"CANCELED", "PENDING_CANCEL"}


def step_4_modify_and_cancel(client: TossClient, ticker: str) -> None:
    print("\n═════ 4/6 · 정정(가격 변경) 후 재취소 ═════")
    price = _get_current_price(client, ticker)
    if price is None:
        logger.error("현재가 조회 실패")
        return
    initial_price = round(price * 0.94, 2 if not ticker.isdigit() else 0)
    modified_price = round(price * 0.93, 2 if not ticker.isdigit() else 0)

    print(f"  ① {initial_price} 로 신규 지정가 접수")
    if not _confirm("실행할까요?"):
        return
    env = client.create_order(
        {
            "clientOrderId": _make_client_order_id(),
            "symbol": ticker,
            "side": "BUY",
            "orderType": "LIMIT",
            "timeInForce": "DAY",
            "quantity": "1",
            "price": str(initial_price),
        }
    )
    order_id = env.result.get("orderId")
    print(f"  → orderId={order_id} · requestId={env.request_id}")

    print(f"  ② {modified_price} 로 정정")
    env = client.modify_order(order_id, {"price": str(modified_price), "quantity": "1"})
    print(f"  → status={env.result.get('status')} · requestId={env.request_id}")
    replaced_id = env.result.get("orderId") if isinstance(env.result, dict) else order_id
    if replaced_id and replaced_id != order_id:
        print(f"  ⓘ REPLACED → 신규 orderId={replaced_id}")
        order_id = replaced_id

    print(f"  ③ 재취소")
    env = client.cancel_order(order_id)
    print(f"  → status={env.result.get('status')} · requestId={env.request_id}")


def step_5_market_sell_optional(client: TossClient) -> None:
    print("\n═════ 5/6 · 시장가 매도 (선택) ═════")
    if not _confirm("실 보유 종목에서 1주 시장가 매도를 실행할까요?"):
        print("  · 스킵")
        return
    ticker = input("  매도 종목 심볼: ").strip()
    if not ticker:
        return
    body = {
        "clientOrderId": _make_client_order_id(),
        "symbol": ticker,
        "side": "SELL",
        "orderType": "MARKET",
        "timeInForce": "DAY",
        "quantity": "1",
    }
    try:
        env = client.create_order(body)
    except OrderRejected as exc:
        logger.error("거절 · %s", exc)
        return
    print(
        f"  ✅ status={env.result.get('status')} · orderId={env.result.get('orderId')} · requestId={env.request_id}"
    )


def step_6_rate_limit_trigger(client: TossClient) -> None:
    print("\n═════ 6/6 · 429 rate-limit 유발 · Retry-After 검증 ═════")
    print("  초당 7회 미체결 지정가 매수 시도 (즉시 취소) · 429 검출 시 성공")
    if not _confirm("실행할까요?"):
        return
    try:
        for i in range(7):
            body = {
                "clientOrderId": _make_client_order_id(),
                "symbol": "005930",
                "side": "BUY",
                "orderType": "LIMIT",
                "timeInForce": "DAY",
                "quantity": "1",
                "price": "1",   # 절대 체결 안될 가격
            }
            try:
                env = client.create_order(body)
                # 즉시 취소
                if env.result.get("orderId"):
                    try:
                        client.cancel_order(env.result["orderId"])
                    except ExecutionError:
                        pass
                print(f"  {i+1}/7 · ok · rate_limit={env.rate_limit}")
            except RateLimitExceeded as exc:
                print(f"  {i+1}/7 · 🎯 429 검출 · Retry-After={exc.retry_after}")
                return
            time.sleep(0.05)
    except OrderRejected as exc:
        print(f"  거절 (429 아님) · {exc}")
    print("  · 429 미검출 · 정상 스로틀 작동 가능성")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 Toss Smoke Test (6단계)")
    parser.add_argument("--ticker", default="005930", help="테스트 대상 심볼 (기본 005930)")
    parser.add_argument(
        "--skip", type=str, default="",
        help="스킵할 단계 콤마 구분 (예: --skip 5,6)",
    )
    args = parser.parse_args()

    skip = {int(s) for s in args.skip.split(",") if s.strip().isdigit()}
    ticker = args.ticker

    print("=" * 60)
    print("🚀 Phase 2 Smoke Test — Toss Open API 6 단계")
    print(f"   ticker={ticker} · skip={sorted(skip) or 'none'}")
    print("=" * 60)
    print("⚠️  실계좌 · 실 자금. 정규장 시간에만 실행 권장.")
    if not _confirm("시작할까요?"):
        return 0

    client = get_toss_client()

    order_id: Optional[str] = None
    if 1 not in skip:
        order_id = step_1_limit_buy_offmarket(client, ticker)
        if order_id and 2 not in skip:
            step_2_status_query(client, order_id)
        if order_id and 3 not in skip:
            step_3_cancel(client, order_id)

    if 4 not in skip:
        step_4_modify_and_cancel(client, ticker)

    if 5 not in skip:
        step_5_market_sell_optional(client)

    if 6 not in skip:
        step_6_rate_limit_trigger(client)

    print("\n" + "=" * 60)
    print("✅ Smoke Test 완료")
    print("   각 단계 requestId 는 로그에서 확인 · order_audit 테이블 조회로 감사 로그 검증")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
