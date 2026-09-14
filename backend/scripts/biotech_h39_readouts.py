"""WP39 · 임상 결과 발표 이벤트 풀 (탐색 · 백그라운드).

대상 CIK:
- H3 target 249 (h3_targets_v2 sic_biotech=True) + WP37(a) 스폰서 상장 32 (h6_membership 소속) · 중복 제거

소스:
- EFTS forms=8-K · dateRange 2019-01-01~2026-09-01 · ciks=<대상 CIK>
- 각 filing 완전 텍스트 (Archives .txt) 다운로드
- Item 7.01 / 8.01 / 2.02 본문 + EX-99 보도자료

키워드 (사전 커밋 · 대소문자 무시):
  topline · top-line · primary endpoint · phase 3 results · phase 2 results · pivotal

방향 태그 (사전 커밋):
- 양성: "met" · "statistically significant" · "primary endpoint achieved"
- 음성: "did not meet" · "failed" · "did not achieve"
- 미분류: 키워드 매치되나 방향 확정 불가

시각 (사전 커밋):
- 8-K acceptance datetime (ET · Filing Header) 파싱
- 장전 (< 09:30 ET) → 당일 D
- 장중/장후 (>= 09:30 ET) → 다음 거래일 D

산출: h_readout_events_{sha}.csv
검증: 표본 20건 수동 대조 (별건)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL, SecBlockedError

import csv
import json
import logging
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h39_readouts")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
CACHE_DIR = DATA_DIR / "h39_readout_cache"
CACHE_DIR.mkdir(exist_ok=True)
CHECKPOINT = DATA_DIR / "h39_readouts_checkpoint.json"

EFTS = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

START = "2019-01-01"
END = "2026-09-01"

KEYWORDS = [
    r"\btopline\b", r"\btop-line\b",
    r"\bprimary endpoint\b",
    r"\bphase 3 results\b", r"\bphase 3 topline\b",
    r"\bphase 2 results\b", r"\bphase 2 topline\b",
    r"\bpivotal\b",
]
KW_RE = re.compile("|".join(KEYWORDS), re.IGNORECASE)

POS_RE = re.compile(r"\b(?:met (?:the |its )?primary endpoint|statistically significant|primary endpoint achieved|met all primary|met the co-primary)\b", re.IGNORECASE)
NEG_RE = re.compile(r"\b(?:did not meet|failed to meet|did not achieve|missed (?:the |its )?primary endpoint|failed the primary|not statistically significant)\b", re.IGNORECASE)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_cik_set(sha: str) -> set[str]:
    """H3 targets biotech + h6 membership 상장 소속 CIK."""
    out = set()
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("sic_biotech") == "True":
                cik = (r.get("target_cik") or "").zfill(10)
                if cik and cik != "0000000000":
                    out.add(cik)
    # h6 membership 소속 티커 → h3_targets_v2 매핑 (ticker → cik)
    tk2cik = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            t = (r.get("ticker") or "").strip()
            c = (r.get("target_cik") or "").zfill(10)
            if t and c:
                tk2cik[t] = c
    with (DATA_DIR / f"h6_membership_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                t = t.strip()
                if t and t in tk2cik:
                    out.add(tk2cik[t])
    return out


def sec_get(client: httpx.Client, url: str, params=None) -> httpx.Response:
    time.sleep(REQ_INTERVAL)
    r = client.get(url, params=params, timeout=30.0)
    if r.status_code == 403:
        raise SecBlockedError(f"403 · {url[:80]}")
    return r


def efts_8k_for_cik(client: httpx.Client, cik10: str) -> list[dict]:
    """EFTS forms=8-K · ciks=<10자리 zero-padded> · dateRange · WP39-2 수정."""
    hits = []
    page_from = 0
    while True:
        r = sec_get(client, EFTS, params={
            "forms": "8-K",
            "dateRange": "custom",
            "startdt": START,
            "enddt": END,
            "ciks": cik10,  # zero-padded 10자리 (EFTS 요구 형식)
            "from": page_from,
            "size": 100,
        })
        if r.status_code != 200:
            break
        j = r.json()
        hh = j.get("hits", {}).get("hits", [])
        if not hh:
            break
        hits.extend(hh)
        total = j.get("hits", {}).get("total", {}).get("value", 0)
        page_from += len(hh)
        if page_from >= total or len(hh) < 100:
            break
    return hits


def fetch_txt_cached(client: httpx.Client, cik10: str, accession: str) -> str | None:
    cache = CACHE_DIR / f"{accession}.txt"
    if cache.exists():
        return cache.read_text(errors="ignore")
    acc_nodash = accession.replace("-", "")
    url = f"{ARCHIVES}/{int(cik10)}/{acc_nodash}/{accession}.txt"
    try:
        r = sec_get(client, url)
        if r.status_code != 200:
            return None
        text = r.text
        # 크기 제한 (5MB · 대용량 8-K 회피)
        if len(text) > 5_000_000:
            text = text[:5_000_000]
        cache.write_text(text)
        return text
    except SecBlockedError:
        raise
    except Exception:
        return None


def classify_direction(body: str) -> str:
    if not body:
        return "unclassified"
    if POS_RE.search(body):
        if NEG_RE.search(body):
            return "mixed"
        return "positive"
    if NEG_RE.search(body):
        return "negative"
    return "unclassified"


def extract_matched_keywords(body: str) -> list[str]:
    if not body:
        return []
    hits = set()
    for kw_pat in KEYWORDS:
        for m in re.finditer(kw_pat, body, re.IGNORECASE):
            hits.add(kw_pat.strip(r"\b"))
    return sorted(hits)


def parse_accept_dt(text: str) -> str | None:
    """8-K SGML 헤더의 ACCEPTANCE-DATETIME."""
    if not text:
        return None
    m = re.search(r"ACCEPTANCE-DATETIME[>\s]+(\d{14})", text)
    if not m:
        return None
    s = m.group(1)
    try:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:14]}"
    except Exception:
        return None


def d_day_from_accept(accept_iso: str) -> tuple[str, str]:
    """장전 (< 09:30 ET) → 당일 D · 장중/장후 → 다음 캘린더일 D."""
    try:
        dt = datetime.fromisoformat(accept_iso)
    except Exception:
        return ("", "unknown")
    session = "premarket" if dt.hour < 9 or (dt.hour == 9 and dt.minute < 30) else ("intraday_or_after" if dt.hour < 16 or (dt.hour == 16 and dt.minute == 0) else "after_hours")
    # 단순화: <09:30 → 당일 · >=09:30 → 다음 캘린더일 (거래일 필터 별건)
    d = dt.date()
    if session == "premarket":
        d_day = d.strftime("%Y-%m-%d")
    else:
        d_day = (d + timedelta(days=1)).strftime("%Y-%m-%d")
    return (d_day, session)


def load_ck() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"processed_ciks": [], "events": [], "stats": {"accs_seen": 0, "kw_match": 0}}


def save_ck(ck: dict):
    CHECKPOINT.write_text(json.dumps(ck, ensure_ascii=False, indent=2))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    ciks = load_cik_set(sha)
    LOG.info("target CIKs: %d", len(ciks))

    # 티커 매핑 (리포트용)
    cik2tk = {}
    with (DATA_DIR / f"h3_targets_v2_{sha}.csv").open() as f:
        for r in csv.DictReader(f):
            c = (r.get("target_cik") or "").zfill(10)
            t = (r.get("ticker") or "").strip()
            if c and t:
                cik2tk[c] = t

    ck = load_ck()
    processed = set(ck.get("processed_ciks", []))
    events = ck.get("events", [])
    stats = ck.get("stats", {"accs_seen": 0, "kw_match": 0})

    try:
        with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}, timeout=30.0) as client:
            for i, cik in enumerate(sorted(ciks), 1):
                if cik in processed:
                    continue
                hits = efts_8k_for_cik(client, cik)
                if i % 20 == 0:
                    LOG.info("progress %d/%d · events %d · accs_seen %d · kw %d",
                             i, len(ciks), len(events), stats["accs_seen"], stats["kw_match"])
                for h in hits:
                    src = h.get("_source", {})
                    acc = src.get("adsh", "")
                    items = src.get("items", "")
                    # Item 7.01/8.01/2.02 만 대상
                    wanted_items = ("2.02", "7.01", "8.01")
                    if items and not any(it in items for it in wanted_items):
                        continue
                    stats["accs_seen"] += 1
                    body = fetch_txt_cached(client, cik, acc)
                    if not body:
                        continue
                    if not KW_RE.search(body):
                        continue
                    stats["kw_match"] += 1
                    direction = classify_direction(body)
                    matched = extract_matched_keywords(body)
                    accept = parse_accept_dt(body)
                    d_day, session = d_day_from_accept(accept) if accept else ("", "unknown")
                    events.append({
                        "cik": cik,
                        "ticker": cik2tk.get(cik, ""),
                        "accession": acc,
                        "file_date": src.get("file_date", ""),
                        "accept_datetime_et": accept or "",
                        "session_bucket": session,
                        "d_day": d_day,
                        "items": items,
                        "direction": direction,
                        "matched_keywords": "|".join(matched),
                    })
                processed.add(cik)
                ck["processed_ciks"] = sorted(processed)
                ck["events"] = events
                ck["stats"] = stats
                if i % 10 == 0:
                    save_ck(ck)
    except SecBlockedError as e:
        LOG.error("BLOCKED · %s · checkpoint saved", e)
        save_ck(ck)
        sys.exit(2)

    save_ck(ck)
    out_path = DATA_DIR / f"h_readout_events_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(events[0].keys()) if events else ["cik"])
        if events:
            w.writeheader()
            w.writerows(events)

    dir_dist = defaultdict(int)
    for e in events:
        dir_dist[e["direction"]] += 1
    per_cik = defaultdict(int)
    for e in events:
        per_cik[e["cik"]] += 1

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "target_ciks": len(ciks),
        "processed_ciks": len(processed),
        "accs_seen": stats["accs_seen"],
        "kw_matches": stats["kw_match"],
        "readout_events_total": len(events),
        "direction_distribution": dict(dir_dist),
        "unique_ciks_with_events": len(per_cik),
        "events_per_cik_median": sorted(per_cik.values())[len(per_cik)//2] if per_cik else 0,
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
