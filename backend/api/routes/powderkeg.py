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
from backend.powderkeg.collectors.events import backfill_powderkeg_events, poll_powderkeg_events
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

    def _extract_robustness(cond_json_str: Optional[str]) -> dict:
        """v1.14 · conditions_json 에서 _robustness meta 추출."""
        if not cond_json_str:
            return {}
        try:
            data = json.loads(cond_json_str)
        except Exception:  # noqa: BLE001
            return {}
        if isinstance(data, dict) and "_robustness" in data:
            r = data["_robustness"]
            return {
                "robustness_score": r.get("score"),
                "robustness_grade": r.get("grade"),
                "condition_margins": r.get("margins", {}),
            }
        return {}

    items = []
    for r in rows:
        cond = json.loads(r.conditions_json) if r.conditions_json else None
        # UI 는 boolean 조건만 필요 · _robustness 필드 제거 후 반환
        if isinstance(cond, dict) and "_robustness" in cond:
            cond = {k: v for k, v in cond.items() if k != "_robustness"}
        rob = _extract_robustness(r.conditions_json)
        items.append({
            "id": r.id, "ticker": r.ticker, "name": r.name,
            "status": r.status, "net_cash_ratio": r.net_cash_ratio,
            "piotroski_f_score": r.piotroski_f_score,
            "owner_pct": r.owner_pct, "treasury_pct": r.treasury_pct,
            "pbr": r.pbr, "dividend_payout": r.dividend_payout,
            "conditions": cond,
            "reject_reasons": r.reject_reasons,
            "locked": getattr(r, "locked", False) or False,
            "added_by": getattr(r, "added_by", "auto") or "auto",
            "user_note": getattr(r, "user_note", None),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            **rob,
        })

    return {
        "disclaimer": DISCLAIMER,
        "run_id": run_id,
        "count": len(rows),
        "items": items,
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
    """탭 3 · 백테스트 리포트 (캐시 읽기 · §9-3 · 5년 표본 60s 초과 대응).

    캐시 없으면 empty 응답 · POST /backtest/{event_type} 트리거 필요.
    """
    from backend.powderkeg.backtest import read_cached_report
    cached = await read_cached_report(event_type)
    if cached is None:
        return {
            "event_type": event_type,
            "aggregate": {"event_type": event_type, "total_events": 0, "valid_events": 0, "per_window": {}, "error_counts": {}},
            "decision": {"event_type": event_type, "validated": False, "reasons": ["no_cache_run_backtest"], "tested_windows": [], "passing_window": None},
            "updated_rows": 0,
            "cached_at": None,
            "disclaimer": DISCLAIMER,
        }
    cached["disclaimer"] = DISCLAIMER
    return cached


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


@router.patch("/list/{item_id}/lock", dependencies=[Depends(require_sniper_token)])
async def toggle_list_lock(item_id: int, locked: bool = Body(..., embed=True)) -> dict[str, Any]:
    """리스트 항목 lock 토글 · locked=True 는 스크리너 재실행 후에도 유지 (Watchlist 패턴)."""
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegList).where(PowderKegList.id == item_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"item {item_id} not found")
        row.locked = bool(locked)
        if locked:
            row.added_by = "user"
    return {"id": item_id, "locked": bool(locked)}


@router.patch("/list/{item_id}/note", dependencies=[Depends(require_sniper_token)])
async def update_list_note(item_id: int, note: str = Body("", embed=True)) -> dict[str, Any]:
    """사용자 코멘트 저장 (분석 노트 · 사유 등)."""
    async with get_session() as session:
        row = (await session.execute(
            select(PowderKegList).where(PowderKegList.id == item_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"item {item_id} not found")
        row.user_note = note.strip() or None
    return {"id": item_id, "user_note": note.strip() or None}


@router.post("/list/manual", dependencies=[Depends(require_sniper_token)])
async def add_manual_to_list(
    ticker: str = Body(..., embed=True),
    run_id: Optional[str] = Body(None, embed=True),
    note: Optional[str] = Body(None, embed=True),
) -> dict[str, Any]:
    """사용자 수동 추가 · locked=True · added_by='user' · 스크리너 후에도 유지."""
    ticker = ticker.strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    from backend.powderkeg.collectors.corp_codes import resolve_corp_code
    from backend.services.models import KrxMarketSnapshot as KRX
    async with get_session() as session:
        if run_id is None:
            run_id = (await session.execute(
                select(PowderKegList.run_id)
                .order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
        if run_id is None:
            run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        # name 자동 해결 (KRX 스냅샷)
        stmt = (
            select(KRX.name)
            .where(KRX.ticker == ticker, KRX.name.is_not(None))
            .order_by(KRX.snapshot_date.desc()).limit(1)
        )
        name = (await session.execute(stmt)).scalar_one_or_none() or ticker
        # 이미 있으면 lock+note 만 갱신
        existing = (await session.execute(
            select(PowderKegList).where(
                PowderKegList.run_id == run_id, PowderKegList.ticker == ticker,
            )
        )).scalar_one_or_none()
        if existing:
            existing.locked = True
            existing.added_by = "user"
            if note:
                existing.user_note = note
            item_id = existing.id
        else:
            row = PowderKegList(
                run_id=run_id, ticker=ticker, name=name,
                status="passed", locked=True, added_by="user",
                user_note=note,
            )
            session.add(row)
            await session.flush()
            item_id = row.id
    logger.info("[powderkeg.manual_add] ticker=%s run=%s note=%s", ticker, run_id, note)
    return {"id": item_id, "ticker": ticker, "name": name, "run_id": run_id, "locked": True}


@router.post("/admin/list/remove", dependencies=[Depends(require_sniper_token)])
async def admin_remove_from_list(
    ticker: str = Body(..., embed=True),
    run_id: Optional[str] = Body(None, embed=True, description="None = 최신 run"),
    reason: Optional[str] = Body(None, embed=True),
) -> dict[str, Any]:
    """수동 · 화약고 리스트에서 특정 종목 완전 제거 (감사 로그 + lock 해제).

    v1.17 (2026-07-16 · 버그 fix):
      · 삭제 후 재평가 시 · 과거 run 에 남아있는 locked=True 흔적으로 재승격되는 문제 fix
      · 모든 run 에서 해당 ticker · locked=False 로 갱신 · union 재승격 차단

    용도: cash_suspect · 지주회사 특성 · 사용자 판단으로 리스트에서 배제.
    """
    from sqlalchemy import delete as _delete, update as _update
    async with get_session() as session:
        if run_id is None:
            run_id = (await session.execute(
                select(PowderKegList.run_id)
                .order_by(PowderKegList.created_at.desc()).limit(1)
            )).scalar_one_or_none()
        if run_id is None:
            raise HTTPException(status_code=404, detail="no runs exist")
        # 감사 로그 · 삭제 전 스냅샷
        stmt = select(PowderKegList).where(
            PowderKegList.run_id == run_id, PowderKegList.ticker == ticker,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"ticker {ticker} not in run {run_id}")
        snapshot = {
            "ticker": row.ticker, "name": row.name, "status": row.status,
            "pbr": row.pbr, "net_cash_ratio": row.net_cash_ratio,
            "owner_pct": row.owner_pct, "reason_removed": reason,
        }
        # (a) 최신 run 에서 삭제
        result = await session.execute(
            _delete(PowderKegList).where(
                PowderKegList.run_id == run_id, PowderKegList.ticker == ticker,
            )
        )
        # (b) v1.17 · 모든 run 에서 lock 해제 · 재승격 차단
        unlock_result = await session.execute(
            _update(PowderKegList).where(
                PowderKegList.ticker == ticker,
                PowderKegList.locked == True,   # noqa: E712
            ).values(locked=False)
        )
    logger.info("[powderkeg.admin] removed · ticker=%s run=%s reason=%s unlocked_runs=%d snapshot=%s",
                ticker, run_id, reason, int(unlock_result.rowcount or 0), snapshot)
    return {
        "deleted": int(result.rowcount or 0),
        "unlocked_runs": int(unlock_result.rowcount or 0),
        "run_id": run_id, "snapshot": snapshot,
    }


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
        # §9-3 backtest 캐시 (5년 표본 60s 초과 대응)
        ("powderkeg_backtest_report", """
            CREATE TABLE IF NOT EXISTS powderkeg_backtest_report (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(4) NOT NULL UNIQUE,
                aggregate_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                total_events INTEGER DEFAULT 0,
                valid_events INTEGER DEFAULT 0,
                validated BOOLEAN DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("ix_powderkeg_backtest_report_event_type",
         "CREATE INDEX IF NOT EXISTS ix_powderkeg_backtest_report_event_type "
         "ON powderkeg_backtest_report (event_type)"),
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
        # Phase 7-2 UI 편집 (locked/added_by/user_note)
        ("powderkeg_list", "locked", "BOOLEAN DEFAULT 0"),
        ("powderkeg_list", "added_by", "VARCHAR(10) DEFAULT 'auto'"),
        ("powderkeg_list", "user_note", "TEXT"),
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
    market: str = Query("KOSDAQ", description="KOSPI/KOSDAQ · KOSDAQ 은 FDR PBR 결측 다수"),
) -> dict[str, Any]:
    """KRX 스냅샷 · FinancialSnapshot 조인 · 저PBR 후보 종목 리스트.

    PBR = market_cap / total_equity 자체 계산 (FDR PBR 컬럼 결측 대응).
    FinancialSnapshot 있는 종목만 pre-filter · 유니버스 확대 실용.
    """
    from backend.services.models import FinancialSnapshot, KrxMarketSnapshot
    async with get_session() as session:
        latest_date = (await session.execute(
            select(KrxMarketSnapshot.snapshot_date)
            .order_by(KrxMarketSnapshot.snapshot_date.desc()).limit(1)
        )).scalar_one_or_none()
        if not latest_date:
            return {"count": 0, "items": []}

        # KRX 스냅샷 · 시총·market 필터
        stmt = (
            select(KrxMarketSnapshot)
            .where(
                KrxMarketSnapshot.snapshot_date == latest_date,
                KrxMarketSnapshot.market == market,
                KrxMarketSnapshot.market_cap.is_not(None),
                KrxMarketSnapshot.market_cap >= min_market_cap,
                KrxMarketSnapshot.market_cap <= max_market_cap,
            )
            .order_by(KrxMarketSnapshot.market_cap.desc())
            .limit(500)   # 후처리 filter 위해 넉넉히
        )
        krx_rows = (await session.execute(stmt)).scalars().all()

        # 각 종목 · FinancialSnapshot.total_equity 조인 · PBR 계산
        candidates: list[dict] = []
        for r in krx_rows:
            fin_stmt = (
                select(FinancialSnapshot.total_equity)
                .where(
                    FinancialSnapshot.ticker == r.ticker,
                    FinancialSnapshot.report_code == "11011",
                )
                .order_by(FinancialSnapshot.reference_date.desc())
                .limit(1)
            )
            equity = (await session.execute(fin_stmt)).scalar_one_or_none()
            pbr = None
            if r.pbr is not None:
                pbr = r.pbr
            elif equity and equity > 0:
                pbr = r.market_cap / equity
            if pbr is None or pbr <= 0 or pbr >= max_pbr:
                continue
            candidates.append({
                "ticker": r.ticker, "name": r.name, "pbr": round(pbr, 3),
                "market_cap": r.market_cap, "close_price": r.close_price,
                "pbr_source": "krx" if r.pbr is not None else "computed",
            })
            if len(candidates) >= limit:
                break

    return {
        "count": len(candidates),
        "snapshot_date": latest_date,
        "filter": {"market": market, "max_pbr": max_pbr, "min_market_cap": min_market_cap, "max_market_cap": max_market_cap},
        "items": candidates,
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


@router.post("/admin/holding-expiry-run", dependencies=[Depends(require_sniper_token)])
async def trigger_holding_expiry() -> dict[str, Any]:
    """수동 실행 · powderkeg_holding_expiry 잡 (§7-5 12개월 재평가).

    스케줄러 잡 (매일 08:00 KST) 과 동일 로직 · 검증·수동 트리거 용도.
    """
    from backend.powderkeg.scheduler import holding_expiry_job
    return await holding_expiry_job()


@router.post("/backtest/stratified/{event_type}", dependencies=[Depends(require_sniper_token)])
async def trigger_stratified_backtest(
    event_type: str,
    stratum: str = Body("powderkeg_passed", embed=True),
) -> dict[str, Any]:
    """화약고 층화 백테스트 · v1.10 (§10-5 층화 · 리뷰어 지적 대응).

    stratum:
      · powderkeg_passed · 화약고 리스트 status=passed 종목만 (교집합 검증)
      · all              · 전체 시장 (대조군)

    결과는 event_type__stratum 키로 캐시 저장 · GET /report/{event_type}__{stratum} 로 조회.
    """
    from backend.powderkeg.backtest import run_stratified_backtest
    return await run_stratified_backtest(event_type=event_type, stratum=stratum)


@router.post("/collectors/news-poll", dependencies=[Depends(require_sniper_token)])
async def trigger_news_poll(
    lookback_hours: int = Body(24, embed=True),
    only_watched: bool = Body(True, embed=True),
) -> dict[str, Any]:
    """뉴스 크롤링 · A1/A2/A6 · 5 RSS 소스 (§7-1-4).

    only_watched=True (기본) · 화약고 리스트 종목만 저장 (스팸 방지).
    """
    from backend.powderkeg.collectors.news_crawler import poll_powderkeg_news
    return await poll_powderkeg_news(lookback_hours=lookback_hours, only_watched=only_watched)


@router.post("/collectors/events-backfill", dependencies=[Depends(require_sniper_token)])
async def trigger_events_backfill(
    start_date: str = Body(..., embed=True, description="YYYY-MM-DD"),
    end_date: str = Body(..., embed=True, description="YYYY-MM-DD"),
    chunk_days: int = Body(30, embed=True, description="청크 크기 (일)"),
    sleep_between_chunks: float = Body(1.0, embed=True),
    watched_tickers: Optional[list[str]] = Body(None, embed=True),
) -> dict[str, Any]:
    """장기 아카이브 backfill · §7-4 5년 백테스트 표본 확보.

    예시: start_date=2021-07-16, end_date=2026-07-15 · 5년 backfill.
    청크당 DART 4 pblntf_ty 조회 · sleep 로 rate limit 완화.
    """
    from datetime import date as _date
    try:
        sd = _date.fromisoformat(start_date)
        ed = _date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date format: {exc}")
    if sd > ed:
        raise HTTPException(status_code=400, detail="start_date > end_date")
    return await backfill_powderkeg_events(
        start_date=sd, end_date=ed,
        chunk_days=chunk_days,
        sleep_between_chunks=sleep_between_chunks,
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
