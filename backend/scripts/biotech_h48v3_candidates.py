"""WP48v2 정비 v3 · 후보 선정 (모든 소스 활성 · Tiingo 우주 × SIC · 왜 후보 구체 문장).

소스 (사전 고정):
(a) WP39 결과 발표 예정/최근: h_readout_events · 최근 90일 이내 or 예정 CT.gov
(b) CT.gov 완료 예정일 0~180일 · h6_membership 스폰서 재사용 (근사 · 개선 시 CT.gov API 직접)
(c) 최근 30일 신규 13D · h3_efts_sc13d_universe date >= today-30d
(d) 연방관보 자문위 공고 · h1a_events_v2 meeting_date ± 60일

CIK → ticker 매핑 확장:
- h3_targets_v2 sic_biotech=True (기존)
- h3_efts_sc13d subject_cik 의 sic 캐시 (h3_efts_sc13d_universe 는 subject sic 이미 확보)
- h41_filer_classification (filer 대상 · subject 아님 · 무관)
- SEC company_tickers.json (모든 CIK → ticker · SIC 미확인 시 companyfacts 조회 필요 · 시간상 SEC 매치만)

시총 필터: $50M~$5B (companyfacts shares × 최근 종가 · h3_mcap + h3_prices_merged)
  · P3a-2 ⑤ · h3_prices_merged 가 없으면 (서버) 일일 시총 단계 결과 <RUNTIME>/mcap_display.json (전날 [8/10] · 주식수 × IEX 종가) 로 구간을 매김
  · P3a-3 ① (PRD v0.7 6절 (가)) · 5B 초과 제외 기록 <RUNTIME>/mcap/over_5b_excluded.json (종목 · 시총 · 확인 날짜)
    마지막 확인일부터 30일 동안은 시총이 unknown 이어도 제외 유지 · 30일이 지나고 새 값이 없으면 다시 판정 (unknown)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import os

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48v3_candidates")

# WP69-3g · 경로는 공용 헬퍼 _biotech_paths 사용 (하드코딩 금지 pytest 검증)
from backend.scripts import _biotech_paths as _P
PROJECT_ROOT = _P.PROJECT_ROOT
DATA_DIR = _P.DATA_DIR
RUNTIME_DIR = _P.RUNTIME_DIR
FALLBACK_DIR = _P.DATA_DIR_DOCS

OUT_DIR = (RUNTIME_DIR / "candidates") if RUNTIME_DIR else (DATA_DIR / "biotech" / "candidates")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _search_paths(name: str) -> list[Path]:
    """RUNTIME > docs > backend/data 순회 · WP69-3e."""
    paths: list[Path] = []
    if RUNTIME_DIR is not None:
        paths.append(RUNTIME_DIR / name)
    paths.append(FALLBACK_DIR / name)
    paths.append(DATA_DIR / name)
    return paths


def _find(name: str) -> Path | None:
    for p in _search_paths(name):
        if p.exists():
            return p
    return None


def _find_glob(pattern: str) -> Path | None:
    """RUNTIME > docs > backend/data 순 · 첫 매치."""
    if RUNTIME_DIR is not None:
        hits = sorted(RUNTIME_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            return hits[0]
    hits = sorted(FALLBACK_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if hits:
        return hits[0]
    hits = sorted(DATA_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


SEC_BY_CIK: dict[str, dict] = {}   # P3a ⑥ · SEC company_tickers 의 CIK → {ticker, name} (load_cik_ticker_map 이 채움)


def load_cik_ticker_map(sha: str) -> tuple[dict, dict]:
    """CIK ↔ ticker 확장 · biotech SIC 필터.

    반환 (cik_meta, tk_meta):
      cik_meta[cik] = {ticker, name, source}
      tk_meta[ticker] = {cik, name}
    """
    cik_meta = {}
    tk_meta = {}

    # 1) h3_targets_v2 sic_biotech (WP69-3e · _find_glob 조회 · anchor sha 자동)
    tp = _find(f"h3_targets_v2_{sha}.csv") or _find_glob("h3_targets_v2_*.csv")
    if tp is None:
        raise SystemExit("h3_targets_v2 파일 없음 (WP69-3e · docs/plans/biotech/data 로 이식 필요)")
    with tp.open() as f:
        for r in csv.DictReader(f):
            if r.get("sic_biotech") != "True":
                continue
            cik = (r.get("target_cik") or "").zfill(10)
            tk = (r.get("ticker") or "").strip()
            nm = (r.get("target_name") or "").strip()
            if cik and cik != "0000000000":
                cik_meta[cik] = {"ticker": tk, "name": nm, "source": "h3_targets_v2"}
            if tk:
                tk_meta[tk] = {"cik": cik, "name": nm}

    # 2) h3_efts_sc13d_universe · subject SIC 2834/2836
    ep = _find(f"h3_efts_sc13d_universe_{sha}.csv") or _find_glob("h3_efts_sc13d_universe_*.csv")
    if ep is not None and ep.exists():
        with ep.open() as f:
            for r in csv.DictReader(f):
                if r.get("sic") not in ("2834", "2836"):
                    continue
                cik = r["subject_cik"]
                if cik in cik_meta:
                    continue
                cik_meta[cik] = {"ticker": "", "name": "", "source": "efts_sc13d"}

    # 3) SEC company_tickers → 위 CIK 에 ticker 채움 · 이름 채움
    #    P3a ⑥ · 위 두 원천에 없는 CIK (예: INCY 879169 · h3_targets_v2 SIC 8731 · sic_biotech False) 는 SEC_BY_CIK 로 따로 둠
    #    → 다른 원천 (WP39 결과 발표 등) 으로 후보가 된 CIK 의 티커 · 이름을 채움 · cik_meta (우주) 는 넓히지 않음
    SEC_BY_CIK.clear()
    sec_p = _find("sec_company_tickers.json") or (DATA_DIR / "sec_company_tickers.json")
    if sec_p.exists():
        for _, e in json.loads(sec_p.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            nm = str(e.get("title", ""))
            if cik not in SEC_BY_CIK:              # 같은 CIK 의 여러 티커 중 명부 첫 항목
                SEC_BY_CIK[cik] = {"ticker": tk, "name": nm}
            if cik in cik_meta:
                if not cik_meta[cik]["ticker"]:
                    cik_meta[cik]["ticker"] = tk
                if not cik_meta[cik]["name"]:
                    cik_meta[cik]["name"] = nm
            if tk and tk not in tk_meta:
                tk_meta[tk] = {"cik": cik, "name": nm}

    return cik_meta, tk_meta


def load_prices_and_mcap(sha: str) -> tuple[dict, dict]:
    """ticker → 최근 close · cik → shares.

    WP69-3e · h3_prices_merged (47MB · 커밋 제외) 부재 시 "미산정" 진행 (사용자 결정).
    Tiingo fallback 은 후속 (키 부재 시 미산정 표기).
    """
    close: dict = {}
    p = _find(f"h3_prices_merged_{sha}.csv") or _find_glob("h3_prices_merged_*.csv")
    if p is not None and p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                try:
                    c = float(r["close"])
                except Exception:
                    continue
                tk = r["ticker"]
                d = r["date"]
                if tk not in close or d > close[tk][0]:
                    close[tk] = (d, c)
        close = {tk: v[1] for tk, v in close.items()}
    # P3a-2 ⑤ · h3_prices_merged 가 없으면 (서버) close 가 비고, main 이 load_mcap_display() 로 구간을 매김
    shares: dict = {}
    p2 = _find(f"h3_mcap_{sha}.csv") or _find_glob("h3_mcap_*.csv")
    if p2 is not None and p2.exists():
        with p2.open() as f:
            for r in csv.DictReader(f):
                try:
                    sh = float(r.get("shares", "") or 0)
                except Exception:
                    sh = 0
                if sh > 0:
                    shares[r["cik"]] = sh
    return close, shares


def source_a_readout(sha: str, days_recent: int = 90) -> list[dict]:
    """WP39 결과 발표 최근 N일 · checkpoint 우선 (csv 미갱신 대응)."""
    events: list[dict] = []
    cp = _find("h39_readouts_checkpoint.json")
    if cp is not None and cp.exists():
        events = json.loads(cp.read_text()).get("events", [])
    if not events:
        p = _find(f"h_readout_events_{sha}.csv") or _find_glob("h_readout_events_*.csv")
        if p is not None and p.exists():
            with p.open() as f:
                events = list(csv.DictReader(f))
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=days_recent)
    out = []
    for e in events:
        d = (e.get("d_day") or e.get("file_date") or "")[:10]
        try:
            dd = datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:
            continue
        if dd >= cutoff:
            out.append({
                "cik": e.get("cik", "").zfill(10),
                "d_day": d,
                "direction": e.get("direction", ""),
                "keywords": e.get("matched_keywords", ""),
            })
    return out


def source_b_ctgov(sha: str) -> list[dict]:
    p = _find(f"h6_membership_{sha}.csv") or _find_glob("h6_membership_*.csv")
    if p is None or not p.exists():
        return []
    out = []
    with p.open() as f:
        for r in csv.DictReader(f):
            for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                t = t.strip()
                if t:
                    out.append({"ticker": t, "theme": r.get("theme", ""), "year": r.get("year", ""), "quarter": r.get("quarter", "")})
    return out


def source_c_recent_13d(sha: str, days: int = 30) -> list[dict]:
    p = _find(f"h3_efts_sc13d_universe_{sha}.csv") or _find_glob("h3_efts_sc13d_universe_*.csv")
    if p is None or not p.exists():
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
    # filer 유형 병기
    fp = _find("h41_filer_classification.json")
    filer_bucket: dict = {}
    if fp is not None and fp.exists():
        for cik, info in json.loads(fp.read_text()).items():
            filer_bucket[cik] = info.get("bucket", "other")
    for r in out:
        r["filer_bucket"] = filer_bucket.get(r["filer_cik"], "unknown")
    return out


def source_d_adcom(sha: str, days_around: int = 60) -> list[dict]:
    p = _find(f"h1a_events_v2_{sha}.csv") or _find_glob("h1a_events_v2_*.csv")
    if p is None or not p.exists():
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
            if abs((d - today).days) <= days_around:
                out.append({
                    "meeting_date": md,
                    "mapped_ticker": r.get("mapped_ticker", ""),
                    "committee": r.get("committee", ""),
                    "sponsor_raw": r.get("sponsor_raw", ""),
                })
    return out


def load_mcap_display() -> tuple[dict, str | None]:
    """P3a-2 ⑤ · ticker → 시총 (주식수 × 종가) · 일일 시총 단계 [8/10] 결과 mcap_display.json (전날 실행분).

    h3 가격 파일이 없는 서버에서만 쓴다. 파일이 없거나 읽지 못하면 빈 값 (구간 unknown · 기존과 같음).
    """
    p = _find("mcap_display.json")
    if p is None:
        return {}, None
    try:
        j = json.loads(p.read_text())
    except (ValueError, OSError):
        LOG.warning("mcap_display.json 읽기 실패 · 시총 구간 unknown")
        return {}, None
    out = {}
    for tk, r in (j.get("rows") or {}).items():
        try:
            out[tk] = float(r["shares"]) * float(r["close"])
        except (KeyError, TypeError, ValueError):
            continue
    return out, j.get("generated")


OVER5B_KEEP_DAYS = 30   # P3a-3 ① · 마지막 확인일부터 제외 유지 기간 (PRD v0.7 6절 (가))


def mcap_bucket(mcap: float) -> str:
    if 50e6 <= mcap < 300e6:
        return "50M-300M"
    if 300e6 <= mcap < 1e9:
        return "300M-1B"
    if 1e9 <= mcap < 5e9:
        return "1B-5B"
    if mcap >= 5e9:
        return "over_5B_excluded"
    return "unknown"


def _over5b_path() -> Path:
    return _P.out_dir("mcap") / "over_5b_excluded.json"


def load_over5b() -> dict:
    p = _over5b_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("rows") or {}
    except (ValueError, OSError):
        LOG.warning("over_5b_excluded.json 읽기 실패 · 제외 기록 없이 판정")
        return {}


def keep_over5b(rows: list[dict], memo: dict, today: date) -> tuple[dict, list[str], list[str]]:
    """P3a-3 ① · rows (ticker · cik · mcap_usd · mcap_bucket) 를 제자리에서 고치고 (새 기록, 유지 종목, 다시 판정 종목) 반환.

    - 오늘 5B 초과 → 기록 갱신 (시총 · 확인 날짜 = 오늘)
    - 오늘 unknown + 기록 있음 + 확인일부터 30일 이내 → 제외 유지 (구간 over_5B_excluded · 시총 = 기록값)
    - 오늘 unknown + 기록 있음 + 30일 지남 → 기록 삭제 · unknown 그대로 (다시 판정)
    - 오늘 5B 미만 값 → 기록 삭제 (새 값이 우선)
    """
    memo = dict(memo)
    kept, expired = [], []
    for c in rows:
        k = c["ticker"] or c["cik"]
        m = memo.get(k)
        if c["mcap_bucket"] == "over_5B_excluded":
            memo[k] = {"ticker": c["ticker"], "cik": c["cik"], "mcap_usd": int(c["mcap_usd"]), "date": today.isoformat()}
        elif c["mcap_bucket"] == "unknown" and m:
            if (today - date.fromisoformat(m["date"])).days <= OVER5B_KEEP_DAYS:
                c["mcap_bucket"] = "over_5B_excluded"
                c["mcap_usd"] = int(m["mcap_usd"])
                kept.append(k)
            else:
                memo.pop(k)
                expired.append(k)
        elif m:
            memo.pop(k)
    return memo, kept, expired


def main():
    require_secure_logging()
    from backend.scripts._biotech_bootstrap import data_sha
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not _find(f"h3_targets_v2_{sha}.csv"):
        # 여러 폴더 순회 fallback (WP69-3e · docs > backend/data)
        for base in (FALLBACK_DIR, DATA_DIR):
            fb = data_sha(base)
            if fb and (base / f"h3_targets_v2_{fb}.csv").exists():
                LOG.info("git_sha %s 데이터 부재 · %s 에서 data_sha fallback → %s", sha, base.name, fb)
                sha = fb
                break

    cik_meta, tk_meta = load_cik_ticker_map(sha)
    close, shares = load_prices_and_mcap(sha)
    LOG.info("cik_meta: %d · tk_meta: %d · prices: %d · shares: %d",
             len(cik_meta), len(tk_meta), len(close), len(shares))
    display, display_date = ({}, None) if close else load_mcap_display()   # P3a-2 ⑤ · 서버 (h3 가격 없음)
    if not close:
        LOG.info("h3 가격 파일 없음 · 시총 구간 = mcap_display.json (generated %s · %d 종목)", display_date, len(display))

    candidates: dict[str, dict] = {}

    def add_candidate(key_ticker: str, key_cik: str, source: str, why: str):
        # key 우선 = cik (CIK 있으면 CIK 기준 · 없으면 ticker)
        if key_cik and key_cik != "0000000000":
            key = key_cik
            info = cik_meta.get(key_cik) or SEC_BY_CIK.get(key_cik) or {"ticker": key_ticker, "name": ""}   # P3a ⑥
            tk = info.get("ticker") or key_ticker
            nm = info.get("name") or ""
        else:
            key = key_ticker or ""
            info = tk_meta.get(key_ticker, {"cik": "", "name": ""}) if key_ticker else {}
            tk = key_ticker
            nm = info.get("name") or ""
        if not key:
            return
        if key not in candidates:
            candidates[key] = {
                "ticker": tk,
                "cik": key_cik or info.get("cik", ""),
                "name": nm,
                "sources": [],
                "reasons": [],
            }
        if source not in candidates[key]["sources"]:
            candidates[key]["sources"].append(source)
        candidates[key]["reasons"].append(why)

    # (a) WP39 결과 발표 최근 90일
    for r in source_a_readout(sha, days_recent=90):
        cik = r["cik"]
        info = cik_meta.get(cik, {})
        tk = info.get("ticker", "")
        add_candidate(tk, cik, "a_readout", f"결과 발표 D-day {r['d_day']} · dir={r['direction']} · kw={r['keywords'][:40]}")

    # (b) CT.gov 완료 예정 (h6_membership 근사)
    for r in source_b_ctgov(sha):
        tk = r["ticker"]
        cik_info = tk_meta.get(tk, {})
        cik = cik_info.get("cik", "")
        add_candidate(tk, cik, "b_ctgov", f"H6 최근 상위 3분위 테마 {r['theme']} 소속 (CT.gov 활동 근사 · {r['year']}Q{r['quarter']})")

    # (c) 최근 30일 신규 13D
    for r in source_c_recent_13d(sha, days=30):
        cik = r["cik"]
        info = cik_meta.get(cik, {})
        tk = info.get("ticker", "")
        add_candidate(tk, cik, "c_recent_13d", f"신규 SC 13D {r['date']} · filer 유형 {r['filer_bucket']}")

    # (d) 자문위 공고
    for r in source_d_adcom(sha, days_around=60):
        tk = r["mapped_ticker"] or ""
        cik = tk_meta.get(tk, {}).get("cik", "") if tk else ""
        if not tk and not cik:
            continue
        add_candidate(tk, cik, "d_adcom", f"자문위 회의 {r['meeting_date']} · {r['committee'] or 'FDA AdCom'}")

    LOG.info("raw candidates: %d", len(candidates))

    # 시총 필터 $50M~$5B (미상은 표기)
    filtered = []
    for key, c in candidates.items():
        tk = c["ticker"]
        cik = c["cik"]
        s = shares.get(cik, 0)
        p = close.get(tk, 0)
        mcap = s * p if s and p else display.get(tk, 0)
        c["mcap_usd"] = int(mcap)
        c["mcap_bucket"] = mcap_bucket(mcap)
    # P3a-3 ① · 5B 초과 제외 기록 (30일 유지)
    run_day = datetime.strptime(_P.today_kst_str("%Y%m%d"), "%Y%m%d").date()
    memo, over5b_kept, over5b_expired = keep_over5b(list(candidates.values()), load_over5b(), run_day)
    _over5b_path().write_text(json.dumps({"updated": run_day.isoformat(), "keep_days": OVER5B_KEEP_DAYS, "rows": memo},
                                         ensure_ascii=False, indent=1))
    if over5b_kept or over5b_expired:
        LOG.info("5B 초과 제외 기록 · 유지 %d %s · 30일 지나 다시 판정 %d %s",
                 len(over5b_kept), sorted(over5b_kept), len(over5b_expired), sorted(over5b_expired))
    for c in candidates.values():
        if c["mcap_bucket"] in ("50M-300M", "300M-1B", "1B-5B", "unknown"):
            filtered.append(c)

    # 정렬 = 소스 수 많은 순 → mcap 알려진 것 우선
    filtered.sort(key=lambda c: (-len(c["sources"]), 0 if c["mcap_bucket"] != "unknown" else 1, c["ticker"] or c["cik"]))
    final = filtered[:80]  # 상한 80 (30~50 요구지만 소스 확장 시 여유)

    today = _P.today_kst_str("%Y%m%d")
    out_path = OUT_DIR / f"biotech_candidates_{today}.csv"
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
                "reasons": " || ".join(c["reasons"][:5]),
            })

    src_dist = defaultdict(int)
    for c in final:
        for s in c["sources"]:
            src_dist[s] += 1
    mcap_dist = defaultdict(int)
    for c in final:
        mcap_dist[c["mcap_bucket"]] += 1
    multi_source = sum(1 for c in final if len(c["sources"]) >= 2)

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "raw_candidates": len(candidates),
        "final_candidates": len(final),
        "multi_source_2_plus": multi_source,
        "source_distribution": dict(src_dist),
        "mcap_distribution": dict(mcap_dist),
        "mcap_source": "h3" if close else f"mcap_display {display_date}",
        "over_5B_excluded": sorted(c["ticker"] or c["cik"] for c in candidates.values() if c["mcap_bucket"] == "over_5B_excluded"),
        "over_5B_kept_by_record": sorted(over5b_kept),
        "over_5B_record_expired": sorted(over5b_expired),
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
