"""Phase C 3 · H6 소속 v2 · 스폰서 → 상장사 매칭 + point-in-time 소속표 + 가격 커버 계획 + 관문 3 초안.

입력 (경로 해석기 · RUNTIME > docs/data > backend/data):
- h6/aact_theme_studies_<날짜>.csv  (biotech_h6_aact_theme_extract 산출 · 서버에서 가져옴)
- sec_company_tickers.json          (SEC 회사명 ↔ 티커 · 현재 상장만)
- universe_skeleton_v2_*.csv        (Tiingo 우주 · 미 거래소 · 상폐 포함 · 첫/마지막 거래일)
- h3_prices_merged_*.csv            (기존 보유 가격 · 티커 열만 읽음)
- h6_rank_growth_*.csv              (기존 봉인 순위 · 3분위 · 관문 판정용 읽기만)

매칭기 v2 (biotech_name_match · 규칙 그대로):
- 정규화 (소문자 · 구두점 · Inc/Corp/Ltd 등 접미어 제거) 후 **완전 일치만 채택**
- Jaccard ≥ 0.8 (토큰 겹침 비율) 는 **후보 CSV 로만 분리** · 자동 채택 금지 (검수 표기)
- 채택 티커가 Tiingo 우주 (미 거래소) 에 없으면 "해외" 로 분류

미매칭 사유 분해 (추정 규칙 · 사전 고정):
- 대학·병원 = AACT agency_class (스폰서 유형) 가 INDUSTRY 아님 OR 이름에 university/hospital/institute 등
- 이름      = Jaccard 후보 있음 (검수 전이라 미채택)
- 해외      = SEC 에 있으나 Tiingo 미 거래소 우주 밖 OR 이름이 해외 법인 형태 (GmbH·AG·S.A.·K.K.·Co., Ltd. 등)
- 비상장    = 위 어디에도 해당 없는 제약사 (INDUSTRY) · 상폐사도 여기 섞임 (SEC 현재 목록 한계 · 생존편향)

소속 규칙 (point-in-time · 그 시점 기준):
- (티커, 테마) 편입 분기 = 그 테마 매치 임상 중 가장 이른 study_first_posted (최초 공개일) 의 분기
- 이탈 없음 (한 번 편입되면 이후 분기 계속 소속)
- 분기 q 소속 수 = 편입 분기 ≤ q  AND  q 에 거래 중 (Tiingo 첫 거래일 ≤ 분기말 · 마지막 거래일 ≥ 분기초)

산출 (<RUNTIME 또는 backend/data/biotech>/h6/):
- h6_membership_v2_<스냅샷일>.csv          ticker · theme · entry_quarter · n_studies · first_nct · sponsor
- h6_membership_v2_quarterly_<스냅샷일>.csv 분기 × 테마 소속 수 (2015Q1~2026Q3)
- h6_sponsor_match_v2_<스냅샷일>.csv       스폰서별 매칭 결과 · 사유
- h6_jaccard_candidates_v2_<스냅샷일>.csv  Jaccard 후보 (검수용 · 미채택)
- h6_membership_v2_summary_<스냅샷일>.json 매칭률 · 분기 요약 · 가격 계획 · 관문 판정
- h6_gate_per_quarter_v2_<스냅샷일>.json    분기별 상위/하위 3분위 소속 수 (관문 판정 근거)
(관문 3 초안 h6_params_v2 는 이 산출 수치로 별도 작성 · Fable 검수 대기)

**백테스트 본 실행 없음** · 수익률 계산 없음 (관문 3 통과 전 금지)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import re
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_name_match import build_index, jaccard, normalize_name, tokens

LOG = logging.getLogger("biotech_h6_membership_v2")

MAIN_THEMES = [
    "obesity_glp1", "hair_loss", "longevity_rejuvenation",
    "meal_replacement_metabolic", "hibernation_hypothermia", "cognitive_memory",
]
CONTROL_THEMES = ["control_nash", "control_amyloid"]
Q_START = (2015, 1)
Q_END = (2026, 3)
JACCARD_MIN = 0.8                 # 매칭기 v2 규칙 (자동 채택 금지 · 후보만)
TIINGO_MONTHLY_BUDGET = 500       # 10월 Tiingo 월 호출 예산 (사용자 지시)
TIINGO_RESERVE = 50               # 일일 파이프·재시도 여유분 (배분 제외)
AUTO_GO_MIN_MEMBERS = 3           # 자동 GO: 소속 ≥ 3 인 분기
AUTO_GO_MIN_QUARTERS = 20         #          가 20개 이상 (h42 정의 승계)

ACADEMIC_CLASSES = {"NIH", "U.S. FED", "FED", "OTHER", "OTHER_GOV", "NETWORK", "INDIV"}
ACADEMIC_RE = re.compile(
    r"universit|hospital|institut|college|medical cent|health system|clinic\b|clinics\b|school|"
    r"foundation|academ|council|ministry|national|research cent|cancer cent|children|infirmary|"
    r"hôpital|hopital|ospedale|klinik|charit|assistance publique|\bnhs\b|trust\b|veterans|group\b",
    re.IGNORECASE,
)
FOREIGN_RE = re.compile(
    r"\bgmbh\b|\bag\b|\bs\.?\s?a\.?\b|\bs\.?p\.?a\.?\b|\bk\.?k\.?\b|co\.?,?\s*ltd|\bb\.?v\.?\b|\bn\.?v\.?\b|"
    r"\ba/s\b|\bab\b|\boy\b|\bpty\b|\bs\.?r\.?l\.?\b|\bsas\b|\bsarl\b|\bkg\b|\bse\b|pvt|private limited|"
    r"\bjsc\b|\bllc\s*\(|\bzao\b|\bооо\b|\btbk\b|\bbhd\b",
    re.IGNORECASE,
)


# ── 분기 유틸 ─────────────────────────────────────────────────────

def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    for n in (10, 7):  # YYYY-MM-DD · YYYY-MM
        try:
            parts = [int(x) for x in s[:n].split("-")]
            return date(parts[0], parts[1], parts[2] if len(parts) > 2 else 1)
        except (ValueError, IndexError):
            continue
    return None


def quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def quarters(start=Q_START, end=Q_END) -> list[tuple[int, int]]:
    out, (y, q) = [], start
    while (y, q) <= end:
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def q_bounds(y: int, q: int) -> tuple[date, date]:
    start = date(y, 3 * q - 2, 1)
    end = date(y + 1, 1, 1) if q == 4 else date(y, 3 * q + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def qlabel(yq: tuple[int, int]) -> str:
    return f"{yq[0]}Q{yq[1]}"


# ── 매칭 ─────────────────────────────────────────────────────────

class SponsorMatcher:
    """매칭기 v2 · 완전 일치 채택 · Jaccard 후보 분리 · 사유 분해."""

    def __init__(self, sec_entries: list[dict], universe: dict[str, dict],
                 aliases: dict[str, str] | None = None) -> None:
        self.idx = build_index(sec_entries)
        self.universe = universe
        # 별칭 사전 (대형 제약 공식명 변형 → 티커) · 정규화 키로 보관 · 매칭기 앞단 적용
        self.aliases = {normalize_name(k): v for k, v in (aliases or {}).items() if normalize_name(k)}
        # Jaccard 가속 · 토큰 → 정규화 키 (공유 토큰 있는 키만 비교 · 결과는 전수 비교와 동일)
        self.tok_idx: dict[str, set[str]] = defaultdict(set)
        for key in self.idx:
            for t in key.split():
                self.tok_idx[t].add(key)

    def jaccard_candidates(self, name: str) -> list[tuple[float, dict]]:
        qs = tokens(name)
        qn = normalize_name(name)
        keys = set().union(*(self.tok_idx.get(t, set()) for t in qs)) if qs else set()
        out = []
        for key in keys:
            if key == qn:
                continue
            j = jaccard(qs, set(key.split()))
            if j >= JACCARD_MIN:
                out.append((j, self.idx[key][0]))
        out.sort(key=lambda x: (-x[0], x[1]["ticker"]))
        return out[:5]

    def match(self, sponsor: str, agency_class: str) -> dict:
        res = {"sponsor": sponsor, "agency_class": agency_class, "ticker": "", "status": "", "reason": "",
               "sec_ticker": "", "jaccard_candidates": "", "method": ""}
        if not sponsor:
            res.update(status="unmatched", reason="이름")
            return res
        alias_tk = self.aliases.get(normalize_name(sponsor))
        if alias_tk and alias_tk in self.universe:
            res.update(ticker=alias_tk, status="listed", method="alias")
            return res
        hits = self.idx.get(normalize_name(sponsor))
        if hits:
            in_uni = [h for h in hits if h["ticker"] in self.universe]
            if in_uni:
                res.update(ticker=in_uni[0]["ticker"], status="listed", method="exact")
                return res
            res.update(status="unmatched", reason="해외", sec_ticker=hits[0]["ticker"])
            return res
        ac = (agency_class or "").upper()
        if ac in ACADEMIC_CLASSES or ACADEMIC_RE.search(sponsor):
            res.update(status="unmatched", reason="대학·병원")
            return res
        cands = self.jaccard_candidates(sponsor)
        if cands:
            res.update(status="unmatched", reason="이름",
                       jaccard_candidates="|".join(f"{c['ticker']}:{c['name']}:{j:.2f}" for j, c in cands))
            return res
        if FOREIGN_RE.search(sponsor):
            res.update(status="unmatched", reason="해외")
            return res
        res.update(status="unmatched", reason="비상장")
        return res


# ── 적재 ─────────────────────────────────────────────────────────

def load_sec_entries() -> list[dict]:
    p = _P.find("sec_company_tickers.json")
    if p is None:
        raise SystemExit("sec_company_tickers.json 없음 (SEC 회사명 목록 · 로컬 backend/data)")
    data = json.loads(p.read_text())
    return [{"ticker": str(e.get("ticker", "")).upper(), "name": e.get("title", ""), "exchange": "",
             "cik": str(e.get("cik_str", ""))} for e in data.values()]


def load_aliases() -> dict[str, str]:
    """docs/plans/biotech/data/sponsor_aliases.csv · alias → ticker (근거 = sec_title 열)."""
    p = _P.find("sponsor_aliases.csv")
    if p is None:
        LOG.warning("sponsor_aliases.csv 없음 · 별칭 미적용")
        return {}
    with p.open() as f:
        return {r["alias"]: r["ticker"].upper() for r in csv.DictReader(f) if r.get("alias")}


def load_universe() -> dict[str, dict]:
    p = _P.find_glob("universe_skeleton_v2_*.csv")
    if p is None:
        raise SystemExit("universe_skeleton_v2 없음 (Tiingo 우주)")
    with p.open() as f:
        return {r["ticker"].upper(): r for r in csv.DictReader(f)}


def load_price_tickers() -> set[str]:
    p = _P.find_glob("h3_prices_merged_*.csv")
    if p is None:
        return set()
    out = set()
    with p.open() as f:
        for r in csv.DictReader(f):
            out.add((r.get("ticker") or "").upper())
    return out


def load_rank_terciles() -> dict[tuple[int, int, str], str]:
    p = _P.find_glob("h6_rank_growth_*.csv")
    if p is None:
        return {}
    with p.open() as f:
        return {(int(r["year"]), int(r["quarter"]), r["theme"]): r["tercile"] for r in csv.DictReader(f)}


def load_studies(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


# ── 소속 구축 ─────────────────────────────────────────────────────

def trading_in(u: dict | None, y: int, q: int) -> bool:
    if not u:
        return False
    fb, lb = parse_date(u.get("first_bar_date", "")), parse_date(u.get("last_bar_date", ""))
    qs, qe = q_bounds(y, q)
    return bool(fb and lb and fb <= qe and lb >= qs)


def build_membership(studies: list[dict], match_by_sponsor: dict[str, dict]) -> list[dict]:
    agg: dict[tuple[str, str], dict] = {}
    for s in studies:
        m = match_by_sponsor.get(s["lead_sponsor"])
        d = parse_date(s.get("study_first_posted", ""))
        if not m or m["status"] != "listed" or d is None:
            continue
        key = (m["ticker"], s["theme"])
        a = agg.get(key)
        if a is None or d < a["_first"]:
            agg[key] = {**(a or {"n_studies": 0}), "_first": d, "first_nct": s["nct_id"], "sponsor": s["lead_sponsor"]}
        agg[key]["n_studies"] = agg[key].get("n_studies", 0) + 1
    rows = []
    for (tk, th), a in sorted(agg.items()):
        rows.append({"ticker": tk, "theme": th, "entry_quarter": qlabel(quarter_of(a["_first"])),
                     "entry_date": a["_first"].isoformat(), "n_studies": a["n_studies"],
                     "first_nct": a["first_nct"], "sponsor": a["sponsor"]})
    return rows


def members_at(membership: list[dict], universe: dict, y: int, q: int) -> dict[str, set[str]]:
    """분기 q 테마별 소속 티커 (편입 ≤ q · 그 분기 거래 중)."""
    out: dict[str, set[str]] = defaultdict(set)
    for r in membership:
        ey, eq = int(r["entry_quarter"][:4]), int(r["entry_quarter"][-1])
        if (ey, eq) <= (y, q) and trading_in(universe.get(r["ticker"]), y, q):
            out[r["theme"]].add(r["ticker"])
    return out


def gate_counts(qmembers: dict[tuple[int, int], dict[str, set[str]]],
                terciles: dict[tuple[int, int, str], str]) -> dict:
    """h42 정의 승계 = 분기별 '상위 3분위 주 테마' 소속 종목 합 ≥ 3 인 분기 수 · 보조 = 하위 3분위도 ≥ 3."""
    good_top = good_both = ranked = 0
    per_q = []
    for (y, q), per in sorted(qmembers.items()):
        top = {t for t in MAIN_THEMES if terciles.get((y, q, t)) == "top"}
        bot = {t for t in MAIN_THEMES if terciles.get((y, q, t)) == "bot"}
        if not top and not bot:
            continue
        ranked += 1
        n_top = len(set().union(*(per.get(t, set()) for t in top))) if top else 0
        n_bot = len(set().union(*(per.get(t, set()) for t in bot))) if bot else 0
        good_top += n_top >= AUTO_GO_MIN_MEMBERS
        good_both += (n_top >= AUTO_GO_MIN_MEMBERS and n_bot >= AUTO_GO_MIN_MEMBERS)
        per_q.append({"quarter": qlabel((y, q)), "top_themes": sorted(top), "bot_themes": sorted(bot),
                      "n_top": n_top, "n_bot": n_bot})
    return {"ranked_quarters": ranked, "good_quarters_top_ge3": good_top,
            "good_quarters_top_and_bot_ge3": good_both,
            "auto_go": good_top >= AUTO_GO_MIN_QUARTERS,
            "auto_go_strict_both": good_both >= AUTO_GO_MIN_QUARTERS, "per_quarter": per_q}


def price_plan(member_tickers: set[str], have: set[str], membership: list[dict]) -> dict:
    need = sorted(member_tickers - have)
    weight = defaultdict(int)
    for r in membership:
        weight[r["ticker"]] += int(r["n_studies"])
    ordered = sorted(need, key=lambda t: (-weight[t], t))  # 임상 많은 종목 우선 (소속 영향 큰 순)
    per_month = TIINGO_MONTHLY_BUDGET - TIINGO_RESERVE
    months = [ordered[i:i + per_month] for i in range(0, len(ordered), per_month)]
    return {"unique_member_tickers": len(member_tickers), "have_prices": len(member_tickers & have),
            "need_tiingo": len(need), "monthly_budget": TIINGO_MONTHLY_BUDGET, "reserve": TIINGO_RESERVE,
            "allocatable_per_month": per_month, "months_needed": len(months),
            "batches": [{"month_index": i + 1, "n": len(b), "first": b[:5]} for i, b in enumerate(months)],
            "priority_rule": "소속 임상 수 많은 순 (1 티커 = 1 호출 · 전 기간 일봉)"}


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--studies", help="aact_theme_studies CSV (미지정 시 해석기로 최신)")
    args = ap.parse_args()

    # 서버 = RUNTIME/h6 · 로컬 = out_dir 규칙과 같은 backend/data/biotech/h6
    sp = Path(args.studies) if args.studies else (_P.find_glob("aact_theme_studies_*.csv", subdir="h6")
                                                  or _P.find_glob("aact_theme_studies_*.csv", subdir="biotech/h6"))
    if sp is None or not sp.exists():
        raise SystemExit("aact_theme_studies CSV 없음 · 서버 추출 (biotech_h6_aact_theme_extract) 선행 필요")
    m = re.search(r"(\d{4}-\d{2}-\d{2})", sp.name)
    snap = m.group(1) if m else "unknown"
    studies = load_studies(sp)
    LOG.info("studies %s · %d 행", sp.name, len(studies))

    universe = load_universe()
    sec_entries = load_sec_entries()
    aliases = load_aliases()
    sponsors: dict[str, str] = {}
    for s in studies:
        sponsors.setdefault(s["lead_sponsor"], s.get("agency_class", ""))
    # 별칭 적용 전 (매칭기 v2 단독) · 비교용
    base = SponsorMatcher(sec_entries, universe)
    before = {name: base.match(name, ac) for name, ac in sponsors.items()}
    matcher = SponsorMatcher(sec_entries, universe, aliases)
    match_by_sponsor = {name: matcher.match(name, ac) for name, ac in sponsors.items()}

    def _rates(mb: dict) -> dict:
        sp_listed = sum(1 for v in mb.values() if v["status"] == "listed")
        st_l = len({s["nct_id"] for s in studies if mb.get(s["lead_sponsor"], {}).get("status") == "listed"})
        st_t = len({s["nct_id"] for s in studies})
        return {"sponsors_listed": sp_listed, "sponsor_listed_rate": round(sp_listed / max(len(mb), 1), 4),
                "studies_listed": st_l, "study_listed_rate": round(st_l / max(st_t, 1), 4)}
    LOG.info("스폰서 %d · 상장 매칭 %d", len(sponsors),
             sum(1 for v in match_by_sponsor.values() if v["status"] == "listed"))

    membership = build_membership(studies, match_by_sponsor)
    qs = quarters()
    qmembers = {yq: members_at(membership, universe, *yq) for yq in qs}
    all_themes = MAIN_THEMES + CONTROL_THEMES
    qrows = [{"quarter": qlabel(yq), **{t: len(qmembers[yq].get(t, set())) for t in all_themes},
              "main_union": len(set().union(*(qmembers[yq].get(t, set()) for t in MAIN_THEMES)))} for yq in qs]

    def _stats(vals: list[int]) -> dict:
        return {"min": min(vals), "median": statistics.median(vals), "max": max(vals)}

    theme_stats = {t: _stats([r[t] for r in qrows]) for t in all_themes + ["main_union"]}
    reasons = defaultdict(int)
    for v in match_by_sponsor.values():
        reasons["상장" if v["status"] == "listed" else v["reason"]] += 1
    # 임상 기준 매칭률 (스폰서 수가 아니라 임상 건수 기준도 병기)
    st_listed = len({s["nct_id"] for s in studies if match_by_sponsor.get(s["lead_sponsor"], {}).get("status") == "listed"})
    st_total = len({s["nct_id"] for s in studies})

    member_tickers = {r["ticker"] for r in membership}
    plan = price_plan(member_tickers, load_price_tickers(), membership)
    gate = gate_counts(qmembers, load_rank_terciles())

    out = _P.out_dir("h6")
    _write_csv(out / f"h6_membership_v2_{snap}.csv", membership,
               ["ticker", "theme", "entry_quarter", "entry_date", "n_studies", "first_nct", "sponsor"])
    _write_csv(out / f"h6_membership_v2_quarterly_{snap}.csv", qrows, ["quarter"] + all_themes + ["main_union"])
    _write_csv(out / f"h6_sponsor_match_v2_{snap}.csv",
               sorted(match_by_sponsor.values(), key=lambda r: (r["status"], r["reason"], r["sponsor"])),
               ["sponsor", "agency_class", "status", "method", "reason", "ticker", "sec_ticker", "jaccard_candidates"])
    _write_csv(out / f"h6_jaccard_candidates_v2_{snap}.csv",
               [v for v in match_by_sponsor.values() if v["jaccard_candidates"]],
               ["sponsor", "agency_class", "jaccard_candidates"])

    summary = {
        "aact_snapshot_date": snap, "studies_csv": sp.name,
        "matched_studies": st_total, "matched_rows": len(studies),
        "aliases_loaded": len(aliases),
        "alias_effect": {"before": _rates(before), "after": _rates(match_by_sponsor),
                         "alias_hits": sum(1 for v in match_by_sponsor.values() if v["method"] == "alias")},
        "sponsors_unique": len(sponsors),
        "sponsors_listed": reasons["상장"],
        "sponsor_listed_rate": round(reasons["상장"] / max(len(sponsors), 1), 4),
        "studies_listed": st_listed, "study_listed_rate": round(st_listed / max(st_total, 1), 4),
        "unmatched_breakdown": {k: reasons.get(k, 0) for k in ("비상장", "대학·병원", "이름", "해외")},
        "membership_pairs": len(membership), "member_tickers": len(member_tickers),
        "quarterly_stats_2015Q1_2026Q3": theme_stats,
        "price_plan": plan,
        "gate": {k: v for k, v in gate.items() if k != "per_quarter"},
        "caveats": [
            "비상장 분류에 폐지 상장사 혼입 가능 · 과거 소속 과소 방향 (SEC company_tickers = 현재 상장사만 · 생존편향)",
            "별칭 사전 = 자체명 변형 + 2015Q1 이전 완전자회사만 · 2015 이후 인수 (Allergan·Shire·Celgene 등) 제외 (point-in-time)",
            "AACT 스냅샷 = 현재 시점 lead_sponsor·제목 · 사후 스폰서 변경 (인수 등) 은 현재 이름 기준",
            "study_first_posted = 최초 공개일 · point-in-time 편입 기준 (이탈 없음)",
        ],
    }
    (out / f"h6_membership_v2_summary_{snap}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (out / f"h6_gate_per_quarter_v2_{snap}.json").write_text(json.dumps(gate["per_quarter"], ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
