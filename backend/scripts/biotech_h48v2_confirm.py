"""WP48-3 v2 · 확인 수집기 (후보 종목만 · 하루 1회 · 상시 순찰 없음).

용도:
- biotech_candidates_YYYYMMDD.csv 후보만 대상
- 각 후보에 대해 3 소스 (apewisdom · StockTwits · Reddit RSS) 언급 수 · 대표 글 최대 5
- 소문 유형 키워드 분류 (결과기대·인수설·증자우려·숏스퀴즈·기타)
- 저장: backend/data/biotech/community_daily/{ticker}_{date}.csv (append)
- 원칙: 본문 미저장 (제목 80자 헤더만) · 개인정보 미저장 · 링크만
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
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48v2_confirm")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
OUT_DIR = DATA_DIR / "biotech" / "community_daily"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = "TossTradebot-BiotechRadar biotech-radar@sung2011103.dev"

APEWISDOM = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
STOCKTWITS = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
REDDIT_SUBS = ["biotechplays", "pennystocks", "wallstreetbets", "stocks"]

KEYWORDS = {
    "clinical_readout": re.compile(r"\b(topline|readout|primary endpoint|phase [123]|PDUFA|adcom|pivotal|data)\b", re.I),
    "buyout": re.compile(r"\b(buyout|acquisition|takeover|acquired|merger|offer)\b", re.I),
    "dilution": re.compile(r"\b(offering|dilution|dilutive|ATM|shelf|warrants?|convertible)\b", re.I),
    "squeeze": re.compile(r"\b(short squeeze|squeeze|short interest|SI|shorted)\b", re.I),
}

CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_candidates(date_str: str) -> list[dict]:
    p = DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_{date_str}.csv"
    if not p.exists():
        return []
    with p.open() as f:
        return list(csv.DictReader(f))


def classify_keywords(text: str) -> list[str]:
    hits = []
    for cat, pat in KEYWORDS.items():
        if pat.search(text or ""):
            hits.append(cat)
    return hits


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


def fetch_stocktwits(client: httpx.Client, ticker: str) -> list[dict]:
    try:
        r = client.get(STOCKTWITS.format(ticker=ticker), timeout=15.0)
        if r.status_code != 200:
            return []
        return r.json().get("messages", [])
    except Exception:
        return []


def fetch_reddit_rss(client: httpx.Client, sub: str) -> list[dict]:
    """r/<sub>/new/.rss · atom+xml 파싱 · 최근 25 posts."""
    try:
        time.sleep(3.5)  # Reddit 정책 · 간격 준수
        r = client.get(f"https://www.reddit.com/r/{sub}/new/.rss", timeout=15.0)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = []
        for e in root.findall("atom:entry", ns):
            title = (e.findtext("atom:title", "", ns) or "").strip()
            link = ""
            link_el = e.find("atom:link", ns)
            if link_el is not None:
                link = link_el.get("href", "")
            updated = e.findtext("atom:updated", "", ns)
            entries.append({"title": title, "link": link, "updated": updated, "sub": sub})
        return entries
    except Exception:
        return []


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cands = load_candidates(today_str)
    LOG.info("candidates: %d", len(cands))
    if not cands:
        LOG.error("no candidates file · run biotech_h48v2_candidates first")
        return

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json,application/xml"}) as client:
        # 1) apewisdom 전체 top 300 조회 (1회)
        ape_map = fetch_apewisdom_map(client, pages=3)
        LOG.info("apewisdom map: %d tickers", len(ape_map))

        # 2) Reddit RSS 4 subs (1회씩 · 4 sub × 3.5s = 14s)
        reddit_posts_all = []
        for sub in REDDIT_SUBS:
            posts = fetch_reddit_rss(client, sub)
            LOG.info("reddit /r/%s/new.rss · %d posts", sub, len(posts))
            for p in posts:
                p["title_upper"] = (p["title"] or "").upper()
            reddit_posts_all.extend(posts)

        # 3) 후보별 확인 · StockTwits 각 1회
        rows = []
        for c in cands:
            tk = (c.get("ticker") or "").strip()
            if not tk:
                continue

            # apewisdom
            ape_hit = ape_map.get(tk)
            def _i(v):
                try:
                    return int(v)
                except Exception:
                    return 0
            ape_mentions = _i(ape_hit.get("mentions")) if ape_hit else 0
            ape_mentions_prev = _i(ape_hit.get("mentions_24h_ago")) if ape_hit else 0
            ape_rank = _i(ape_hit.get("rank")) if ape_hit else 0

            # StockTwits
            st_msgs = fetch_stocktwits(client, tk)
            time.sleep(1.0)
            st_count = len(st_msgs)
            st_bullish = sum(1 for m in st_msgs if isinstance(m.get("entities"), dict) and (m["entities"].get("sentiment", {}) or {}).get("basic") == "Bullish")
            st_bearish = sum(1 for m in st_msgs if isinstance(m.get("entities"), dict) and (m["entities"].get("sentiment", {}) or {}).get("basic") == "Bearish")
            st_samples = []
            for m in st_msgs[:5]:
                body = (m.get("body", "") or "")[:80].replace("\n", " ")
                kws = classify_keywords(m.get("body", "") or "")
                st_samples.append({"title": body, "link": f"https://stocktwits.com/message/{m.get('id')}", "keywords": kws, "created_at": m.get("created_at", "")})

            # Reddit RSS · $CASHTAG 매치
            reddit_hits = []
            for p in reddit_posts_all:
                if f"${tk}" in p["title_upper"] or f" {tk} " in f" {p['title_upper']} ":
                    reddit_hits.append(p)
            reddit_count = len(reddit_hits)
            reddit_samples = []
            for p in reddit_hits[:5]:
                kws = classify_keywords(p["title"])
                reddit_samples.append({"title": p["title"][:80], "link": p["link"], "keywords": kws, "sub": p.get("sub", ""), "updated": p.get("updated", "")})

            total_mentions = ape_mentions + st_count + reddit_count
            kw_all = set()
            for s in st_samples + reddit_samples:
                kw_all.update(s.get("keywords", []))
            stage = "quiet"
            if total_mentions >= 20:
                stage = "spread"
            elif total_mentions >= 5:
                stage = "early"

            rows.append({
                "date": today_dash,
                "ticker": tk,
                "name": c.get("name", ""),
                "mcap_bucket": c.get("mcap_bucket", ""),
                "why_candidate": c.get("reasons", "")[:200],
                "apewisdom_mentions_24h": ape_mentions,
                "apewisdom_prev": ape_mentions_prev,
                "apewisdom_rank": ape_rank,
                "stocktwits_msgs_last30": st_count,
                "stocktwits_bullish": st_bullish,
                "stocktwits_bearish": st_bearish,
                "reddit_hits_rss": reddit_count,
                "total_mentions_today": total_mentions,
                "keywords_all": "|".join(sorted(kw_all)),
                "stage": stage,
                "st_samples_top3": json.dumps(st_samples[:3], ensure_ascii=False),
                "reddit_samples_top3": json.dumps(reddit_samples[:3], ensure_ascii=False),
            })

    out_path = OUT_DIR / f"community_confirm_{today_str}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    stage_dist = Counter(r["stage"] for r in rows)
    with_mentions = sum(1 for r in rows if r["total_mentions_today"] > 0)
    quiet = sum(1 for r in rows if r["stage"] == "quiet")

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        "candidates": len(cands),
        "candidates_with_mentions": with_mentions,
        "candidates_quiet": quiet,
        "stage_dist": dict(stage_dist),
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
