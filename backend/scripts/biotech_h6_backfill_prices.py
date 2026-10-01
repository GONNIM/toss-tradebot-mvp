"""WP90-2 · H6 가격 보충 (Tiingo 19회 승인 · 2026-10-01) · 벤치마크 XBI · IWM + 기존 17종목 전 기간.

- 수집기 biotech_h6_collect_prices.run() 그대로 (1종목 1호출 · 2014-10-01 ~ 오늘 · 장부 시간당 50회 · 월 고유 · 403·429 즉시 중단)
- 벤치마크 → backend/data/biotech/h6/h6_benchmarks_tiingo_<YYYYMMDD>.csv
- 17종목 → 같은 날 h6_prices_tiingo_<YYYYMMDD>.csv 에 합침 (이미 있는 종목 행은 바꾸지 않음)
- 합친 뒤 SHA-256 재계산 · summary.json input_seal 갱신 (이전 값은 input_seal_history 에 보존)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_h6_collect_prices as h6

LOG = logging.getLogger("biotech_h6_backfill_prices")
BENCH = ["XBI", "IWM"]
LEGACY17 = ["ACRS", "ALGS", "BIOA", "BMEA", "CGTX", "CRBP", "ENTA", "LEXX", "MBX", "MDGL", "OPK", "RANI", "RYTM",
            "SGMT", "SKYE", "TLSA", "VTVT"]


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    key = (os.environ.get("TIINGO_API_KEY") or "").strip()
    if not key:
        raise SystemExit("TIINGO_API_KEY 없음")
    today = datetime.now(timezone(timedelta(hours=9))).date()
    client = httpx.Client(timeout=60)
    res = h6.run(BENCH + LEGACY17, key, client.get, today)
    client.close()
    del key
    bars = res.pop("bars")
    hdir = _P.out_dir("h6")
    bench_out = hdir / f"h6_benchmarks_tiingo_{today:%Y%m%d}.csv"
    with bench_out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=h6.CSV_FIELDS)
        w.writeheader()
        for t in BENCH:
            w.writerows(bars.get(t, []))
    main_csv = hdir / f"h6_prices_tiingo_{today:%Y%m%d}.csv"
    existing = h6.load_bars_csv(main_csv)
    added = [t for t in LEGACY17 if bars.get(t) and t not in existing]
    with main_csv.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=h6.CSV_FIELDS)
        for t in added:
            w.writerows(bars[t])
    new_sha = sha256(main_csv)
    summary_paths = [main_csv.with_suffix(".summary.json"),
                     h6.targets_path().parent / f"h6_prices_tiingo_{today:%Y%m%d}.summary.json"]
    for p in summary_paths:
        s = json.loads(p.read_text())
        hist = s.get("input_seal_history", [])
        if s.get("input_seal"):
            hist.append(s["input_seal"])
        s["input_seal_history"] = hist
        s["input_seal"] = {"file": "backend/data/biotech/h6/h6_prices_tiingo_20261001.csv", "sha256": new_sha,
                           "sealed": f"{datetime.now(timezone(timedelta(hours=9))):%Y-%m-%d %H:%M} WP90-2 · 기존 17종목 전 기간 합친 뒤",
                           "benchmarks": {"file": "backend/data/biotech/h6/h6_benchmarks_tiingo_20261001.csv",
                                          "sha256": sha256(bench_out)}}
        s["backfill_wp90_2"] = {k: res[k] for k in ("requests", "success", "failed", "not_attempted", "blocked",
                                                     "monthly_unique_used", "monthly_remaining")}
        s["backfill_wp90_2"]["first_bar_date"] = res.get("first_bar_date")
        s["backfill_wp90_2"]["merged_tickers"] = added
        p.write_text(json.dumps(s, ensure_ascii=False, indent=2))
    print(json.dumps({**{k: res[k] for k in ("requests", "success", "failed", "blocked", "monthly_unique_used")},
                      "merged": len(added), "bench_rows": sum(len(bars.get(t, [])) for t in BENCH),
                      "first_bar_date": res.get("first_bar_date"), "sha256": new_sha}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
