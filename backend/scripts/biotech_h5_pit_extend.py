"""WP21-2 PIT 확장 · FY2018/FY2019 사업보고서 (2019·2020 제출분) GLP-1 스캔.

용도:
- 23 후보사 (WP3 기존) DART pblntf_ty=A · 사업보고서 필터
- rcept_dt 가 2019/2020 년인 사업보고서 (FY2018/FY2019 재무제표) 원문 다운로드
- GLP-1 키워드 매치 → pit_entry_quarter 재산출 (기존 v3 대비 앞당김)
- h5_kr_mapping_v4 갱신 (pit_entry_quarter_v5)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import io
import json
import logging
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h5_pit_extend")

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

KEYWORDS = ["GLP-1", "GLP1", "비만치료제", "세마글루타이드", "터제파타이드", "리라글루타이드", "위고비", "오젬픽", "마운자로", "인크레틴"]


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_corp_codes() -> dict:
    return json.loads((DATA_DIR / "dart_corp_codes.json").read_text())


def fetch_2019_2020_reports(client: httpx.Client, corp_code: str) -> list[dict]:
    all_rows = []
    for year in (2019, 2020):
        r = client.get(
            f"{DART_BASE}/list.json",
            params={
                "crtfc_key": DART_KEY, "corp_code": corp_code,
                "bgn_de": f"{year}0101", "end_de": f"{year}1231",
                "pblntf_ty": "A", "page_no": 1, "page_count": 100,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("status") == "013":
            continue
        for row in j.get("list", []):
            if "사업보고서" in row.get("report_nm", ""):
                all_rows.append(row)
        time.sleep(REQ_INTERVAL)
    return all_rows


def fetch_document(client: httpx.Client, rcept_no: str) -> str | None:
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
        stripped = re.sub(r"<[^>]+>", " ", merged)
        cache_path.write_text(stripped)
        return stripped
    except Exception as e:
        LOG.warning("doc fail rcept=%s: %s", rcept_no, e)
        return None


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not DART_KEY:
        return
    sha = git_sha()
    LOG.info("git_sha=%s", sha)
    corp_map = load_corp_codes()

    updated = []
    hits_by_company: dict[str, list[dict]] = {}
    with httpx.Client(headers={"User-Agent": "TossTradebot-BiotechRadar biotech-radar@sung2011103.dev"}) as client:
        for name in CANDIDATES:
            if name not in corp_map:
                continue
            info = corp_map[name]
            reports = fetch_2019_2020_reports(client, info["corp_code"])
            for r in reports:
                text = fetch_document(client, r["rcept_no"])
                if not text:
                    continue
                hits = [kw for kw in KEYWORDS if kw.lower() in text.lower()]
                if hits:
                    hits_by_company.setdefault(name, []).append({
                        "rcept_no": r["rcept_no"], "rcept_dt": r["rcept_dt"],
                        "report_nm": r["report_nm"], "keywords": ",".join(hits),
                    })
                time.sleep(REQ_INTERVAL)

    # PIT 재산출: 각 후보사의 최초 GLP-1 언급 사업보고서 rcept_dt → 분기
    old_v4 = list(csv.DictReader((DATA_DIR / f"h5_kr_mapping_v4_{sha}.csv").open()))
    v4_by_name = {r["candidate_name"]: r for r in old_v4}

    v5_rows = []
    changed = 0
    for name, v4row in v4_by_name.items():
        hits = hits_by_company.get(name, [])
        old_pit = v4row["pit_entry_quarter"]
        new_pit = old_pit
        if hits:
            earliest = min(hits, key=lambda h: h["rcept_dt"])
            dt = earliest["rcept_dt"]
            y = dt[:4]
            m = int(dt[4:6])
            q = (m - 1) // 3 + 1
            candidate_pit = f"{y}Q{q}"
            if candidate_pit < old_pit:
                new_pit = candidate_pit
                changed += 1
        v5_rows.append({
            **v4row,
            "pit_entry_quarter_v5": new_pit,
            "pit_source": "fy2018_2019_extension" if new_pit != old_pit else "unchanged_v4",
        })

    out_path = DATA_DIR / f"h5_kr_mapping_v5_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(v5_rows[0].keys()))
        w.writeheader()
        w.writerows(v5_rows)

    # 요약
    le_2019q4 = sum(1 for r in v5_rows if r["pit_entry_quarter_v5"] and r["pit_entry_quarter_v5"] <= "2019Q4")
    dist = {}
    for r in v5_rows:
        dist[r["pit_entry_quarter_v5"]] = dist.get(r["pit_entry_quarter_v5"], 0) + 1
    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "companies_scanned": len(v4_by_name),
        "companies_with_new_hits": len(hits_by_company),
        "pit_changed": changed,
        "pit_le_2019Q4_count": le_2019q4,
        "pit_distribution": dist,
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
