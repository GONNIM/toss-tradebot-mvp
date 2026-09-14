"""WP48v2 정비 v3 · 확인 수집기 (StockTwits 24h · 단계 규칙 사전 고정 · RSS 매치 병기).

단계 규칙 (사전 고정 · 60일 전 조정 금지):
- 조용 (quiet): ST 24h ≤ 2 AND apewisdom 미등장
- 초기 (early): ST 24h ≥ 3 × 30일 평균 (기준선 ≥ 7일 확보 후 · 미확보 시 "수집 중" 표기)
- 과열 (frenzy): apewisdom rank ≤ 100 OR ST 24h ≥ 100
- 확산 (spread): 그 외

RSS 매치는 보조 표시 · 유형 태그는 ST 24h ≥ 5 인 종목만 부여.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48v3_confirm")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
OUT_DIR = DATA_DIR / "biotech" / "community_daily"
OUT_DIR.mkdir(parents=True, exist_ok=True)
BASELINE_DIR = DATA_DIR / "biotech" / "st_baseline"
BASELINE_DIR.mkdir(parents=True, exist_ok=True)

UA = "TossTradebot-BiotechRadar biotech-radar@sung2011103.dev"
APEWISDOM = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
STOCKTWITS = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
STOCKTWITS_MAX = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json?max={max_id}"
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


def load_candidates(date_str: str) -> list[dict]:
    p = DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_{date_str}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def fetch_apewisdom_map(client: httpx.Client, pages: int = 3) -> dict[str, dict]:
    out = {}
    for p in range(1, pages + 1):
        try:
            r = client.get(APEWISDOM.format(page=p), timeout=15.0)
            if r.status_code != 200:
                break
            for e in r.json().get("results", []):
                out[(e.get("ticker") or "").upper()] = e
        except Exception:
            break
        time.sleep(1.0)
    return out


def fetch_stocktwits_paged(client: httpx.Client, ticker: str, cutoff_utc: datetime, cap: int = 300) -> list[dict]:
    """24h 창 · 30건 전부 24h 내이면 max 커서로 이어받기 · 최대 cap 300."""
    all_msgs = []
    max_id = None
    while len(all_msgs) < cap:
        try:
            url = STOCKTWITS.format(ticker=ticker) if not max_id else STOCKTWITS_MAX.format(ticker=ticker, max_id=max_id)
            r = client.get(url, timeout=15.0)
            if r.status_code != 200:
                break
            msgs = r.json().get("messages", [])
            if not msgs:
                break
            # 24h 필터
            recent = []
            oldest_id = msgs[-1].get("id") if msgs else None
            for m in msgs:
                created = m.get("created_at", "")
                try:
                    cdt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    continue
                if cdt >= cutoff_utc:
                    recent.append(m)
            all_msgs.extend(recent)
            # 마지막 메시지가 24h 밖이면 종료
            if len(recent) < len(msgs):
                break
            # 페이지네이션
            max_id = oldest_id - 1 if oldest_id else None
            if not max_id:
                break
            time.sleep(1.0)
        except Exception:
            break
    return all_msgs[:cap]


def fetch_reddit_rss(client: httpx.Client, sub: str) -> list[dict]:
    try:
        time.sleep(3.5)
        r = client.get(f"https://www.reddit.com/r/{sub}/new/.rss", timeout=15.0)
        if r.status_code != 200:
            return [{"_status": r.status_code}]  # 오류 marker
        try:
            root = ET.fromstring(r.text)
        except Exception:
            return [{"_status": "parse_fail"}]
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        out = []
        for e in root.findall("atom:entry", ns):
            title = (e.findtext("atom:title", "", ns) or "").strip()
            link_el = e.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            updated = e.findtext("atom:updated", "", ns)
            out.append({"title": title, "link": link, "updated": updated, "sub": sub})
        return out
    except Exception as e:
        return [{"_status": f"err_{str(e)[:30]}"}]


def load_st_baseline(ticker: str) -> tuple[int, float]:
    """지난 최대 30일 baseline · (n_days, mean_st_24h)."""
    files = sorted(BASELINE_DIR.glob(f"{ticker}_*.json"))[-30:]
    if not files:
        return (0, 0.0)
    vals = []
    for f in files:
        try:
            vals.append(json.loads(f.read_text()).get("st_24h", 0))
        except Exception:
            continue
    if not vals:
        return (0, 0.0)
    return (len(vals), sum(vals) / len(vals))


def save_st_baseline(ticker: str, date_str: str, st_24h: int):
    p = BASELINE_DIR / f"{ticker}_{date_str}.json"
    p.write_text(json.dumps({"date": date_str, "st_24h": st_24h}))


def stage(st_24h: int, ape_rank: int, baseline_n: int, baseline_mean: float) -> str:
    if st_24h <= 2 and ape_rank == 0:
        return "quiet"
    if ape_rank > 0 and ape_rank <= 100:
        return "frenzy"
    if st_24h >= 100:
        return "frenzy"
    if baseline_n >= 7 and st_24h >= 3 * baseline_mean and baseline_mean > 0:
        return "early"
    if baseline_n < 7:
        return "collecting"
    return "spread"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=24)

    cands = load_candidates(today_str)
    LOG.info("candidates: %d", len(cands))

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,application/xml"}) as client:
        ape_map = fetch_apewisdom_map(client, pages=3)
        LOG.info("apewisdom map: %d tickers", len(ape_map))

        reddit_posts = []
        reddit_errors = {}
        for sub in REDDIT_SUBS:
            posts = fetch_reddit_rss(client, sub)
            if posts and posts[0].get("_status"):
                reddit_errors[sub] = posts[0]["_status"]
                LOG.info("reddit /r/%s = ERROR %s", sub, posts[0]["_status"])
                continue
            LOG.info("reddit /r/%s = %d posts", sub, len(posts))
            for p in posts:
                p["title_upper"] = (p["title"] or "").upper()
            reddit_posts.extend(posts)

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

            st_msgs = fetch_stocktwits_paged(client, tk, cutoff_utc, cap=300)
            time.sleep(1.0)
            st_24h = len(st_msgs)
            st_bull = sum(1 for m in st_msgs if isinstance(m.get("entities"), dict) and (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish")
            st_bear = sum(1 for m in st_msgs if isinstance(m.get("entities"), dict) and (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish")

            st_samples = []
            for m in st_msgs[:5]:
                body = (m.get("body", "") or "")[:80].replace("\n", " ")
                st_samples.append({"title": body, "link": f"https://stocktwits.com/message/{m.get('id')}", "kw": classify(m.get("body", ""))})

            reddit_hits = [p for p in reddit_posts if f"${tk}" in p["title_upper"] or f" {tk} " in f" {p['title_upper']} "]
            reddit_samples = [{"title": p["title"][:80], "link": p["link"], "sub": p.get("sub", ""), "kw": classify(p["title"])} for p in reddit_hits[:3]]

            baseline_n, baseline_mean = load_st_baseline(tk)
            save_st_baseline(tk, today_str, st_24h)

            st_baseline_mult = round(st_24h / max(1e-6, baseline_mean), 2) if baseline_mean > 0 else None
            stage_val = stage(st_24h, ape_rank, baseline_n, baseline_mean)

            # 유형 태그는 ST 24h >= 5 종목만
            kws = set()
            if st_24h >= 5:
                for s in st_samples:
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
                "st_24h": st_24h,
                "st_bullish": st_bull,
                "st_bearish": st_bear,
                "st_baseline_n": baseline_n,
                "st_baseline_mean": round(baseline_mean, 2),
                "st_baseline_mult": st_baseline_mult if st_baseline_mult is not None else "collecting",
                "reddit_rss_matches": len(reddit_hits),
                "stage": stage_val,
                "keywords": "|".join(sorted(kws)) if kws else "",
                "st_samples": json.dumps(st_samples[:3], ensure_ascii=False),
                "reddit_samples": json.dumps(reddit_samples[:3], ensure_ascii=False),
            })

    out_path = OUT_DIR / f"community_confirm_{today_str}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    stage_dist = Counter(r["stage"] for r in rows)
    reddit_note = ", ".join(f"{sub}:{err}" for sub, err in reddit_errors.items()) if reddit_errors else "all_ok"

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "candidates": len(cands),
        "stage_dist": dict(stage_dist),
        "reddit_status": reddit_note,
        "reddit_posts_ok": {sub: len([p for p in reddit_posts if p.get("sub") == sub]) for sub in REDDIT_SUBS},
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
