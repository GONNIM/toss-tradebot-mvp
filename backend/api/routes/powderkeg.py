"""Powder Keg API 라우트 · Phase 7-6.

원칙 (지시서 §7-6-2):
    - 모든 화면 하단 고지: "본 화면은 공시·재무 데이터 기반 관찰 후보이며
      투자 권유가 아닙니다. 오너 관련 이벤트 표기는 공시·언론 보도 사실의 인용입니다."
    - 오너 개인 사건 표기는 공시/기사 원문 링크만 · 판단 문구 X (§7-6-3 명예훼손 방지).

라우트 분류:
    조회 (인증 없음)
        GET /list · GET /events · GET /report/{event_type}
        GET /tickets · GET /disclaimer
    편집·실행 (X-API-Token · require_sniper_token 재사용)
        POST /screener/run · POST /backtest/{event_type}
        POST /triggers/process
        POST /ticket · PATCH /ticket/{id}/approve · PATCH /ticket/{id}/reject
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select

from backend.api.auth import require_sniper_token
from backend.powderkeg.backtest import run_backtest_for_event_type
from backend.powderkeg.collectors.corp_codes import (
    refresh_corp_codes,
    resolve_corp_code,
    resolve_many,
)
from backend.powderkeg.collectors.dart_financials import collect_batch as dart_collect_batch
from backend.powderkeg.collectors.dart_shareholders import collect_batch as sh_collect_batch
from backend.powderkeg.collectors.events import poll_powderkeg_events
from backend.powderkeg.collectors.ftc_big_biz import list_all as list_big_biz, refresh_from_seed
from backend.powderkeg.collectors.krx_market import collect_market_snapshot
from backend.powderkeg.orders import (
    TicketCreateRequest,
    TicketValidationError,
    approve_ticket,
    check_holding_expiry,
    create_ticket,
    reject_ticket,
)
from backend.powderkeg.screener import run_screener
from backend.powderkeg.triggers import process_pending_events
from backend.services.db import get_session
from backend.services.models import (
    PowderKegEvent,
    PowderKegList,
    PowderKegOrderTicket,
)

logger = logging.getLogger(__name__)
router = APIRouter()


DISCLAIMER = (
    "본 화면은 공시·재무 데이터 기반 관찰 후보이며 투자 권유가 아닙니다. "
    "오너 관련 이벤트 표기는 공시·언론 보도 사실의 인용입니다."
)


# ═══════════════════════════════════════════════════════════════
# 조회 (인증 없음)
# ═══════════════════════════════════════════════════════════════
@router.get("/disclaimer")
async def get_disclaimer() -> dict[str, str]:
    return {"disclaimer": DISCLAIMER}


@router.get("/list")
async def get_list(
    run_id: Optional[str] = Query(None, description="특정 run · None = 최신"),
    status: Optional[str] = Query(None, description="passed / rejected / cash_suspect"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    """탭 1 · 화약고 리스트."""
    async with get_session() as session:
        if run_id is None:
            latest = (await session.execute(
                select(PowderKegList.run_id).order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
            run_id = latest
        if run_id is None:
            return {"disclaimer": DISCLAIMER, "run_id": None, "items": []}
        stmt = select(PowderKegList).where(PowderKegList.run_id == run_id)
        if status:
            stmt = stmt.where(PowderKegList.status == status)
        stmt = stmt.order_by(PowderKegList.net_cash_ratio.desc().nulls_last()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "count": len(rows),
        "items": [
            {
                "id": r.id, "ticker": r.ticker, "name": r.name,
                "status": r.status, "net_cash_ratio": r.net_cash_ratio,
                "piotroski_f_score": r.piotroski_f_score,
                "owner_pct": r.owner_pct, "treasury_pct": r.treasury_pct,
                "pbr": r.pbr, "dividend_payout": r.dividend_payout,
                "conditions": json.loads(r.conditions_json) if r.conditions_json else None,
                "reject_reasons": r.reject_reasons,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/events")
async def get_events(
    ticker: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    hours: int = Query(72, ge=1, le=720),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """탭 2 · 불꽃 피드 (Type A/B 타임라인)."""
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    async with get_session() as session:
        stmt = select(PowderKegEvent).where(PowderKegEvent.detected_at >= since)
        if ticker:
            stmt = stmt.where(PowderKegEvent.ticker == ticker)
        if event_type:
            stmt = stmt.where(PowderKegEvent.event_type == event_type)
        stmt = stmt.order_by(PowderKegEvent.detected_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "disclaimer": DISCLAIMER,
        "count": len(rows),
        "items": [
            {
                "id": r.id, "ticker": r.ticker, "event_type": r.event_type,
                "kind": "A" if r.event_type.startswith("A") else "B",
                "source": r.source, "source_id": r.source_id,
                "title": r.title,           # 원문 그대로 · 판단 문구 X
                "url": r.url,               # 원문 링크만 (§7-6-3)
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "release_date": r.release_date.isoformat() if r.release_date else None,
                "confidence": r.confidence,
                "needs_human_review": r.needs_human_review,
                "action_taken": r.action_taken,
                "validated": r.validated,
            }
            for r in rows
        ],
    }


@router.get("/report/{event_type}")
async def get_report(event_type: str) -> dict[str, Any]:
    """탭 3 · 백테스트 리포트 (저장 캐시 없음 · 매 호출 재계산 · v2 캐시)."""
    report = await run_backtest_for_event_type(event_type)
    report["disclaimer"] = DISCLAIMER
    return report


@router.get("/tickets")
async def get_tickets(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    async with get_session() as session:
        stmt = select(PowderKegOrderTicket)
        if status:
            stmt = stmt.where(PowderKegOrderTicket.status == status)
        stmt = stmt.order_by(PowderKegOrderTicket.created_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
    return {
        "disclaimer": DISCLAIMER,
        "count": len(rows),
        "items": [
            {
                "id": r.id, "event_id": r.event_id, "ticker": r.ticker,
                "proposed_qty": r.proposed_qty, "proposed_price": r.proposed_price,
                "invalidation_price": r.invalidation_price,
                "invalidation_logic": r.invalidation_logic,
                "status": r.status, "approver": r.approver,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "holding_days_max": r.holding_days_max,
                "executed_order_uuid": r.executed_order_uuid,
            }
            for r in rows
        ],
    }


@router.get("/holding-expiry")
async def get_expiry() -> dict[str, Any]:
    """12개월 초과 재평가 대상."""
    expired = await check_holding_expiry()
    return {"disclaimer": DISCLAIMER, "count": len(expired), "items": expired}


# ═══════════════════════════════════════════════════════════════
# 편집·실행 (X-API-Token 필수)
# ═══════════════════════════════════════════════════════════════
# ─── corp_code 매핑 (Phase 7-1g) ────────────────
@router.post("/collectors/corp-codes-refresh", dependencies=[Depends(require_sniper_token)])
async def trigger_corp_codes_refresh() -> dict[str, Any]:
    """DART fetch_corp_codes → DartCorpCodeMap 갱신 (월 1회 권장)."""
    return await refresh_corp_codes()


@router.get("/corp-code/{ticker}")
async def get_corp_code(ticker: str) -> dict[str, Optional[str]]:
    """KRX 6자리 → corp_code 조회 · UI 확인용."""
    cc = await resolve_corp_code(ticker)
    return {"ticker": ticker, "corp_code": cc}


# ─── 수동 스키마 마이그레이션 · SQLite CREATE / ALTER ─
@router.post("/admin/migrate-schema", dependencies=[Depends(require_sniper_token)])
async def migrate_schema() -> dict[str, Any]:
    """스키마 마이그레이션:
    1. Base.metadata.create_all · 미존재 테이블 생성 (신규 모델 반영)
    2. ALTER TABLE ADD COLUMN · 기존 테이블 컬럼 추가 (SQLite 제약 우회)
    """
    from sqlalchemy import text
    from backend.services.db import engine
    from backend.services.models import Base

    changes: list[str] = []
    errors: list[str] = []

    # 1. WAL 모드 활성 · 동시 read/write 완화 · create_all 락 회피 도움
    try:
        async with get_session() as session:
            r = await session.execute(text("PRAGMA journal_mode=WAL"))
            changes.append(f"journal_mode={r.scalar()}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"wal: {str(exc)[:150]}")

    # 2. 직접 CREATE TABLE IF NOT EXISTS · SQLAlchemy PRAGMA lookup 우회
    #    신규 모델 추가 시 여기 append (컬럼 정의는 models.py 와 일치 유지)
    direct_creates = [
        ("powderkeg_dart_corp_code", """
            CREATE TABLE IF NOT EXISTS powderkeg_dart_corp_code (
                corp_code VARCHAR(8) NOT NULL PRIMARY KEY,
                corp_name VARCHAR(200) NOT NULL,
                stock_code VARCHAR(10),
                modify_date VARCHAR(10),
                refreshed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_dart_corp_code_stock",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_dart_corp_code_stock "
         "ON powderkeg_dart_corp_code (stock_code)"),
    ]
    async with get_session() as session:
        for name, ddl in direct_creates:
            try:
                await session.execute(text(ddl))
                changes.append(f"create:{name}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {str(exc)[:150]}")

    # 3. ALTER TABLE ADD COLUMN (기존 테이블 · schema drift)
    alter_stmts = [
        ("powderkeg_krx_snapshot", "name", "VARCHAR(100)"),
    ]
    async with get_session() as session:
        for table, col, col_type in alter_stmts:
            try:
                await session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                changes.append(f"alter:{table}.{col}")
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "duplicate column name" in msg.lower() or "already" in msg.lower():
                    continue
                errors.append(f"{table}.{col}: {msg[:100]}")
    return {"applied": changes, "errors": errors}


# ─── Collectors 트리거 (인증 필수 · 외부 API 호출 · 부하 유의) ─
@router.post("/collectors/ftc-refresh", dependencies=[Depends(require_sniper_token)])
async def trigger_ftc_refresh(year: int = Body(2026, embed=True)) -> dict[str, Any]:
    """공정위 대기업집단 seed → BigBusinessGroup 재적재."""
    return await refresh_from_seed(year)


@router.get("/candidates/kosdaq-low-pbr")
async def get_kosdaq_low_pbr_candidates(
    max_pbr: float = Query(0.7, description="PBR 상한"),
    min_market_cap: float = Query(30_000_000_000, description="시총 하한 (원)"),
    max_market_cap: float = Query(1_000_000_000_000_000, description="시총 상한"),
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """KRX 스냅샷 필터 · KOSDAQ 저PBR 후보 종목 리스트.

    스크리너 batch 대상 선정용. 데이터 수집 전 pre-filter.
    """
    from backend.services.models import KrxMarketSnapshot
    async with get_session() as session:
        # 최신 snapshot_date
        latest_date = (await session.execute(
            select(KrxMarketSnapshot.snapshot_date)
            .order_by(KrxMarketSnapshot.snapshot_date.desc()).limit(1)
        )).scalar_one_or_none()
        if not latest_date:
            return {"count": 0, "items": []}
        stmt = (
            select(KrxMarketSnapshot)
            .where(
                KrxMarketSnapshot.snapshot_date == latest_date,
                KrxMarketSnapshot.market == "KOSDAQ",
                KrxMarketSnapshot.pbr.is_not(None),
                KrxMarketSnapshot.pbr < max_pbr,
                KrxMarketSnapshot.pbr > 0,
                KrxMarketSnapshot.market_cap.is_not(None),
                KrxMarketSnapshot.market_cap >= min_market_cap,
                KrxMarketSnapshot.market_cap <= max_market_cap,
            )
            .order_by(KrxMarketSnapshot.market_cap.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(rows),
        "snapshot_date": latest_date,
        "filter": {"max_pbr": max_pbr, "min_market_cap": min_market_cap, "max_market_cap": max_market_cap},
        "items": [
            {
                "ticker": r.ticker, "name": r.name, "pbr": r.pbr,
                "market_cap": r.market_cap, "close_price": r.close_price,
            }
            for r in rows
        ],
    }


@router.get("/big-biz")
async def get_big_biz(year: int = Query(2026)) -> dict[str, Any]:
    """대기업집단 목록 조회 (디버그·UI 검증용)."""
    items = await list_big_biz(year)
    return {"year": year, "count": len(items), "items": items}


@router.post("/collectors/krx-snapshot", dependencies=[Depends(require_sniper_token)])
async def trigger_krx_snapshot(
    tickers: Optional[list[str]] = Body(None, embed=True),
    include_adv60: bool = Body(False, embed=True),
) -> dict[str, Any]:
    """KRX 시장 스냅샷 (KOSPI+KOSDAQ 전체 또는 tickers 지정)."""
    return await collect_market_snapshot(
        tickers=set(tickers) if tickers else None,
        include_adv60=include_adv60,
    )


@router.post("/collectors/dart-financials", dependencies=[Depends(require_sniper_token)])
async def trigger_dart_financials(
    tickers: Optional[list[str]] = Body(None, embed=True),
    targets: Optional[list[dict[str, str]]] = Body(None, embed=True),
    bsns_year: int = Body(2026, embed=True),
    reprt_code: str = Body("11011", embed=True),
) -> dict[str, Any]:
    """DART 재무제표 batch 수집.

    입력 방식 (하나만):
      tickers: ["005930", "000660", ...] · corp_code 자동 해결 (DartCorpCodeMap 필요)
      targets: [{"ticker": ..., "corp_code": ...}, ...] · 직접 지정

    reprt_code: 11011(사업)·11012(반기)·11013(1분기)·11014(3분기)
    """
    pairs = await _resolve_pairs(tickers, targets)
    if not pairs:
        raise HTTPException(status_code=400, detail="no valid (ticker,corp_code) resolved")
    return await dart_collect_batch(pairs, bsns_year=bsns_year, reprt_code=reprt_code)


async def _resolve_pairs(
    tickers: Optional[list[str]], targets: Optional[list[dict[str, str]]],
) -> list[tuple[str, str]]:
    """tickers → corp_codes 자동 해결 · targets 직접 지정 · 하나 이상 필수."""
    if targets:
        return [(t["ticker"], t["corp_code"]) for t in targets
                if t.get("ticker") and t.get("corp_code")]
    if tickers:
        cc_map = await resolve_many(tickers)
        return [(tk, cc_map[tk]) for tk in tickers if cc_map.get(tk)]
    return []


@router.post("/collectors/dart-shareholders", dependencies=[Depends(require_sniper_token)])
async def trigger_dart_shareholders(
    tickers: Optional[list[str]] = Body(None, embed=True),
    targets: Optional[list[dict[str, str]]] = Body(None, embed=True),
    bsns_year: int = Body(2025, embed=True),
    reprt_code: str = Body("11011", embed=True),
) -> dict[str, Any]:
    """DART 최대주주 현황 + 자기주식 batch.

    입력 방식 (하나만):
      tickers: 티커 리스트 · corp_code 자동 해결
      targets: 직접 지정
    """
    pairs = await _resolve_pairs(tickers, targets)
    if not pairs:
        raise HTTPException(status_code=400, detail="no valid (ticker,corp_code) resolved")
    return await sh_collect_batch(pairs, bsns_year=bsns_year, reprt_code=reprt_code)


@router.post("/collectors/events-poll", dependencies=[Depends(require_sniper_token)])
async def trigger_events_poll(
    lookback_days: int = Body(1, embed=True),
    watched_tickers: Optional[list[str]] = Body(None, embed=True),
) -> dict[str, Any]:
    """DART 공시 이벤트 폴링 · Type A/B 분류 후 PowderKegEvent 저장.

    watched_tickers None = 모든 매칭 저장 · list = 감시 대상만.
    """
    return await poll_powderkeg_events(
        lookback_days=lookback_days,
        watched_tickers=set(watched_tickers) if watched_tickers else None,
    )


@router.post("/screener/run", dependencies=[Depends(require_sniper_token)])
async def trigger_screener(
    tickers: list[str] = Body(..., embed=True),
    year: int = Body(2026, embed=True),
) -> dict[str, Any]:
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers required")
    return await run_screener(tickers, year=year)


@router.post("/backtest/{event_type}", dependencies=[Depends(require_sniper_token)])
async def trigger_backtest(event_type: str) -> dict[str, Any]:
    """이벤트 타입 백테스트 실행 + validated 승격 (게이트 통과 시)."""
    return await run_backtest_for_event_type(event_type)


@router.post("/triggers/process", dependencies=[Depends(require_sniper_token)])
async def trigger_process_pending() -> dict[str, Any]:
    """미처리 이벤트 batch · Type A/B 액션 실행."""
    return await process_pending_events()


@router.post("/ticket", dependencies=[Depends(require_sniper_token)])
async def create_ticket_route(
    event_id: int = Body(...),
    ticker: str = Body(...),
    proposed_qty: int = Body(...),
    invalidation_price: float = Body(...),
    invalidation_logic: str = Body(...),
    total_capital_krw: float = Body(...),
    per_ticker_krw: float = Body(...),
    proposed_price: Optional[float] = Body(None),
    holding_days_max: int = Body(365),
) -> dict[str, Any]:
    req = TicketCreateRequest(
        event_id=event_id, ticker=ticker,
        proposed_qty=proposed_qty,
        invalidation_price=invalidation_price,
        invalidation_logic=invalidation_logic,
        proposed_price=proposed_price,
        holding_days_max=holding_days_max,
    )
    try:
        tid = await create_ticket(req, total_capital_krw, per_ticker_krw)
    except TicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": tid, "status": "pending"}


@router.patch("/ticket/{ticket_id}/approve", dependencies=[Depends(require_sniper_token)])
async def approve_route(ticket_id: int, approver: str = Body(..., embed=True)) -> dict[str, Any]:
    ok = await approve_ticket(ticket_id, approver)
    if not ok:
        raise HTTPException(status_code=400, detail="approve_failed(status_not_pending)")
    return {"id": ticket_id, "status": "approved"}


@router.patch("/ticket/{ticket_id}/reject", dependencies=[Depends(require_sniper_token)])
async def reject_route(ticket_id: int, reason: str = Body(..., embed=True)) -> dict[str, Any]:
    ok = await reject_ticket(ticket_id, reason)
    if not ok:
        raise HTTPException(status_code=400, detail="reject_failed(status_not_pending)")
    return {"id": ticket_id, "status": "rejected"}
