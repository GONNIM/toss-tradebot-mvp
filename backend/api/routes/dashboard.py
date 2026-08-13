"""대시보드 요약 — Phase K (Toss API) 활성 후.

2026-08-13 · toss-account 실시간 스냅샷 라우트 추가 (Fable 5 지시).
인증 필수 (require_sniper_token) · 실 계좌 노출 방지.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select

logger = logging.getLogger(__name__)

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


def _to_float(v, default=None):
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _sum_marketvalue_krw(items: list[dict]) -> float:
    """items 각 종목의 marketValue.krw 합산 (KR 이면 원본 · US 이면 환산 필드 확인)."""
    total = 0.0
    for it in items:
        mv = it.get("marketValue") or {}
        if isinstance(mv, dict):
            v = _to_float(mv.get("krw") or mv.get("amount"))
            if v:
                total += v
    return total


@router.get(
    "/toss-account",
    response_model=TossAccountSnapshot,
    dependencies=[Depends(require_sniper_token)],
)
async def get_toss_account():
    """토스증권 '내 계좌' 미러링 (Fable 5 · 2026-08-13).

    인증 필수 · 원본 우선 · 자체 계산은 검산 병기 (broker-api-source-of-truth).
    """
    fetched_at = datetime.now(timezone.utc)
    journal_set = await _journal_ticker_set()
    market_open = _is_us_market_open(fetched_at)
    price_source = "realtime" if market_open else "prior_close"

    # 원본 우선 (Fable 5 broker-api-source-of-truth · 2026-08-13):
    #   holdings() 응답 = dict · items[] + 상위 집계 (totalPurchaseAmount·marketValue·profitLoss)
    #   각 item: symbol·quantity·averagePurchasePrice·lastPrice·currency·(name?)·(marketValue?)·(profitLoss?)
    try:
        from backend.execution.brokers.toss_client import get_toss_client
        client = get_toss_client()
        holdings_dict = client.holdings() or {}
        cash_krw = None
        cash_usd = None
        try:
            bp_krw = client.buying_power(currency="KRW") or {}
            cash_krw = _to_float(bp_krw.get("cashBuyingPower"))
        except Exception:  # noqa: BLE001
            pass
        try:
            bp_usd = client.buying_power(currency="USD") or {}
            cash_usd = _to_float(bp_usd.get("cashBuyingPower"))
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

    # 상위 집계 (원본 우선 · Fable 5 broker-api-source-of-truth)
    total_purchase = holdings_dict.get("totalPurchaseAmount") or {}
    market_value_agg = holdings_dict.get("marketValue") or {}
    profit_loss_agg = holdings_dict.get("profitLoss") or {}

    # 층 2B 필드 (내 투자)
    investment_market_value_krw = _to_float(market_value_agg.get("krw") or market_value_agg.get("amount"))
    investment_cost_krw = _to_float(total_purchase.get("krw"))
    investment_pnl_krw = _to_float(profit_loss_agg.get("krw") or profit_loss_agg.get("amount"))
    investment_pnl_pct = _to_float(profit_loss_agg.get("rate") or profit_loss_agg.get("ratio"))
    investment_pnl_source = "api" if (investment_market_value_krw is not None and investment_pnl_krw is not None) else "computed"

    # 수익률 fallback (원금 기준 · Fable 5: 분모 명시 필요)
    if investment_pnl_pct is None and investment_cost_krw and investment_pnl_krw is not None:
        investment_pnl_pct = round(investment_pnl_krw / investment_cost_krw * 100, 2)

    items = holdings_dict.get("items") or []
    kr_holdings: list[TossHolding] = []
    us_holdings: list[TossHolding] = []
    kr_mv_sum = 0.0
    kr_cost_sum = 0.0
    us_mv_krw_sum = 0.0
    us_cost_krw_sum = 0.0

    for item in items:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").strip()
        if not sym:
            continue
        qty = _to_float(item.get("quantity"), 0) or 0
        if qty <= 0:
            continue
        avg = _to_float(item.get("averagePurchasePrice"), 0) or 0
        cur = _to_float(item.get("lastPrice"))
        currency = (item.get("currency") or "").upper() or ("KRW" if sym.isdigit() else "USD")
        name = item.get("name") or item.get("koreanName") or item.get("displayName")

        # item 안에 marketValue/profitLoss 있으면 원본 우선 (없으면 계산)
        item_mv_obj = item.get("marketValue") or {}
        item_pl_obj = item.get("profitLoss") or {}

        # native 통화 값
        mv_native = _to_float(item_mv_obj.get("amount"))
        if mv_native is None and cur is not None:
            mv_native = round(qty * cur, 4)
        cost_native = _to_float(item_mv_obj.get("costBasis")) or round(qty * avg, 4)
        pnl_native = _to_float(item_pl_obj.get("amount"))
        if pnl_native is None and mv_native is not None:
            pnl_native = round(mv_native - cost_native, 4)
        pnl_pct = _to_float(item_pl_obj.get("rate")) or _to_float(item_pl_obj.get("ratio"))
        if pnl_pct is None and cost_native > 0 and pnl_native is not None:
            pnl_pct = round(pnl_native / cost_native * 100, 2)

        # KRW 환산 (US 종목 총계·표시용 · 상위 marketValue.krw 있으면 그거 · 없으면 하드코드 환율)
        mv_krw = _to_float(item_mv_obj.get("krw"))
        if mv_krw is None:
            if currency == "KRW":
                mv_krw = mv_native
            elif mv_native is not None:
                # constants USDKRW 대신 상위 집계 값에서 역산 or 하드코드 fallback
                mv_krw = round(mv_native * 1330, 0)

        holding = TossHolding(
            symbol=sym,
            name=name,
            currency=currency,
            qty=qty,
            avg_price=avg,
            current_price=cur,
            market_value=mv_native,
            cost_basis=cost_native,
            unrealized_pnl=pnl_native,
            unrealized_pnl_pct=pnl_pct,
            market_value_krw=mv_krw,
            journal_recorded=sym.upper() in journal_set,
        )
        if currency == "KRW":
            kr_holdings.append(holding)
            if mv_native is not None:
                kr_mv_sum += mv_native
            kr_cost_sum += cost_native
        else:
            us_holdings.append(holding)
            if mv_krw is not None:
                us_mv_krw_sum += mv_krw
            # US cost KRW 환산 (검산용)
            us_cost_krw_sum += round(cost_native * 1330, 0)

    # 층 3 · 섹션 소계 (자체 합산 · KR/US 별도)
    kr_market_value = round(kr_mv_sum, 0) if kr_holdings else None
    kr_cost = round(kr_cost_sum, 0) if kr_holdings else None
    kr_pnl = round(kr_mv_sum - kr_cost_sum, 0) if kr_holdings else None
    kr_pnl_pct = round((kr_mv_sum - kr_cost_sum) / kr_cost_sum * 100, 2) if kr_cost_sum > 0 else None

    us_market_value_krw = round(us_mv_krw_sum, 0) if us_holdings else None
    us_cost_krw = round(us_cost_krw_sum, 0) if us_holdings else None
    us_pnl_krw = round(us_mv_krw_sum - us_cost_krw_sum, 0) if us_holdings else None
    us_pnl_pct = round((us_mv_krw_sum - us_cost_krw_sum) / us_cost_krw_sum * 100, 2) if us_cost_krw_sum > 0 else None

    # 층 2B fallback (API 없으면 자체 합산)
    if investment_market_value_krw is None:
        computed_mv = kr_mv_sum + us_mv_krw_sum
        investment_market_value_krw = computed_mv if computed_mv > 0 else None
        if investment_pnl_source == "api":
            investment_pnl_source = "computed"

    # 층 2A · 주문 가능
    cash_usd_krw = round((cash_usd or 0) * 1330, 0) if cash_usd else 0
    order_available_krw = round((cash_krw or 0) + cash_usd_krw, 0) if (cash_krw or cash_usd) else None

    # 층 1 · 총 자산 = 주문 가능 + 내 투자
    total_asset_krw = None
    if investment_market_value_krw is not None or order_available_krw is not None:
        total_asset_krw = round((investment_market_value_krw or 0) + (order_available_krw or 0), 0)

    # ─── 회계 항등식 게이트 (Fable 5 · ±1원 · 근사 X) ─────────
    identity_asset_ok = True
    identity_asset_diff = None
    if total_asset_krw is not None and investment_market_value_krw is not None and order_available_krw is not None:
        expected_asset = (order_available_krw or 0) + (investment_market_value_krw or 0)
        diff = round(expected_asset - total_asset_krw, 0)
        identity_asset_diff = diff
        identity_asset_ok = abs(diff) <= 1
        if not identity_asset_ok:
            logger.warning(
                "[dashboard.toss] 항등식 위반 · 주문가능+내투자 != 총자산 · diff=%s KRW · "
                "order_available=%s · investment=%s · total=%s",
                diff, order_available_krw, investment_market_value_krw, total_asset_krw,
            )

    identity_investment_ok = True
    identity_investment_diff = None
    if investment_market_value_krw is not None and (kr_market_value is not None or us_market_value_krw is not None):
        expected_inv = (kr_market_value or 0) + (us_market_value_krw or 0)
        diff = round(expected_inv - investment_market_value_krw, 0)
        identity_investment_diff = diff
        identity_investment_ok = abs(diff) <= 1
        if not identity_investment_ok:
            logger.warning(
                "[dashboard.toss] 항등식 위반 · 국내+해외 != 내투자 · diff=%s KRW · "
                "kr=%s · us_krw=%s · investment=%s",
                diff, kr_market_value, us_market_value_krw, investment_market_value_krw,
            )

    _last_success["toss_account"] = fetched_at
    return TossAccountSnapshot(
        ok=True,
        last_success_at=fetched_at,
        fetched_at=fetched_at,
        market_open=market_open,
        price_source=price_source,
        total_asset_krw=total_asset_krw,
        order_available_krw=order_available_krw,
        cash_krw=cash_krw,
        cash_usd=cash_usd,
        investment_market_value_krw=round(investment_market_value_krw, 0) if investment_market_value_krw else None,
        investment_cost_krw=round(investment_cost_krw, 0) if investment_cost_krw else None,
        investment_pnl_krw=round(investment_pnl_krw, 0) if investment_pnl_krw is not None else None,
        investment_pnl_pct=investment_pnl_pct,
        investment_pnl_source=investment_pnl_source,
        kr_market_value=kr_market_value,
        kr_cost=kr_cost,
        kr_pnl=kr_pnl,
        kr_pnl_pct=kr_pnl_pct,
        kr_holdings=kr_holdings,
        us_market_value_krw=us_market_value_krw,
        us_cost_krw=us_cost_krw,
        us_pnl_krw=us_pnl_krw,
        us_pnl_pct=us_pnl_pct,
        us_holdings=us_holdings,
        identity_asset_ok=identity_asset_ok,
        identity_asset_diff=identity_asset_diff,
        identity_investment_ok=identity_investment_ok,
        identity_investment_diff=identity_investment_diff,
    )
