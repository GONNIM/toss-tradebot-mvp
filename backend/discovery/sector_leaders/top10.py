"""투자 종목 Top 10 — 매력도 점수 기반 상위 종목 산출 (B-2j).

매력도 = 0.5 × Confluence + 0.3 × 신뢰도(|best_r|) + 0.2 × R/R 정규화
  · Confluence: max(0, score) — 양의 시그널만 매수 후보
  · 신뢰도: |best_r| (0~1)
  · R/R: min(ratio / 3.0, 1.0) — 3:1 이상이면 만점

진입가 v2.0 (2026-07-08~) — entry_price.py 로 위임
  · 52W 위치 + ATR14 + 200MA 이격도 기반 과열 판정
  · 과열(52W ≥85% or MA200 ≥+25%): entry_price=None, 🔴 관망
  · 정상: entry_price = 현재가 − 1.0 × ATR14 (변동성 조정)
  · 상세: docs/plans/sector-leaders-top10-entry-refinement/plan.md §5
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.customs_interim import yoy_for_period
from backend.discovery.data_sources.naver_quote import fetch_quotes
from backend.discovery.sector_leaders.confluence import compute_confluence
from backend.discovery.sector_leaders.entry_price import compute_entry_price
from backend.discovery.sector_leaders.forecast import (
    compute_rr_ratio,
    historical_quantiles,
    multi_horizon_forecast,
    recommend_stop_take,
)
from backend.discovery.sector_leaders.backtest import daily_to_monthly
from backend.services.models import (
    CustomsInterimExport,
    KrxDailyCandle,
    KrxStockMeta,
    MotirExportHistory,
    MotirItemExport,
    MotirRegionExport,
    SectorLeader,
)


@dataclass(frozen=True)
class Top10Item:
    rank: int
    ticker: str
    name: str
    item: str
    market_cap_krw: Optional[float]

    current_price: float
    entry_price: Optional[float]  # v2.0: 과열 시 None
    entry_status: str             # 🟢 / 🟡 / 🔴 + 설명
    entry_gap_pct: Optional[float]  # v2.0: 과열 시 None

    point_price: float          # 예측수익가
    point_pct: float            # 수익률
    stop_price: Optional[float]
    stop_pct: Optional[float]
    take_price: Optional[float]
    take_pct: Optional[float]

    confluence_score: float     # -1 ~ +1
    confidence_stars: str       # ★ / ★★ / ★★★
    confidence_label: str       # weak / medium / strong
    attractiveness: float       # 0 ~ 1

    horizon_months: int
    best_r: Optional[float]
    sample_warning: bool

    # 현재가 출처
    price_source: str           # "live" | "fallback"
    price_at: Optional[str]     # ISO timestamp (live) 또는 None (fallback)
    price_market_status: Optional[str]  # OPEN / CLOSE / None

    # v2.0 진입가 근거 (2026-07-08~) — plan.md §5-3
    high_52w: float             # 52주 최고 종가
    low_52w: float              # 52주 최저 종가
    pos_52w: float              # 0.0 (52W 저) ~ 1.0 (52W 고)
    atr14: float                # 14일 ATR (변동성)
    ma200: Optional[float]      # 200MA — 250일 미만이면 None
    ma200_deviation: Optional[float]  # 200MA 이격도 (소수)
    overheat: bool              # 과열 여부 (52W ≥85% or MA200 ≥+25%)
    entry_method: str = "v2.0-atr"


# ─────────────────────────────────────────────────────────────────
# 매력도 계산
# ─────────────────────────────────────────────────────────────────


def compute_attractiveness(
    confluence_score: float,
    best_r: Optional[float],
    rr_ratio: Optional[float],
) -> float:
    """매력도 점수 0~1.

    - confluence: max(0, score) — 음의 시그널은 0 (매수 비추천)
    - 신뢰도: |best_r| clipped to 1
    - R/R: min(ratio/3.0, 1.0) — 3:1 이상 만점
    """
    conf = max(0.0, confluence_score)
    confidence = min(abs(best_r or 0.0), 1.0)
    rr = min((rr_ratio or 0.0) / 3.0, 1.0)
    return 0.5 * conf + 0.3 * confidence + 0.2 * rr


def _stars_from_r(best_r: Optional[float]) -> tuple[str, str]:
    if best_r is None:
        return "★", "weak"
    a = abs(best_r)
    if a >= 0.7:
        return "★★★", "strong"
    if a >= 0.4:
        return "★★", "medium"
    return "★", "weak"


# ─────────────────────────────────────────────────────────────────
# Top 10 산출
# ─────────────────────────────────────────────────────────────────


async def compute_top10(
    session: AsyncSession,
    top_n: int = 10,
) -> list[Top10Item]:
    """SectorLeader 전체 → 매력도 정렬 → 상위 N."""
    from datetime import datetime, timezone

    # 일괄 사전 load
    leaders = (
        await session.execute(select(SectorLeader).order_by(SectorLeader.rank))
    ).scalars().all()
    metas = (await session.execute(select(KrxStockMeta))).scalars().all()
    meta_by_ticker = {m.ticker: m for m in metas}

    # 실시간 현재가 일괄 fetch (60초 캐시, 외부 실패 시 last_close fallback)
    live_quotes = await fetch_quotes([leader.ticker for leader in leaders])

    # 일봉 → 종목별 월말 종가/수익률 + OHLC 시계열 (진입가 v2.0)
    prices = (
        await session.execute(
            select(KrxDailyCandle).order_by(
                KrxDailyCandle.ticker, KrxDailyCandle.date
            )
        )
    ).scalars().all()
    daily_by_ticker: dict[str, list[tuple[str, float]]] = {}
    # v2.0: (high, low, close) 시계열 — entry_price 계산용 (오래된→최근)
    ohlc_by_ticker: dict[str, list[tuple[float, float, float]]] = {}
    for p in prices:
        daily_by_ticker.setdefault(p.ticker, []).append((p.date, p.close))
        ohlc_by_ticker.setdefault(p.ticker, []).append((p.high, p.low, p.close))
    monthly_by_ticker: dict[str, tuple[dict[str, float], dict[str, float]]] = {
        t: daily_to_monthly(d) for t, d in daily_by_ticker.items()
    }

    # 수출 yoy 시계열 (품목별)
    items = (
        await session.execute(
            select(MotirItemExport).where(MotirItemExport.yoy_pct.is_not(None))
        )
    ).scalars().all()
    yoy_by_item: dict[str, dict[str, float]] = {}
    final_by_item_month: dict[tuple[str, str], float] = {}
    for i in items:
        yoy_by_item.setdefault(i.item, {})[i.month] = i.yoy_pct
        final_by_item_month[(i.item, i.month)] = i.yoy_pct

    # 지역 yoy (월별 dict)
    regions = (await session.execute(select(MotirRegionExport))).scalars().all()
    region_yoy_by_month: dict[str, dict[str, float]] = {}
    for r in regions:
        if r.yoy_pct is not None:
            region_yoy_by_month.setdefault(r.month, {})[r.region] = r.yoy_pct

    # 잠정→확정 history (품목별)
    histories = (
        await session.execute(
            select(MotirExportHistory).where(MotirExportHistory.kind == "item")
        )
    ).scalars().all()
    history_by_item: dict[str, list[tuple[float, float]]] = {}
    for h in histories:
        if h.yoy_pct is None:
            continue
        curr = final_by_item_month.get((h.key, h.month))
        if curr is None:
            continue
        history_by_item.setdefault(h.key, []).append((h.yoy_pct, curr))

    # 관세청 잠정 매크로 YoY — 한 번만 fetch (전 종목 공통)
    customs_yoy: Optional[float] = None
    customs_period_label: Optional[str] = None
    latest_customs = (
        await session.execute(
            select(CustomsInterimExport)
            .where(CustomsInterimExport.country_code == "TOTAL")
            .order_by(desc(CustomsInterimExport.month), desc(CustomsInterimExport.period))
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_customs is not None:
        customs_yoy = await yoy_for_period(
            session,
            month=latest_customs.month,
            period=latest_customs.period,
            country_code="TOTAL",
        )
        customs_period_label = f"{latest_customs.month}/{latest_customs.period}"

    candidates: list[Top10Item] = []

    for leader in leaders:
        ticker = leader.ticker
        item = leader.item
        meta = meta_by_ticker.get(ticker)
        if meta is None or not meta.last_close or meta.last_close <= 0:
            continue

        # 현재가 — 실시간 우선, 실패 시 last_close fallback
        quote = live_quotes.get(ticker.zfill(6)) or live_quotes.get(ticker)
        if quote is not None and quote.current_price > 0:
            current_price = quote.current_price
            price_source = "live"
            price_at = datetime.fromtimestamp(
                quote.fetched_at, tz=timezone.utc
            ).isoformat()
            price_market_status = quote.market_status
        else:
            current_price = meta.last_close
            price_source = "fallback"
            price_at = None
            price_market_status = None

        close_map, ret_map = monthly_by_ticker.get(ticker, ({}, {}))
        if not close_map:
            continue

        yoy_map = yoy_by_item.get(item, {})
        if not yoy_map:
            continue
        latest_month = max(yoy_map.keys())
        latest_yoy = yoy_map[latest_month]

        region_yoys = region_yoy_by_month.get(latest_month, {})
        history_pairs = history_by_item.get(item, [])

        correlation_sign = 1 if (leader.best_r or 0) >= 0 else -1

        # Confluence (5종 시그널)
        confluence = compute_confluence(
            yoy_pct=latest_yoy,
            region_latest_yoys=region_yoys,
            monthly_close_by_month=close_map,
            history_revisions=history_pairs,
            correlation_sign=correlation_sign,
            customs_interim_yoy=customs_yoy,
            customs_interim_period=customs_period_label,
        )

        # Forecast — best_lag horizon
        best_lag = leader.best_lag_months if leader.best_lag_months is not None else 3
        # multi_horizon_forecast 는 양의 horizon 만 지원 — 음의 best_lag 는 |abs|
        h_target = max(1, abs(best_lag))
        horizons_out = multi_horizon_forecast(
            yoy_map, ret_map, latest_yoy, horizons=(h_target,)
        )
        if not horizons_out:
            continue
        horizon = horizons_out[0]

        # Historical band
        band = historical_quantiles(close_map, h_target)
        if band is None:
            continue

        # R/R
        rr = compute_rr_ratio(current_price, horizon.point_estimate_pct, band)
        # Stop / Take
        st = recommend_stop_take(current_price, horizon.point_estimate_pct, band)

        # 매력도
        attr = compute_attractiveness(
            confluence.score,
            leader.best_r,
            rr.ratio if rr else None,
        )

        # 점추정 가격 (참고용 — 진입가 산출과 무관, 예측수익가로만 노출)
        point_price = current_price * (1 + horizon.point_estimate_pct / 100)

        # 진입가 v2.0 — 52W 위치 + ATR14 + 200MA 이격도 기반
        entry_result = compute_entry_price(
            current_price=current_price,
            ohlc=ohlc_by_ticker.get(ticker, []),
        )

        stars, conf_label = _stars_from_r(leader.best_r)

        candidates.append(
            Top10Item(
                rank=0,  # 정렬 후 할당
                ticker=ticker,
                name=leader.name,
                item=item,
                market_cap_krw=leader.market_cap_krw,
                current_price=current_price,
                entry_price=entry_result.entry_price,
                entry_status=entry_result.entry_status,
                entry_gap_pct=entry_result.entry_gap_pct,
                point_price=point_price,
                point_pct=horizon.point_estimate_pct,
                stop_price=(st.stop_price if st else None),
                stop_pct=(st.stop_pct if st else None),
                take_price=(st.take_price if st else None),
                take_pct=(st.take_pct if st else None),
                confluence_score=confluence.score,
                confidence_stars=stars,
                confidence_label=conf_label,
                attractiveness=attr,
                horizon_months=h_target,
                best_r=leader.best_r,
                sample_warning=horizon.sample_warning,
                price_source=price_source,
                price_at=price_at,
                price_market_status=price_market_status,
                # v2.0 진입가 근거
                high_52w=entry_result.high_52w,
                low_52w=entry_result.low_52w,
                pos_52w=entry_result.pos_52w,
                atr14=entry_result.atr14,
                ma200=entry_result.ma200,
                ma200_deviation=entry_result.ma200_deviation,
                overheat=entry_result.overheat,
                entry_method=entry_result.entry_method,
            )
        )

    # 정렬 + 종목 무결성 (한 종목이 여러 품목에 매핑되어도 가장 강한 페어만 유지)
    candidates.sort(key=lambda c: c.attractiveness, reverse=True)
    seen: set[str] = set()
    unique: list[Top10Item] = []
    for c in candidates:
        if c.ticker in seen:
            continue
        seen.add(c.ticker)
        unique.append(c)
    top = unique[:top_n]
    return [
        Top10Item(**{**c.__dict__, "rank": i + 1}) for i, c in enumerate(top)
    ]
