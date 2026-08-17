"""Principles 라우트 (v1.0.2 · 2026-08-17).

엔드포인트:
  GET /charter                 — 헌장 JSON (정적)
  GET /screener/latest         — 최신 배치 결과 (3분류 요약 + 종목 리스트)
  GET /screener/runs?limit=10  — 최근 배치 이력
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from backend.principles.charter import load_charter
from backend.services.db import get_session
from backend.services.models import PrinciplesResult, PrinciplesRun

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
            try:
                reasons = json.loads(r.reasons_json) if r.reasons_json else None
                missing = json.loads(r.missing_fields_json) if r.missing_fields_json else None
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
