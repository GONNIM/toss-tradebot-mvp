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
    # 1120-01 단계 3 · /sniper 잠금을 풂 (상황판을 /admin/settings 에도 둠 · test_safety_panel_on_settings_screen)
    assert LOCKED == {"/plans", "/plans/new", "/plans/adopt", "/account", "/admin/settings", "/admin/notifications", "/admin/menu"}
    # 1120-01 단계 3 · 권고 7개 정확 대조 (합친 옛 화면 5개 더함)
    assert RECOMMENDED_HIDE == ("/lab", "/influencer/serenity-hunter", "/vip", "/logs", "/lab/moonshot", "/principles", "/rulebook")
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
    await client.put(f"{URL}/sector-leaders", headers=H, json={"visible": False})
    r = await client.post(f"{URL}/apply-recommended", headers=H)
    assert r.status_code == 200 and r.json()["applied"] == len(RECOMMENDED_HIDE) == 7
    by = _by_key(r)
    assert all(by[k]["visible"] is False for k in RECOMMENDED_HIDE)
    # 권고 밖 설정은 그대로: 내가 숨긴 것은 숨김 · 안 숨긴 것은 보임 (받을 화면은 보임)
    assert by["/watchlist"]["visible"] is False and by["/sector-leaders"]["visible"] is False
    for k in ("/biotech", "/account", "/journal", "/lab/crazy", "/influencer/serenity", "/principles/screener"):
        assert by[k]["visible"] is True, k


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
    # 칸 숨김은 링크의 경로(`?` 앞)로 판단한다 (frontend/lib/menu-visibility.ts pathOf · 1120-01 단계 3)
    assert {s[2].split("?")[0] for s in _SECTIONS} <= set(MENU_SCREENS)
    links = {s[0]: s[2] for s in _SECTIONS}
    # Moonshot 칸은 합친 Crazy 화면 탭을 가리킨다 → /lab/moonshot 을 권고대로 숨겨도 칸이 빠지지 않는다
    assert links["moonshot"] == "/lab/crazy?view=moonshot"
    assert not ({s[2].split("?")[0] for s in _SECTIONS} & set(RECOMMENDED_HIDE))


# ─── 1120-01 단계 3 · 합침 정적 검사 (되돌리면 실패) ───

def _src(rel: str) -> str:
    path = FE / rel
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        pytest.fail(f"{rel} 를 읽지 못했습니다: {exc}")


# 받을 화면 → 탭으로 불러 그리는 원래 화면 (dynamic import 경로)
_MERGES = {
    "app/account/page.tsx": ['import("../vip/page")'],
    "app/journal/page.tsx": ['import("../logs/page")'],
    "app/lab/crazy/page.tsx": ['import("../moonshot/page")'],
    "app/influencer/serenity/page.tsx": ['import("./backtest/page")', 'import("./methodology/page")'],
    "app/principles/screener/page.tsx": ['import("../../rulebook/page")', 'import("../page")', 'import("../verification/page")'],
}


@pytest.mark.parametrize("rel,imports", list(_MERGES.items()))
def test_receiving_screens_render_merged_tabs(rel, imports):
    src = _src(rel)
    assert "<MergedTabs" in src, f"{rel} 가 탭 부품을 그리지 않습니다"
    for imp in imports:
        assert imp in src, f"{rel} 에 {imp} 가 없습니다"


def test_merged_tabs_use_search_params_inside_suspense():
    src = _src("components/layout/MergedTabs.tsx")
    assert "useSearchParams" in src and "<Suspense" in src
    # useSearchParams 를 부르는 곳은 Suspense 안 내부 부품뿐이어야 한다 (export 된 MergedTabs 본체는 Suspense 만 그림)
    body = src[src.index("export function MergedTabs"):src.index("export function pickView")]
    assert "useSearchParams(" not in body and "<Suspense" in body


def test_docs_folded_into_main_screens():
    bio = _src("app/biotech/page.tsx")
    assert "<BiotechDocsViewer" in bio and 'id="biotech-docs"' in bio
    assert "<BiotechDocsViewer" in _src("app/biotech/docs/page.tsx")
    assert 'id="powderkeg-guide"' in _src("app/powderkeg/page.tsx")


def test_serenity_ticker_detail_has_tab_bar():
    assert "<TabBar" in _src("app/influencer/serenity/[ticker]/page.tsx")


def test_safety_panel_on_settings_screen():
    """비상 정지 발동 · 해제 길: 잠긴 /admin/settings 에 상황판과 로그인 줄이 그려져야 한다.
    /sniper 잠금을 풀었다면 이 조건이 반드시 지켜져야 한다 (import 만 남긴 되돌림도 잡는다)."""
    src = _src("app/admin/settings/page.tsx")
    assert "<SafetyPanel" in src and "<AdminSessionBar" in src
    assert '"sniper", "kill-switch"' in src  # 로그인 · 로그아웃 때 Kill Switch 상태 다시 읽기
    assert "/admin/settings" in LOCKED
    # /sniper 는 잠금 밖이다 → 숨겨도 발동 · 해제 길은 /admin/settings 에 남아야 한다 (위 검사). /sniper 에도 그대로 둔다.
    assert "/sniper" not in LOCKED
    assert "<SafetyPanel" in _src("app/sniper/page.tsx")


def test_frontend_recommended_keys_match_server():
    src = _src("lib/menu-visibility.ts")
    block = re.search(r"RECOMMENDED_HIDE_KEYS\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert block, "화면 권고 상수 RECOMMENDED_HIDE_KEYS 를 찾지 못했습니다"
    assert tuple(re.findall(r'"(/[^"]*)"', block.group(1))) == RECOMMENDED_HIDE
    # 확인 문구는 권고 상수에서 만든다 (이름을 고정해 적지 않음)
    menu = _src("app/admin/menu/page.tsx")
    assert "RECOMMENDED_HIDE_KEYS" in menu and "실험장 · 인플루언서 Hunter)만" not in menu


# ── 1123-02 · 합친 화면에서 위 메뉴 탭 줄과 화면 안 탭 줄이 겹치지 않음 ─────
def test_merged_host_hides_duplicate_nav_row():
    nav = _src("components/layout/AppNav.tsx")
    lib = _src("lib/menu-visibility.ts")
    assert "export function mergedTabsHere(pathname: string)" in lib
    assert "pathOf(t.href) === pathname" in lib                    # ?view= 를 뗀 받을 화면 주소로 대조
    assert "new Set([pathname, ...olds])" in lib                   # 화면 자신 + 합쳐 들어온 옛 주소
    assert "const covered = sections.length === 0 ? mergedTabsHere(pathname) : null;" in nav  # 분류 줄 묶음(후보)은 그대로
    assert "{rowTabs.length > 0 && (" in nav and "{rowTabs.map((t) =>" in nav
    assert "{shownTabs.map((t) =>" not in nav
    # 받을 화면 두 곳이 실제로 MergedTabs 를 그리고, 옛 주소가 그 화면으로 합쳐져 있다
    for host, old in (("app/account/page.tsx", '"/vip": { href: "/account?view=vip"'), ("app/journal/page.tsx", '"/logs": { href: "/journal?view=logs"')):
        assert "<MergedTabs" in _src(host)
        assert old in lib
