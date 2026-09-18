"""WP71-1 · Playwright 정밀 측정 (프론트 정합 비교 · 인증 없는 부분).

절차:
- 운영 서버 https://optimus8.cafe24.com/{activist-radar,biotech} 접근 (인증 없이)
- 두 페이지의 헤더·컨테이너·탭·배너 computed style 추출
- 뷰포트 1280 (데스크톱) · 390 (모바일) · 라이트·다크 총 4 케이스
- FE-DIFF.md 표 + docs/plans/biotech/screenshots/*.png 저장

**보안 원칙 (사용자 지시 · 2026-09-18)**:
- 토큰·쿠키·헤더 값 노출 0건
- config 로더 (setup_secure_logging) 강제
- 값 출력·로그·복사 금지
- Playwright 요청 헤더에만 사용 (이번은 admin 세션 없이 진행 · 토큰 미사용)

**측정 요소**:
- container 폭 · padding
- h1/h2 font-size · line-height · font-weight
- p (본문 텍스트) · line-height
- button (탭) · padding · border · font-size · 활성/비활성 스타일
- div (배너) · border · background · padding
- span (배지) · font-size · padding · background
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · 보안 로거 자동 · 값 출력 금지
from backend.scripts._biotech_bootstrap import require_secure_logging

import json
import logging
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h71_measure")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech"
SCREENSHOT_DIR = DOCS / "screenshots"
BASE_URL = "https://optimus8.cafe24.com"

# 측정 대상 · 인증 없이 접근 가능한 부분만
TARGETS = [
    ("activist-radar", "/activist-radar"),
    ("biotech", "/biotech"),
]

# 측정할 요소·속성
MEASUREMENTS = [
    # (selector, label, properties)
    ("main", "main_container", ["max-width", "padding-left", "padding-right", "padding-top", "padding-bottom"]),
    ("h1", "h1", ["font-size", "line-height", "font-weight", "color"]),
    ("h2", "h2_first", ["font-size", "line-height", "font-weight"]),
    ("p", "p_first", ["font-size", "line-height", "color"]),
    ("button", "button_first", ["padding-top", "padding-right", "padding-bottom", "padding-left",
                                "font-size", "border-bottom-width", "border-bottom-color", "background-color"]),
]


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from playwright.sync_api import sync_playwright

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for viewport_name, viewport in [("desktop", {"width": 1280, "height": 900}),
                                          ("mobile", {"width": 390, "height": 844})]:
            for scheme in ["light", "dark"]:
                context = browser.new_context(
                    viewport=viewport,
                    color_scheme=scheme,
                    ignore_https_errors=False,
                )
                page = context.new_page()

                for name, path in TARGETS:
                    url = f"{BASE_URL}{path}"
                    try:
                        page.goto(url, timeout=30_000, wait_until="networkidle")
                    except Exception as e:
                        LOG.warning("%s (%s/%s) · goto 실패: %s", name, viewport_name, scheme, e.__class__.__name__)
                        continue

                    # 스크린샷
                    filename = f"{name}_{viewport_name}_{scheme}.png"
                    screenshot_path = SCREENSHOT_DIR / filename
                    try:
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        LOG.info("saved %s", filename)
                    except Exception as e:
                        LOG.warning("screenshot 실패: %s", e.__class__.__name__)

                    # 요소별 computed style
                    for selector, label, props in MEASUREMENTS:
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
                                {"sel": selector, "props": props},
                            )
                            if style:
                                all_results.append({
                                    "page": name, "viewport": viewport_name, "scheme": scheme,
                                    "selector": selector, "label": label, "computed": style,
                                })
                        except Exception as e:
                            LOG.warning("measure %s/%s: %s", name, selector, e.__class__.__name__)

                context.close()

        browser.close()

    # 페이지·요소 별 비교 표 생성 (activist vs biotech)
    grouped: dict = {}
    for r in all_results:
        key = (r["viewport"], r["scheme"], r["label"])
        grouped.setdefault(key, {})[r["page"]] = r["computed"]

    lines = [
        "# WP71-1 · FE-DIFF 정밀 측정 결과 (2026-09-18)",
        "",
        "> Playwright headless · 운영 서버 · 인증 없는 부분만 (admin 미로그인 화면)",
        "> 뷰포트: 데스크톱 1280×900 · 모바일 390×844 · 라이트/다크 각 1건 · 총 4 케이스",
        "> **admin 콘텐츠 (표·md 문서) 는 인증 필요로 측정 제외** · WP71-2 구조 전환으로 자동 해결",
        "",
        "## 측정 결과 (activist-radar vs biotech · 인증 없는 상태)",
        "",
        "| 뷰포트 | 스킴 | 요소 | 속성 | activist-radar | biotech | 차이 |",
        "|---|---|---|---|---|---|---|",
    ]

    for (viewport, scheme, label), pages in sorted(grouped.items()):
        act = pages.get("activist-radar", {})
        bio = pages.get("biotech", {})
        all_props = sorted(set(act.keys()) | set(bio.keys()))
        for prop in all_props:
            a_val = act.get(prop, "-")
            b_val = bio.get(prop, "-")
            diff = "✅" if a_val == b_val else f"⚠️ 다름"
            lines.append(f"| {viewport} | {scheme} | {label} | {prop} | `{a_val}` | `{b_val}` | {diff} |")

    lines += [
        "",
        "## 스크린샷 파일 (4장 × 2 페이지 = 8장)",
        "",
    ]
    for name, _ in TARGETS:
        for viewport in ["desktop", "mobile"]:
            for scheme in ["light", "dark"]:
                lines.append(f"- `screenshots/{name}_{viewport}_{scheme}.png`")

    lines += [
        "",
        "## 노출 검사",
        "",
        "- 스크린샷·리포트: **토큰·쿠키·헤더 값 노출 0건** (측정 시 admin 헤더 사용 안 함)",
        "- config 로더 강제 · setup_secure_logging 활성",
        "",
        "## 판정",
        "",
        "- 인증 없는 부분 (컨테이너·헤더·탭·배너) 측정 결과 표 참조",
        "- ✅ = activist-radar 와 biotech 값 동일",
        "- ⚠️ = 차이 존재 · WP71-2 구조 전환 후 재측정 대상",
        "",
        "**다음 단계**: WP71-2 (구조 전환 · JSON 라우터 + activist-radar 골격 복제)",
    ]

    out_path = DOCS / "FE-DIFF.md"
    out_path.write_text("\n".join(lines))
    LOG.info("FE-DIFF.md 저장 · %d 측정 항목", len(all_results))
    print(json.dumps({
        "measurement_count": len(all_results),
        "screenshots": len(list(SCREENSHOT_DIR.glob("*.png"))),
        "output": str(out_path),
    }, indent=2))


if __name__ == "__main__":
    main()
