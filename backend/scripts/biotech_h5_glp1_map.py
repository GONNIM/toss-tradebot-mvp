"""WP3 · H5 GLP-1 계열 국내 연계 매핑 실측.

용도:
- DART OpenAPI 로 GLP-1/비만치료제 관련 국내 상장 기업 20건 매핑
- 유형 3 (Class effect) 사전 정의 목록 대상 · `report_nm` 근거 필수
- 현대약품 (License-in/out 유형 1) 별도 기록 확인

원칙:
- 결제 금지 · 기존 DART_API_KEY 사용 (backend/.env)
- 룰만 사전: 후보 회사명 목록 → DART corp_code 조회 → 최근 5년 공시 (`pblntf_ty=B` 주요사항보고서)
- 산출: h5_kr_mapping_{sha}.csv (근거 rcept_no 필수)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 자격증명 URL 파라미터 노출 차단 (2026-09-08 · sung2011103@naver.com DART_KEY 노출 대응)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h5_glp1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
load_dotenv(PROJECT_ROOT / "backend" / ".env")

DART_KEY = os.getenv("DART_API_KEY", "")
DART_BASE = "https://opendart.fss.or.kr/api"
REQ_INTERVAL = 0.3

# GLP-1 계열 국내 개발 후보 (사전 커밋 · 공지된 파이프라인 보유 기업)
GLP1_CANDIDATES = [
    "한미약품",
    "펩트론",
    "디앤디파마텍",
    "인벤티지랩",
    "라파스",
    "프로티나",
    "큐로셀",
    "동아에스티",
    "일동제약",
    "종근당",
    "유한양행",
    "대웅제약",
    "삼천당제약",
    "삼양홀딩스",
    "메디톡스",
    "휴온스",
    "부광약품",
    "SK바이오팜",
    "셀트리온",
    "삼성바이오로직스",
    "HK이노엔",
    "보령",
    "동성제약",
    "현대약품",  # License-in/out 별도 확인
]

# 관련 키워드 (report_nm 매치)
GLP1_KEYWORDS = [
    "GLP-1",
    "GLP1",
    "비만",
    "당뇨",
    "글루카곤",
    "세마글루타이드",
    "터제파타이드",
    "리라글루타이드",
    "인크레틴",
    "체중",
    "위고비",
    "오젬픽",
    "마운자로",
    "노보노디스크",
    "일라이릴리",
    "노보",
    "릴리",
    "위주엔",
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


def load_corp_codes() -> dict[str, str]:
    """DART corp_code.xml (전체) 를 조회하여 회사명 → corp_code 사전 반환.

    DART 는 별도 zip 배포 (corpCode.xml) · 상당량 · 캐시.
    """
    cache = DATA_DIR / "dart_corp_codes.json"
    if cache.exists():
        return json.loads(cache.read_text())

    LOG.info("fetching DART corp_code archive...")
    import io
    import zipfile
    import xml.etree.ElementTree as ET

    with httpx.Client() as client:
        r = client.get(
            f"{DART_BASE}/corpCode.xml",
            params={"crtfc_key": DART_KEY},
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.content
    zf = zipfile.ZipFile(io.BytesIO(data))
    xml_bytes = zf.read(zf.namelist()[0])
    root = ET.fromstring(xml_bytes)
    out = {}
    for elem in root.findall("list"):
        name = elem.findtext("corp_name") or ""
        code = elem.findtext("corp_code") or ""
        stock_code = elem.findtext("stock_code") or ""
        if name and code and stock_code.strip():
            out[name] = {"corp_code": code, "stock_code": stock_code.strip()}
    cache.write_text(json.dumps(out, ensure_ascii=False))
    LOG.info("cached %d listed corp_codes", len(out))
    return out


def fetch_disclosure(
    client: httpx.Client, corp_code: str, bgn: str, end: str
) -> list[dict]:
    """DART list.json 조회 · pblntf_ty=B (주요사항보고서) 5년."""
    all_rows = []
    page = 1
    while True:
        r = client.get(
            f"{DART_BASE}/list.json",
            params={
                "crtfc_key": DART_KEY,
                "corp_code": corp_code,
                "bgn_de": bgn,
                "end_de": end,
                "pblntf_ty": "B",
                "page_no": page,
                "page_count": 100,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("status") not in ("000", "013"):
            LOG.warning("DART status=%s message=%s", j.get("status"), j.get("message"))
            break
        if j.get("status") == "013":  # no data
            break
        rows = j.get("list", [])
        all_rows.extend(rows)
        if page >= j.get("total_page", 1):
            break
        page += 1
        time.sleep(REQ_INTERVAL)
    return all_rows


def find_glp1_reports(rows: list[dict]) -> list[dict]:
    """report_nm 에 GLP-1 관련 키워드 매치."""
    out = []
    for row in rows:
        rn = row.get("report_nm", "")
        for kw in GLP1_KEYWORDS:
            if kw.lower() in rn.lower():
                row["match_keyword"] = kw
                out.append(row)
                break
    return out


def main():
    require_secure_logging()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not DART_KEY:
        LOG.error("DART_API_KEY missing")
        sys.exit(1)
    sha = git_sha()
    LOG.info("git_sha=%s · DART_KEY set=%s len=%d", sha, bool(DART_KEY), len(DART_KEY))

    corp_map = load_corp_codes()
    LOG.info("loaded %d listed corp_codes", len(corp_map))

    hits = []
    hyundai_pharm_rows = []
    call_count = 0
    with httpx.Client(headers={"User-Agent": "TossTradebot-BiotechRadar/1.0"}) as client:
        for name in GLP1_CANDIDATES:
            if name not in corp_map:
                LOG.info("candidate not in corp_map: %s", name)
                continue
            info = corp_map[name]
            LOG.info("querying %s (corp=%s stock=%s)", name, info["corp_code"], info["stock_code"])
            rows = fetch_disclosure(client, info["corp_code"], "20200101", "20260908")
            call_count += 1
            time.sleep(REQ_INTERVAL)
            matches = find_glp1_reports(rows)
            for m in matches:
                m["candidate_name"] = name
                m["stock_code"] = info["stock_code"]
                hits.append(m)
            if name == "현대약품":
                hyundai_pharm_rows = rows

            if call_count >= 500:  # 예산 상한
                LOG.warning("hit call budget · stop")
                break

    LOG.info("total GLP-1 matches: %d", len(hits))
    LOG.info("현대약품 total disclosures: %d", len(hyundai_pharm_rows))

    # 저장
    out_path = DATA_DIR / f"h5_kr_mapping_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "candidate_name",
                "stock_code",
                "corp_code",
                "rcept_no",
                "rcept_dt",
                "report_nm",
                "match_keyword",
                "flr_nm",
            ],
        )
        w.writeheader()
        for h in hits:
            w.writerow(
                {
                    "candidate_name": h.get("candidate_name"),
                    "stock_code": h.get("stock_code"),
                    "corp_code": h.get("corp_code"),
                    "rcept_no": h.get("rcept_no"),
                    "rcept_dt": h.get("rcept_dt"),
                    "report_nm": h.get("report_nm"),
                    "match_keyword": h.get("match_keyword"),
                    "flr_nm": h.get("flr_nm"),
                }
            )

    # 유형 분포 (report_nm 기반 근사)
    type_dist = {"license": 0, "supply": 0, "clinical": 0, "other": 0}
    for h in hits:
        rn = h.get("report_nm", "")
        if any(k in rn for k in ["기술이전", "라이선스", "License", "기술도입"]):
            type_dist["license"] += 1
        elif any(k in rn for k in ["공급", "판매", "유통"]):
            type_dist["supply"] += 1
        elif any(k in rn for k in ["임상", "IND", "허가"]):
            type_dist["clinical"] += 1
        else:
            type_dist["other"] += 1

    summary = {
        "git_sha": sha,
        "candidates_queried": call_count,
        "total_matches": len(hits),
        "distinct_companies": len(set(h.get("candidate_name") for h in hits)),
        "type_dist_by_report_nm": type_dist,
        "hyundai_pharm_total_disclosures": len(hyundai_pharm_rows),
        "hyundai_pharm_glp1_matches": sum(
            1 for r in hyundai_pharm_rows if any(k.lower() in r.get("report_nm", "").lower() for k in GLP1_KEYWORDS)
        ),
        "csv_path": str(out_path),
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
