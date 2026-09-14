"""WP49 · 시간 상태 분리 (A 뉴스예정 / B 뉴스직후 / C 해당없음).

- A: 미래 날짜 존재 (CT.gov primary_completion_date > today OR 자문위 회의일 > today)
- B: 지난 30일 내 8-K 결과 발표 (WP39)
- C: 그 외

비바이오 제외 (SIC 2834/2836 재확인) · 빈 티커 제거.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h49_time_state")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_biotech_ciks(sha: str) -> set[str]:
    """SIC 2834/2836 확정 CIK 집합."""
    out = set()
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("sic_biotech") == "True":
                cik = (r.get("target_cik") or "").zfill(10)
                if cik and cik != "0000000000":
                    out.add(cik)
    # EFTS subject sic 2834/2836
    ep = DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv"
    if ep.exists():
        with ep.open() as f:
            for r in csv.DictReader(f):
                if r.get("sic") in ("2834", "2836"):
                    out.add(r["subject_cik"])
    return out


def load_readout_events(sha: str) -> dict[str, list[dict]]:
    """CIK → readout events · 최근 30일 (B 상태 판정)."""
    cp = DATA_DIR / "h39_readouts_checkpoint.json"
    if not cp.exists():
        return {}
    events = json.loads(cp.read_text()).get("events", [])
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=30)
    out = defaultdict(list)
    for e in events:
        dd = e.get("d_day", "")
        try:
            d = datetime.strptime(dd, "%Y-%m-%d").date()
        except Exception:
            continue
        if cutoff <= d <= today:
            out[e["cik"].zfill(10)].append({
                "d_day": dd,
                "days_since": (today - d).days,
                "direction": e.get("direction", ""),
                "kw": e.get("matched_keywords", ""),
            })
    return out


def load_adcom_future(sha: str) -> dict[str, list[dict]]:
    """자문위 회의일 > today · sponsor_raw 로 매핑 (mapped_ticker 부족 시 skip)."""
    p = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    if not p.exists():
        return {}
    today = datetime.now(timezone.utc).date()
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

    cands_path = DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_{today_str}.csv"
    cands = list(csv.DictReader(cands_path.open()))
    LOG.info("candidates: %d", len(cands))

    biotech_ciks = load_biotech_ciks(sha)
    readouts_b = load_readout_events(sha)
    adcom_future = load_adcom_future(sha)
    LOG.info("biotech CIKs: %d · readouts B: %d · adcom future: %d",
             len(biotech_ciks), len(readouts_b), len(adcom_future))

    out_rows = []
    dist = defaultdict(int)

    for c in cands:
        tk = (c.get("ticker") or "").strip()
        cik = (c.get("cik") or "").zfill(10)

        # 빈 티커 제거
        if not tk:
            dist["dropped_empty_ticker"] += 1
            continue

        # 비바이오 제외 (biotech_ticker_set 만 편입된 종목 = SIC 확인 안됨 → 확인 실패 시 flag)
        if cik and cik != "0000000000" and cik not in biotech_ciks:
            dist["dropped_non_biotech_sic"] += 1
            continue

        # 시간 상태 판정
        time_state = "C"
        state_note = ""
        b_events = readouts_b.get(cik, [])
        a_adcom = adcom_future.get(tk, [])

        # reasons 안 "결과 발표 D-day" 는 과거 → B 상태로 재분류
        reasons = c.get("reasons", "")
        past_readout_from_reasons = []
        for m in re.finditer(r"결과 발표 D-day (\d{4}-\d{2}-\d{2}) · dir=(\S+)", reasons):
            d_str, direction = m.group(1), m.group(2)
            try:
                d = datetime.strptime(d_str, "%Y-%m-%d").date()
                today = datetime.now(timezone.utc).date()
                if 0 <= (today - d).days <= 30:
                    past_readout_from_reasons.append({"d_day": d_str, "days_since": (today - d).days, "direction": direction, "kw": ""})
            except Exception:
                pass
        b_all = b_events + past_readout_from_reasons

        if a_adcom:
            time_state = "A"
            first = min(a_adcom, key=lambda x: x["days_to"])
            state_note = f"자문위 회의 예정 D-{first['days_to']} ({first['meeting_date']} · {first['committee'] or 'FDA'})"
        elif b_all:
            time_state = "B"
            first = min(b_all, key=lambda x: x["days_since"])
            state_note = f"발표 후 {first['days_since']}일 ({first['d_day']} · dir={first['direction']})"

        dist[f"state_{time_state}"] += 1
        c["time_state"] = time_state
        c["state_note"] = state_note
        out_rows.append(c)

    out_path = DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_v2_{today_str}.csv"
    fields = list(cands[0].keys()) + ["time_state", "state_note"]
    fields = list(dict.fromkeys(fields))
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            for k in fields:
                r.setdefault(k, "")
            w.writerow(r)

    summary = {"git_sha": sha, "csv_path": str(out_path),
               "input_candidates": len(cands),
               "output_candidates": len(out_rows),
               "distribution": dict(dist)}
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
