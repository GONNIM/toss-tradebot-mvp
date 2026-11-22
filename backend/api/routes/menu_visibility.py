"""메뉴 보이기 설정 API (1120-01 · 2026-11-21) — 화면 /admin/menu.

화면을 지우지 않는다. 메뉴 탭에서만 뺀다 (주소 · 알림 링크로는 그대로 열림).
- GET 은 공개 (비로그인 방문자의 메뉴도 같은 값으로 그려진다 · 응답은 key · visible · locked 만).
- 쓰기 3개(PUT · apply-recommended · show-all)만 require_sniper_token (알림 설정과 같음).
- 행이 없으면 보임. 표가 없거나 읽기 실패면 모두 보임 (메뉴가 사라지지 않게).
- 배포 때 DB 를 바꾸는 코드는 없다. 사용자가 「권고대로 숨기기」를 누를 때만 바뀐다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from backend.api.auth import require_sniper_token

logger = logging.getLogger(__name__)

# 허용 key = 메뉴 탭 주소 24개 (후보 13 · 계획 3 · 계좌 2 · 기록 2 · 설정 4) + 새 /admin/menu = 25개.
# frontend/components/layout/AppNav.tsx 의 GROUPS 와 어긋나면 backend/tests/test_menu_visibility.py 가 실패한다.
MENU_SCREENS: tuple[str, ...] = (
    "/watchlist", "/sniper", "/lab/crazy", "/lab/moonshot", "/lab/meme-watch", "/biotech",
    "/influencer/serenity", "/influencer/serenity-hunter", "/activist-radar", "/powderkeg",
    "/principles/screener", "/rulebook", "/sector-leaders",
    "/plans", "/plans/new", "/plans/adopt",
    "/account", "/vip",
    "/journal", "/logs",
    "/admin/settings", "/admin/notifications", "/admin/menu", "/principles", "/lab",
)

# 잠금 7개: 실주문 · 비상 정지 · 다시 켜기로 가는 길은 숨길 수 없다 (서버와 화면 상수 양쪽에서 강제).
# 1120-01 단계 3 (11/22): 비상 정지 상황판(발동 · 해제)을 잠긴 /admin/settings 에도 두고 로컬에서 발동 → 해제 한 바퀴를
# 확인한 뒤 /sniper 잠금을 풀었다 (8 → 7). /admin/settings 에서 상황판을 빼면 test_safety_panel_on_settings_screen 이 실패한다.
LOCKED: frozenset[str] = frozenset({
    "/plans", "/plans/new", "/plans/adopt", "/account",
    "/admin/settings", "/admin/notifications", "/admin/menu",
})

# 「권고대로 숨기기」 대상 (메뉴 탭만) · 화면 상수 frontend/lib/menu-visibility.ts RECOMMENDED_HIDE_KEYS 와 같아야 한다 (시험이 대조).
# 1120-01 단계 3 (11/22): 다른 화면 탭으로 합친 옛 화면 5개를 더함 — /vip(→ /account) · /logs(→ /journal) ·
# /lab/moonshot(→ /lab/crazy) · /principles · /rulebook(→ /principles/screener). 옛 주소는 그대로 열린다.
RECOMMENDED_HIDE: tuple[str, ...] = (
    "/lab", "/influencer/serenity-hunter",
    "/vip", "/logs", "/lab/moonshot", "/principles", "/rulebook",
)

router = APIRouter()


class VisibilityUpdate(BaseModel):
    visible: bool


def _screens(hidden: set[str]) -> dict:
    return {
        "screens": [
            {"key": k, "visible": (k in LOCKED) or (k not in hidden), "locked": k in LOCKED}
            for k in MENU_SCREENS
        ]
    }


async def _hidden_keys() -> set[str]:
    """DB 에서 숨김 key 를 읽는다. 표가 없거나 읽기 실패면 빈 집합 (모두 보임)."""
    try:
        from backend.services.db import get_session
        from backend.services.models import MenuVisibility as M

        async with get_session() as session:
            rows = await session.execute(select(M.key).where(M.visible.is_(False)))
            return {r[0] for r in rows}
    except Exception as exc:  # noqa: BLE001 — 메뉴가 사라지지 않게 모두 보임으로 응답
        logger.warning("[menu-visibility] 읽기 실패 · 모두 보임으로 응답: %s", exc)
        return set()


async def _set_visible(keys: list[str], visible: bool) -> None:
    from backend.services.db import get_session
    from backend.services.models import MenuVisibility as M

    async with get_session() as session:
        for k in keys:
            row = await session.get(M, k)
            if row is None:
                session.add(M(key=k, visible=visible))
            else:
                row.visible = visible


@router.get("")
async def list_screens() -> dict:
    return _screens(await _hidden_keys())


@router.put("/{key:path}", dependencies=[Depends(require_sniper_token)])
async def update_screen(key: str, body: VisibilityUpdate) -> dict:
    # 주소 맨 앞 「/」 는 있어도 없어도 된다 (/menu-visibility/lab/crazy)
    key = key if key.startswith("/") else "/" + key
    if key not in MENU_SCREENS:
        raise HTTPException(status_code=400, detail=f"메뉴에 없는 화면입니다: {key}")
    if key in LOCKED:
        raise HTTPException(status_code=409, detail=f"숨길 수 없는 화면입니다: {key}")
    await _set_visible([key], body.visible)
    return _screens(await _hidden_keys())


@router.post("/apply-recommended", dependencies=[Depends(require_sniper_token)])
async def apply_recommended() -> dict:
    # 권고 목록만 숨기고 다른 행은 건드리지 않는다
    keys = [k for k in RECOMMENDED_HIDE if k in MENU_SCREENS and k not in LOCKED]
    await _set_visible(keys, False)
    return {"applied": len(keys), **_screens(await _hidden_keys())}


@router.post("/show-all", dependencies=[Depends(require_sniper_token)])
async def show_all() -> dict:
    from backend.services.db import get_session
    from backend.services.models import MenuVisibility as M

    async with get_session() as session:
        rows = (await session.execute(select(M).where(M.visible.is_(False)))).scalars().all()
        for r in rows:
            r.visible = True
    return _screens(await _hidden_keys())
