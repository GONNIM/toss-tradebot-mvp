"""WP7 · H4 apewisdom biotech 언급 스냅샷 (전향 수집기 · burn-in 시작).

용도:
- 30분마다 apewisdom 언급 순위 스냅샷 저장
- biotech_ticker_set_add7af7.csv 304 티커만 필터
- burn-in 60일 · 게이트 (60건 이벤트 or 6개월) 후 H4 백테스트 착수 가능

원칙:
- 무인증 · 무료 · biotech 독립 이름공간
- 저장: h4_apewisdom_snapshots_{sha}.csv (append) + snapshot json 원본 별도
- 실행 형태: `python -m backend.scripts.biotech_h4_watcher --once` (단일 스냅샷) · cron 은 별도

⚠ 자매 프로젝트 활동 로직 재사용 금지 (H4 독립 격리 · B47)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx

APEWISDOM_BASE = "https://apewisdom.io/api/v1.0"

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

LOG = logging.getLogger("biotech_h4_watcher")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


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


def load_biotech_tickers(sha: str) -> set[str]:
    path = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if not path.exists():
        LOG.warning("biotech_ticker_set not found: %s", path)
        return set()
    out = set()
    with path.open() as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip()
            if t and t != "-":
                out.add(t.upper())
    return out


def main():
    require_secure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="단일 스냅샷만 수집 (cron 없이 검증용)")
    parser.add_argument("--filter", default="all-stocks", help="apewisdom filter (all-stocks/wallstreetbets/...)")
    parser.add_argument("--pages", type=int, default=3, help="수집 페이지 수 (rank ~300)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    biotech = load_biotech_tickers(sha)
    LOG.info("biotech ticker set: %d", len(biotech))

    snapshot_ts = datetime.now(timezone.utc).isoformat()
    biotech_hits = []
    all_mentions = 0
    with httpx.Client(
        headers={
            "User-Agent": "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)",
            "Accept": "application/json",
        }
    ) as client:
        for page in range(1, args.pages + 1):
            LOG.info("fetching page %d filter=%s", page, args.filter)
            url = f"{APEWISDOM_BASE}/filter/{args.filter}/page/{page}"
            try:
                r = client.get(url, timeout=30.0)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                LOG.error("page %d failed: %s", page, e)
                break
            for entry in data.get("results", []):
                all_mentions += 1
                t = (entry.get("ticker") or "").upper()
                if t in biotech:

                    def _int(v):
                        try:
                            return int(v)
                        except Exception:
                            return 0

                    mc = _int(entry.get("mentions"))
                    mp = _int(entry.get("mentions_24h_ago"))
                    biotech_hits.append(
                        {
                            "snapshot_ts": snapshot_ts,
                            "filter": args.filter,
                            "page": page,
                            "ticker": t,
                            "rank": _int(entry.get("rank")),
                            "mention_count_24h": mc,
                            "mentions_24h_ago": mp,
                            "upvotes": _int(entry.get("upvotes")),
                            "trend_up": mc > mp,
                        }
                    )
            if page >= data.get("pages", 1):
                break

    LOG.info("biotech hits: %d / total mentions scanned: %d", len(biotech_hits), all_mentions)

    # append
    out_path = DATA_DIR / f"h4_apewisdom_snapshots_{sha}.csv"
    exists = out_path.exists()
    with out_path.open("a", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "snapshot_ts",
                "filter",
                "page",
                "ticker",
                "rank",
                "mention_count_24h",
                "mentions_24h_ago",
                "upvotes",
                "trend_up",
            ],
        )
        if not exists:
            w.writeheader()
        w.writerows(biotech_hits)

    print(
        json.dumps(
            {
                "git_sha": sha,
                "snapshot_ts": snapshot_ts,
                "filter": args.filter,
                "pages_fetched": args.pages,
                "biotech_hits": len(biotech_hits),
                "distinct_biotech_tickers": len(set(h["ticker"] for h in biotech_hits)),
                "total_mentions_scanned": all_mentions,
                "csv_path": str(out_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
