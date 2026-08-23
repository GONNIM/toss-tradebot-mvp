"""Principles 라우트 (v1.0.2 · 2026-08-17).

엔드포인트:
  GET /charter                 — 헌장 JSON (정적)
  GET /screener/latest         — 최신 배치 결과 (3분류 요약 + 종목 리스트)
  GET /screener/runs?limit=10  — 최근 배치 이력
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import desc, select

from backend.principles.charter import load_charter
from backend.services.db import get_session
from backend.services.models import (
    PrinciplesGateBlockLog,
    PrinciplesResult,
    PrinciplesRun,
    PrinciplesVerificationConfirm,
)

router = APIRouter()


@router.get("/charter")
async def get_charter() -> dict:
    return load_charter()


@router.get("/screener/runs")
async def list_runs(limit: int = Query(10, ge=1, le=50)) -> list[dict]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(PrinciplesRun).order_by(desc(PrinciplesRun.started_at)).limit(limit)
            )
        ).scalars().all()
        return [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "trigger": r.trigger,
                "charter_version": r.charter_version,
                "universe_size": r.universe_size,
                "pass_count": r.pass_count,
                "fail_count": r.fail_count,
                "insufficient_count": r.insufficient_count,
                "dart_call_count": r.dart_call_count,
                "elapsed_sec": r.elapsed_sec,
            }
            for r in rows
        ]


@router.get("/screener/latest")
async def get_latest() -> dict:
    """최신 run + 종목별 결과 (verdict 별 그룹핑)."""
    async with get_session() as session:
        run = (
            await session.execute(
                select(PrinciplesRun).order_by(desc(PrinciplesRun.started_at)).limit(1)
            )
        ).scalar_one_or_none()
        if run is None:
            return {"run": None, "results": {"PASS": [], "FAIL": [], "INSUFFICIENT_DATA": []}}
        results = (
            await session.execute(
                select(PrinciplesResult).where(PrinciplesResult.run_id == run.id)
            )
        ).scalars().all()
        grouped: dict[str, list[dict]] = {"PASS": [], "FAIL": [], "INSUFFICIENT_DATA": []}
        for r in results:
            reasons: Optional[list] = None
            missing: Optional[list] = None
            vtags: Optional[list] = None
            try:
                reasons = json.loads(r.reasons_json) if r.reasons_json else None
                missing = json.loads(r.missing_fields_json) if r.missing_fields_json else None
                vtags = json.loads(r.verification_tags) if r.verification_tags else None
            except json.JSONDecodeError:
                pass
            grouped.setdefault(r.verdict, []).append({
                "ticker": r.ticker,
                "name": r.name,
                "industry_code": r.industry_code,
                "is_financial_sector": r.is_financial_sector,
                "per_ttm": r.per_ttm,
                "per_operating": r.per_operating,
                "payout_ratio_3y_avg": r.payout_ratio_3y_avg,
                "dividend_years": r.dividend_years,
                "dividend_cut": r.dividend_cut,
                "debt_ratio": r.debt_ratio,
                "interest_coverage": r.interest_coverage,
                "reasons": reasons,
                "missing_fields": missing,
                "verification_tags": vtags,
            })
        return {
            "run": {
                "id": run.id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "charter_version": run.charter_version,
                "universe_size": run.universe_size,
                "pass_count": run.pass_count,
                "fail_count": run.fail_count,
                "insufficient_count": run.insufficient_count,
                "dart_call_count": run.dart_call_count,
                "elapsed_sec": run.elapsed_sec,
            },
            "results": grouped,
        }


# ─── gate-design-v1 §3-1 · PrinciplesGate 차단 이력 (세션 A · 2026-08-23) ────


@router.get("/gate/blocked-recent")
async def list_blocked_recent(
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    """최근 차단 이력 (관리 화면 병치용).

    Returns:
      {"total_24h": N, "by_reason_24h": {reason: count, ...}, "recent": [...]}
    """
    from datetime import datetime, timedelta
    async with get_session() as session:
        cutoff_24h = datetime.now() - timedelta(hours=24)
        recent_rows = (
            await session.execute(
                select(PrinciplesGateBlockLog)
                .order_by(desc(PrinciplesGateBlockLog.id))
                .limit(limit)
            )
        ).scalars().all()
        last_24h_rows = (
            await session.execute(
                select(PrinciplesGateBlockLog)
                .where(PrinciplesGateBlockLog.created_at >= cutoff_24h)
            )
        ).scalars().all()
        by_reason: dict[str, int] = {}
        bypass_24h = 0
        for r in last_24h_rows:
            by_reason[r.reason] = by_reason.get(r.reason, 0) + 1
            if r.reason == "whitelist_bypass":
                bypass_24h += 1
        block_24h = len(last_24h_rows) - bypass_24h
        return {
            "total_24h": len(last_24h_rows),
            "block_24h": block_24h,
            "bypass_24h": bypass_24h,
            "by_reason_24h": by_reason,
            "recent": [
                {
                    "id": r.id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "ticker": r.ticker,
                    "source": r.source,
                    "reason": r.reason,
                    "detail": r.detail,
                    "run_id": r.run_id,
                }
                for r in recent_rows
            ],
        }


# ─── gate-design-v1 §3-3 · 실체 검증 확인 (세션 B · 2026-08-23) ────


@router.get("/verification/pending")
async def list_pending_verifications() -> dict:
    """최신 PASS 종목 중 태깅 있는데 미확인 (재확인 필요) 리스트.

    스코프 = (ticker, tags_hash) 이중키 · 태그 구성 동일 확인만 통과.
    """
    from backend.principles.verification_tagger import tags_hash as _hash
    async with get_session() as session:
        latest_run = (
            await session.execute(
                select(PrinciplesRun)
                .where(PrinciplesRun.finished_at.is_not(None))
                .order_by(desc(PrinciplesRun.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_run is None:
            return {"run_id": None, "pending": []}
        pass_rows = (
            await session.execute(
                select(PrinciplesResult)
                .where(PrinciplesResult.run_id == latest_run.id)
                .where(PrinciplesResult.verdict == "PASS")
            )
        ).scalars().all()
        pending: list[dict] = []
        for r in pass_rows:
            if not r.verification_tags:
                continue
            try:
                tags = list(json.loads(r.verification_tags))
            except (ValueError, TypeError):
                continue
            if not tags:
                continue
            h = _hash(tags)
            # 확인 조회
            confirm = (
                await session.execute(
                    select(PrinciplesVerificationConfirm)
                    .where(PrinciplesVerificationConfirm.ticker == r.ticker)
                    .where(PrinciplesVerificationConfirm.tags_hash == h)
                )
            ).scalar_one_or_none()
            if confirm is None:
                pending.append({
                    "ticker": r.ticker,
                    "name": r.name,
                    "tags": tags,
                    "tags_hash": h,
                    "per_ttm": r.per_ttm,
                })
        return {"run_id": latest_run.id, "pending": pending}


@router.post("/verification/confirm")
async def confirm_verification(
    body: dict = Body(...),
) -> dict:
    """실체 검증 확인 저장 · 스코프 (ticker, tags_hash) 이중키.

    보완 (2026-08-23 사용자 지시 · 선승인 방지):
      최신 유효 run 의 해당 ticker verification_tags 를 조회 · 제출 tags 와
      정렬 비교 (hash 일치) 시에만 저장. 불일치 or 미태깅 → 400 + 현재 실제 태그 반환.
      사유: 임의 (ticker, tags_hash) 선승인 시 미래 태그 발생 순간 자동 통과 백지
      승인 구멍. 확인 = 현재 근거에 대한 승인.

    Body: {"ticker": "033530", "tags": ["single_quarter_outlier"], "confirmed_by": "user@x"}
    """
    from backend.principles.verification_tagger import tags_hash as _hash
    ticker = body.get("ticker")
    tags = body.get("tags") or []
    confirmed_by = body.get("confirmed_by")
    if not ticker or not isinstance(tags, list) or not tags:
        raise HTTPException(400, "ticker 와 비어있지 않은 tags 필수")
    submitted_hash = _hash(tags)
    tags_json_str = json.dumps(sorted(tags), ensure_ascii=False)
    async with get_session() as session:
        latest_run = (
            await session.execute(
                select(PrinciplesRun)
                .where(PrinciplesRun.finished_at.is_not(None))
                .order_by(desc(PrinciplesRun.id))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_run is None:
            raise HTTPException(400, {"error": "no_valid_run", "message": "완료된 principles_runs 없음"})

        # 보완 · 최신 run 의 해당 ticker verification_tags 조회 · 정렬 비교
        result_row = (
            await session.execute(
                select(PrinciplesResult)
                .where(PrinciplesResult.run_id == latest_run.id)
                .where(PrinciplesResult.ticker == ticker)
            )
        ).scalar_one_or_none()
        current_tags: list[str] = []
        if result_row and result_row.verification_tags:
            try:
                current_tags = list(json.loads(result_row.verification_tags))
            except (ValueError, TypeError):
                current_tags = []
        current_hash = _hash(current_tags) if current_tags else None
        if not current_tags:
            raise HTTPException(400, {
                "error": "not_tagged",
                "message": f"ticker {ticker} 는 최신 run #{latest_run.id} 에서 태깅되지 않음 (확인 불필요)",
                "current_tags": [],
                "current_hash": None,
            })
        if submitted_hash != current_hash:
            raise HTTPException(400, {
                "error": "tags_mismatch",
                "message": f"제출 태그가 현재 근거와 불일치 (선승인 방지 · 백지 승인 차단)",
                "submitted_tags": sorted(tags),
                "submitted_hash": submitted_hash,
                "current_tags": sorted(current_tags),
                "current_hash": current_hash,
            })

        # 검증 통과 · 저장 (idempotent)
        existing = (
            await session.execute(
                select(PrinciplesVerificationConfirm)
                .where(PrinciplesVerificationConfirm.ticker == ticker)
                .where(PrinciplesVerificationConfirm.tags_hash == submitted_hash)
            )
        ).scalar_one_or_none()
        if existing:
            return {
                "status": "already_confirmed",
                "ticker": ticker,
                "tags_hash": submitted_hash,
                "confirmed_at": existing.confirmed_at.isoformat() if existing.confirmed_at else None,
            }
        session.add(PrinciplesVerificationConfirm(
            ticker=ticker,
            tags_hash=submitted_hash,
            tags_json=tags_json_str,
            confirmed_by=confirmed_by,
            run_id_at_confirm=latest_run.id,
        ))
        await session.commit()
        return {
            "status": "confirmed",
            "ticker": ticker,
            "tags_hash": submitted_hash,
            "tags": sorted(tags),
            "run_id_at_confirm": latest_run.id,
        }
