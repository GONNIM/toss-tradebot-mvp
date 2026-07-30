#!/usr/bin/env python3
"""Toss Tradebot Wiki sync · Phase C 주 6 · 2026-07-30.

참조: docs/plans/toss-tradebot-tobe/stage2-architecture.md §4-5
      docs/plans/toss-tradebot-tobe/reviews/perspective-c-knowledge-assetization.md 권고 6
      패턴: /Users/gonnim/GON-Dev/gonnim-landing/scripts/sync-kickoff.ts

로컬 macOS 실행 · 서버 배포 무관.

경로 3개 (본 세션 · Weekly + Tickers 우선 · Runs 는 서버측 훅 신설 필요):
    Weekly/{YYYY-Www}.md   — 매주 일 08:00 KST · 이번 주 tier 이동 요약
    Tickers/{ticker}.md    — tier 변경 감지된 종목별 append

Runs/{run_id}.md 는 다음 세션 or 서버측 훅 (run 종료 훅 · POST → local webhook).

사용:
    python3 scripts/sync_wiki.py --dry-run                    # 실 write 없이 프리뷰
    python3 scripts/sync_wiki.py --target weekly              # 주간만
    python3 scripts/sync_wiki.py --target tickers             # 종목별만
    python3 scripts/sync_wiki.py                              # 전체

crontab 등록 예 (매주 일 08:00 KST):
    0 8 * * 0 cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp && \
        /usr/bin/python3 scripts/sync_wiki.py >> ~/.cache/toss-tradebot-sync.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import httpx  # type: ignore
except ImportError:
    print("ERROR: httpx 미설치 · brew install python3 후 pip3 install httpx", file=sys.stderr)
    sys.exit(1)


WIKI_ROOT = Path("/Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP")
API_BASE = "https://optimus8.cafe24.com/api/v1"

MARKER_START = "<!-- WIKI_SYNC:START -->"
MARKER_END = "<!-- WIKI_SYNC:END -->"

WEEKLY_HEADER = """# {year_week} · Toss Tradebot 주간 요약

> **자동 동기화** by `scripts/sync_wiki.py` · **수동 편집 시 다음 sync 에 덮어씀** ({start} 사이 영역)
> 참조: docs/plans/toss-tradebot-tobe/sprint-revenue-integration.md §2 (Weekly Report)
> 정보 제공만 · 투자 권유 아님

## 이번 주 Tier 이동 이벤트

{marker_start}
{body}
{marker_end}
"""

TICKER_HEADER = """# {ticker} · Toss Tradebot 종목 노트

> **자동 append** by `scripts/sync_wiki.py` (Tier 이동 시)
> 상단 요약 · 하단 시계열 (오래된 순 → 최신)
> 정보 제공만 · 투자 권유 아님

## 최근 Tier 이동

{marker_start}
{body}
{marker_end}
"""


def fetch(url: str) -> Any:
    with httpx.Client(timeout=20) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.json()


def fmt_dt(iso: str) -> str:
    return iso.replace("T", " ").split(".")[0]


def sync_weekly(dry_run: bool) -> int:
    """이번 주 tier 이동 요약 → Weekly/{YYYY-Www}.md."""
    now = datetime.now()
    year_week = now.strftime("%Y-W%V")  # ISO week
    target = WIKI_ROOT / "Weekly" / f"{year_week}.md"

    events = fetch(f"{API_BASE}/insights/tier-history/recent?days=7&limit=100")

    if not events:
        body = "이번 주 tier 이동 이벤트 없음."
    else:
        lines = [
            f"| 시각 | 종목 | 이전 → 현재 | 유형 | 비고 |",
            f"|---|---|---|---|---|",
        ]
        for e in events:
            prev = e.get("prev_tier") or "—"
            curr = e.get("curr_tier")
            note = (e.get("note") or "").replace("|", "\\|")
            lines.append(
                f"| {fmt_dt(e['changed_at'])} | {e['ticker']} | {prev} → {curr} | "
                f"{e['change_type']} | {note} |"
            )
        body = "\n".join(lines)

    content = WEEKLY_HEADER.format(
        year_week=year_week,
        start=MARKER_START,
        marker_start=MARKER_START,
        body=body,
        marker_end=MARKER_END,
    )

    return _write(target, content, dry_run)


def sync_tickers(dry_run: bool) -> int:
    """tier 이동 감지된 종목별 파일 upsert."""
    events = fetch(f"{API_BASE}/insights/tier-history/recent?days=7&limit=200")

    tickers: set[str] = {e["ticker"] for e in events}
    updated = 0
    for ticker in sorted(tickers):
        history = fetch(f"{API_BASE}/insights/tier-history/{ticker}?limit=50")
        lines = [
            f"| 시각 | 이전 → 현재 | 유형 | 가설 | 비고 |",
            f"|---|---|---|---|---|",
        ]
        for h in history:
            prev = h.get("prev_tier") or "—"
            curr = h.get("curr_tier")
            hyp = h.get("hypothesis_id") or "—"
            note = (h.get("note") or "").replace("|", "\\|")
            lines.append(
                f"| {fmt_dt(h['changed_at'])} | {prev} → {curr} | "
                f"{h['change_type']} | {hyp} | {note} |"
            )
        body = "\n".join(lines) if history else "tier 이동 이력 없음."
        content = TICKER_HEADER.format(
            ticker=ticker,
            start=MARKER_START,
            marker_start=MARKER_START,
            body=body,
            marker_end=MARKER_END,
        )
        target = WIKI_ROOT / "Tickers" / f"{ticker}.md"
        if _write(target, content, dry_run):
            updated += 1
    return updated


def _write(target: Path, content: str, dry_run: bool) -> int:
    """실 write · 기존 파일 있으면 마커 영역만 교체 · 없으면 통째로 생성."""
    if target.exists():
        old = target.read_text(encoding="utf-8")
        if MARKER_START in old and MARKER_END in old:
            before = old.split(MARKER_START, 1)[0]
            after = old.split(MARKER_END, 1)[1]
            new_body = content.split(MARKER_START, 1)[1].split(MARKER_END, 1)[0]
            new_content = f"{before}{MARKER_START}{new_body}{MARKER_END}{after}"
        else:
            new_content = content
    else:
        new_content = content

    if dry_run:
        print(f"[dry-run] {target} · {len(new_content)} bytes")
        return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    print(f"[write] {target}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="실 write 없이 프리뷰")
    parser.add_argument(
        "--target",
        choices=["weekly", "tickers", "all"],
        default="all",
    )
    args = parser.parse_args()

    if not WIKI_ROOT.exists():
        print(f"ERROR: WIKI_ROOT 없음: {WIKI_ROOT}", file=sys.stderr)
        return 1

    started = datetime.now()
    print(f"[sync] start · target={args.target} · dry_run={args.dry_run}")

    total = 0
    try:
        if args.target in ("weekly", "all"):
            total += sync_weekly(args.dry_run)
        if args.target in ("tickers", "all"):
            total += sync_tickers(args.dry_run)
    except httpx.HTTPError as e:
        print(f"[sync] API 실패: {e}", file=sys.stderr)
        return 2

    elapsed = (datetime.now() - started).total_seconds()
    print(f"[sync] done · files={total} · elapsed={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
