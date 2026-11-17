"""1112-03 · 배포 전 비교 · 새 코드(공식 API)로 받은 결과를 11/12 사본(AACT)과 대조한다 (계획 5절 기준 1~7).

사용 (이 맥 · 서버 안 건드림 · 공개 API 에 후보 이름을 보내므로 계획 5절 단계에서 메인이 한 번만 실행):
    PYTHONPATH=. backend/venv/bin/python -m backend.scripts.biotech_ctgov_compare \
        <11/12 사본 ctgov_snapshot_20261112.json> <후보 CSV biotech_candidates_v3_*.csv> <출력 폴더>

출력 폴더(저장소 밖 scratchpad 로 지정할 것 · 종목 · 금액이 들어 있어 공개 저장소에 올리면 안 됨):
    compare_result.json · compare_report.md · new_snapshot_preview.json
저장소의 ctgov_snapshot.json · 날짜별 사본 · 알림은 건드리지 않는다.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from backend.scripts import biotech_ctgov_api as api
from backend.scripts import biotech_h69_aact_weekly as w

LOG = logging.getLogger("biotech_ctgov_compare")

SKIP_FIELDS = {"ticker", "nct_id", "role", "match_method", "days_to"}   # 4 · 5 절에서 따로 보거나 날짜에 따라 달라지는 칸
DATE_STATUS_FIELDS = {"overall_status", "primary_completion_date", "primary_completion_date_type",
                      "completion_date", "completion_date_type", "last_update_posted_date"}
ORDERED_LIST_FIELDS = {"conditions", "mesh_terms"}


def load_candidates(path: Path) -> dict[str, str]:
    with path.open() as f:
        return {(r.get("ticker") or "").strip(): (r.get("name") or "").strip()
                for r in csv.DictReader(f) if (r.get("ticker") or "").strip() and (r.get("name") or "").strip()}


def nearest_upcoming(matches: list[dict], ref: date) -> dict[str, tuple[str, str]]:
    """종목별 lead 시험 가운데 1차 완료일이 ref 이후인 가장 가까운 (날짜 · NCT)."""
    best: dict[str, tuple[str, str]] = {}
    for m in matches:
        d = m.get("primary_completion_date") or ""
        if m.get("role") != "lead" or not d or d < ref.isoformat():
            continue
        cur = best.get(m["ticker"])
        if cur is None or (d, m["nct_id"]) < cur:
            best[m["ticker"]] = (d, m["nct_id"])
    return best


def compare(old: dict, new_matches: list[dict], new_counts: dict, raw_ncts: set[str], ref: date) -> dict:
    om = {m["nct_id"]: m for m in old.get("matches", [])}
    nm = {m["nct_id"]: m for m in new_matches}
    res: dict = {"old_study": len(om), "new_study": len(nm), "ref_date": ref.isoformat()}

    # 1) lead 이고 days_to 0 이상인 시험은 전부 다시 잡혀야 한다
    must = [n for n, m in om.items() if m.get("role") == "lead" and (m.get("days_to") is not None and m["days_to"] >= 0)]
    missing = []
    for n in sorted(must):
        if n in nm and nm[n].get("role") == "lead" and nm[n]["ticker"] == om[n]["ticker"]:
            continue
        why = ("받은 결과에 없음 (검색에 안 걸림)" if n not in raw_ncts
               else "받았으나 맞추기 규칙에서 버려짐" if n not in nm
               else f"다시 잡혔으나 종목·역할이 다름 ({nm[n]['ticker']} · {nm[n]['role']})")
        missing.append({"nct_id": n, "ticker": om[n]["ticker"], "reason": why})
    res["c1_lead_upcoming_total"] = len(must)
    res["c1_missing"] = missing
    res["c1_pass"] = not missing

    # 2) 전체 NCT 95% 이상
    got = [n for n in om if n in nm]
    res["c2_recapture"] = len(got)
    res["c2_ratio"] = round(len(got) / len(om), 4) if om else 0.0
    res["c2_pass"] = res["c2_ratio"] >= 0.95
    res["c2_missing_not_in_raw"] = sorted(n for n in om if n not in nm and n not in raw_ncts)
    res["c2_missing_rule_dropped"] = sorted(n for n in om if n not in nm and n in raw_ncts)

    # 3) 종목 집합
    ot, nt = {m["ticker"] for m in om.values()}, {m["ticker"] for m in nm.values()}
    res["c3_old_tickers"], res["c3_new_tickers"] = len(ot), len(nt)
    res["c3_only_old"], res["c3_only_new"] = sorted(ot - nt), sorted(nt - ot)
    res["c3_pass"] = ot == nt

    # 4) 종목별 가장 가까운 예정 시험 · sponsor_active_counts
    on, nn = nearest_upcoming(list(om.values()), ref), nearest_upcoming(new_matches, ref)
    diff_near = {t: {"old": on.get(t), "new": nn.get(t)} for t in sorted(set(on) | set(nn)) if on.get(t) != nn.get(t)}
    def _ns(d):   # NCT 목록은 순서가 아니라 집합으로 본다 (AACT 는 파일 순서 · 새 코드는 번호 순)
        return {k: ({**v, "lead_phase2_plus_ncts": sorted(v.get("lead_phase2_plus_ncts") or [])} if isinstance(v, dict) else v)
                for k, v in (d or {}).items()}
    oc, nc = _ns(old.get("sponsor_active_counts", {})), _ns(new_counts)
    diff_cnt = {t: {"old": oc.get(t), "new": nc.get(t)} for t in sorted(set(oc) | set(nc)) if oc.get(t) != nc.get(t)}
    res["c4_nearest_diff"], res["c4_active_counts_diff"] = diff_near, diff_cnt
    res["c4_pass"] = not diff_near and not diff_cnt

    # 5) NCT 별 ticker · role
    diff_role = {n: {"old": [om[n]["ticker"], om[n]["role"]], "new": [nm[n]["ticker"], nm[n]["role"]]}
                 for n in sorted(got) if (om[n]["ticker"], om[n]["role"]) != (nm[n]["ticker"], nm[n]["role"])}
    res["c5_diff"] = diff_role
    res["c5_pass"] = not diff_role

    # 6) 같은 NCT 의 칸 값 차이 · 칸별 개수와 목록 (11/12 뒤 갱신으로 인정되는 날짜 · 상태 차이는 따로 센다)
    by_field: dict[str, list] = {}
    updated_ok: dict[str, int] = {}
    for n in sorted(got):
        o, x = om[n], nm[n]
        recently = (x.get("last_update_posted_date") or "") >= ref.isoformat()   # 11/12 사본은 그날 갱신 전 자료일 수 있어 같은 날도 갱신으로 본다
        for k in sorted((set(o) | set(x)) - SKIP_FIELDS):
            if o.get(k) == x.get(k):
                continue
            if k in DATE_STATUS_FIELDS and recently:
                updated_ok[k] = updated_ok.get(k, 0) + 1
                continue
            row = {"nct_id": n, "old": o.get(k), "new": x.get(k)}
            if k in ORDERED_LIST_FIELDS and isinstance(o.get(k), list) and isinstance(x.get(k), list):
                row["same_set_different_order"] = sorted(o[k]) == sorted(x[k])
            by_field.setdefault(k, []).append(row)
    res["c6_counts"] = {k: len(v) for k, v in by_field.items()}
    res["c6_updated_after_ref_counts"] = updated_ok
    res["c6_diff"] = by_field
    res["c6_pass"] = not by_field

    # 7) 새로 더 잡힌 NCT
    res["c7_new_only"] = sorted(n for n in nm if n not in om)
    return res


def render_md(res: dict) -> str:
    ok = lambda b: "통과" if b else "미달"  # noqa: E731
    lines = [
        f"# 1112-03 비교 결과 (기준일 {res['ref_date']})", "",
        f"- 11/12 사본 study {res['old_study']} · 새 API study {res['new_study']}", "",
        "| 기준 | 결과 | 숫자 |", "|---|---|---|",
        f"| 1 lead·days_to≥0 전부 다시 잡힘 | {ok(res['c1_pass'])} | 대상 {res['c1_lead_upcoming_total']} · 빠짐 {len(res['c1_missing'])} |",
        f"| 2 전체 NCT 95% 이상 | {ok(res['c2_pass'])} | {res['c2_recapture']}/{res['old_study']} ({res['c2_ratio']:.1%}) |",
        f"| 3 종목 집합 같음 | {ok(res['c3_pass'])} | 옛 {res['c3_old_tickers']} · 새 {res['c3_new_tickers']} · 옛에만 {len(res['c3_only_old'])} · 새에만 {len(res['c3_only_new'])} |",
        f"| 4 가장 가까운 예정 시험 · 진행 중 임상 수 | {ok(res['c4_pass'])} | 가까운 시험 다름 {len(res['c4_nearest_diff'])} · 임상 수 다름 {len(res['c4_active_counts_diff'])} |",
        f"| 5 NCT별 종목·역할 | {ok(res['c5_pass'])} | 다름 {len(res['c5_diff'])} |",
        f"| 6 칸 값 차이 | {ok(res['c6_pass'])} | 칸별 {res['c6_counts']} · 11/12 뒤 갱신으로 인정 {res['c6_updated_after_ref_counts']} |",
        f"| 7 새로 더 잡힘 | 참고 | {len(res['c7_new_only'])} |", "",
    ]
    if res["c1_missing"]:
        lines += ["## 1 빠진 시험 (lead · 예정)", ""] + [f"- {m['nct_id']} · {m['ticker']} · {m['reason']}" for m in res["c1_missing"]] + [""]
    for key, title in (("c2_missing_not_in_raw", "2 검색에 안 걸린 NCT"), ("c2_missing_rule_dropped", "2 맞추기 규칙에서 버려진 NCT"),
                       ("c3_only_old", "3 옛 사본에만 있는 종목"), ("c3_only_new", "3 새 결과에만 있는 종목"),
                       ("c7_new_only", "7 새로 더 잡힌 NCT")):
        if res[key]:
            lines += [f"## {title}", "", ", ".join(res[key]), ""]
    return "\n".join(lines)


def main() -> None:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old_snapshot", type=Path, help="11/12 사본 ctgov_snapshot_20261112.json")
    ap.add_argument("candidates_csv", type=Path, help="11/12 실행 때 쓴 후보 CSV")
    ap.add_argument("out_dir", type=Path, help="결과 폴더 (저장소 밖)")
    args = ap.parse_args()

    old = json.loads(args.old_snapshot.read_text())
    names = load_candidates(args.candidates_csv)
    if not names:
        raise SystemExit("후보 CSV 에 ticker · name 칸이 없음")
    ref = datetime.fromisoformat(old["generated_utc"].replace("Z", "+00:00")).date() if old.get("generated_utc") \
        else date.fromisoformat(old["aact_snapshot_date"])
    today = datetime.now(timezone.utc).date()
    aliases = w._load_aliases()

    client = api.CtgovClient()
    try:
        ts = api.get_data_timestamp(client)
        raw, zero = api.fetch_all(client, api.build_queries(names, aliases))
    except api.CtgovStop as e:
        raise SystemExit(f"받기 중단 · {e} · 응답 코드별 {dict(client.codes)}")
    matches, _diag = api.match_studies(raw, w.SponsorMatcher(names, aliases), today)
    counts = w.sponsor_active_counts(matches)
    res = compare(old, matches, counts, set(raw), ref)
    res.update({"api_data_timestamp": ts, "queries": len(api.build_queries(names, aliases)), "zero_result_names": len(zero),
                "requests": client.requests, "response_codes": {str(k): v for k, v in client.codes.items()}})

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "compare_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    (args.out_dir / "compare_report.md").write_text(render_md(res))
    (args.out_dir / "new_snapshot_preview.json").write_text(
        json.dumps({"source": api.SOURCE, "api_data_timestamp": ts, "matches": matches, "sponsor_active_counts": counts},
                   ensure_ascii=False, indent=1))
    print(render_md(res))
    print(f"결과 폴더 · {args.out_dir}")


if __name__ == "__main__":
    main()
