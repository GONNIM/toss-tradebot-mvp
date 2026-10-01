"""WP90 · H6 창 커버 판정식 v2.1 (외부 요청 0회 · 로컬 자료만).

판정식 원문 (docs/plans/biotech/B83-collection-plan.md · h6_params_v2.json price_collection.coverage_report):
    first_bar ≤ 창시작 + 7일 AND last_bar ≥ event − 30일
H6 적용: 창시작 = 리밸런싱 분기 (순위 분기 t 의 다음 분기) 첫 영업일 · event = 보유 창 종료일 (t+h 분기 마지막 영업일) · h ∈ {1, 4}

대상 = 순위 분기 t (h6_gate_per_quarter_v2 의 42 분기) 마다 소속 종목 (편입 분기 ≤ t AND t 에 거래 중) · 테마 무관 종목 단위
기존 17종목 가격은 2020-01-02 부터만 있음 → 2020 이전 분기는 h3_source_before_2020 으로 따로 셈 (거래 여부 미확인)
가격 = Tiingo 59 (backend/data/biotech/h6/h6_prices_tiingo_20261001.csv) + 기존 17 (backend/data/h3_prices_merged_add7af7.csv)
보유 창 종료일이 오늘 이후면 "미완료" 로 따로 셈 (통과·실패에 넣지 않음)

산출: docs/plans/biotech/verification/H6/c3-20260928/h6_window_coverage_v21_20261001.csv (분기별)
      · 같은 이름 _by_ticker.csv (종목별 제외 창 수)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VER = ROOT / "docs/plans/biotech/verification/H6/c3-20260928"
MEMBERS = ROOT / "backend/data/biotech/h6/h6_membership_v2_2026-09-28.csv"
TIINGO = ROOT / "backend/data/biotech/h6/h6_prices_tiingo_20261001.csv"
H3 = ROOT / "backend/data/h3_prices_merged_add7af7.csv"
GATE = VER / "h6_gate_per_quarter_v2_2026-09-28.json"
TODAY = date(2026, 10, 1)
H3_START = date(2020, 1, 2)   # 기존 17종목 가격 (yfinance) 의 시작일 · 이전 분기는 거래 여부를 알 수 없음


def qparse(s: str) -> tuple[int, int]:
    return int(s[:4]), int(s[-1])


def qadd(y: int, q: int, n: int) -> tuple[int, int]:
    k = y * 4 + (q - 1) + n
    return k // 4, k % 4 + 1


def q_first_bday(y: int, q: int) -> date:
    d = date(y, 3 * (q - 1) + 1, 1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def q_last_bday(y: int, q: int) -> date:
    ny, nq = qadd(y, q, 1)
    d = date(ny, 3 * (nq - 1) + 1, 1) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def bar_ranges() -> dict[str, tuple[date, date]]:
    rng: dict[str, list[str]] = {}
    for path, col in ((TIINGO, "date"), (H3, "date")):
        with path.open() as f:
            for r in csv.DictReader(f):
                d = r[col][:10]
                cur = rng.setdefault(r["ticker"], [d, d])
                cur[0], cur[1] = min(cur[0], d), max(cur[1], d)
    return {t: (date.fromisoformat(a), date.fromisoformat(b)) for t, (a, b) in rng.items()}


def main(low_list: list[str]) -> None:
    require_secure_logging()
    gate = json.loads(GATE.read_text())
    quarters = [g["quarter"] for g in gate]
    members = list(csv.DictReader(MEMBERS.open()))
    entry: dict[str, str] = {}
    for m in members:
        entry[m["ticker"]] = min(entry.get(m["ticker"], m["entry_quarter"]), m["entry_quarter"])
    rng = bar_ranges()
    tiingo_set = {r["ticker"] for r in csv.DictReader(TIINGO.open())}
    h3_only = {t for t in entry if t not in tiingo_set}
    rows, by_tk = [], defaultdict(lambda: {"h1_fail": 0, "h4_fail": 0, "h1_n": 0, "h4_n": 0})
    for qs in quarters:
        y, q = qparse(qs)
        ry, rq = qadd(y, q, 1)
        start = q_first_bday(ry, rq)
        qstart, qend = q_first_bday(y, q), q_last_bday(y, q)
        listed = sorted(t for t, e in entry.items() if e <= qs)
        # 소속 규칙 (h6_params_v2 membership.point_in_time) · 분기 t 에 거래 중 (가격 자료의 첫·마지막 거래일 기준) 인 종목만
        tks = [t for t in listed if t in rng and rng[t][0] <= qend and rng[t][1] >= qstart]
        h3_cut = [t for t in listed if t not in tks and t in h3_only and qend < H3_START]
        row = {"rank_quarter": qs, "rebalance_start": start.isoformat(), "entered": len(listed),
               "not_trading": len(listed) - len(tks) - len(h3_cut), "h3_source_before_2020": len(h3_cut), "members": len(tks)}
        for h in (1, 4):
            ey, eq = qadd(y, q, h)
            end = q_last_bday(ey, eq)
            row[f"h{h}_end"] = end.isoformat()
            if end > TODAY:
                row[f"h{h}_pass"], row[f"h{h}_fail"], row[f"h{h}_incomplete"] = 0, 0, len(tks)
                continue
            ok = fail = 0
            for t in tks:
                fb, lb = rng.get(t, (None, None))
                passed = fb is not None and fb <= start + timedelta(days=7) and lb >= end - timedelta(days=30)
                ok += passed
                fail += not passed
                by_tk[t][f"h{h}_n"] += 1
                by_tk[t][f"h{h}_fail"] += not passed
            row[f"h{h}_pass"], row[f"h{h}_fail"], row[f"h{h}_incomplete"] = ok, fail, 0
        rows.append(row)
    out = VER / "h6_window_coverage_v21_20261001.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    out2 = VER / "h6_window_coverage_v21_20261001_by_ticker.csv"
    with out2.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "entry_quarter", "first_bar", "last_bar", "price_source", "h1_windows", "h1_excluded", "h4_windows", "h4_excluded"])
        tiingo = tiingo_set
        for t in sorted(entry):
            fb, lb = rng.get(t, (None, None))
            v = by_tk[t]
            w.writerow([t, entry[t], fb, lb, "tiingo" if t in tiingo else "h3_yfinance", v["h1_n"], v["h1_fail"], v["h4_n"], v["h4_fail"]])
    tot = {k: sum(r[k] for r in rows) for k in ("entered", "not_trading", "h3_source_before_2020", "members", "h1_pass", "h1_fail",
                                                "h1_incomplete", "h4_pass", "h4_fail", "h4_incomplete")}
    print(json.dumps({"quarters": len(rows), **tot, "out": str(out.relative_to(ROOT)), "by_ticker": str(out2.relative_to(ROOT)),
                      "low12": {t: (by_tk[t]["h1_fail"], by_tk[t]["h4_fail"]) for t in low_list}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1].split(",") if len(sys.argv) > 1 else [])
