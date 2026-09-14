"""WP50 · CT.gov 스폰서 검색으로 A 상태 (뉴스 예정) 실측.

후보 66사 각각 CT.gov API v2 스폰서 검색:
- query.leadSponsor = 회사명
- filter.overallStatus = RECRUITING · ACTIVE_NOT_RECRUITING
- primaryCompletionDate > today (0~365일)
- 최근접 1건 → A 상태 · 예정일까지 n일 · NCT 번호 근거

+ h1a_events_v2 자문위 회의일 > today 병기 (mapped_ticker 있으면)

원칙: 무인증 · 각 후보 1회 · 30분 예상
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h50_ct_upcoming")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
UA = "TossTradebot-BiotechRadar biotech-radar@sung2011103.dev"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def fetch_upcoming(client: httpx.Client, sponsor_name: str) -> list[dict]:
    """스폰서 활성 임상 · primary_completion 미래."""
    if not sponsor_name:
        return []
    try:
        r = client.get(CTGOV, params={
            "query.lead": sponsor_name,
            "pageSize": 30,
            "format": "json",
            "fields": "protocolSection.identificationModule.nctId,"
                      "protocolSection.statusModule.overallStatus,"
                      "protocolSection.statusModule.primaryCompletionDateStruct,"
                      "protocolSection.designModule.phases,"
                      "protocolSection.identificationModule.briefTitle",
        }, timeout=30.0)
        if r.status_code != 200:
            return []
        studies = r.json().get("studies", [])
        today = datetime.now(timezone.utc).date()
        upcoming = []
        for st in studies:
            ps = st.get("protocolSection", {})
            status = ps.get("statusModule", {}).get("overallStatus", "")
            if status not in ("RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"):
                continue
            date_str = ps.get("statusModule", {}).get("primaryCompletionDateStruct", {}).get("date", "")
            if not date_str:
                continue
            try:
                if len(date_str) == 7:
                    d = datetime.strptime(date_str[:7] + "-15", "%Y-%m-%d").date()
                else:
                    d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            delta = (d - today).days
            if 0 < delta <= 365:
                upcoming.append({
                    "nct": ps.get("identificationModule", {}).get("nctId", ""),
                    "date": date_str[:10],
                    "days_to": delta,
                    "phases": "|".join(ps.get("designModule", {}).get("phases", [])),
                    "status": ps.get("statusModule", {}).get("overallStatus", ""),
                })
        upcoming.sort(key=lambda x: x["days_to"])
        return upcoming
    except Exception as e:
        LOG.debug("ct.gov fail %s: %s", sponsor_name, e)
        return []


def load_adcom_future(sha: str) -> dict[str, list[dict]]:
    p = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    if not p.exists():
        return {}
    today = datetime.now(timezone.utc).date()
    from collections import defaultdict
    out = defaultdict(list)
    with p.open() as f:
        for r in csv.DictReader(f):
            md = (r.get("meeting_date") or "").strip()
            if not md:
                continue
            try:
                d = datetime.strptime(md, "%Y-%m-%d").date()
            except Exception:
                continue
            if d > today:
                tk = (r.get("mapped_ticker") or "").strip()
                if tk:
                    out[tk].append({"meeting_date": md, "days_to": (d - today).days, "committee": r.get("committee", "")})
    return out


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    cands_v2 = list(csv.DictReader((DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_v2_{today_str}.csv").open()))
    LOG.info("candidates v2: %d", len(cands_v2))

    adcom_future = load_adcom_future(sha)

    rows_out = []
    dist = Counter()
    sample_field_absence = []

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}) as client:
        for i, c in enumerate(cands_v2, 1):
            tk = (c.get("ticker") or "").strip()
            nm = (c.get("name") or "").strip()

            # 자문위 미래 매치 (Ticker 기준)
            adcom_hits = adcom_future.get(tk, [])
            adcom_note = ""
            if adcom_hits:
                first = min(adcom_hits, key=lambda x: x["days_to"])
                adcom_note = f"자문위 회의 D-{first['days_to']} ({first['meeting_date']} · {first['committee']})"

            # CT.gov 스폰서 미래 primary_completion
            ct_hits = fetch_upcoming(client, nm) if nm else []
            time.sleep(0.4)

            # A 상태 판정: adcom OR ct_hits
            if adcom_hits or ct_hits:
                new_state = "A"
                if ct_hits:
                    ct_first = ct_hits[0]
                    ct_note = f"CT.gov {ct_first['nct']} 완료 예정 D-{ct_first['days_to']} ({ct_first['date']} · {ct_first['phases']})"
                else:
                    ct_note = ""
                note = " || ".join(filter(None, [adcom_note, ct_note]))
            else:
                # 기존 상태 유지 (B/C)
                new_state = c.get("time_state", "C")
                note = c.get("state_note", "")

            dist[new_state] += 1
            if not ct_hits and nm:
                sample_field_absence.append(nm[:40])

            row = dict(c)
            row["time_state_v50"] = new_state
            row["state_note_v50"] = note
            row["ctgov_upcoming_count"] = len(ct_hits)
            row["adcom_upcoming_count"] = len(adcom_hits)
            rows_out.append(row)

            if i % 10 == 0:
                LOG.info("progress %d/%d · A=%d B=%d C=%d", i, len(cands_v2), dist["A"], dist["B"], dist["C"])

    out_path = DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_v3_{today_str}.csv"
    fields = list(rows_out[0].keys()) if rows_out else []
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    summary = {
        "git_sha": sha, "csv_path": str(out_path),
        "input": len(cands_v2), "output": len(rows_out),
        "distribution": dict(dist),
        "sample_field_absence_top10": sample_field_absence[:10],
        "note": "A 상태 = CT.gov 활성 임상 primary_completion 미래 OR 자문위 회의 미래 · CT.gov leadSponsor 검색 실측",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
