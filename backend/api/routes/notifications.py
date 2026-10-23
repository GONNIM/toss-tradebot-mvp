"""알림 설정 API (1022-09 · 2026-10-23) — 화면 /admin/notifications.

인증: require_sniper_token (관리자 쿠키 세션 우선 · X-API-Token 대체).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from backend.api.auth import require_sniper_token
from backend.services import notification_settings as ns
from backend.services.notification_log import utcnow

router = APIRouter(dependencies=[Depends(require_sniper_token)])


class SettingUpdate(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    resend_minutes: Optional[int] = None
    min_level: Optional[str] = None


def _iso(v: Optional[datetime]) -> Optional[str]:
    # UTC naive 로 저장 · 화면이 시간대를 붙여 보여 줌
    return v.isoformat() + "Z" if v else None


async def _status() -> dict[str, dict]:
    """종류별 마지막 성공·최근 실패(오류 요지)·오늘 건너뜀 수."""
    from backend.services.db import get_session
    from backend.services.models import NotificationLog as L

    out: dict[str, dict] = {}
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with get_session() as session:
        for result, key in (("sent", "last_sent_at"), ("failed", "last_failed_at")):
            rows = await session.execute(select(L.category, func.max(L.created_at)).where(L.result == result).group_by(L.category))
            for cat, ts in rows:
                out.setdefault(cat, {})[key] = _iso(ts)
        rows = await session.execute(
            select(L.category, func.count()).where(L.result == "skipped", L.created_at >= today).group_by(L.category)
        )
        for cat, n in rows:
            out.setdefault(cat, {})["skipped_today"] = n
        for cat, info in out.items():
            if info.get("last_failed_at"):
                err = await session.execute(
                    select(L.error).where(L.category == cat, L.result == "failed").order_by(L.created_at.desc(), L.id.desc()).limit(1)
                )
                info["last_error"] = err.scalar()
    return out


def _row(category: str, meta: ns.CategoryMeta, view: Optional[ns.SettingView], status: dict) -> dict:
    s = status.get(category, {})
    return {
        "category": category,
        "label": meta.label,
        "group": meta.group,
        "page": meta.page,
        "locked": meta.locked,
        "configurable": view is not None,
        "recommended": meta.recommended,
        "reason": meta.reason,
        "enabled": view.enabled if view else True,
        "mode": view.mode if view else "immediate",
        "resend_minutes": view.resend_minutes if view else 0,
        "min_level": view.min_level if view else "info",
        "last_sent_at": s.get("last_sent_at"),
        "last_failed_at": s.get("last_failed_at"),
        "last_error": s.get("last_error"),
        "skipped_today": s.get("skipped_today", 0),
    }


@router.get("/settings")
async def list_settings() -> list[dict]:
    status = await _status()
    rows = []
    for key, meta in ns.CATEGORIES.items():
        rows.append(_row(key, meta, await ns.get_setting(key), status))
    for key, meta in ns.DISPLAY_ONLY.items():
        rows.append(_row(key, meta, None, status))
    return rows


@router.put("/settings/{category}")
async def update_setting(category: str, body: SettingUpdate) -> dict:
    try:
        view = await ns.save_setting(category, **body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"알 수 없는 알림 종류: {category}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _row(category, ns.CATEGORIES[category], view, await _status())


@router.post("/settings/apply-recommended")
async def apply_recommended() -> dict:
    return {"applied": await ns.apply_recommended()}


@router.get("/log")
async def list_log(category: Optional[str] = None, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    from backend.services.db import get_session
    from backend.services.models import NotificationLog as L

    stmt = select(L).order_by(L.created_at.desc(), L.id.desc()).limit(limit)
    if category:
        stmt = stmt.where(L.category == category)
    async with get_session() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {"category": r.category, "title": r.title, "result": r.result, "error": r.error, "created_at": _iso(r.created_at)}
        for r in rows
    ]
