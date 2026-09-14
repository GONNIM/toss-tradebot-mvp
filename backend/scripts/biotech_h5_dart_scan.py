"""WP12 · H5 매핑 대안 · DART 사업보고서 본문 GLP-1 키워드 스캔.

용도:
- WP3 pblntf_ty=B 실패 → 정기공시(A) 사업보고서 본문 스캔으로 대체
- 대상: GLP-1 후보 24개사 (WP3 목록) · corp_code → 사업보고서 rcept_no
- 각 사업보고서 XBRL/원문 다운로드 → "GLP-1|비만치료제|세마글루타이드" 스캔
- 결과: 언급 회사 목록 + 근거 rcept_no

식약처 오픈API:
- data.mfds.go.kr 인증키 필요 (미보유) · 실측 제한 · 후속 별건

원칙:
- 결제 금지 · biotech 이름공간 · DART_API_KEY 재사용 (마스킹 필터 적용)
- 호출 수 예산 기록 (예산 ≤500 · principles 배치 방해 방지)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import io
import json
import logging
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h5_dart_scan")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CACHE_DIR = DATA_DIR / "h5_dart_doc_cache"
CACHE_DIR.mkdir(exist_ok=True)

DART_KEY = os.getenv("DART_API_KEY", "")
DART_BASE = "https://opendart.fss.or.kr/api"
REQ_INTERVAL = 0.3

CANDIDATES = [
    "한미약품", "펩트론", "디앤디파마텍", "인벤티지랩", "라파스", "프로티나",
    "큐로셀", "동아에스티", "일동제약", "종근당", "유한양행", "대웅제약",
    "삼천당제약", "삼양홀딩스", "메디톡스", "휴온스", "부광약품", "SK바이오팜",
    "셀트리온", "삼성바이오로직스", "HK이노엔", "보령", "동성제약", "현대약품",
]

KEYWORDS = [
    "GLP-1", "GLP1", "비만치료제", "세마글루타이드", "터제파타이드",
    "리라글루타이드", "위고비", "오젬픽", "마운자로", "인크레틴",
]


def git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def load_corp_codes() -> dict:
    cache = DATA_DIR / "dart_corp_codes.json"
    if not cache.exists():
        LOG.error("run biotech_h5_glp1_map first to populate dart_corp_codes.json")
        sys.exit(1)
    return json.loads(cache.read_text())


def fetch_annual_reports(client: httpx.Client, corp_code: str, year_start: int = 2021, year_end: int = 2025) -> list[dict]:
    """DART list.json · pblntf_ty=A · report_nm 에 사업보고서 매치 필터."""
    all_rows = []
    for year in range(year_start, year_end + 1):
        r = client.get(
            f"{DART_BASE}/list.json",
            params={
                "crtfc_key": DART_KEY,
                "corp_code": corp_code,
                "bgn_de": f"{year}0101",
                "end_de": f"{year}1231",
                "pblntf_ty": "A",
                "page_no": 1,
                "page_count": 100,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("status") == "013":
            continue
        if j.get("status") != "000":
            LOG.warning("DART status=%s", j.get("status"))
            continue
        for row in j.get("list", []):
            rn = row.get("report_nm", "")
            if "사업보고서" in rn:
                all_rows.append(row)
        time.sleep(REQ_INTERVAL)
    return all_rows


def fetch_document(client: httpx.Client, rcept_no: str) -> str | None:
    """DART document.xml (zip) · 사업보고서 원문."""
    cache_path = CACHE_DIR / f"{rcept_no}.txt"
    if cache_path.exists():
        return cache_path.read_text(errors="ignore")
    try:
        r = client.get(
            f"{DART_BASE}/document.xml",
            params={"crtfc_key": DART_KEY, "rcept_no": rcept_no},
            timeout=60.0,
        )
        r.raise_for_status()
        # Response is zip file
        try:
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            texts = []
            for name in zf.namelist():
                try:
                    body = zf.read(name).decode("euc-kr", errors="ignore")
                except Exception:
                    body = zf.read(name).decode("utf-8", errors="ignore")
                texts.append(body)
            merged = "\n".join(texts)
        except zipfile.BadZipFile:
            merged = r.text
        # Strip XML tags for cleaner keyword search
        stripped = re.sub(r"<[^>]+>", " ", merged)
        cache_path.write_text(stripped)
        return stripped
    except Exception as e:
        LOG.warning("document fetch failed rcept=%s: %s", rcept_no, e)
        return None


def scan_keywords(text: str) -> list[str]:
    if not text:
        return []
    hits = []
    for kw in KEYWORDS:
        if kw.lower() in text.lower():
            hits.append(kw)
    return hits


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not DART_KEY:
        LOG.error("DART_API_KEY missing")
        sys.exit(1)
    sha = git_sha()
    LOG.info("git_sha=%s · DART_KEY set=%s", sha, bool(DART_KEY))

    corp_map = load_corp_codes()
    call_count = 0
    doc_count = 0
    hits_per_company = {}
    hyundai_result = "관계 미확인"
    rows_out = []

    with httpx.Client(headers={"User-Agent": "TossTradebot-BiotechRadar/1.0"}) as client:
        for name in CANDIDATES:
            if name not in corp_map:
                LOG.info("skip · corp_map 부재: %s", name)
                continue
            info = corp_map[name]
            LOG.info("processing %s (corp=%s stock=%s)", name, info["corp_code"], info["stock_code"])
            reports = fetch_annual_reports(client, info["corp_code"])
            call_count += 5  # 5 years
            LOG.info("  annual reports: %d", len(reports))
            for report in reports:
                rcept_no = report.get("rcept_no", "")
                text = fetch_document(client, rcept_no)
                doc_count += 1
                time.sleep(REQ_INTERVAL)
                hits = scan_keywords(text or "")
                if hits:
                    hits_per_company.setdefault(name, []).append(
                        {
                            "rcept_no": rcept_no,
                            "rcept_dt": report.get("rcept_dt"),
                            "report_nm": report.get("report_nm"),
                            "keywords": ",".join(hits),
                        }
                    )
                    rows_out.append(
                        {
                            "candidate_name": name,
                            "stock_code": info["stock_code"],
                            "corp_code": info["corp_code"],
                            "rcept_no": rcept_no,
                            "rcept_dt": report.get("rcept_dt"),
                            "report_nm": report.get("report_nm"),
                            "keywords": ",".join(hits),
                        }
                    )
            if call_count >= 500:
                LOG.warning("call budget hit · stop")
                break

    if "현대약품" in hits_per_company:
        hyundai_result = f"연계 확인 · rcept {len(hits_per_company['현대약품'])}건"
    elif "현대약품" in corp_map:
        hyundai_result = "관계 미확인 (사업보고서 GLP-1 키워드 매치 0)"

    # 저장
    out_path = DATA_DIR / f"h5_dart_scan_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "candidate_name", "stock_code", "corp_code",
                "rcept_no", "rcept_dt", "report_nm", "keywords",
            ],
        )
        w.writeheader()
        w.writerows(rows_out)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "candidates_queried": len(hits_per_company) + sum(1 for c in CANDIDATES if c in corp_map) - len(hits_per_company),
        "dart_calls": call_count,
        "documents_fetched": doc_count,
        "companies_with_hits": len(hits_per_company),
        "hyundai_pharm_result": hyundai_result,
        "mfds_status": "미측정 (인증키 미보유 · 후속 별건)",
        "hits_per_company": {k: len(v) for k, v in hits_per_company.items()},
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
