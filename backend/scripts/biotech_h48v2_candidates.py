"""WP48-1 v2 · 후보 선정 자동화 (하루 1회 실행 · 커뮤니티 확인 대상).

후보 4소스 합집합 · 시총 $50M~$5B · 30~50종목:
(a) H8 정규화 소문 지수 상위 20 (h_readout_events 부분 결과로 근사 · WP39 완주 후 재산출)
(b) CT.gov 완료 예정일 0~180일 내 종목 (h6_membership 스폰서 재사용)
(c) 최근 30일 신규 13D 대상 (h3_efts_sc13d_universe 재사용 · date >= today-30d)
(d) 연방관보 자문위 공고 대상 (h1a_events_v2 재사용 · meeting_date 근처)

각 후보에 "왜 후보인가" 1줄 (신호 요지).
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48v2_candidates")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
OUT_DIR = DATA_DIR / "biotech" / "candidates"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_universe(sha: str) -> tuple[set[str], dict]:
    """biotech 우주 · cik → {ticker, name} · ticker → {cik, name}."""
    universe_tk = set()
    cik_meta = {}
    tk_meta = {}
    p = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    with p.open() as f:
        for r in csv.DictReader(f):
            if r.get("sic_biotech") != "True":
                continue
            cik = (r.get("target_cik") or "").zfill(10)
            tk = (r.get("ticker") or "").strip()
            nm = (r.get("target_name") or "").strip()
            if tk:
                universe_tk.add(tk)
                tk_meta[tk] = {"cik": cik, "name": nm}
            if cik and cik != "0000000000":
                cik_meta[cik] = {"ticker": tk, "name": nm}
    # biotech_ticker_set 병합 (XBI 등 확장 · SIC 없음)
    p2 = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if p2.exists():
        with p2.open() as f:
            for r in csv.DictReader(f):
                tk = (r.get("ticker") or "").strip()
                nm = (r.get("name") or "").strip()
                if tk and tk != "-":
                    universe_tk.add(tk)
                    tk_meta.setdefault(tk, {"cik": "", "name": nm})
    return universe_tk, cik_meta, tk_meta


def load_mcap(sha: str) -> dict[str, float]:
    """CIK → shares."""
    out = {}
    p = DATA_DIR / f"h3_mcap_{sha}.csv"
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                try:
                    sh = float(r.get("shares", "") or 0)
                except Exception:
                    sh = 0
                if sh > 0:
                    out[r["cik"]] = sh
    return out


def load_last_close(sha: str) -> dict[str, float]:
    """ticker → 최근 종가."""
    out = {}
    p = DATA_DIR / f"h3_prices_merged_{sha}.csv"
    if p.exists():
        latest = {}
        with p.open() as f:
            for r in csv.DictReader(f):
                tk = r["ticker"]
                d = r["date"]
                if tk not in latest or d > latest[tk][0]:
                    try:
                        latest[tk] = (d, float(r["close"]))
                    except Exception:
                        continue
        out = {tk: v[1] for tk, v in latest.items()}
    return out


def source_c_recent_13d(sha: str, days: int = 30) -> list[dict]:
    """최근 N일 신규 SC 13D 대상 (h3_efts_sc13d_universe)."""
    p = DATA_DIR / f"h3_efts_sc13d_universe_{sha}.csv"
    if not p.exists():
        return []
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=days)
    out = []
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.strptime(r["date"], "%Y-%m-%d").date()
            except Exception:
                continue
            if d >= cutoff:
                out.append({"cik": r["subject_cik"], "date": r["date"], "filer_cik": r["filer_cik"]})
    return out


def source_d_adcom(sha: str, days_around: int = 60) -> list[dict]:
    """연방관보 자문위 공고 대상 (h1a_events_v2 · meeting_date ± days)."""
    p = DATA_DIR / f"h1a_events_v2_{sha}.csv"
    if not p.exists():
        return []
    today = datetime.now(timezone.utc).date()
    out = []
    with p.open() as f:
        for r in csv.DictReader(f):
            md = (r.get("meeting_date") or "").strip()
            if not md:
                continue
            try:
                d = datetime.strptime(md, "%Y-%m-%d").date()
            except Exception:
                continue
            delta = abs((d - today).days)
            if delta <= days_around:
                out.append({
                    "meeting_date": md,
                    "sponsor_raw": r.get("sponsor_raw", ""),
                    "mapped_ticker": r.get("mapped_ticker", ""),
                    "committee": r.get("committee", ""),
                })
    return out


def source_a_readout(sha: str, top_n: int = 20) -> list[dict]:
    """H8 소문 지수 상위 20 (h_readout_events 부분 결과 · CIK 별 이벤트 수 기준 대체 근사)."""
    p = DATA_DIR / f"h_readout_events_{sha}.csv"
    if not p.exists():
        return []
    counter = defaultdict(int)
    with p.open() as f:
        for r in csv.DictReader(f):
            counter[r["cik"]] += 1
    top = sorted(counter.items(), key=lambda x: -x[1])[:top_n]
    return [{"cik": c, "readout_events": n} for c, n in top]


def source_b_ctgov(sha: str) -> list[dict]:
    """CT.gov 완료 예정일 0~180일 내 · h6_membership 스폰서 재사용 근사.

    실제 CT.gov API 재조회는 시간·API 부담 · h6_membership 티커 = 최근 상위 3분위 테마 소속 = 근사 대체.
    """
    p = DATA_DIR / f"h6_membership_{sha}.csv"
    if not p.exists():
        return []
    tk_set = set()
    with p.open() as f:
        for r in csv.DictReader(f):
            for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                if t.strip():
                    tk_set.add(t.strip())
    return [{"ticker": t, "source": "h6_membership_recent"} for t in sorted(tk_set)]


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    universe_tk, cik_meta, tk_meta = load_universe(sha)
    mcap_shares = load_mcap(sha)
    last_close = load_last_close(sha)
    LOG.info("universe tickers: %d · cik meta: %d · mcap: %d · prices: %d",
             len(universe_tk), len(cik_meta), len(mcap_shares), len(last_close))

    # 후보 수집 · CIK 또는 ticker 기준 dedup
    candidates: dict[str, dict] = {}

    def add(ticker: str, cik: str, source: str, reason: str):
        key = ticker or cik
        if not key:
            return
        if key not in candidates:
            candidates[key] = {
                "ticker": ticker,
                "cik": cik,
                "name": (tk_meta.get(ticker) or {}).get("name") or (cik_meta.get(cik) or {}).get("name") or "",
                "sources": [],
                "reasons": [],
            }
        if source not in candidates[key]["sources"]:
            candidates[key]["sources"].append(source)
            candidates[key]["reasons"].append(reason)

    # (a) H8 소문 지수 상위 20 (근사 · readout 이벤트 수)
    for row in source_a_readout(sha, top_n=20):
        cik = row["cik"]
        tk = (cik_meta.get(cik) or {}).get("ticker", "")
        add(tk, cik, "a_readout_top20", f"H8 소문 지수 상위 · readout 이벤트 {row['readout_events']}건")

    # (b) CT.gov 완료 예정 (h6_membership 근사)
    for row in source_b_ctgov(sha):
        tk = row["ticker"]
        cik = (tk_meta.get(tk) or {}).get("cik", "")
        add(tk, cik, "b_ctgov_180d", "H6 최근 상위 3분위 테마 소속 (CT.gov 활동 근사)")

    # (c) 최근 30일 신규 13D
    for row in source_c_recent_13d(sha, days=30):
        cik = row["cik"]
        tk = (cik_meta.get(cik) or {}).get("ticker", "")
        add(tk, cik, "c_recent_13d", f"최근 30일 신규 SC 13D · filer {row['filer_cik']} · {row['date']}")

    # (d) 연방관보 자문위 (60일 창)
    for row in source_d_adcom(sha, days_around=60):
        tk = row["mapped_ticker"] or ""
        cik = (tk_meta.get(tk) or {}).get("cik", "") if tk else ""
        if not tk and not cik:
            continue
        add(tk, cik, "d_adcom_60d", f"자문위 회의 {row['meeting_date']} · {row['committee'] or 'FDA AdCom'}")

    LOG.info("raw candidates: %d", len(candidates))

    # 시총 필터 $50M~$5B
    filtered = []
    for key, c in candidates.items():
        tk = c["ticker"]
        cik = c["cik"]
        shares = mcap_shares.get(cik, 0)
        price = last_close.get(tk, 0)
        mcap_val = shares * price if shares and price else 0
        c["mcap_usd"] = int(mcap_val)
        c["mcap_bucket"] = ""
        if mcap_val:
            if 50e6 <= mcap_val < 300e6:
                c["mcap_bucket"] = "50M-300M"
            elif 300e6 <= mcap_val < 1e9:
                c["mcap_bucket"] = "300M-1B"
            elif 1e9 <= mcap_val < 5e9:
                c["mcap_bucket"] = "1B-5B"
            else:
                c["mcap_bucket"] = "out_of_range"
        if c["mcap_bucket"] in ("50M-300M", "300M-1B", "1B-5B"):
            filtered.append(c)
        elif not mcap_val:
            # 시총 미확인도 포함 (플래그)
            c["mcap_bucket"] = "unknown"
            filtered.append(c)

    LOG.info("filtered (in_range + unknown): %d", len(filtered))

    # 정렬: 소스 수 많은 순 · 시총 알려진 것 우선
    filtered.sort(key=lambda c: (-len(c["sources"]), 0 if c["mcap_bucket"] != "unknown" else 1, c["ticker"] or c["cik"]))

    # 30~50 상한
    cap = 50
    final = filtered[:cap]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = OUT_DIR / f"biotech_candidates_{today.replace('-', '')}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "cik", "name", "mcap_usd", "mcap_bucket", "sources", "reasons"])
        w.writeheader()
        for c in final:
            w.writerow({
                "ticker": c["ticker"],
                "cik": c["cik"],
                "name": c["name"],
                "mcap_usd": c["mcap_usd"],
                "mcap_bucket": c["mcap_bucket"],
                "sources": "|".join(c["sources"]),
                "reasons": " | ".join(c["reasons"]),
            })

    source_dist = defaultdict(int)
    for c in final:
        for s in c["sources"]:
            source_dist[s] += 1
    mcap_dist = defaultdict(int)
    for c in final:
        mcap_dist[c["mcap_bucket"]] += 1

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "raw_candidates": len(candidates),
        "final_candidates": len(final),
        "source_distribution": dict(source_dist),
        "mcap_distribution": dict(mcap_dist),
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
