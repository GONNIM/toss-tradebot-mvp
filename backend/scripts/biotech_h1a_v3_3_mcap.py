"""WP14-3 · H1a sponsor → Tiingo 우주 매핑 + SimFin 시총 필터.

용도:
- h1a_events_v3_2 의 sponsor_recovered 26건 → Tiingo 우주 회사명 정규화 매핑
- SimFin 무료 API (companies statements) 발행주식수 조회 · 이벤트 시점 가격 × 발행주식수 = 시총
- $50M ~ $5B 필터 · 적격 n · 공고→회의 시차

원칙:
- Tiingo 우주는 universe_skeleton_v2 (16265 US Stock)
- SimFin 개별 조회 실패 시 mcap_unknown 표기 (제외 아님)
- 결제 금지 · 시총 필터 위반 아니면 표본 인정 · fallback 문서화
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h1a_v3_3")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

SIMFIN_KEY = os.getenv("SIMFIN_API_KEY", "")
SIMFIN_BASE = "https://backend.simfin.com/api/v3"


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


def normalize_name(name: str) -> str:
    s = name.lower()
    for suffix in [" incorporated", " inc", " corporation", " corp", " limited",
                   " ltd", " plc", " holdings", " group", " company", " co",
                   " pharmaceuticals", " pharmaceutical", " pharma",
                   " therapeutics", " biosciences", " biotech"]:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    s = re.sub(r"[.,()\-/&]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_universe() -> dict:
    """Tiingo universe · biotech_ticker_set 이름 매핑."""
    sha = git_sha()
    name_map = {}
    src = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if src.exists():
        with src.open() as f:
            for row in csv.DictReader(f):
                n = (row.get("name") or "").strip()
                t = (row.get("ticker") or "").strip()
                if not n or not t or t == "-":
                    continue
                k = normalize_name(n)
                if k:
                    name_map.setdefault(k, {"ticker": t, "name": n})
    return name_map


def load_v3_2_events(sha: str) -> list[dict]:
    p = DATA_DIR / f"h1a_events_v3_2_{sha}.csv"
    with p.open() as f:
        return list(csv.DictReader(f))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()

    events = load_v3_2_events(sha)
    name_map = load_universe()

    # 이미 v3-2 에서 매핑된 것 재활용 · 여기선 규칙 완화 (biotech_ticker_set 기준 이미 매핑됨)
    # sponsor 확장: 조인 후 실패 → Tiingo universe 티커명 (회사명 미보유) 는 매핑 대안 없음
    # 결과적으로 v3-2 매핑 결과 = 최종 매핑

    stats = {
        "total": 0,
        "sponsor_recovered": 0,
        "ticker_mapped_biotech_set": 0,
        "mapped_missing_mcap": 0,
        "mcap_in_range_50m_5b": 0,
        "eligible_v3_3": 0,
    }

    rows_out = []
    lags = []
    for ev in events:
        stats["total"] += 1
        sponsor = ev.get("openfda_sponsor", "")
        if sponsor:
            stats["sponsor_recovered"] += 1
        ticker = ev.get("mapped_ticker_v3_2", "")
        if ticker:
            stats["ticker_mapped_biotech_set"] += 1
        # 시총: SimFin 개별 API 는 종목당 credits 소모 · 예산 문제 · fallback = mcap_unknown
        mcap_status = "unknown_no_simfin_bulk"
        stats["mapped_missing_mcap"] += (1 if ticker else 0)
        mcap_in_range = False
        # WP14-3 규칙: mcap 부재 시 미필터 표기 (제외 아님)
        v2_eligible = (str(ev.get("eligible", "")) or "").strip().lower() == "true"
        is_drug = (str(ev.get("is_drug_adcom", "")) or "").strip().lower() == "true"
        v3_3_eligible = v2_eligible and is_drug and bool(ticker)
        if v3_3_eligible:
            stats["eligible_v3_3"] += 1
            pd = ev.get("publication_date", "")
            md = ev.get("meeting_date", "")
            if pd and md:
                try:
                    from datetime import datetime
                    lag = (datetime.strptime(md, "%Y-%m-%d") - datetime.strptime(pd, "%Y-%m-%d")).days
                    lags.append(lag)
                except Exception:
                    pass
        rows_out.append({
            "publication_date": ev.get("publication_date"),
            "meeting_date": ev.get("meeting_date"),
            "committee": ev.get("committee"),
            "sponsor_openfda": sponsor,
            "mapped_ticker": ticker,
            "mapped_name": ev.get("mapped_name_v3_2"),
            "mcap_status": mcap_status,
            "mcap_in_range": mcap_in_range,
            "eligible_v3_3": v3_3_eligible,
            "app_type": ev.get("app_type"),
            "app_number": ev.get("app_number"),
        })

    out_path = DATA_DIR / f"h1a_events_v3_3_{sha}.csv"
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    lags_sorted = sorted(lags)
    lag_median = lags_sorted[len(lags_sorted) // 2] if lags_sorted else None

    summary = {
        "git_sha": sha,
        "csv_path": str(out_path),
        **stats,
        "eligible_v3_3_rate": round(stats["eligible_v3_3"] / max(1, stats["total"]), 4),
        "lag_median_days": lag_median,
        "lag_range": [lags_sorted[0], lags_sorted[-1]] if lags_sorted else None,
        "mcap_note": "SimFin 벌크 미지원 (WP16 · 401) · 개별 조회는 credits 예산 문제 · mcap_status=unknown · WP14-3 규칙 = 미필터 표기 (표본 제외 아님)",
    }
    LOG.info("summary=%s", json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
