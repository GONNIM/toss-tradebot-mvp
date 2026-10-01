"""WP90-2 · H6 규칙 (b) · 비만 테마 소속 종목 시점별 시총 (SEC companyfacts 최대 52회 승인 · 2026-10-01).

설계 (h6_params_v2.json pre_run_rules.b_obesity_mcap_split · 무변경):
- 시총 = 리밸런싱 분기 첫 영업일 adj_close × 발행주식수 (dei:EntityCommonStockSharesOutstanding · 그 시점 이전 최신 공시)
- 미확보 = unknown · '대형 제외' 열에서도 유지 (확인된 5B+ 만 제외)

시점 규칙 (미래 정보 차단): 제출일 (filed) ≤ 리밸런싱일 인 값 중 가장 최근 제출 공시 (accn) 하나
  · 그 공시 안 같은 기준일 (end) 값이 여럿이면 합산 (WP83-2 · 주식 종류 둘 이상)
SEC: biotech_sec_common.build_client() 단일 헤더 · 회사당 1회 · 403·429 즉시 중단 · 하루 장부 "h6_shares"
원문 캐시: backend/data/biotech/h6/companyfacts/CIK<10>.json (git 제외 · 다시 요청하지 않음)
산출: docs/plans/biotech/verification/H6/c3-20260928/h6_obesity_mcap_pit_20261001.csv
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
from datetime import date
from pathlib import Path

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_h6_window_coverage import GATE, MEMBERS, VER, q_first_bday, q_last_bday, qadd, qparse
from backend.scripts.biotech_sec_common import SecBlockedError, SecDailyLedger, build_client, sec_get

LOG = logging.getLogger("biotech_h6_obesity_mcap")
ROOT = Path(__file__).resolve().parents[2]
PRICES = ROOT / "backend/data/biotech/h6/h6_prices_tiingo_20261001.csv"
TICKERS = ROOT / "docs/plans/biotech/data/sec_company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
LARGE = 5_000_000_000
OUT = VER / "h6_obesity_mcap_pit_20261001.csv"


def shares_pit(facts: dict, on: str) -> dict | None:
    """제출일 ≤ on 인 dei 값 중 가장 최근 제출 공시 · 그 공시의 가장 늦은 기준일 값 합산."""
    node = (facts.get("facts", {}) or {}).get("dei", {}).get("EntityCommonStockSharesOutstanding")
    items = [i for i in ((node or {}).get("units", {}) or {}).get("shares", []) if i.get("val") is not None and i.get("filed", "") <= on]
    if not items:
        return None
    best_filed = max(i["filed"] for i in items)
    accn = max(i.get("accn", "") for i in items if i["filed"] == best_filed)
    same = [i for i in items if i.get("accn", "") == accn]
    end = max(i.get("end", "") for i in same)
    vals = [i for i in same if i.get("end", "") == end]
    return {"shares": sum(int(i["val"]) for i in vals), "filed": best_filed, "end": end, "accn": accn, "n_values": len(vals)}


def first_adj_close(rows: list[dict], start: date) -> tuple[str, float] | None:
    for r in rows:
        if r["date"] >= start.isoformat():
            return r["date"], float(r["adjClose"])
    return None


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    members = [m for m in csv.DictReader(MEMBERS.open()) if m["theme"] == "obesity_glp1"]
    entry = {}
    for m in members:
        entry[m["ticker"]] = min(entry.get(m["ticker"], m["entry_quarter"]), m["entry_quarter"])
    sec = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in json.loads(TICKERS.read_text()).values()}
    sec.setdefault("EOCN", "0001595353")
    prices: dict[str, list[dict]] = {}
    with PRICES.open() as f:
        for r in csv.DictReader(f):
            if r["ticker"] in entry:
                prices.setdefault(r["ticker"], []).append(r)
    for v in prices.values():
        v.sort(key=lambda r: r["date"])

    cache_dir = _P.out_dir("h6") / "companyfacts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ledger = SecDailyLedger.load()
    facts: dict[str, dict | None] = {}
    requests, blocked = 0, None
    client = build_client()
    try:
        for tk in sorted(entry):
            cik = sec.get(tk)
            if not cik:
                facts[tk] = None
                continue
            cp = cache_dir / f"CIK{cik}.json"
            if cp.exists():
                facts[tk] = json.loads(cp.read_text())
                continue
            if blocked:
                facts[tk] = None
                continue
            requests += 1
            ledger.add("h6_shares")
            try:
                r = sec_get(client, FACTS_URL.format(cik=cik))
            except SecBlockedError as e:
                blocked = str(e)
                facts[tk] = None
                LOG.error("SEC 차단 · %s · 즉시 중단", e)
                continue
            if r.get("status") == 429:
                blocked = "SEC HTTP 429"
                facts[tk] = None
                LOG.error("SEC 429 · 즉시 중단")
                continue
            if r.get("status") == 200 and r.get("json"):
                cp.write_text(json.dumps(r["json"]))
                facts[tk] = r["json"]
            else:
                facts[tk] = None
    finally:
        client.close()
        ledger.save()

    gate = json.loads(GATE.read_text())
    rows = []
    for g in gate:
        y, q = qparse(g["quarter"])
        ry, rq = qadd(y, q, 1)
        start = q_first_bday(ry, rq)
        qs, qe = q_first_bday(y, q), q_last_bday(y, q)
        for tk in sorted(entry):
            if entry[tk] > g["quarter"]:
                continue
            pr = prices.get(tk, [])
            if not pr or pr[0]["date"] > qe.isoformat() or pr[-1]["date"] < qs.isoformat():
                continue   # 그 분기 거래 중 아님 = 소속 아님
            px = first_adj_close(pr, start)
            sh = shares_pit(facts[tk], start.isoformat()) if facts.get(tk) else None
            mcap = px[1] * sh["shares"] if (px and sh) else None
            verdict = "unknown" if mcap is None else ("large_5b_plus" if mcap >= LARGE else "below_5b")
            rows.append({"ticker": tk, "rank_quarter": g["quarter"], "rebalance_date": px[0] if px else start.isoformat(),
                         "shares": sh["shares"] if sh else "", "shares_filed": sh["filed"] if sh else "",
                         "shares_end": sh["end"] if sh else "", "n_share_values": sh["n_values"] if sh else "",
                         "adj_close": round(px[1], 4) if px else "", "mcap_usd": round(mcap) if mcap else "", "verdict": verdict})
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    no_dei = sorted(tk for tk in entry if not facts.get(tk) or not (facts[tk].get("facts", {}).get("dei", {}).get("EntityCommonStockSharesOutstanding")))
    unk = sum(r["verdict"] == "unknown" for r in rows)
    print(json.dumps({"members": len(entry), "requests": requests, "blocked": blocked, "ledger_h6_shares": ledger.counts.get("h6_shares", 0),
                      "rows": len(rows), "unknown_rows": unk, "unknown_pct": round(unk / len(rows) * 100, 1),
                      "large_rows": sum(r["verdict"] == "large_5b_plus" for r in rows),
                      "no_dei_companies": no_dei, "no_dei_pct": round(len(no_dei) / len(entry) * 100, 1),
                      "out": str(OUT.relative_to(ROOT))}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
