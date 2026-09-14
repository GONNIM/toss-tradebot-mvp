"""WP65 · Form 4 증분 수집 (일일 파이프 · 최근 30일 · 55 CIK).

WP28-2 는 전량 수집 (55 CIK · Form 4 최근 60건) · 이건 초회 백필.
WP65 는 일일 증분: 각 filer 의 submissions.json 최신 accession · 이미 캐시 있는지 확인 후 신규만 append.

**출력**:
- 캐시 갱신: `backend/data/h28v2_form4_issuer_buys_{sha}.json` (덧붙임)
- rumor daily 리포트에 표 4 병기 · radar 순위표에 "임원·대주주 매수" 꼬리표

**하단 문구** (표 4):
- "잠정 확인 → **유보 강등** · WP63-3 견고성 (d) 13D 중복 제외 CI 하한 < 0 · 60일 전향 재평가 (2026-11-15)"
- 소액 실전 규칙 적용
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_h28v2_form4_channel import (
    load_fund_ciks, sec_get, fetch_form4_accessions, fetch_form4_xml, parse_form4,
)
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING

import csv
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h65_form4_daily")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_events_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    fund_ciks = load_fund_ciks()
    LOG.info("filers (WP28-2 55 CIK): %d", len(fund_ciks))

    cache_path = DATA_DIR / f"h28v2_form4_issuer_buys_{sha}.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    # 최근 30일 컷오프
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    new_buys = 0
    with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM,
                                "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
        for i, filer_cik in enumerate(fund_ciks, 1):
            try:
                accs = fetch_form4_accessions(client, filer_cik)
            except Exception:
                continue
            # 30일 이내 accession 만
            recent = [a for a in accs if a.get("date", "") >= cutoff]
            if not recent:
                continue
            # 기존 accession 세트
            existing = set()
            for b in cache.get(filer_cik, {}).get("buys", []):
                if b.get("accession"):
                    existing.add(b["accession"])
            fresh_recent = [a for a in recent if a["accession"] not in existing]
            if not fresh_recent:
                continue
            LOG.info("[%d/%d] filer %s: +%d fresh accessions (30d)", i, len(fund_ciks), filer_cik, len(fresh_recent))
            for a in fresh_recent[:20]:  # 하루당 filer 최대 20건
                try:
                    xml = fetch_form4_xml(client, filer_cik, a["accession"])
                except Exception:
                    continue
                if xml is None:
                    continue
                for b in parse_form4(xml):
                    b["filing_date"] = a["date"]
                    b["filer_cik"] = filer_cik
                    b["accession"] = a["accession"]
                    if filer_cik not in cache:
                        cache[filer_cik] = {"n_accs": 0, "n_buys": 0, "buys": []}
                    cache[filer_cik]["buys"].append(b)
                    cache[filer_cik]["n_buys"] = len(cache[filer_cik]["buys"])
                    new_buys += 1

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    LOG.info("증분 · 신규 buys: +%d · 전체 filers cached: %d", new_buys, len(cache))

    # 표 4 · 최근 20 거래일 F4 매수 (rumor daily 확장용)
    cutoff_20d = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")  # 20 거래일 ≈ 30 달력일
    table4 = []
    for filer_cik, info in cache.items():
        for b in info.get("buys", []):
            tx_date = b.get("tx_date", "")
            if tx_date >= cutoff_20d:
                # 발행사 시총 부재/필터는 뷰어 단계 · 여기는 원값
                elapsed_days = (datetime.now(timezone.utc).date() - datetime.strptime(tx_date, "%Y-%m-%d").date()).days if tx_date else 0
                table4.append({
                    "filing_date": b.get("filing_date", ""),
                    "tx_date": tx_date,
                    "elapsed_days": elapsed_days,
                    "issuer_cik": b.get("issuer_cik", ""),
                    "issuer_name": b.get("issuer_name", ""),
                    "filer_cik": filer_cik,
                    "shares": b.get("shares", 0),
                    "accession": b.get("accession", ""),
                })
    table4.sort(key=lambda x: x["tx_date"], reverse=True)
    table4 = table4[:30]  # 최근 30건

    out_csv = DATA_DIR / f"h65_form4_daily_table_{sha}.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filing_date", "tx_date", "elapsed_days", "issuer_cik", "issuer_name",
                    "filer_cik", "shares", "accession"])
        for row in table4:
            w.writerow([row["filing_date"], row["tx_date"], row["elapsed_days"],
                        row["issuer_cik"], row["issuer_name"], row["filer_cik"],
                        row["shares"], row["accession"]])

    # 순위표 꼬리표용 issuer_cik 세트
    tagged_ciks = {row["issuer_cik"] for row in table4}
    tag_out = DATA_DIR / f"h65_f4_tag_ciks_{sha}.json"
    tag_out.write_text(json.dumps(sorted(tagged_ciks), ensure_ascii=False, indent=2))

    print(json.dumps({
        "git_sha": sha,
        "new_buys_added": new_buys,
        "total_filers_cached": len(cache),
        "table4_rows": len(table4),
        "table4_csv": str(out_csv),
        "tagged_issuer_ciks": len(tagged_ciks),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
