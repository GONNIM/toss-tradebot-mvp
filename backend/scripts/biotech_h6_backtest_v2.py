"""WP90-2 · H6 본 백테스트 v2 (h6_params_v2.json 그대로 · 2026-10-01 승인).

1차 판정 (gate3_conditions.a_primary_decision):
  규칙 (a) 1안 · 분기 t 에 소속 < 3 인 주 테마 제외 → 남은 k 테마를 봉인 순위 (h6_rank_growth rank) 순으로
  상위 = 앞 max(1, round(k/3)) · 하위 = 뒤 같은 수 · k < 3 이면 그 분기 제외
  다중 테마 종목 = 그 분기 남은 테마 중 최고 순위 테마로 배정 (membership.multi_theme)
  보유 = 분기 t+1 첫 거래일 adj_close 진입 · 1분기 / 4분기 창 끝 거래일 adj_close · 동일 비중 · 왕복 비용 1.0%
  초과수익 = log(바구니 총수익) − log(XBI 총수익) − 비용 · 차이 = 상위 − 하위 (분기별)
  CI = 분기 클러스터 부트스트랩 (재추출 단위 = 분기 · seed 42 · 10,000회) · 보조 = iid (종목-분기 이벤트)
  통과 = 두 창 모두 CI 하한 > 0 · 한 창만 = 부분 지지 · 두 창 모두 ≤ 0 = 폐기
규칙 (b): 비만 테마 2열 = 전체 / 확인된 5B+ 제외 (unknown 유지) · 판정은 전체 열
참고: 기존 3분위 (h6_rank_growth tercile 그대로) 결과 병기 · 판정 미사용
외부 요청 0회 · 입력 = 봉인 CSV (summary.json input_seal)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date
from pathlib import Path

from backend.scripts.biotech_h6_window_coverage import GATE, MEMBERS, VER, q_first_bday, q_last_bday, qadd, qparse

ROOT = Path(__file__).resolve().parents[2]
PRICES = ROOT / "backend/data/biotech/h6/h6_prices_tiingo_20261001.csv"
BENCH = ROOT / "backend/data/biotech/h6/h6_benchmarks_tiingo_20261001.csv"
RANKS = ROOT / "backend/data/h6_rank_growth_add7af7.csv"
MCAP = VER / "h6_obesity_mcap_pit_20261001.csv"
SUMMARY = VER / "h6_prices_tiingo_20261001.summary.json"
OUT_Q = VER / "h6_backtest_v2_quarterly_20261001.csv"
OUT_SEAL = VER / "h6_backtest_v2_seal_20261001.json"
MAIN = ["obesity_glp1", "hair_loss", "longevity_rejuvenation", "meal_replacement_metabolic", "hibernation_hypothermia", "cognitive_memory"]
COST = 0.01
BOOT, SEED = 10_000, 42
MIN_MEMBERS = 3


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_series(path: Path) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with path.open() as f:
        for r in csv.DictReader(f):
            try:
                out[r["ticker"]][r["date"][:10]] = float(r["adjClose"])
            except (TypeError, ValueError):
                continue
    return out


def price_on_or_after(s: dict[str, float], cal: list[str], d: str) -> float | None:
    return s.get(d)


def main() -> None:
    require_secure_logging()
    seal = json.loads(SUMMARY.read_text())["input_seal"]
    assert sha256(PRICES) == seal["sha256"], "가격 CSV 해시가 봉인과 다름"
    assert sha256(BENCH) == seal["benchmarks"]["sha256"], "벤치마크 해시가 봉인과 다름"
    px = load_series(PRICES)
    xbi = load_series(BENCH)["XBI"]
    cal = sorted(xbi)                                   # 거래일 달력 = XBI 거래일
    last_day = cal[-1]
    ranks: dict[tuple[int, int], list[str]] = defaultdict(list)
    terc: dict[tuple[int, int, str], str] = {}
    tmp = defaultdict(list)
    for r in csv.DictReader(RANKS.open()):
        k = (int(r["year"]), int(r["quarter"]))
        tmp[k].append((int(r["rank"]), r["theme"]))
        terc[(k[0], k[1], r["theme"])] = r["tercile"]
    for k, v in tmp.items():
        ranks[k] = [t for _, t in sorted(v) if t in MAIN]
    members = list(csv.DictReader(MEMBERS.open()))
    rng = {t: (min(s), max(s)) for t, s in px.items()}
    large = {(r["ticker"], r["rank_quarter"]) for r in csv.DictReader(MCAP.open()) if r["verdict"] == "large_5b_plus"}
    unknown = {(r["ticker"], r["rank_quarter"]) for r in csv.DictReader(MCAP.open()) if r["verdict"] == "unknown"}

    def first_cal_on_or_after(d: date) -> str | None:
        s = d.isoformat()
        return next((c for c in cal if c >= s), None)

    def last_cal_on_or_before(d: date) -> str | None:
        s = d.isoformat()
        prev = [c for c in cal if c <= s]
        return prev[-1] if prev else None

    quarters = [g["quarter"] for g in json.loads(GATE.read_text())]
    events = []          # 종목-분기-창 단위
    qrows = []
    for qs in quarters:
        y, q = qparse(qs)
        qa, qb = q_first_bday(y, q).isoformat(), q_last_bday(y, q).isoformat()
        per: dict[str, set[str]] = defaultdict(set)
        for m in members:
            if m["theme"] in MAIN and m["entry_quarter"] <= qs and m["ticker"] in rng and rng[m["ticker"]][0] <= qb and rng[m["ticker"]][1] >= qa:
                per[m["theme"]].add(m["ticker"])
        order = ranks[(y, q)]
        elig = [t for t in order if len(per.get(t, set())) >= MIN_MEMBERS]
        ry, rq = qadd(y, q, 1)
        start = first_cal_on_or_after(q_first_bday(ry, rq))
        for method in ("rule_a1", "tercile_ref"):
            if method == "rule_a1":
                if len(elig) < 3:
                    qrows.append({"rank_quarter": qs, "method": method, "skipped": "k<3"})
                    continue
                n = max(1, round(len(elig) / 3))
                top, bot, ranked_themes = elig[:n], elig[-n:], elig
            else:
                top = [t for t in order if terc.get((y, q, t)) == "top"]
                bot = [t for t in order if terc.get((y, q, t)) == "bot"]
                ranked_themes = order
            assign: dict[str, str] = {}
            for t in ranked_themes:                       # 최고 순위 테마로 배정
                for tk in per.get(t, set()):
                    assign.setdefault(tk, t)
            for h in (1, 4):
                ey, eq = qadd(y, q, h)
                end = last_cal_on_or_before(q_last_bday(ey, eq))
                complete = start is not None and end is not None and q_last_bday(ey, eq).isoformat() <= last_day
                for col in ("full", "ex_large"):
                    row = {"rank_quarter": qs, "method": method, "horizon_q": h, "column": col, "entry": start, "exit": end,
                           "k_themes": len(elig), "top_themes": "|".join(top), "bot_themes": "|".join(bot)}
                    if not complete:
                        qrows.append({**row, "skipped": "window_incomplete"})
                        continue
                    xr = math.log(xbi[end] / xbi[start])
                    side_vals = {}
                    for side, themes in (("top", top), ("bot", bot)):
                        gross, tks = [], []
                        for tk, th in sorted(assign.items()):
                            if th not in themes:
                                continue
                            if col == "ex_large" and th == "obesity_glp1" and (tk, qs) in large:
                                continue
                            p0, p1 = px[tk].get(start), px[tk].get(end)
                            if not p0 or not p1:
                                continue
                            g = p1 / p0
                            gross.append(g)
                            tks.append((tk, th, g))
                            if col == "full":
                                events.append({"rank_quarter": qs, "method": method, "h": h, "side": side, "ticker": tk, "theme": th,
                                               "log_excess": math.log(g) - xr - COST, "gross": g, "xbi_gross": xbi[end] / xbi[start]})
                        side_vals[side] = (math.log(sum(gross) / len(gross)) - xr - COST) if gross else None
                        row[f"n_{side}"] = len(gross)
                        row[f"{side}_log_excess"] = round(side_vals[side], 6) if side_vals[side] is not None else ""
                        if side == "top" and gross:
                            xg = xbi[end] / xbi[start]
                            by = defaultdict(list)
                            for tk, th, g in tks:
                                by[th].append(g)
                            row["top_contrib"] = json.dumps({th: round(len(v) / len(gross) * (sum(v) / len(v) - xg), 6) for th, v in by.items()})
                            row["top_names"] = " ".join(sorted(t for t, _, _ in tks))
                        if side == "bot" and gross:
                            row["bot_names"] = " ".join(sorted(t for t, _, _ in tks))
                    if side_vals.get("top") is not None and side_vals.get("bot") is not None:
                        row["diff"] = round(side_vals["top"] - side_vals["bot"], 6)
                    else:
                        row["skipped"] = "empty_basket"
                    qrows.append(row)

    fields = ["rank_quarter", "method", "horizon_q", "column", "entry", "exit", "k_themes", "top_themes", "bot_themes",
              "n_top", "n_bot", "top_log_excess", "bot_log_excess", "diff", "top_contrib", "top_names", "bot_names", "skipped"]
    with OUT_Q.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in qrows:
            w.writerow({k: r.get(k, "") for k in fields})

    def cluster_ci(vals: list[float]) -> tuple[float, float]:
        rnd = random.Random(SEED)
        n = len(vals)
        means = sorted(sum(vals[rnd.randrange(n)] for _ in range(n)) / n for _ in range(BOOT))
        return round(means[int(0.025 * BOOT)], 6), round(means[int(0.975 * BOOT) - 1], 6)

    def iid_ci(top: list[float], bot: list[float]) -> tuple[float, float]:
        rnd = random.Random(SEED)
        d = []
        for _ in range(BOOT):
            a = sum(top[rnd.randrange(len(top))] for _ in range(len(top))) / len(top)
            b = sum(bot[rnd.randrange(len(bot))] for _ in range(len(bot))) / len(bot)
            d.append(a - b)
        d.sort()
        return round(d[int(0.025 * BOOT)], 6), round(d[int(0.975 * BOOT) - 1], 6)

    res: dict = {"input_seal": seal, "params": "docs/plans/biotech/data/h6_params_v2.json (무변경)", "boot": BOOT, "seed": SEED,
                 "cost_round_trip": COST, "results": {}}
    for method in ("rule_a1", "tercile_ref"):
        for col in ("full", "ex_large"):
            for h in (1, 4):
                rows = [r for r in qrows if r.get("method") == method and r.get("column") == col and r.get("horizon_q") == h and "diff" in r and not r.get("skipped")]
                diffs = [r["diff"] for r in rows]
                key = f"{method}|{col}|{h}Q"
                out = {"quarters": len(diffs), "mean_diff": round(sum(diffs) / len(diffs), 6) if diffs else None,
                       "cluster_ci95": cluster_ci(diffs) if len(diffs) >= 2 else None,
                       "top_mean": round(sum(r["top_log_excess"] for r in rows) / len(rows), 6) if rows else None,
                       "bot_mean": round(sum(r["bot_log_excess"] for r in rows) / len(rows), 6) if rows else None,
                       "quarters_top_beats_bot": sum(d > 0 for d in diffs)}
                if col == "full":
                    ev_t = [e["log_excess"] for e in events if e["method"] == method and e["h"] == h and e["side"] == "top"]
                    ev_b = [e["log_excess"] for e in events if e["method"] == method and e["h"] == h and e["side"] == "bot"]
                    out["iid_events"] = {"n_top": len(ev_t), "n_bot": len(ev_b), "ci95": iid_ci(ev_t, ev_b) if ev_t and ev_b else None}
                res["results"][key] = out
    def verdict(method: str, col: str) -> str:
        lows = [res["results"][f"{method}|{col}|{h}Q"]["cluster_ci95"][0] for h in (1, 4)]
        passed = [lo > 0 for lo in lows]
        return "알파 통과" if all(passed) else ("부분 지지" if any(passed) else "폐기")
    res["verdict_primary_full"] = verdict("rule_a1", "full")
    res["verdict_ex_large_observe"] = verdict("rule_a1", "ex_large")
    res["verdict_tercile_reference"] = verdict("tercile_ref", "full")
    # 테마별 기여 (1차 · 전체 열 · 상위 묶음) · 분기 평균
    contrib = {}
    for h in (1, 4):
        acc = defaultdict(float)
        rows = [r for r in qrows if r.get("method") == "rule_a1" and r.get("column") == "full" and r.get("horizon_q") == h and r.get("top_contrib")]
        for r in rows:
            for th, v in json.loads(r["top_contrib"]).items():
                acc[th] += v / len(rows)
        contrib[f"{h}Q"] = {th: round(v, 6) for th, v in sorted(acc.items(), key=lambda kv: -abs(kv[1]))}
    res["top_basket_theme_contribution_simple_excess_mean"] = contrib
    res["unknown_mcap_rows"] = len(unknown)
    OUT_SEAL.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in res.items() if k not in ("input_seal",)}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
