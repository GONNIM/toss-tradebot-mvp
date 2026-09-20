"""WP69-3b · 서버 IP 외부 소스 접근 확정 (읽기 전용 · 각 소스 GET 1회).

**규칙**:
- biotech_sec_common 의 SEC_UA · SEC_FROM · SEC_ACCEPT_ENCODING 상수 참조 (하드코딩 금지).
- 각 소스 GET 1회 · 200/403/429 기록.
- **소스별 중단** (전체 중단 아님) · 하나 실패해도 다른 소스는 계속 시도.
- 결과는 stdout JSON + docs/plans/biotech/SOURCE-CHECK.md 저장.

사용 (서버):
    cd /root/toss-tradebot-mvp
    PYTHONPATH=. backend/.venv/bin/python -m backend.scripts.biotech_h69_source_check

**보안**:
- setup_secure_logging 강제 (require_secure_logging).
- 응답 본문·헤더 노출 금지 (status 코드·엔드포인트만 기록).
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · 보안 로거 자동
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_h69_source_check")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = PROJECT_ROOT / "docs" / "plans" / "biotech" / "SOURCE-CHECK.md"

HEADERS = {
    "User-Agent": SEC_UA,
    "From": SEC_FROM,
    "Accept-Encoding": SEC_ACCEPT_ENCODING,
}

# 파이프에서 실제 사용하는 파라미터와 동일 (사용자 지시)
SOURCES = [
    ("SEC EDGAR submissions", "https://data.sec.gov/submissions/CIK0001318605.json"),
    ("CT.gov v2 studies", "https://clinicaltrials.gov/api/v2/studies?pageSize=1"),
    ("StockTwits symbol stream", "https://api.stocktwits.com/api/2/streams/symbol/AAPL.json"),
    ("apewisdom all-stocks", "https://apewisdom.io/api/v1.0/filter/all-stocks"),
    ("Reddit RSS biotechplays", "https://www.reddit.com/r/biotechplays/new/.rss"),
]


def _check_one(name: str, url: str) -> dict:
    """단일 소스 GET · 200/403/429/etc 기록 · 본문 노출 없음."""
    try:
        r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=15.0)
        return {
            "name": name,
            "url_prefix": url.split("?")[0],
            "status": r.status_code,
            "content_type": r.headers.get("content-type", "").split(";")[0],
            "body_bytes": len(r.content),
            "verdict": (
                "OK" if 200 <= r.status_code < 300
                else "BLOCKED" if r.status_code in (403, 429)
                else "OTHER"
            ),
        }
    except httpx.HTTPError as e:
        return {
            "name": name,
            "url_prefix": url.split("?")[0],
            "status": None,
            "verdict": "EXC",
            "exception": e.__class__.__name__,
        }


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    results = []
    for name, url in SOURCES:
        r = _check_one(name, url)
        LOG.info("%s · HTTP %s · %s", r["name"], r.get("status", "?"), r["verdict"])
        results.append(r)
        time.sleep(0.6)  # SEC 10 req/s 안 · 다른 소스 rate 보수적

    # md 저장
    now_utc = datetime.now(timezone.utc).isoformat()
    lines = [
        "# SOURCE-CHECK · biotech 외부 소스 접근 확정",
        "",
        f"> 실행: {now_utc} · 서버 IP · biotech_sec_common 상수 UA·From·Accept-Encoding",
        "> 각 소스 GET 1회 · 소스별 중단 · 하나 실패해도 다른 소스 계속 시도",
        "",
        "| 소스 | URL prefix | HTTP | 본문 bytes | 판정 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['name']} | `{r['url_prefix']}` | "
            f"{r.get('status', 'EXC')} | {r.get('body_bytes', '-')} | {r['verdict']} |"
        )
    lines += [
        "",
        "## 판정 규칙",
        "- **OK** = 2xx · 서버 IP·UA 접근 성립",
        "- **BLOCKED** = 403/429 · 우회 금지 · 대안 검토 (CT.gov = AACT 주간 스냅샷)",
        "- **OTHER** = 그 외 (redirect·5xx 등) · 파이프 개별 대응",
        "- **EXC** = 네트워크·TLS 예외 · 재시도 대상",
        "",
        f"## 노출 검사",
        "- 응답 본문·헤더 로그 없음 (status·bytes 만)",
        "- 토큰·쿠키·자격증명 사용 없음",
    ]
    OUT_PATH.write_text("\n".join(lines))
    LOG.info("SOURCE-CHECK.md 저장 · %d 소스", len(results))
    print(json.dumps({"generated": now_utc, "results": results}, indent=2))


if __name__ == "__main__":
    main()
