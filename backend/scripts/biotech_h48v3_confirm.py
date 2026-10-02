"""WP48v3 확인 수집기 · **WP69-3d γ+α 재작성** (2026-09-20).

배경 (사용자 결정 2026-09-20):
- StockTwits 서버 IP 차단 (WP69-3b 실측 403) → **서버 채널은 apewisdom + Reddit RSS 만** (γ)
- 로컬 st_24h 는 있으면 표3 보조 열 (α · 이 스크립트는 서버용 · st_24h=0/미수집 처리)
- 30일 기준선을 서버에서 재축적 시작 · 7일 미만 "collecting" 표기 (사전 고정 규칙 유지)
- 임계 재검토 · **h_radar_params v1.5 changelog** 참조 · 가중치 동일

단계 규칙 v1.5 (사전 고정 · 60일 전 조정 금지 · 임계 채널 합산 기준):
- collecting: baseline < 7일 (수집 중 · 판정 유보)
- quiet: apewisdom 미등장 AND baseline_mean_24h ≤ 5 (조용)
- frenzy: apewisdom rank ≤ 100 OR (baseline ≥ 7 AND apewisdom_24h ≥ 5 × mean) OR reddit_matches ≥ 5 (과열)
- early: baseline ≥ 7 AND (apewisdom_24h ≥ 3 × mean AND mean > 0) (초기)
- spread: 그 외 (확산)

RSS 매치는 보조 표시 · 유형 태그는 apewisdom_24h ≥ 5 OR reddit_matches ≥ 1 일 때만 부여.

**보안·규칙**:
- biotech_sec_common 상수 (SEC_UA / SEC_FROM / SEC_ACCEPT_ENCODING) 참조 (하드코딩 금지)
- 소스별 중단 (403/429) · 전체 중단 아님
- 우회 금지 (β·δ 제외)
- BIOTECH_RUNTIME_DIR · baseline 은 여기에 축적 (서버 배포 reset --hard 무영향)

**호환**:
- 산출 CSV 컬럼 (`st_24h`, `st_baseline_n`, `st_baseline_mean`, `st_baseline_mult`) 유지
  → API/frontend 무회귀 (표3 렌더 그대로 · 값 소스만 apewisdom baseline 으로 교체)
- st_24h = apewisdom 24시간 언급 수 (아래 "st_24h": ape_24h 와 같음 · 레딧 매치는 reddit_rss_matches 열 · 2026-09-30 WP86 주석 정정)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING

import csv
from typing import Any, Callable
import json
import logging
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48v3_confirm")

# WP69-3g · 경로는 공용 헬퍼 _biotech_paths 사용
from backend.scripts import _biotech_paths as _P
PROJECT_ROOT = _P.PROJECT_ROOT
DATA_DIR = _P.DATA_DIR

_rt = os.environ.get("BIOTECH_RUNTIME_DIR", "").strip()
RUNTIME_DIR = Path(_rt) if _rt else None

# 산출 · 기준선 폴더 (WP69-3b RUNTIME 우선)
OUT_DIR = (RUNTIME_DIR / "community_daily") if RUNTIME_DIR else (DATA_DIR / "biotech" / "community_daily")
OUT_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_DIR = (RUNTIME_DIR / "st_baseline") if RUNTIME_DIR else (DATA_DIR / "biotech" / "st_baseline")
BASELINE_DIR.mkdir(parents=True, exist_ok=True)

# 헤더 · biotech_sec_common 상수 참조 (WP69-3d 사용자 규칙)
HEADERS = {
    "User-Agent": SEC_UA,
    "From": SEC_FROM,
    "Accept-Encoding": SEC_ACCEPT_ENCODING,
    "Accept": "application/json,application/xml",
}

APEWISDOM = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"

# WP98-2 · 레딧은 레딧 전용 User-Agent (SEC 헤더 상수 쓰지 않음) · 4곳 묶음 RSS 1회
#   2026-09-22~10-02: 곳마다 1회씩 4회 요청 → 첫 곳만 200 · 나머지 3곳 매일 429 (x-ratelimit-remaining 0)
REDDIT_UA = "TossTradebot BiotechRadar/1.0 (contact: suauncle@gmail.com)"
REDDIT_HEADERS = {"User-Agent": REDDIT_UA, "Accept": "application/atom+xml"}
REDDIT_RETRY_WAIT = 60      # 429 이면 60초 뒤 1회 재시도
REDDIT_MIN_GAP = 2.0        # 요청 사이 최소 간격 (초)
REDDIT_FALLBACK_SUB = "biotechplays"
REDDIT_SUBS = ["biotechplays", "pennystocks", "wallstreetbets", "stocks"]

KEYWORDS = {
    "readout": re.compile(r"\b(topline|readout|primary endpoint|phase [123]|PDUFA|adcom|pivotal|data)\b", re.I),
    "buyout": re.compile(r"\b(buyout|acquisition|takeover|acquired|merger|offer)\b", re.I),
    "dilution": re.compile(r"\b(offering|dilution|dilutive|ATM|shelf|warrants?|convertible)\b", re.I),
    "squeeze": re.compile(r"\b(short squeeze|squeeze|short interest|SI|shorted)\b", re.I),
}


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def classify(text: str) -> list[str]:
    return [c for c, p in KEYWORDS.items() if p.search(text or "")]


def _find_candidates_v3_input(date_str: str) -> Path | None:
    """candidates_v3 (h50 산출) → confirm 은 candidates 원본 v1 CSV 로부터 파생.

    기존 흐름: h48v3_candidates → biotech_candidates_YYYYMMDD.csv → confirm 이 이를 읽음.
    v3 는 h50 결과 · v1 은 원본. 여기서는 v1 을 사용.
    """
    dirs = []
    if RUNTIME_DIR is not None:
        dirs.append(RUNTIME_DIR / "candidates")
    dirs.append(DATA_DIR / "biotech" / "candidates")
    for d in dirs:
        p = d / f"biotech_candidates_{date_str}.csv"
        if p.exists():
            return p
    return None


def fetch_apewisdom_map(client: httpx.Client, pages: int = 3) -> tuple[dict[str, dict], bool]:
    """apewisdom 전체 목록 · 페이지 순회. 403/429 감지 시 즉시 중단 (사용자 규칙)."""
    out: dict[str, dict] = {}
    ok = True
    for p in range(1, pages + 1):
        try:
            r = client.get(APEWISDOM.format(page=p), timeout=15.0)
            if r.status_code in (403, 429):
                LOG.error("apewisdom · HTTP %d · 소스 즉시 중단 (page=%d)", r.status_code, p)
                ok = False
                break
            if r.status_code != 200:
                LOG.warning("apewisdom · HTTP %d · page=%d 부분", r.status_code, p)
                break
            for e in r.json().get("results", []):
                out[(e.get("ticker") or "").upper()] = e
        except Exception as e:
            LOG.warning("apewisdom · %s · page=%d", e.__class__.__name__, p)
            break
        time.sleep(1.0)
    return out, ok


def parse_reddit_atom(text: str) -> list[dict]:
    """Atom → 글 목록 · 곳 이름은 <category term> (묶음 RSS 에서 곳 구분)."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(text)
    out = []
    for e in root.findall("atom:entry", ns):
        cat = e.find("atom:category", ns)
        link_el = e.find("atom:link", ns)
        out.append({"id": (e.findtext("atom:id", "", ns) or "").strip(),
                    "title": (e.findtext("atom:title", "", ns) or "").strip(),
                    "link": link_el.get("href", "") if link_el is not None else "",
                    "updated": e.findtext("atom:updated", "", ns),
                    "sub": (cat.get("term", "") if cat is not None else "").lower()})
    return out


def fetch_reddit(get: Callable[[str], Any], sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict], dict]:
    """WP98-3 · 4곳 묶음 RSS 1회 + biotechplays 단독 1회 (하루 2회) · 각각 429 면 60초 뒤 1회 재시도 · 403 은 즉시 중단.

    묶음은 글이 많은 곳 (wallstreetbets 등) 이 최근 100개를 채워 biotechplays 가 빠짐 (2026-10-02 서버 시험 0개) → 단독으로 보충.
    두 결과를 합치고 글 ID 로 중복 제거 · "4곳 중 N곳" = 성공한 요청이 덮는 곳의 합집합.
    """
    combined = f"https://www.reddit.com/r/{'+'.join(REDDIT_SUBS)}/new/.rss?limit=100"
    single = f"https://www.reddit.com/r/{REDDIT_FALLBACK_SUB}/new/.rss?limit=100"
    attempts: list[dict] = []
    covered: set[str] = set()
    merged: dict[str, dict] = {}
    stop = False

    def _one(kind: str, url: str, subs: list[str]) -> None:
        nonlocal stop
        r = None
        for k in (kind, f"{kind}_retry"):
            try:
                r = get(url)
                attempts.append({"kind": k, "http": r.status_code})
            except Exception as e:  # noqa: BLE001
                attempts.append({"kind": k, "http": f"err_{e.__class__.__name__}"})
                r = None
                break
            if r.status_code == 429 and k == kind:
                sleep(REDDIT_RETRY_WAIT)
                continue
            break
        if r is None:
            return
        if r.status_code == 403:
            stop = True
            return
        if r.status_code != 200:
            return
        try:
            posts = parse_reddit_atom(r.text)
        except ET.ParseError:
            attempts[-1]["http"] = "parse_fail"
            return
        covered.update(subs)
        for p in posts:
            merged.setdefault(p.get("id") or p.get("link") or p["title"], p)

    _one("combined", combined, list(REDDIT_SUBS))
    if not stop:
        sleep(REDDIT_MIN_GAP)
        _one("single", single, [REDDIT_FALLBACK_SUB])
    posts = list(merged.values())
    per_sub: dict[str, int] = {}
    for p in posts:
        per_sub[p["sub"]] = per_sub.get(p["sub"], 0) + 1
    mode = "+".join(a["kind"] for a in attempts if a["http"] == 200) or "none"
    return posts, {"subs_total": len(REDDIT_SUBS), "subs_collected": len(covered), "mode": mode,
                   "attempts": attempts, "posts": len(posts), "per_sub": per_sub}


def fetch_reddit_rss(client: httpx.Client, sub: str) -> tuple[list[dict], bool]:
    """Reddit RSS · 403/429 시 소스 중단."""
    try:
        time.sleep(3.5)
        r = client.get(f"https://www.reddit.com/r/{sub}/new/.rss", timeout=15.0)
        if r.status_code in (403, 429):
            LOG.error("reddit /r/%s · HTTP %d · 소스 즉시 중단", sub, r.status_code)
            return [], False
        if r.status_code != 200:
            return [{"_status": r.status_code}], True
        try:
            root = ET.fromstring(r.text)
        except Exception:
            return [{"_status": "parse_fail"}], True
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        out = []
        for e in root.findall("atom:entry", ns):
            title = (e.findtext("atom:title", "", ns) or "").strip()
            link_el = e.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            updated = e.findtext("atom:updated", "", ns)
            out.append({"title": title, "link": link, "updated": updated, "sub": sub})
        return out, True
    except Exception as e:
        return [{"_status": f"err_{str(e)[:30]}"}], True


BASELINE_FLOOR = 1.0   # WP86 · 기준선 하한 (하루 1건) · 평균 0.25 → 128배 같은 부풀림 방지 · 평균 0 종목도 배수 계산


def baseline_multiple(ape_24h: int, baseline_mean: float) -> float:
    """평소 대비 배수 = 오늘 apewisdom 언급 / max(1.0, 기준선 평균) (WP86 · 2026-09-30 규칙 변경)."""
    return round(ape_24h / max(BASELINE_FLOOR, baseline_mean), 2)


def load_baseline(ticker: str) -> tuple[int, float]:
    """지난 최대 30일 baseline · (n_days, mean_24h). apewisdom_24h 값 축적."""
    files = sorted(BASELINE_DIR.glob(f"{ticker}_*.json"))[-30:]
    if not files:
        return (0, 0.0)
    vals = []
    for f in files:
        try:
            d = json.loads(f.read_text())
            # WP69-3d · apewisdom_24h 값 우선 · 하위 호환 st_24h
            v = d.get("apewisdom_24h", d.get("st_24h", 0))
            vals.append(int(v) if v is not None else 0)
        except Exception:
            continue
    if not vals:
        return (0, 0.0)
    return (len(vals), sum(vals) / len(vals))


def save_baseline(ticker: str, date_str: str, apewisdom_24h: int, reddit_matches: int):
    p = BASELINE_DIR / f"{ticker}_{date_str}.json"
    p.write_text(json.dumps({
        "date": date_str,
        "apewisdom_24h": apewisdom_24h,
        "reddit_matches": reddit_matches,
    }))


def stage(apewisdom_24h: int, ape_rank: int, reddit_matches: int, baseline_n: int, baseline_mean: float) -> str:
    """단계 규칙 v1.5 (사전 고정 · 임계 h_radar_params v1.5 정합)."""
    if baseline_n < 7:
        return "collecting"
    if ape_rank == 0 and baseline_mean <= 5.0 and apewisdom_24h == 0:
        return "quiet"
    if ape_rank > 0 and ape_rank <= 100:
        return "frenzy"
    if reddit_matches >= 5:
        return "frenzy"
    if baseline_mean > 0 and apewisdom_24h >= 5 * baseline_mean:
        return "frenzy"
    if baseline_mean > 0 and apewisdom_24h >= 3 * baseline_mean:
        return "early"
    return "spread"


def _notify_reddit_blocked(day: str, status: dict) -> None:
    """레딧 전부 차단 · 텔레그램 warning 하루 1회 (표시 파일로 중복 방지)."""
    marker = OUT_DIR / f"reddit_blocked_warned_{day}"
    if marker.exists():
        return
    marker.write_text(json.dumps(status.get("attempts", []), ensure_ascii=False))
    try:
        import asyncio
        from backend.services.notifier import TelegramNotifier
        asyncio.run(TelegramNotifier().send_warning(
            title="biotech 레딧 입력 없음", body=f"4곳 묶음 · 재시도 · biotechplays 단독 모두 실패 · 시도 {status.get('attempts')}"))
    except Exception as e:  # noqa: BLE001
        LOG.warning("notifier 실패 · %s", e.__class__.__name__)


def reddit_probe() -> dict:
    """WP98-2 · 시험 모드 · 요청만 보내고 결과 출력 · 파일 쓰기 없음."""
    with httpx.Client(headers=REDDIT_HEADERS, timeout=15.0) as rclient:
        _posts, status = fetch_reddit(rclient.get)
    print(json.dumps(status, ensure_ascii=False))
    return status


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import sys as _sys
    if "--reddit-probe" in _sys.argv:
        reddit_probe()
        return
    sha = git_sha()

    today_str = _P.today_kst_str("%Y%m%d")
    today_dash = _P.today_kst_str("%Y-%m-%d")

    cands_path = _find_candidates_v3_input(today_str)
    if not cands_path:
        LOG.error("biotech_candidates_%s.csv 없음 · h48v3_candidates 선행 필요", today_str)
        raise SystemExit(48)
    cands = list(csv.DictReader(cands_path.open()))
    LOG.info("candidates: %d · %s", len(cands), cands_path)

    with httpx.Client(headers=HEADERS) as client:
        ape_map, ape_ok = fetch_apewisdom_map(client, pages=3)
        LOG.info("apewisdom · %d tickers · ok=%s", len(ape_map), ape_ok)

        # WP98-2 · 레딧 묶음 RSS (레딧 전용 클라이언트 · SEC 헤더 아님)
        with httpx.Client(headers=REDDIT_HEADERS, timeout=15.0) as rclient:
            reddit_posts, reddit_status = fetch_reddit(rclient.get)
        for p in reddit_posts:
            p["title_upper"] = (p["title"] or "").upper()
        reddit_errors = {a["kind"]: a["http"] for a in reddit_status["attempts"] if a["http"] != 200}
        (OUT_DIR / f"reddit_status_{today_str}.json").write_text(json.dumps(reddit_status, ensure_ascii=False))
        LOG.info("reddit · 4곳 중 %d곳 수집 · 방식 %s · 글 %d · 곳별 %s · 시도 %s", reddit_status["subs_collected"],
                 reddit_status["mode"], reddit_status["posts"], reddit_status["per_sub"], reddit_status["attempts"])
        if reddit_status["subs_collected"] == 0:
            _notify_reddit_blocked(today_str, reddit_status)
        LOG.info("reddit · %d posts · errors=%s", len(reddit_posts), reddit_errors)

        rows = []
        for c in cands:
            tk = (c.get("ticker") or "").strip()
            if not tk:
                continue

            ape = ape_map.get(tk)

            def _i(v):
                try:
                    return int(v)
                except Exception:
                    return 0
            ape_rank = _i(ape.get("rank")) if ape else 0
            ape_24h = _i(ape.get("mentions")) if ape else 0
            ape_prev = _i(ape.get("mentions_24h_ago")) if ape else 0

            # Reddit 매치
            reddit_hits = [p for p in reddit_posts if f"${tk}" in p["title_upper"] or f" {tk} " in f" {p['title_upper']} "]
            reddit_samples = [{"title": p["title"][:80], "link": p["link"], "sub": p.get("sub", ""), "kw": classify(p["title"])} for p in reddit_hits[:3]]

            baseline_n, baseline_mean = load_baseline(tk)
            save_baseline(tk, today_str, ape_24h, len(reddit_hits))

            baseline_mult = baseline_multiple(ape_24h, baseline_mean)   # WP86 · 기준선 하한 1건 (평균 0 이어도 계산)
            stage_val = stage(ape_24h, ape_rank, len(reddit_hits), baseline_n, baseline_mean)

            # 유형 태그 (apewisdom 5+ 또는 reddit 매치 1+)
            kws = set()
            if ape_24h >= 5:
                for s in reddit_samples:
                    kws.update(s["kw"])
            for s in reddit_samples:
                kws.update(s["kw"])

            rows.append({
                "date": today_dash,
                "ticker": tk,
                "name": c.get("name", ""),
                "mcap_bucket": c.get("mcap_bucket", ""),
                "why_candidate": c.get("reasons", "")[:250],
                "sources": c.get("sources", ""),
                "apewisdom_rank": ape_rank,
                "apewisdom_24h": ape_24h,
                "apewisdom_prev": ape_prev,
                # 호환 컬럼 (기존 API 무회귀 · 의미: 서버 채널 총 언급수)
                "st_24h": ape_24h,
                "st_bullish": 0,  # StockTwits 채널 삭제로 미측정 (WP69-3d)
                "st_bearish": 0,
                "st_baseline_n": baseline_n,
                "st_baseline_mean": round(baseline_mean, 2),
                "st_baseline_mult": baseline_mult if baseline_mult is not None else "collecting",
                "reddit_rss_matches": len(reddit_hits),
                "stage": stage_val,
                "keywords": "|".join(sorted(kws)) if kws else "",
                # StockTwits 삭제 · 로컬 α 있으면 별도 CSV 병기 (미구현 · 다음 세션)
                "st_samples": "[]",
                "reddit_samples": json.dumps(reddit_samples[:3], ensure_ascii=False),
                # WP77-1 · 급등 브리핑 표시 전용 (제목 원문·링크·RSS 갱신 시각 · 최대 5) · 키워드·단계·점수에 쓰지 않음
                "reddit_posts": json.dumps(
                    [{"title": p["title"][:200], "link": p["link"], "sub": p.get("sub", ""), "updated": p.get("updated", "")}
                     for p in reddit_hits[:5]], ensure_ascii=False),
            })

    out_path = OUT_DIR / f"community_confirm_{today_str}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)

    stage_dist = Counter(r["stage"] for r in rows)
    reddit_note = ", ".join(f"{sub}:{err}" for sub, err in reddit_errors.items()) if reddit_errors else "all_ok"

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "candidates": len(cands),
        "stage_dist": dict(stage_dist),
        "apewisdom_ok": ape_ok,
        "reddit_status": reddit_note,
        "note": "WP69-3d γ+α · StockTwits 제거 (서버 IP 차단) · apewisdom + Reddit RSS 서버 채널 · 기준선 서버 재축적 (7일 미만 collecting)",
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
