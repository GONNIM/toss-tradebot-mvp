"""메뉴 보이기 설정 API (1120-01 단계 1)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from backend.api.routes.menu_visibility import LOCKED, MENU_SCREENS, RECOMMENDED_HIDE

TOKEN = "test-sniper-token-menu"
H = {"X-API-Token": TOKEN}
URL = "/api/v1/menu-visibility"
FE = Path(__file__).resolve().parents[2] / "frontend"


@pytest_asyncio.fixture
async def client(monkeypatch):
    from backend.services.db import get_session, init_db
    from backend.services.models import MenuVisibility, SniperApiAccess

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as session:
        for model in (MenuVisibility, SniperApiAccess):
            await session.execute(delete(model))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _by_key(resp) -> dict:
    return {s["key"]: s for s in resp.json()["screens"]}


def test_constants_shape():
    assert len(MENU_SCREENS) == 25 and len(set(MENU_SCREENS)) == 25
    assert LOCKED == {"/plans", "/plans/new", "/plans/adopt", "/account", "/admin/settings", "/admin/notifications", "/admin/menu", "/sniper"}
    assert LOCKED <= set(MENU_SCREENS) and set(RECOMMENDED_HIDE) <= set(MENU_SCREENS)
    assert not (set(RECOMMENDED_HIDE) & LOCKED)


@pytest.mark.asyncio
async def test_default_all_visible_and_public_get(client):
    r = await client.get(URL)  # 로그인 없이 200
    assert r.status_code == 200
    body = r.json()
    assert list(body) == ["screens"]
    assert len(body["screens"]) == 25
    assert all(set(s) == {"key", "visible", "locked"} for s in body["screens"])
    assert all(s["visible"] for s in body["screens"])
    assert {k for k, s in _by_key(r).items() if s["locked"]} == LOCKED


@pytest.mark.asyncio
async def test_writes_require_auth(client):
    assert (await client.put(f"{URL}/lab/crazy", json={"visible": False})).status_code == 401
    assert (await client.post(f"{URL}/apply-recommended")).status_code == 401
    assert (await client.post(f"{URL}/show-all")).status_code == 401
    assert all(s["visible"] for s in (await client.get(URL)).json()["screens"])  # 아무것도 안 바뀜


@pytest.mark.asyncio
async def test_hide_and_restore(client):
    r = await client.put(f"{URL}/lab/crazy", headers=H, json={"visible": False})
    assert r.status_code == 200 and _by_key(r)["/lab/crazy"]["visible"] is False
    assert _by_key(await client.get(URL))["/lab/crazy"]["visible"] is False  # 비로그인 GET 도 숨김
    assert _by_key(await client.get(URL))["/lab/moonshot"]["visible"] is True
    r = await client.put(f"{URL}/lab/crazy", headers=H, json={"visible": True})
    assert _by_key(r)["/lab/crazy"]["visible"] is True


@pytest.mark.asyncio
async def test_unknown_key_400_and_locked_409(client):
    assert (await client.put(f"{URL}/lab/backtest", headers=H, json={"visible": False})).status_code == 400
    assert (await client.put(f"{URL}/nope", headers=H, json={"visible": False})).status_code == 400
    for k in LOCKED:
        r = await client.put(f"{URL}{k}", headers=H, json={"visible": False})
        assert r.status_code == 409, k


@pytest.mark.asyncio
async def test_locked_visible_even_with_hidden_row(client):
    from backend.services.db import get_session
    from backend.services.models import MenuVisibility

    async with get_session() as session:
        for k in LOCKED:
            session.add(MenuVisibility(key=k, visible=False))
    by = _by_key(await client.get(URL))
    assert all(by[k]["visible"] is True and by[k]["locked"] is True for k in LOCKED)


@pytest.mark.asyncio
async def test_apply_recommended_touches_only_recommended(client):
    await client.put(f"{URL}/watchlist", headers=H, json={"visible": False})
    await client.put(f"{URL}/lab/moonshot", headers=H, json={"visible": False})
    r = await client.post(f"{URL}/apply-recommended", headers=H)
    assert r.status_code == 200 and r.json()["applied"] == len(RECOMMENDED_HIDE)
    by = _by_key(r)
    assert all(by[k]["visible"] is False for k in RECOMMENDED_HIDE)
    # 권고 밖 설정은 그대로: 내가 숨긴 것은 숨김 · 안 숨긴 것은 보임
    assert by["/watchlist"]["visible"] is False and by["/lab/moonshot"]["visible"] is False
    assert by["/vip"]["visible"] is True and by["/biotech"]["visible"] is True


@pytest.mark.asyncio
async def test_show_all(client):
    await client.put(f"{URL}/watchlist", headers=H, json={"visible": False})
    await client.post(f"{URL}/apply-recommended", headers=H)
    r = await client.post(f"{URL}/show-all", headers=H)
    assert r.status_code == 200 and all(s["visible"] for s in r.json()["screens"])


@pytest.mark.asyncio
async def test_missing_table_shows_all(client):
    from backend.services.db import get_session, init_db

    await client.put(f"{URL}/watchlist", headers=H, json={"visible": False})
    async with get_session() as session:
        await session.execute(text("DROP TABLE menu_visibility"))
    try:
        r = await client.get(URL)
        assert r.status_code == 200
        assert len(r.json()["screens"]) == 25 and all(s["visible"] for s in r.json()["screens"])
    finally:
        await init_db()


def _appnav_tab_hrefs() -> list[str]:
    path = FE / "components" / "layout" / "AppNav.tsx"
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail(f"AppNav.tsx 를 읽지 못했습니다: {exc}")
    start = src.index("export const GROUPS")
    end = src.index("function sectionsOf")
    hrefs = re.findall(r'\{\s*href:\s*"(/[^"]*)"\s*,\s*label:', src[start:end])
    assert hrefs, "AppNav.tsx 에서 탭 주소를 하나도 뽑지 못했습니다 (파일 모양이 바뀌었는지 확인)"
    return hrefs


def test_menu_screens_match_appnav_groups():
    hrefs = _appnav_tab_hrefs()
    assert len(hrefs) == len(set(hrefs))
    assert sorted(hrefs) == sorted(MENU_SCREENS)


def test_frontend_locked_keys_match_server():
    src = (FE / "lib" / "menu-visibility.ts").read_text(encoding="utf-8")
    block = re.search(r"LOCKED_KEYS\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert block, "화면 잠금 상수 LOCKED_KEYS 를 찾지 못했습니다"
    keys = set(re.findall(r'"(/[^"]*)"', block.group(1)))
    assert keys == set(LOCKED)


def test_frontend_menu_check():
    if shutil.which("npx") is None or not (FE / "node_modules").exists():
        pytest.skip("npx 또는 node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/menu-visibility.check.ts"], cwd=FE, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "menu-visibility ok" in r.stdout


def test_today_sections_point_to_menu_screens():
    """오늘 후보 7개 칸이 가리키는 화면은 모두 메뉴 key 여야 숨김 규칙이 걸린다."""
    from backend.api.routes.today import _SECTIONS

    assert len(_SECTIONS) == 7
    assert {s[2] for s in _SECTIONS} <= set(MENU_SCREENS)
