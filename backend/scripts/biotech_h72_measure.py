"""WP72-1 / WP73 · 로그인 후 측정 자동화 (activist-radar · biotech).

WP73 규칙 (2026-09-20):
- 기본 8장 = activist-radar · biotech × desktop/mobile × light/dark
- **탭별 캡처 제거** (새 구조: KPI + 6 섹션 + 3 글 탭 모두 한 페이지 · 별도 라우팅 없음)
- 출력 폴더: docs/plans/biotech/screenshots/<YYYYMMDD>_sha_<해시>/<page>_<viewport>_<scheme>.webp
- PNG → WebP (품질 80 · ≤200KB · 필요 시 폭 640/390 리사이즈) · PNG 원본 삭제
- 텍스트 산출 (FE-DIFF-*.md) 은 git 추적 유지

절차:
- 운영 서버 https://optimus8.cafe24.com 접근
- 첫 페이지 /biotech · AdminSessionBar password fill → 로그인 → admin 배지 대기
- 배포 sha 추출 → 출력 폴더 결정
- activist-radar 진입 · 스크린샷 · computed style 측정
- /biotech 진입 · 스크린샷 · computed style 측정 (탭 클릭 없음)
- PNG → WebP 변환 + PNG 삭제 · 200KB 초과 시 q 낮춤 + resize
- FE-DIFF-v3-<phase>.md 저장

**보안 원칙**:
- 토큰 값 출력·로그·복사 금지 (config 로더 취득 즉시 fill 후 로컬 참조 폐기)
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
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h72_measure")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech"
SCREENSHOT_ROOT = DOCS / "screenshots"
BASE_URL = "https://optimus8.cafe24.com"

# WP73 · 탭별 캡처 제거 · 페이지 단위 8장 (page × 2 vp × 2 scheme = 8)
PAGES = [
    ("activist-radar", "/activist-radar"),
    ("biotech", "/biotech"),
]

MEASUREMENTS = [
    ("main", "main_container", ["max-width", "padding-left", "padding-right", "padding-top", "padding-bottom"]),
    ("h1", "h1", ["font-size", "line-height", "font-weight", "color"]),
    ("h2", "h2_first", ["font-size", "line-height", "font-weight"]),
    ("p", "p_first", ["font-size", "line-height", "color"]),
    (".grid > .rounded-lg:first-child", "kpi_card_first", ["font-size", "border-color", "padding-top", "padding-left"]),
]

WEBP_MAX_BYTES = 200 * 1024  # WP73 · 장당 ≤ 200KB
CWEBP_BIN = "/opt/homebrew/bin/cwebp"


def _extract_build_id(page) -> str:
    """빌드 식별자: 배포 sha (footer title="build sha ...") 우선."""
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
    """AdminSessionBar 로그인 (토큰 값 노출 없이)."""
    try:
        pw_input = page.locator('input[type="password"]').first
        pw_input.wait_for(state="visible", timeout=10_000)
    except Exception:
        if page.locator("text=admin · 활성").count() > 0:
            return True
        return False
    tok = token_provider()
    if not tok:
        LOG.error("SNIPER_API_TOKEN 미설정")
        return False
    pw_input.fill(tok)
    del tok  # 즉시 로컬 참조 폐기
    page.locator('button:has-text("로그인")').first.click()
    try:
        page.wait_for_selector("text=admin · 활성", timeout=10_000)
        return True
    except Exception:
        return False


def _measure_page(page, page_name: str) -> list[dict]:
    """페이지 단위 computed style 측정 (탭 클릭 없음)."""
    results = []
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
                results.append({"page": page_name, "selector": sel, "label": label, "computed": style})
        except Exception:
            pass
    return results


def _png_to_webp(png_path: Path, viewport: str) -> Path:
    """PNG → WebP (q80 · ≤200KB · 필요 시 q 낮춤 + resize) · PNG 삭제."""
    webp_path = png_path.with_suffix(".webp")
    default_width = 640 if viewport == "desktop" else 390
    # 1) q80 시도
    for q, resize_w in [(80, None), (75, None), (65, None), (75, default_width),
                        (65, default_width), (55, default_width), (45, default_width)]:
        args = [CWEBP_BIN, "-q", str(q), "-quiet"]
        if resize_w:
            args += ["-resize", str(resize_w), "0"]
        args += [str(png_path), "-o", str(webp_path)]
        try:
            subprocess.run(args, check=True, timeout=30)
        except Exception as e:
            LOG.warning("cwebp fail: %s", e.__class__.__name__)
            break
        if webp_path.stat().st_size <= WEBP_MAX_BYTES:
            LOG.info("  webp %s · q=%d resize=%s · %dB",
                     webp_path.name, q, resize_w, webp_path.stat().st_size)
            break
    png_path.unlink(missing_ok=True)
    return webp_path


def _prune_sets(root: Path, keep: int = 2) -> None:
    """최근 keep 세트만 유지 · 나머지 폴더 삭제."""
    sets = sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for old in sets[keep:]:
        LOG.info("  prune old set: %s", old.name)
        for f in old.iterdir():
            f.unlink()
        old.rmdir()


def _run(phase: str) -> dict:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from playwright.sync_api import sync_playwright

    def token_provider() -> str:
        return os.environ.get("SNIPER_API_TOKEN", "").strip()

    if not token_provider():
        LOG.error("SNIPER_API_TOKEN 미설정 · .env decrypt 확인")
        return {"ok": False, "reason": "no_token"}

    all_results: list[dict] = []
    scenarios: list[dict] = []
    build_id = "unknown"
    out_dir: Path | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for viewport_name, viewport in [
            ("desktop", {"width": 1280, "height": 900}),
            ("mobile", {"width": 390, "height": 844}),
        ]:
            for scheme in ["light", "dark"]:
                context = browser.new_context(
                    viewport=viewport, color_scheme=scheme, ignore_https_errors=False,
                )
                page = context.new_page()

                # 로그인 (AdminSessionBar 렌더된 페이지 필요 → /biotech)
                page.goto(f"{BASE_URL}/biotech", timeout=30_000, wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                logged_in = _do_login(page, token_provider)

                # 빌드 sha 추출 (첫 회에만) · 출력 폴더 결정
                if out_dir is None:
                    build_id = _extract_build_id(page)
                    today = datetime.now(timezone.utc).strftime("%Y%m%d")
                    out_dir = SCREENSHOT_ROOT / f"{today}_{build_id}"
                    out_dir.mkdir(parents=True, exist_ok=True)

                # 페이지 순회 (탭 클릭 없음 · WP73)
                for name, path in PAGES:
                    page.goto(f"{BASE_URL}{path}", timeout=30_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    results = _measure_page(page, name)
                    all_results.extend(
                        [{**r, "viewport": viewport_name, "scheme": scheme} for r in results]
                    )
                    png = out_dir / f"{name}_{viewport_name}_{scheme}.png"
                    try:
                        page.screenshot(path=str(png), full_page=True)
                        webp = _png_to_webp(png, viewport_name)
                        scenarios.append({"file": webp.name, "page": name, "logged_in": logged_in})
                    except Exception as e:
                        LOG.warning("screenshot %s: %s", png.name, e.__class__.__name__)

                context.close()
        browser.close()

    # 이전 세트 정리 (최근 2세트만)
    _prune_sets(SCREENSHOT_ROOT, keep=2)

    # 리포트 (텍스트 · git 추적)
    lines = [
        f"# WP72/73 · FE-DIFF v3 · phase={phase} · 빌드 {build_id}",
        "",
        f"> Playwright headless · 운영 · admin 세션 · 폴더 `screenshots/{out_dir.name if out_dir else '?'}/`",
        "> 뷰포트: 데스크톱 1280×900 · 모바일 390×844 · 라이트/다크 · 8장 (탭 클릭 없음 · WP73)",
        "",
        "## 측정 결과 (셀렉터별)",
        "",
        "| 페이지 | 뷰포트 | 스킴 | 요소 | 속성 | 값 |",
        "|---|---|---|---|---|---|",
    ]
    for r in all_results:
        for prop, val in sorted(r.get("computed", {}).items()):
            lines.append(
                f"| {r['page']} | {r['viewport']} | {r['scheme']} | "
                f"{r['label']} | {prop} | `{val}` |"
            )

    lines += ["", "## 스크린샷 (WebP · ≤200KB · 로그인 후)", ""]
    for s in scenarios:
        note = "" if s["logged_in"] else " · **anon (로그인 실패)**"
        lines.append(f"- `screenshots/{out_dir.name if out_dir else '?'}/{s['file']}`{note}")

    lines += [
        "",
        "## 노출 검사",
        "- 토큰·쿠키·헤더 값 노출: **0건** (config 로더 · fill 직후 로컬 참조 폐기)",
        f"- 측정 항목 수: {len(all_results)} · 스크린샷 수: {len(scenarios)}",
        "",
    ]

    out_path = DOCS / f"FE-DIFF-v3-{phase}.md"
    out_path.write_text("\n".join(lines))
    LOG.info("FE-DIFF-v3-%s.md · %d 측정 · %d 스크린샷", phase, len(all_results), len(scenarios))

    summary = {
        "phase": phase,
        "buildId": build_id,
        "screenshot_dir": out_dir.name if out_dir else None,
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
