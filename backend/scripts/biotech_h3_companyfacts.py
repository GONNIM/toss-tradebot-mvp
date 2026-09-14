"""WP1-B bg2 · companyfacts → 발행주식수 (이벤트일 이하 최근접) → h3_mcap.

용도:
- h3_targets_v2 sic_biotech=True target CIK 각각 /api/xbrl/companyfacts/CIK.json
- dei:EntityCommonStockSharesOutstanding | us-gaap:CommonStockSharesOutstanding 시계열
- 이벤트일 이하 최근접 asof → shares · 원장 target 별 저장
- h3_events (B98) 로부터 이벤트 목록 확보 · target 별 max event_date 기준
- 산출: h3_mcap_{sha}.csv (cik · asof · shares · source_concept)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import (
    SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError,
)

import csv
import json
import logging
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h3_companyfacts")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CHECKPOINT = DATA_DIR / "h3_companyfacts_checkpoint.json"

CF = "https://data.sec.gov/api/xbrl/companyfacts"


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


def load_targets(sha: str) -> list[dict]:
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    with p.open() as f:
        return [r for r in csv.DictReader(f) if r.get("sic_biotech") == "True"]


def load_events(sha: str) -> dict[str, str]:
    """target_cik → max event_date (여러 이벤트 중 마지막 · asof 기준으로 사용)."""
    p = DATA_DIR / f"h3_events_{sha}.csv"
    out: dict[str, str] = {}
    if not p.exists():
        return out
    with p.open() as f:
        for r in csv.DictReader(f):
            t = r.get("target_cik", "")
            d = r.get("event_date", "")
            if not t or not d:
                continue
            if t not in out or d > out[t]:
                out[t] = d
    return out


def sec_get(client: httpx.Client, url: str) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def extract_shares_series(companyfacts: dict) -> list[tuple[str, float, str]]:
    """companyfacts JSON → [(end_date, shares, concept)] 시계열 (오름차순)."""
    facts = companyfacts.get("facts", {}) or {}
    candidates = []
    for ns, key in [
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ]:
        node = facts.get(ns, {}).get(key)
        if not node:
            continue
        units = node.get("units", {}).get("shares", [])
        for u in units:
            end = u.get("end", "")
            val = u.get("val")
            if not end or val is None:
                continue
            try:
                candidates.append((end, float(val), f"{ns}:{key}"))
            except Exception:
                continue
    candidates.sort(key=lambda x: x[0])
    return candidates


def asof_shares(series: list[tuple[str, float, str]], asof: str) -> tuple[str, float, str] | None:
    """asof 이하 최근접 값."""
    best = None
    for e, v, c in series:
        if e <= asof:
            best = (e, v, c)
        else:
            break
    return best


def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed_ciks": [], "rows": [], "stats": {"cf_ok": 0, "cf_no_shares": 0, "cf_fail": 0}}


def save_ck(ck: dict):
    CHECKPOINT.write_text(json.dumps(ck, ensure_ascii=False, indent=2))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    targets = load_targets(sha)
    events = load_events(sha)
    LOG.info("bio targets: %d · event-covered: %d", len(targets), len(events))

    ck = load_checkpoint()
    processed = set(ck.get("processed_ciks", []))
    rows = ck.get("rows", [])
    stats = ck.get("stats", {"cf_ok": 0, "cf_no_shares": 0, "cf_fail": 0})

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for t in targets:
                cik = t.get("target_cik", "").zfill(10)
                if cik == "0000000000":
                    continue
                if cik in processed:
                    continue
                # asof: event_date max · 부재 시 오늘
                asof = events.get(cik.lstrip("0")) or events.get(cik) or "2026-09-01"
                url = f"{CF}/CIK{cik}.json"
                try:
                    r = sec_get(client, url)
                except SecBlockedError:
                    raise
                if r.status_code != 200:
                    stats["cf_fail"] = stats.get("cf_fail", 0) + 1
                    processed.add(cik)
                    continue
                try:
                    data = r.json()
                except Exception:
                    stats["cf_fail"] = stats.get("cf_fail", 0) + 1
                    processed.add(cik)
                    continue
                series = extract_shares_series(data)
                if not series:
                    stats["cf_no_shares"] = stats.get("cf_no_shares", 0) + 1
                    rows.append({"cik": cik, "asof": asof, "shares": "", "source_concept": ""})
                else:
                    best = asof_shares(series, asof)
                    if best:
                        end, val, cc = best
                        stats["cf_ok"] = stats.get("cf_ok", 0) + 1
                        rows.append({"cik": cik, "asof": asof, "shares_asof_date": end, "shares": val, "source_concept": cc})
                    else:
                        stats["cf_no_shares"] = stats.get("cf_no_shares", 0) + 1
                        rows.append({"cik": cik, "asof": asof, "shares": "", "source_concept": ""})
                processed.add(cik)
                if len(processed) % 25 == 0:
                    ck["processed_ciks"] = sorted(processed)
                    ck["rows"] = rows
                    ck["stats"] = stats
                    save_ck(ck)
                    LOG.info("progress %d/%d · ok=%d fail=%d no_shares=%d",
                             len(processed), len(targets), stats.get("cf_ok", 0),
                             stats.get("cf_fail", 0), stats.get("cf_no_shares", 0))
    except SecBlockedError as e:
        LOG.error("SEC BLOCKED · %s", e)
        save_ck(ck)
        sys.exit(2)

    out_path = DATA_DIR / f"h3_mcap_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cik", "asof", "shares_asof_date", "shares", "source_concept"])
        w.writeheader()
        for r in rows:
            if "shares_asof_date" not in r:
                r["shares_asof_date"] = ""
            w.writerow(r)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "targets_total": len(targets),
        "processed": len(processed),
        "cf_ok": stats.get("cf_ok", 0),
        "cf_no_shares": stats.get("cf_no_shares", 0),
        "cf_fail": stats.get("cf_fail", 0),
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
