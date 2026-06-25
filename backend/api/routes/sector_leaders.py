"""Sector Leaders 라우트 (B-2e).

엔드포인트:
- GET /                — 17 품목 카드 요약 + 각 품목 Top N 주도주
- GET /items/{item}    — 단일 품목 상세 (수출 13M + 주도주 + r/lag)
- GET /tickers/{ticker} — 단일 종목 상세 (24M 일봉 + 해당 품목 수출 + r/lag)

설계: docs/plans/sector-leaders/01-mvp-design.md
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import asc, desc, func, select

from backend.api.schemas import (
    BacktestBucketResponse,
    ConfluenceResponse,
    ExportSeriesPoint,
    FanChartPointResponse,
    ForecastDisclaimer,
    HistoricalBandResponse,
    HorizonAdvice,
    HorizonForecastResponse,
    LatestSignalHintResponse,
    MonthlyJoinRowResponse,
    OOSMetricsResponse,
    PriceSeriesPoint,
    RiskRewardResponse,
    SectorItemDetail,
    SectorItemSummary,
    SectorLeaderResponse,
    SignalContributionResponse,
    StopTakeProfitResponse,
    TickerAnalysisResponse,
    TickerConfluenceResponse,
    TickerDetail,
    TickerForecastResponse,
    Top10ItemResponse,
    Top10Response,
    VerdictResponse,
)
from backend.discovery.data_sources.customs_interim import yoy_for_period
from backend.discovery.data_sources.mapping import load_mapping
from backend.discovery.sector_leaders import (
    compute_confluence,
    compute_monthly_join,
    compute_rr_ratio,
    compute_top10,
    compute_verdict,
    compute_yoy_buckets,
    daily_to_monthly,
    fan_chart_points,
    historical_quantiles,
    latest_signal_hint,
    multi_horizon_forecast,
    oos_validate,
    recommend_stop_take,
)
from backend.services.db import get_session
from backend.services.models import (
    CustomsInterimExport,
    KrxDailyCandle,
    MotirExportHistory,
    MotirItemExport,
    MotirRegionExport,
    SectorLeader,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# GET /top10  — 투자 종목 Top 10 (B-2j)
# ─────────────────────────────────────────────────────────────────


@router.get("/top10", response_model=Top10Response)
async def get_top10(limit: int = Query(10, ge=1, le=51)):
    """매력도 점수 상위 N — Confluence 0.5 + 신뢰도 0.3 + R/R 0.2."""
    from datetime import datetime

    async with get_session() as session:
        items = await compute_top10(session, top_n=limit)
        # total_candidates: 양의 매력도 종목 개수 (참고용)
        all_count = (
            await session.execute(select(func.count()).select_from(SectorLeader))
        ).scalar() or 0

    return Top10Response(
        items=[Top10ItemResponse(**it.__dict__) for it in items],
        total_candidates=all_count,
        computed_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )


CONFIDENCE_RANK = {"strong": 0, "medium": 1, "weak": 2}


def _strongest(a: str, b: str) -> str:
    return a if CONFIDENCE_RANK.get(a, 9) <= CONFIDENCE_RANK.get(b, 9) else b


# ─────────────────────────────────────────────────────────────────
# GET /  — 17 품목 카드 요약
# ─────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[SectorItemSummary])
async def list_items(top_n: int = Query(3, ge=1, le=10)):
    """매핑된 모든 품목 + 최신 월 수출 + 품목 내 최강 배지."""
    mapping = load_mapping()["items"]

    async with get_session() as session:
        leaders_rows = (
            await session.execute(
                select(SectorLeader).order_by(SectorLeader.item, SectorLeader.rank)
            )
        ).scalars().all()
        latest_exports = (
            await session.execute(
                select(MotirItemExport).order_by(
                    MotirItemExport.item, desc(MotirItemExport.month)
                )
            )
        ).scalars().all()

    # 품목별 최신 수출
    latest_by_item: dict[str, MotirItemExport] = {}
    for r in latest_exports:
        if r.item not in latest_by_item:
            latest_by_item[r.item] = r

    # 품목별 leaders 그룹화
    leaders_by_item: dict[str, list[SectorLeader]] = {}
    for r in leaders_rows:
        leaders_by_item.setdefault(r.item, []).append(r)

    out: list[SectorItemSummary] = []
    for item_name in mapping.keys():
        leaders = leaders_by_item.get(item_name, [])
        top_conf = "weak"
        for l in leaders:
            top_conf = _strongest(top_conf, l.confidence)
        latest = latest_by_item.get(item_name)
        out.append(
            SectorItemSummary(
                item=item_name,
                latest_value_musd=latest.value_musd if latest else None,
                latest_yoy_pct=latest.yoy_pct if latest else None,
                top_confidence=top_conf,
                leader_count=len(leaders),
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────
# GET /items/{item}  — 품목 상세
# ─────────────────────────────────────────────────────────────────


@router.get("/items/{item}", response_model=SectorItemDetail)
async def get_item_detail(item: str, top_n: int = Query(3, ge=1, le=20)):
    """단일 품목 상세 — 수출 13M 시계열 + 주도주 Top N + r/lag."""
    mapping = load_mapping()["items"]
    if item not in mapping:
        raise HTTPException(404, f"품목 매핑 없음: {item}")
    description = mapping[item].get("description")

    async with get_session() as session:
        exports = (
            await session.execute(
                select(MotirItemExport)
                .where(MotirItemExport.item == item)
                .order_by(asc(MotirItemExport.month))
            )
        ).scalars().all()
        leaders = (
            await session.execute(
                select(SectorLeader)
                .where(SectorLeader.item == item)
                .order_by(SectorLeader.rank)
                .limit(top_n)
            )
        ).scalars().all()

    return SectorItemDetail(
        item=item,
        description=description,
        export_series=[
            ExportSeriesPoint(month=e.month, value_musd=e.value_musd, yoy_pct=e.yoy_pct)
            for e in exports
        ],
        leaders=[SectorLeaderResponse.model_validate(l) for l in leaders],
    )


# ─────────────────────────────────────────────────────────────────
# GET /tickers/{ticker}  — 종목 상세
# ─────────────────────────────────────────────────────────────────


@router.get("/tickers/{ticker}", response_model=TickerDetail)
async def get_ticker_detail(
    ticker: str,
    item: Optional[str] = Query(
        None, description="동일 종목이 여러 품목에 매핑된 경우 명시"
    ),
):
    """단일 종목 24M 일봉 + 해당 품목 수출 시계열 + r/lag."""
    async with get_session() as session:
        # SectorLeader 조회 — item 명시 안 하면 동일 ticker 의 가장 강한 페어
        stmt = (
            select(SectorLeader)
            .where(SectorLeader.ticker == ticker)
            .order_by(SectorLeader.rank)
        )
        if item:
            stmt = stmt.where(SectorLeader.item == item)
        leaders = (await session.execute(stmt)).scalars().all()
        if not leaders:
            raise HTTPException(404, f"종목 매핑 없음: {ticker}")
        leader = leaders[0]

        prices = (
            await session.execute(
                select(KrxDailyCandle)
                .where(KrxDailyCandle.ticker == ticker)
                .order_by(asc(KrxDailyCandle.date))
            )
        ).scalars().all()

        exports = (
            await session.execute(
                select(MotirItemExport)
                .where(MotirItemExport.item == leader.item)
                .order_by(asc(MotirItemExport.month))
            )
        ).scalars().all()

    return TickerDetail(
        leader=SectorLeaderResponse.model_validate(leader),
        price_series=[
            PriceSeriesPoint(date=p.date, close=p.close, return_pct=p.return_pct)
            for p in prices
        ],
        export_series=[
            ExportSeriesPoint(month=e.month, value_musd=e.value_musd, yoy_pct=e.yoy_pct)
            for e in exports
        ],
    )


# ─────────────────────────────────────────────────────────────────
# GET /tickers/{ticker}/analysis  — 분석 패널 통합 응답 (B-2f)
# ─────────────────────────────────────────────────────────────────


@router.get("/tickers/{ticker}/analysis", response_model=TickerAnalysisResponse)
async def get_ticker_analysis(
    ticker: str,
    item: Optional[str] = Query(None, description="동일 종목 다중 매핑 시"),
):
    """종목 분석 패널 통합 데이터 — 가격·수출·백테스트·시그널."""
    async with get_session() as session:
        stmt = (
            select(SectorLeader)
            .where(SectorLeader.ticker == ticker)
            .order_by(SectorLeader.rank)
        )
        if item:
            stmt = stmt.where(SectorLeader.item == item)
        leader = (await session.execute(stmt)).scalars().first()
        if leader is None:
            raise HTTPException(404, f"종목 매핑 없음: {ticker}")

        prices = (
            await session.execute(
                select(KrxDailyCandle)
                .where(KrxDailyCandle.ticker == ticker)
                .order_by(asc(KrxDailyCandle.date))
            )
        ).scalars().all()

        exports = (
            await session.execute(
                select(MotirItemExport)
                .where(MotirItemExport.item == leader.item)
                .order_by(asc(MotirItemExport.month))
            )
        ).scalars().all()

    # 일봉 → 월말 종가 + 월간 수익률
    daily_pairs = [(p.date, p.close) for p in prices]
    close_map, ret_map = daily_to_monthly(daily_pairs)

    yoy_map = {e.month: e.yoy_pct for e in exports if e.yoy_pct is not None}
    value_map = {e.month: e.value_musd for e in exports}

    correlation_sign = 1 if (leader.best_r is not None and leader.best_r >= 0) else -1
    best_lag = leader.best_lag_months or 0

    buckets_lag0 = compute_yoy_buckets(yoy_map, ret_map, lag_months=0)
    buckets_best = compute_yoy_buckets(yoy_map, ret_map, lag_months=best_lag)

    join_rows = compute_monthly_join(
        yoy_map, value_map, close_map, ret_map, correlation_sign=correlation_sign,
    )

    hint = latest_signal_hint(
        yoy_map,
        best_lag_months=best_lag,
        correlation_r=leader.best_r or 0.0,
    )

    return TickerAnalysisResponse(
        leader=SectorLeaderResponse.model_validate(leader),
        correlation_sign=correlation_sign,
        export_series=[
            ExportSeriesPoint(month=e.month, value_musd=e.value_musd, yoy_pct=e.yoy_pct)
            for e in exports
        ],
        monthly_close=[
            PriceSeriesPoint(date=m, close=c, return_pct=ret_map.get(m))
            for m, c in close_map.items()
        ],
        backtest_lag0=[BacktestBucketResponse(**b.__dict__) for b in buckets_lag0],
        backtest_best_lag=[BacktestBucketResponse(**b.__dict__) for b in buckets_best],
        monthly_join=[MonthlyJoinRowResponse(**r.__dict__) for r in join_rows],
        latest_signal=(
            LatestSignalHintResponse(**hint.__dict__) if hint else None
        ),
    )


# ─────────────────────────────────────────────────────────────────
# GET /tickers/{ticker}/forecast  — Multi-horizon 미래 예측 (B-2g)
# ─────────────────────────────────────────────────────────────────


@router.get("/tickers/{ticker}/forecast", response_model=TickerForecastResponse)
async def get_ticker_forecast(
    ticker: str,
    item: Optional[str] = Query(None),
    horizons: str = Query("1,3,6", description="콤마 분리, 예: '1,3,6'"),
):
    """미래 주가 예측 — Lagged Linear Regression + Multi-horizon + Fan Chart + OOS."""
    try:
        horizon_list = tuple(int(h) for h in horizons.split(",") if h.strip())
    except ValueError:
        raise HTTPException(400, f"invalid horizons: {horizons!r}")
    if not horizon_list:
        raise HTTPException(400, "horizons empty")

    async with get_session() as session:
        stmt = (
            select(SectorLeader)
            .where(SectorLeader.ticker == ticker)
            .order_by(SectorLeader.rank)
        )
        if item:
            stmt = stmt.where(SectorLeader.item == item)
        leader = (await session.execute(stmt)).scalars().first()
        if leader is None:
            raise HTTPException(404, f"종목 매핑 없음: {ticker}")

        prices = (
            await session.execute(
                select(KrxDailyCandle)
                .where(KrxDailyCandle.ticker == ticker)
                .order_by(asc(KrxDailyCandle.date))
            )
        ).scalars().all()

        exports = (
            await session.execute(
                select(MotirItemExport)
                .where(MotirItemExport.item == leader.item)
                .order_by(asc(MotirItemExport.month))
            )
        ).scalars().all()

    daily_pairs = [(p.date, p.close) for p in prices]
    close_map, ret_map = daily_to_monthly(daily_pairs)
    yoy_map = {e.month: e.yoy_pct for e in exports if e.yoy_pct is not None}

    if not yoy_map:
        raise HTTPException(404, f"수출 시계열 없음: {leader.item}")

    latest_month = max(yoy_map.keys())
    latest_yoy = yoy_map[latest_month]

    horizons_out = multi_horizon_forecast(yoy_map, ret_map, latest_yoy, horizons=horizon_list)
    fan = fan_chart_points(
        yoy_map, ret_map, latest_yoy, latest_data_month=latest_month, n_horizons=max(horizon_list)
    )

    # 실측 분위수 — fan chart 모든 horizon (1..max) 에 대해 계산
    bands_out = []
    for h in range(1, max(horizon_list) + 1):
        band = historical_quantiles(close_map, h)
        if band is not None:
            bands_out.append(band)

    best_lag = leader.best_lag_months or 0
    oos = oos_validate(yoy_map, ret_map, lag_months=best_lag)

    correlation_sign = 1 if (leader.best_r is not None and leader.best_r >= 0) else -1

    disclaimer = ForecastDisclaimer(
        method="lagged_linear_regression_ols + historical_quantiles_nonparametric",
        ci_method="historical_p10_p90_quantiles_of_rolling_window",
        sample_window=f"{min(yoy_map.keys())} ~ {latest_month} ({len(yoy_map)}M)",
        limitations=[
            "기본 시나리오 = 단변량 회귀 점추정 (수출 YoY → 수익률)",
            "강세/약세 범위 = 종목 24M rolling 누적 수익률의 실측 P10/P90",
            "기본 점추정이 강세/약세 범위를 벗어나면 '통계적 이례' — 시그널 매우 강함",
            "본 모델은 보조 신호 — 투자 권유 아님 · 사용자 자체 판단 필수",
        ],
    )

    # 현재가 — 실시간 우선, 실패 시 일봉 마지막 종가 fallback
    from datetime import datetime, timezone
    from backend.discovery.data_sources.naver_quote import fetch_one
    fallback_close = prices[-1].close if prices else None
    fallback_date = prices[-1].date if prices else None
    quote = await fetch_one(ticker)
    if quote is not None and quote.current_price > 0:
        latest_close = quote.current_price
        latest_close_date = None
        price_source = "live"
        price_at = datetime.fromtimestamp(
            quote.fetched_at, tz=timezone.utc
        ).isoformat()
        price_market_status = quote.market_status
    else:
        latest_close = fallback_close
        latest_close_date = fallback_date
        price_source = "fallback"
        price_at = None
        price_market_status = None

    # v4 — horizon별 종합 판정 / R/R / Stop·Take
    bands_by_h = {b.horizon_months: b for b in bands_out}
    advice_list: list[HorizonAdvice] = []
    for h in horizons_out:
        band = bands_by_h.get(h.horizon_months)
        verdict = compute_verdict(
            h, band, oos_hit_rate=(oos.hit_rate if oos else None)
        )
        rr = (
            compute_rr_ratio(latest_close, h.point_estimate_pct, band)
            if latest_close is not None
            else None
        )
        st = (
            recommend_stop_take(latest_close, h.point_estimate_pct, band)
            if latest_close is not None
            else None
        )
        advice_list.append(
            HorizonAdvice(
                horizon_months=h.horizon_months,
                verdict=VerdictResponse(**verdict.__dict__),
                risk_reward=RiskRewardResponse(**rr.__dict__) if rr else None,
                stop_take=StopTakeProfitResponse(**st.__dict__) if st else None,
            )
        )

    return TickerForecastResponse(
        leader=SectorLeaderResponse.model_validate(leader),
        correlation_sign=correlation_sign,
        latest_data_month=latest_month,
        latest_input_yoy=latest_yoy,
        latest_close_krw=latest_close,
        latest_close_date=latest_close_date,
        horizons=[HorizonForecastResponse(**h.__dict__) for h in horizons_out],
        fan_chart=[FanChartPointResponse(**f.__dict__) for f in fan],
        historical_bands=[HistoricalBandResponse(**b.__dict__) for b in bands_out],
        advice_by_horizon=advice_list,
        oos_metrics=(OOSMetricsResponse(**oos.__dict__) if oos else None),
        disclaimer=disclaimer,
        price_source=price_source,
        price_at=price_at,
        price_market_status=price_market_status,
    )


# ─────────────────────────────────────────────────────────────────
# GET /tickers/{ticker}/confluence  — 다중 시그널 통합 (B-2i-a)
# ─────────────────────────────────────────────────────────────────


@router.get("/tickers/{ticker}/confluence", response_model=TickerConfluenceResponse)
async def get_ticker_confluence(
    ticker: str,
    item: Optional[str] = Query(None),
):
    """4종 시그널(수출/지역/모멘텀/갱신) 통합 — Confluence Score."""
    async with get_session() as session:
        stmt = (
            select(SectorLeader)
            .where(SectorLeader.ticker == ticker)
            .order_by(SectorLeader.rank)
        )
        if item:
            stmt = stmt.where(SectorLeader.item == item)
        leader = (await session.execute(stmt)).scalars().first()
        if leader is None:
            raise HTTPException(404, f"종목 매핑 없음: {ticker}")

        # 최신 수출 yoy
        latest_item = (
            await session.execute(
                select(MotirItemExport)
                .where(
                    MotirItemExport.item == leader.item,
                    MotirItemExport.yoy_pct.is_not(None),
                )
                .order_by(desc(MotirItemExport.month))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_item is None:
            raise HTTPException(404, f"수출 시계열 없음: {leader.item}")

        latest_month = latest_item.month
        latest_yoy = latest_item.yoy_pct or 0.0

        # 지역별 최신 yoy
        region_rows = (
            await session.execute(
                select(MotirRegionExport)
                .where(MotirRegionExport.month == latest_month)
            )
        ).scalars().all()
        region_yoys: dict[str, float] = {
            r.region: r.yoy_pct for r in region_rows if r.yoy_pct is not None
        }

        # 종목 일봉 → 월말 종가
        prices = (
            await session.execute(
                select(KrxDailyCandle)
                .where(KrxDailyCandle.ticker == ticker)
                .order_by(asc(KrxDailyCandle.date))
            )
        ).scalars().all()
        daily_pairs = [(p.date, p.close) for p in prices]
        close_map, _ = daily_to_monthly(daily_pairs)

        # 잠정→확정 변경 이력
        history_rows = (
            await session.execute(
                select(MotirExportHistory)
                .where(
                    MotirExportHistory.kind == "item",
                    MotirExportHistory.key == leader.item,
                )
            )
        ).scalars().all()
        # 각 이력 행: history 의 yoy(이전) vs 현재 최종 (MotirItemExport)
        # 단순화: 각 이력 → (이전 yoy, 현재 final yoy) 페어
        # 현재 final 가져오기
        final_by_month = {
            it.month: it.yoy_pct
            for it in (await session.execute(select(MotirItemExport).where(MotirItemExport.item == leader.item))).scalars().all()
            if it.yoy_pct is not None
        }
        revisions: list[tuple[float, float]] = []
        for h in history_rows:
            if h.yoy_pct is None:
                continue
            curr = final_by_month.get(h.month)
            if curr is None:
                continue
            revisions.append((h.yoy_pct, curr))

    correlation_sign = 1 if (leader.best_r is not None and leader.best_r >= 0) else -1

    # 관세청 잠정 YoY — 가장 최근 1~20일 우선, 없으면 1~10일
    customs_yoy: Optional[float] = None
    customs_period_label: Optional[str] = None
    async with get_session() as session2:
        # 최신 관세청 데이터 month·period 찾기
        latest_customs = (
            await session2.execute(
                select(CustomsInterimExport)
                .where(CustomsInterimExport.country_code == "TOTAL")
                .order_by(desc(CustomsInterimExport.month), desc(CustomsInterimExport.period))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_customs is not None:
            customs_yoy = await yoy_for_period(
                session2,
                month=latest_customs.month,
                period=latest_customs.period,
                country_code="TOTAL",
            )
            customs_period_label = f"{latest_customs.month}/{latest_customs.period}"

    result = compute_confluence(
        yoy_pct=latest_yoy,
        region_latest_yoys=region_yoys,
        monthly_close_by_month=close_map,
        history_revisions=revisions,
        correlation_sign=correlation_sign,
        customs_interim_yoy=customs_yoy,
        customs_interim_period=customs_period_label,
    )

    return TickerConfluenceResponse(
        leader=SectorLeaderResponse.model_validate(leader),
        correlation_sign=correlation_sign,
        latest_data_month=latest_month,
        confluence=ConfluenceResponse(
            score=result.score,
            score_pct=result.score_pct,
            direction=result.direction,
            agreement_count=result.agreement_count,
            disagreement_count=result.disagreement_count,
            total_signals=result.total_signals,
            contributions=[
                SignalContributionResponse(**c.__dict__) for c in result.contributions
            ],
            grade=result.grade,
            grade_label=result.grade_label,
            grade_color=result.grade_color,
            interpretation=result.interpretation,
        ),
    )
