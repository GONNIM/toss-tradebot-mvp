"""WP48-2 · 소문 순찰기 (StockTwits + apewisdom · biotech 우주 필터).

용도:
- 30분마다 실행 (cron / 수동 · 로컬 상시 대체) · 사용자 조회 아님 · 능동 순찰
- StockTwits: 바이오 우주 상위 50 티커 심볼 stream · 최근 messages · 티커·키워드 추출
- apewisdom: top ~300 · biotech ∩ 언급 카운트
- 저장: backend/data/biotech/rumor/posts_YYYYMMDD.csv (append · 중복 제거 post_id)
- 필드: post_id · community · title · score · comments · created_utc · permalink · tickers[] · keywords[]
- 본문 미저장 · 개인정보 미저장

원칙:
- 선언 UA · 간격 준수
- 티커 추출: $CASHTAG 우선 · 대문자 토큰은 바이오 우주 티커 집합 매치 시만 · 불용어 (CEO/FDA/IPO/DD/YOLO 등)
- 키워드 사전 (사전 커밋 · 5분류): clinical_readout · buyout · dilution · squeeze · other
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

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48_patrol")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data" / "biotech" / "rumor"
DATA_DIR.mkdir(parents=True, exist_ok=True)

APEWISDOM = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
STOCKTWITS = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
UA = "TossTradebot-BiotechRadar biotech-radar@sung2011103.dev"

STOPWORDS = {
    "CEO", "CFO", "COO", "FDA", "SEC", "IPO", "DD", "YOLO", "TA", "USA", "US",
    "AI", "ML", "EV", "NYSE", "NASDAQ", "ETF", "IRA", "USD", "GDP", "PDUFA",
    "ADCOM", "IND", "NDA", "BLA", "PR", "LOL", "OMG", "TL", "DR",
}

KEYWORDS = {
    "clinical_readout": re.compile(r"\b(topline|readout|primary endpoint|phase [123]|PDUFA|adcom|pivotal)\b", re.I),
    "buyout": re.compile(r"\b(buyout|acquisition|takeover|acquired|merger|offer(?:ing bid)?)\b", re.I),
    "dilution": re.compile(r"\b(offering|dilution|dilutive|ATM|shelf|warrants?|convertible)\b", re.I),
    "squeeze": re.compile(r"\b(short squeeze|squeeze|short interest|SI|shorted|reg sho)\b", re.I),
}

CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
UPPER_TOKEN_RE = re.compile(r"\b([A-Z]{2,5})\b")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_universe(sha: str) -> set[str]:
    u = set()
    p = PROJECT_ROOT / "backend" / "data" / f"biotech_ticker_set_{sha}.csv"
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                t = (r.get("ticker") or "").strip()
                if t and t != "-":
                    u.add(t.upper())
    p2 = PROJECT_ROOT / "backend" / "data" / f"h3_targets_v2_{sha}.csv"
    if p2.exists():
        with p2.open() as f:
            for r in csv.DictReader(f):
                if r.get("sic_biotech") == "True":
                    t = (r.get("ticker") or "").strip()
                    if t:
                        u.add(t.upper())
    return u


def extract_tickers(text: str, universe: set[str]) -> list[str]:
    hits = set()
    for m in CASHTAG_RE.finditer(text or ""):
        tk = m.group(1).upper()
        if tk in universe and tk not in STOPWORDS:
            hits.add(tk)
    for m in UPPER_TOKEN_RE.finditer(text or ""):
        tk = m.group(1).upper()
        if tk in universe and tk not in STOPWORDS:
            hits.add(tk)
    return sorted(hits)


def extract_keywords(text: str) -> list[str]:
    hits = []
    for cat, pat in KEYWORDS.items():
        if pat.search(text or ""):
            hits.append(cat)
    return hits


def fetch_stocktwits(client: httpx.Client, ticker: str) -> list[dict]:
    try:
        r = client.get(STOCKTWITS.format(ticker=ticker), timeout=15.0)
        if r.status_code != 200:
            return []
        return r.json().get("messages", [])
    except Exception:
        return []


def fetch_apewisdom(client: httpx.Client, pages: int = 3) -> list[dict]:
    out = []
    for p in range(1, pages + 1):
        try:
            r = client.get(APEWISDOM.format(page=p), timeout=15.0)
            if r.status_code != 200:
                break
            for e in r.json().get("results", []):
                out.append(e)
        except Exception:
            break
        time.sleep(1.0)
    return out


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    universe = load_universe(sha)
    LOG.info("biotech universe: %d", len(universe))

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    posts_path = DATA_DIR / f"posts_{today}.csv"
    existing_ids = set()
    if posts_path.exists():
        with posts_path.open() as f:
            for r in csv.DictReader(f):
                existing_ids.add(r["post_id"])

    new_rows = []
    apewisdom_snap = []

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}) as c:
        # 1) apewisdom → biotech 매치 상위 50 티커 확보
        ape = fetch_apewisdom(c, pages=3)
        for e in ape:
            tk = (e.get("ticker") or "").upper()
            def _i(v):
                try:
                    return int(v)
                except Exception:
                    return 0
            if tk in universe:
                apewisdom_snap.append({
                    "snapshot_ts": datetime.now(timezone.utc).isoformat(),
                    "community": "apewisdom",
                    "ticker": tk,
                    "rank": _i(e.get("rank")),
                    "mentions_24h": _i(e.get("mentions")),
                    "mentions_24h_ago": _i(e.get("mentions_24h_ago")),
                })
        LOG.info("apewisdom biotech hits: %d", len(apewisdom_snap))

        # 2) StockTwits · biotech 우주 상위 50 (apewisdom 순위 or 우주 sort)
        top_tickers = [r["ticker"] for r in apewisdom_snap[:50]] or sorted(universe)[:50]
        for tk in top_tickers[:50]:
            msgs = fetch_stocktwits(c, tk)
            time.sleep(1.0)
            for m in msgs:
                pid = f"stocktwits_{m.get('id')}"
                if pid in existing_ids:
                    continue
                body = m.get("body", "") or ""
                created = m.get("created_at", "")
                # 티커·키워드 추출
                tickers_found = extract_tickers(body, universe)
                if tk not in tickers_found:
                    tickers_found.append(tk)  # 심볼 stream 원 티커 보장
                kws = extract_keywords(body)
                # 개인정보 · 본문 미저장 (title 만 · body 대신 첫 60자 요약)
                title = body[:80].replace("\n", " ")
                new_rows.append({
                    "post_id": pid,
                    "community": "stocktwits",
                    "title": title,
                    "score": m.get("likes", {}).get("total", 0) if isinstance(m.get("likes"), dict) else 0,
                    "comments": m.get("conversation", {}).get("replies", 0) if isinstance(m.get("conversation"), dict) else 0,
                    "created_utc": created,
                    "permalink": f"https://stocktwits.com/message/{m.get('id')}",
                    "tickers": "|".join(tickers_found),
                    "keywords": "|".join(kws),
                })

    # append CSV
    fieldnames = ["post_id", "community", "title", "score", "comments", "created_utc", "permalink", "tickers", "keywords"]
    exists = posts_path.exists()
    with posts_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerows(new_rows)

    # apewisdom snapshot 별도
    ape_path = DATA_DIR / f"apewisdom_snap_{today}.csv"
    ape_exists = ape_path.exists()
    with ape_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["snapshot_ts", "community", "ticker", "rank", "mentions_24h", "mentions_24h_ago"])
        if not ape_exists:
            w.writeheader()
        w.writerows(apewisdom_snap)

    # 티커 추출 정확도 표본 20건
    sample_20 = new_rows[:20]
    valid_extractions = sum(1 for r in sample_20 if r["tickers"])

    summary = {
        "git_sha": sha,
        "universe_size": len(universe),
        "apewisdom_snap_rows": len(apewisdom_snap),
        "stocktwits_new_posts": len(new_rows),
        "existing_ids_before": len(existing_ids),
        "posts_csv": str(posts_path),
        "ape_snap_csv": str(ape_path),
        "sample_ticker_extraction_accuracy": f"{valid_extractions}/20 (자동추출 성공 카운트)",
        "sample_20": [{"ticker_hits": r["tickers"], "kw": r["keywords"], "title_head": r["title"][:60]} for r in sample_20],
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2)[:2000])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
