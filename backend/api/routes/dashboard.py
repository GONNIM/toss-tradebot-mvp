"""대시보드 요약 — Phase K (Toss API) 활성 후.

2026-08-13 · toss-account 실시간 스냅샷 라우트 추가 (Fable 5 지시).
인증 필수 (require_sniper_token) · 실 계좌 노출 방지.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select

from backend.api.auth import require_sniper_token
from backend.api.schemas import DashboardSummary, TossAccountSnapshot, TossHolding
from backend.services.db import get_session
from backend.services.models import AccountPosition, AuditTrade, EngineStatus, UserJudgment

router = APIRouter()

# ─── Toss 스냅샷 캐시 · 마지막 성공 (Fable 5 정직 UX) ────────────────
# in-memory · 프로세스 재시작 시 소실 · 크리티컬 X

_last_success: dict[str, datetime] = {}  # key="toss_account"


@router.get("/", response_model=DashboardSummary, dependencies=[Depends(require_sniper_token)])
async def get_summary():
    """자동매매 대시보드 요약 · 인증 필수 (2026-08-13 Fable 5)."""
    async with get_session() as session:
        positions = (await session.execute(select(AccountPosition))).scalars().all()

        total_value = 0.0
        total_cost = 0.0
        for p in positions:
            qty = p.qty or 0
            avg_price = p.avg_price or 0
            total_cost += qty * avg_price
            total_value += qty * avg_price  # 실 평가가는 Phase K (Toss API) 후

        unrealized = total_value - total_cost
        realized = 0.0  # Phase K — AuditTrade 기반 계산은 SELL/BUY 매칭 후

        # 마지막 거래
        last_trade = (await session.execute(
            select(AuditTrade).order_by(desc(AuditTrade.timestamp)).limit(1)
        )).scalar_one_or_none()

        # 엔진 상태 (Phase K)
        engine = (await session.execute(
            select(EngineStatus).order_by(desc(EngineStatus.updated_at)).limit(1)
        )).scalar_one_or_none()

        engine_status = "not_initialized"
        if engine:
            engine_status = "running" if engine.is_running else "stopped"

        return DashboardSummary(
            total_value_usd=total_value,
            total_cost_usd=total_cost,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=unrealized,
            open_positions=len(positions),
            last_trade_at=last_trade.timestamp if last_trade else None,
            engine_status=engine_status,
        )


# ─── Toss 실계좌 스냅샷 (2026-08-13 · Fable 5 · 인증 필수) ─────────────


def _is_us_market_open(now: Optional[datetime] = None) -> bool:
    """US 정규장 판정 · 09:30~16:00 ET · 주말 제외.

    간이 판정 (holiday 미고려 · 필요 시 pandas_market_calendars 도입).
    """
    now = now or datetime.now(timezone.utc)
    # ET = UTC−5 (EST) or UTC−4 (EDT · DST). DST 판정 없이 UTC-4 근사 (여름).
    # 정확한 판정은 후속 · 지금은 "언제나 실시간" 오해만 방지가 목적.
    et = now.astimezone(timezone.utc).replace(tzinfo=None)  # naive UTC
    import zoneinfo
    try:
        et = now.astimezone(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        return False
    if et.weekday() >= 5:  # 토(5)·일(6)
        return False
    minutes = et.hour * 60 + et.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


async def _journal_ticker_set() -> set[str]:
    """저널 판정이 존재하는 티커 집합 · 대조 컬럼용 (Fable 5 저널 30건 캠페인)."""
    async with get_session() as session:
        rows = (await session.execute(
            select(UserJudgment.ticker).distinct()
        )).scalars().all()
    return {t.strip().upper() for t in rows if t}


@router.get(
    "/toss-account",
    response_model=TossAccountSnapshot,
    dependencies=[Depends(require_sniper_token)],
)
async def get_toss_account():
    """토스증권 실시간 계좌 스냅샷 · 잔고 + 보유종목 + 저널 대조.

    인증 필수 (Fable 5: 실 계좌 노출 절대 금지).
    실패 시 200 + ok=False + error_reason · 프론트가 정직하게 표시.
    """
    fetched_at = datetime.now(timezone.utc)
    journal_set = await _journal_ticker_set()
    market_open = _is_us_market_open(fetched_at)
    price_source = "realtime" if market_open else "prior_close"

    # 실 응답 구조 (docs/analysis/toss-api-survey.md §1.5 · toss_adapter.py:210-259 검증):
    #   holdings() → dict · items[] 배열 (symbol/quantity/averagePurchasePrice/lastPrice/currency)
    #   buying_power() → dict (cashBuyingPower)
    #   lastPrice 는 이미 items 에 포함 · prices() 호출 불필요.
    try:
        from backend.execution.brokers.toss_client import get_toss_client
        client = get_toss_client()
        holdings_dict = client.holdings() or {}
        balance_krw = None
        balance_usd = None
        try:
            bp_krw = client.buying_power(currency="KRW") or {}
            balance_krw = float(bp_krw.get("cashBuyingPower", 0)) or None
        except Exception:  # noqa: BLE001
            pass
        try:
            bp_usd = client.buying_power(currency="USD") or {}
            balance_usd = float(bp_usd.get("cashBuyingPower", 0)) or None
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        return TossAccountSnapshot(
            ok=False,
            error_reason=f"{type(exc).__name__}: {str(exc)[:180]}",
            last_success_at=_last_success.get("toss_account"),
            fetched_at=fetched_at,
            market_open=market_open,
            price_source=price_source,
        )

    items = holdings_dict.get("items") or []
    holdings: list[TossHolding] = []
    total_cost = 0.0
    total_mv = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").strip()
        if not sym:
            continue
        try:
            qty = float(item.get("quantity") or 0)
            avg = float(item.get("averagePurchasePrice") or 0)
        except (ValueError, TypeError):
            continue
        if qty <= 0:
            continue
        try:
            cur_raw = item.get("lastPrice")
            cur = float(cur_raw) if cur_raw not in (None, "", 0) else None
        except (ValueError, TypeError):
            cur = None
        cost = round(qty * avg, 4)
        mv = round(qty * cur, 4) if cur else None
        pnl = round(mv - cost, 4) if mv is not None else None
        pnl_pct = round((mv - cost) / cost * 100, 2) if (mv is not None and cost > 0) else None
        total_cost += cost
        if mv is not None:
            total_mv += mv
        holdings.append(TossHolding(
            symbol=sym,
            qty=qty,
            avg_price=avg,
            current_price=cur,
            market_value_usd=mv,
            cost_basis_usd=cost,
            unrealized_pnl_usd=pnl,
            unrealized_pnl_pct=pnl_pct,
            journal_recorded=sym.upper() in journal_set,
        ))

    total_pnl = round(total_mv - total_cost, 4) if total_mv else None
    total_pnl_pct = round((total_mv - total_cost) / total_cost * 100, 2) if total_cost > 0 else None
    total_value = round(total_mv + (balance_usd or 0), 4) if total_mv or balance_usd else None

    _last_success["toss_account"] = fetched_at
    return TossAccountSnapshot(
        ok=True,
        last_success_at=fetched_at,
        fetched_at=fetched_at,
        market_open=market_open,
        price_source=price_source,
        balance_krw=balance_krw,
        balance_usd=balance_usd,
        total_value_usd=total_value,
        total_cost_usd=round(total_cost, 4) if total_cost else None,
        total_pnl_usd=total_pnl,
        total_pnl_pct=total_pnl_pct,
        holdings=holdings,
    )
