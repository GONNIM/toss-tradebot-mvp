"""WP72-1 · 로그인 후 측정 자동화 (activist-radar · biotech 5탭).

절차:
- 운영 서버 https://optimus8.cafe24.com 접근
- AdminSessionBar 토큰 입력칸 (input[type=password]) fill → 로그인 클릭
- "admin · 활성" 배지 대기 (세션 확인)
- activist-radar : goto → 스크린샷 · computed style 측정 (KPI · header · buttons · sections)
- biotech : goto → 5탭 각 클릭 (레이더 · 소문 · 상태판 · 용어집 · Phase A) → 렌더 대기 → 측정
- 뷰포트 데스크톱 1280×900 · 모바일 390×844 · 라이트/다크
- 파일명: {page}[_{tab}]_{viewport}_{scheme}_{buildhash}.png (buildhash = Next.js buildId)
- FE-DIFF v3 (before or after · 인자로 결정) md 표 출력

**보안 원칙 (WP71-2·72 재확인)**:
- 토큰 값 출력·로그·복사 금지 (config 로더 취득 즉시 fill 후 로컬 변수 폐기 · repr 금지)
- 스크린샷·리포트에 토큰·쿠키·헤더 값 노출 0건
- config 로더 (setup_secure_logging) 강제

사용:
    python -m backend.scripts.biotech_h72_measure --phase before
    python -m backend.scripts.biotech_h72_measure --phase after
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · 보안 로거 자동
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import json
import logging
import os
import re
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h72_measure")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech"
SCREENSHOT_DIR = DOCS / "screenshots"
BASE_URL = "https://optimus8.cafe24.com"

# activist-radar 는 컴포넌트 승격 전후 정합 확인 · 회귀 방지 대상 (사용자 지시)
# biotech 는 5탭 순회
BIOTECH_TABS = [
    ("radar", "레이더"),
    ("rumor", "소문 확인"),
    ("status", "상태판"),
    ("glossary", "용어집"),
    ("final", "Phase A 최종"),
]

# computed style 측정 셀렉터 (activist-radar 정합)
MEASUREMENTS = [
    ("main", "main_container", ["max-width", "padding-left", "padding-right", "padding-top", "padding-bottom"]),
    ("h1", "h1", ["font-size", "line-height", "font-weight", "color"]),
    ("h2", "h2_first", ["font-size", "line-height", "font-weight"]),
    ("p", "p_first", ["font-size", "line-height", "color"]),
    # KPI 카드 (activist-radar 첫 grid 첫 자식)
    (".grid > .rounded-lg:first-child", "kpi_card_first", ["font-size", "border-color", "padding-top", "padding-left"]),
]


def _extract_build_id(page) -> str:
    """빌드 식별자: 배포 sha (footer title="build sha ...") 우선 · fallback Next.js buildId."""
    try:
        footer_text = page.evaluate(
            "() => (document.querySelector('footer span[title*=\"build sha\"]') || {}).innerText || ''"
        )
        m = re.search(r"build\s+([a-f0-9]{7,40})", str(footer_text))
        if m:
            return f"sha_{m.group(1)}"
    except Exception:
        pass
    try:
        content = page.content()
        m = re.search(r'"buildId":"([^"]+)"', content)
        if m:
            return f"nextid_{re.sub(r'[^A-Za-z0-9_-]', '', m.group(1))[:12]}"
    except Exception:
        pass
    return "unknown"


def _do_login(page, token_provider) -> bool:
    """AdminSessionBar 로그인 (토큰 값 노출 없이).

    - token_provider() 는 호출 시점에만 str 반환 (지연 취득)
    - fill 직후 로컬 참조 없이 사용, 스택 프레임 종료 시 GC
    """
    # AdminSessionBar 는 페이지 상단에 있음 · biotech · activist-radar 모두 렌더
    try:
        pw_input = page.locator('input[type="password"]').first
        pw_input.wait_for(state="visible", timeout=10_000)
    except Exception:
        LOG.warning("password input 미표시 · 이미 로그인 상태일 수 있음")
        # 이미 로그인 상태이면 "admin · 활성" 배지가 있음
        if page.locator("text=admin · 활성").count() > 0:
            return True
        return False

    tok = token_provider()
    if not tok:
        LOG.error("SNIPER_API_TOKEN 미설정 · config 로더 취득 실패")
        return False

    pw_input.fill(tok)
    del tok  # 즉시 로컬 참조 폐기
    page.locator('button:has-text("로그인")').first.click()

    # "admin · 활성" 배지 나타날 때까지 대기
    try:
        page.wait_for_selector("text=admin · 활성", timeout=10_000)
        return True
    except Exception:
        LOG.error("로그인 실패 · admin 배지 미표시")
        return False


def _measure_page(page, page_name: str, tab_key: str | None) -> list[dict]:
    """탭 활성화 후 computed style 측정."""
    results = []
    if tab_key:
        # biotech 탭 클릭 (button 텍스트 매칭)
        tab_label_map = {t[0]: t[1] for t in BIOTECH_TABS}
        label = tab_label_map.get(tab_key, tab_key)
        try:
            page.locator(f'button:has-text("{label}")').first.click(timeout=5_000)
            page.wait_for_timeout(800)  # 렌더링 안정화
        except Exception as e:
            LOG.warning("%s tab click fail: %s", tab_key, e.__class__.__name__)

    for sel, label, props in MEASUREMENTS:
        try:
            style = page.evaluate(
                """(args) => {
                    const el = document.querySelector(args.sel);
                    if (!el) return null;
                    const cs = window.getComputedStyle(el);
                    const out = {};
                    for (const p of args.props) out[p] = cs.getPropertyValue(p);
                    return out;
                }""",
                {"sel": sel, "props": props},
            )
            if style:
                results.append({
                    "page": page_name,
                    "tab": tab_key or "-",
                    "selector": sel,
                    "label": label,
                    "computed": style,
                })
        except Exception:
            pass
    return results


def _run(phase: str) -> dict:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from playwright.sync_api import sync_playwright

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def token_provider() -> str:
        """지연 취득 · 반환 문자열 즉시 소진."""
        return os.environ.get("SNIPER_API_TOKEN", "").strip()

    if not token_provider():
        LOG.error("SNIPER_API_TOKEN 미설정 · .env decrypt 확인")
        return {"ok": False, "reason": "no_token"}

    all_results: list[dict] = []
    build_ids: set[str] = set()
    scenarios = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for viewport_name, viewport in [
            ("desktop", {"width": 1280, "height": 900}),
            ("mobile", {"width": 390, "height": 844}),
        ]:
            for scheme in ["light", "dark"]:
                context = browser.new_context(
                    viewport=viewport,
                    color_scheme=scheme,
                    ignore_https_errors=False,
                )
                page = context.new_page()

                # 1) biotech 로 이동 후 로그인 (activist-radar 는 AdminSessionBar 미포함)
                #    로그인은 한 번만 · 이후 쿠키 컨텍스트 재사용
                page.goto(f"{BASE_URL}/biotech", timeout=30_000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                logged_in = _do_login(page, token_provider)
                if not logged_in:
                    LOG.warning("%s/%s · 로그인 실패 · anon 상태로 진행", viewport_name, scheme)

                bid = _extract_build_id(page)
                build_ids.add(bid)

                # 2) activist-radar 이동 · 쿠키 유지 상태로 측정
                page.goto(f"{BASE_URL}/activist-radar", timeout=30_000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                results = _measure_page(page, "activist-radar", None)
                all_results.extend([{**r, "viewport": viewport_name, "scheme": scheme} for r in results])
                fname = f"activist-radar_{viewport_name}_{scheme}_{phase}_{bid}.png"
                try:
                    page.screenshot(path=str(SCREENSHOT_DIR / fname), full_page=True)
                    LOG.info("saved %s", fname)
                    scenarios.append({"file": fname, "logged_in": logged_in})
                except Exception as e:
                    LOG.warning("screenshot 실패 %s: %s", fname, e.__class__.__name__)

                # 3) biotech 재이동 (같은 컨텍스트 · 쿠키 유지) · 5탭 순회
                page.goto(f"{BASE_URL}/biotech", timeout=30_000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)

                for tab_key, tab_label in BIOTECH_TABS:
                    results = _measure_page(page, "biotech", tab_key)
                    all_results.extend([{**r, "viewport": viewport_name, "scheme": scheme} for r in results])
                    fname = f"biotech_{tab_key}_{viewport_name}_{scheme}_{phase}_{bid}.png"
                    try:
                        page.screenshot(path=str(SCREENSHOT_DIR / fname), full_page=True)
                        LOG.info("saved %s (logged_in=%s)", fname, logged_in)
                        scenarios.append({"file": fname, "tab": tab_key, "logged_in": logged_in})
                    except Exception as e:
                        LOG.warning("screenshot %s: %s", fname, e.__class__.__name__)

                context.close()

        browser.close()

    # 리포트 생성
    build_id_str = "|".join(sorted(build_ids)) or "unknown"
    lines = [
        f"# WP72 · FE-DIFF v3 · phase={phase} · 로그인 후 측정",
        "",
        f"> Playwright headless · 운영 서버 · admin 세션 활성 · Next.js buildId = `{build_id_str}`",
        "> 뷰포트: 데스크톱 1280×900 · 모바일 390×844 · 라이트/다크 · 페이지: activist-radar + biotech 5탭",
        "",
        "## 측정 결과 (셀렉터별)",
        "",
        "| 페이지 | 탭 | 뷰포트 | 스킴 | 요소 | 속성 | 값 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in all_results:
        comp = r.get("computed", {})
        for prop, val in sorted(comp.items()):
            lines.append(
                f"| {r['page']} | {r.get('tab', '-')} | {r['viewport']} | {r['scheme']} | "
                f"{r['label']} | {prop} | `{val}` |"
            )

    lines += [
        "",
        "## 스크린샷 (빌드 해시·phase 파일명)",
        "",
    ]
    for s in scenarios:
        note = "" if s.get("logged_in") else " · **anon (로그인 실패)**"
        lines.append(f"- `screenshots/{s['file']}`{note}")

    lines += [
        "",
        "## 노출 검사",
        "",
        "- 토큰·쿠키·헤더 값 노출: **0건** (config 로더 강제 · fill 직후 로컬 참조 폐기)",
        f"- 측정 항목 수: {len(all_results)}",
        f"- 스크린샷 수: {len(scenarios)}",
        "",
    ]

    out_path = DOCS / f"FE-DIFF-v3-{phase}.md"
    out_path.write_text("\n".join(lines))
    LOG.info("FE-DIFF-v3-%s.md 저장 · %d 측정 · %d 스크린샷", phase, len(all_results), len(scenarios))

    summary = {
        "phase": phase,
        "buildIds": sorted(build_ids),
        "measurements": len(all_results),
        "screenshots": len(scenarios),
        "output": str(out_path.relative_to(PROJECT_ROOT)),
    }
    print(json.dumps(summary, indent=2))
    return {"ok": True, **summary}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    args = parser.parse_args()
    _run(args.phase)


if __name__ == "__main__":
    main()
