"""WP81 · 질환 분류 자동화 (설계서 docs/plans/biotech/verification/dictionaries/auto_category_design.md 원칙 6개).

적용 순서: 수동 사전 (docs/plans/biotech/data/condition_categories.csv) > MeSH 트리 > 키워드 어간 > 기타.
- 수동 사전은 이 모듈이 절대 쓰거나 덮어쓰지 않는다 (사전에 있는 용어는 자동 분류 대상에서 뺀다).
- 자동 결과 = <RUNTIME>/auto_categories.json (basis = auto-mesh | auto-stem) · 검수 제안 = <RUNTIME>/auto_category_proposals_<날짜>.csv
- NLM (미국 국립의학도서관) MeSH 조회는 주간 AACT 잡에서만 · 초당 3회 이하 · 403·429 즉시 중단 · 캐시 <RUNTIME>/mesh_cache.json
  (한 번 조회한 용어는 다시 요청하지 않음 · 결과 없음도 캐시)
- 일일 07:00 파이프·API 는 NLM 을 부르지 않고 auto_categories.json 만 읽는다.

MeSH 규칙 = WP81 두 단계 규칙 (2026-09-30 · 수동 사전 326개 기준 일치율 92.9%):
  1단계 예외 (위에서부터 첫 일치 하나) → 2단계 트리 순서 (앞에 있는 트리가 이김).
어간 = docs/plans/biotech/data/auto_category_stems.json (경로 해석기 조회 · 변경은 dictionaries_changelog.md 기록) · 순서 "암 → 건강인·약동학 → 나머지" 는 코드가 강제.

로컬 시험 실행 (NLM 요청 없이 캐시만 쓰려면 --no-fetch):
    PYTHONPATH=. backend/venv/bin/python -m backend.scripts.biotech_auto_category --snapshot <ctgov_snapshot.json> [--no-fetch]
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_sec_common import SEC_FROM, SEC_UA

LOG = logging.getLogger("biotech_auto_category")

NLM_MIN_INTERVAL = 0.34          # 초당 3회 이하
NLM_LOOKUP = "https://id.nlm.nih.gov/mesh/lookup"
NLM_SPARQL = "https://id.nlm.nih.gov/mesh/sparql"
SPARQL_Q = ("PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#> PREFIX mesh: <http://id.nlm.nih.gov/mesh/> "
            "SELECT ?d ?tn WHERE {{ ?c meshv:term|meshv:preferredTerm mesh:{t} . "
            "?d meshv:concept|meshv:preferredConcept ?c . ?d meshv:treeNumber ?tn }}")

# ── MeSH 트리 규칙 (WP81 · 사전 고정) ──────────────────────────────────
MARKER = re.compile(r"hereditary|familial|congenital|inborn|x-linked|autosomal|dystroph|deficiency", re.I)
RARE = "희귀 유전"


def _has(trees: list[str], pre: str) -> bool:
    return any(t == pre or t.startswith(pre + ".") for t in trees)


EXCEPTIONS: list[tuple[Callable[[str, list[str]], Any], str]] = [  # 1단계 · 위에서부터 첫 일치 하나만
    (lambda n, t: MARKER.search(n) and _has(t, "C16"), RARE),                                  # 유전 표지어 + C16
    (lambda n, t: any(_has(t, p) for p in ("C16.320.070", "C16.320.190", "C16.320.290",
                                            "C16.320.365", "C16.320.400", "C16.320.577",
                                            "C16.320.565", "C16.320.322", "C16.320.144")), RARE),  # WP82 가지 추가
    (lambda n, t: _has(t, "C18.452.811"), RARE),                                                  # WP82 · 포르피린증
    (lambda n, t: _has(t, "C11.270"), RARE),
    (lambda n, t: _has(t, "C17.300"), "면역·염증"),
    (lambda n, t: _has(t, "C15.378.190.625") or _has(t, "C15.378.190.636"), "암"),
    (lambda n, t: _has(t, "C23.888.592.612"), "통증"),
    (lambda n, t: _has(t, "C23.550.470"), "면역·염증"),
    (lambda n, t: _has(t, "C26.404"), "근골격"),
    (lambda n, t: _has(t, "C06.552.241"), "비만·대사"),
    (lambda n, t: _has(t, "C08.381.423"), "심혈관"),
    (lambda n, t: _has(t, "B03") or _has(t, "B04"), "감염"),
    (lambda n, t: _has(t, "G07.690.725") or _has(t, "M01.774") or _has(t, "M01.955"), "건강인·약동학"),
    (lambda n, t: _has(t, "F01.145.126"), "신경·정신"),                                          # F01 의 다른 가지는 대응 없음
]
ORDER: list[tuple[Callable[[list[str]], bool], str]] = [  # 2단계 · 앞에 있는 트리가 이김
    (lambda t: _has(t, "C04"), "암"),
    (lambda t: _has(t, "C01"), "감염"),
    (lambda t: any(x.startswith("C10") and not _has([x], "C10.597") for x in t), "신경·정신"),
    (lambda t: _has(t, "C11"), "안과"),
    (lambda t: _has(t, "C09"), "청각·이비인후"),
    (lambda t: _has(t, "C08"), "호흡기"),
    (lambda t: _has(t, "C14"), "심혈관"),
    (lambda t: _has(t, "C06"), "소화기"),
    (lambda t: _has(t, "C12") or _has(t, "C13"), "신장"),
    (lambda t: _has(t, "C15"), "혈액"),
    (lambda t: _has(t, "C05"), "근골격"),
    (lambda t: _has(t, "C17"), "피부"),
    (lambda t: _has(t, "C18") or _has(t, "C19"), "비만·대사"),
    (lambda t: _has(t, "C20"), "면역·염증"),
    (lambda t: _has(t, "F03"), "신경·정신"),
    (lambda t: _has(t, "C10.597"), "신경·정신"),
    (lambda t: _has(t, "C16"), RARE),                                                             # 표지어 없는 C16
]


def mesh_category(name: str, trees: list[str]) -> str | None:
    """트리 규칙 · 대응 없음이면 None (어간 단계로 넘김)."""
    if not trees:
        return None
    trees = [x for x in trees if not _has([x], "C04.588.614.550")]  # 이 가지는 C04 로 보지 않음
    for f, cat in EXCEPTIONS:
        if f(name, trees):
            return cat
    for f, cat in ORDER:
        if f(trees):
            return cat
    return None


# ── 키워드 어간 ─────────────────────────────────────────────────────
FIRST_STEM_ORDER = ("암", "건강인·약동학")   # 코드가 강제하는 앞 순서 (사용자 지시) · 그 뒤 약어 → 나머지 어간


def _abbr_rx(abbr: str) -> re.Pattern:
    """약어 · 단어 경계 (앞뒤 영숫자 없음 · 괄호 안·하이픈 앞 포함) · 대소문자 구분."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(abbr)}(?![A-Za-z0-9])")


def load_stems(path: Path | None = None) -> list[tuple[str, re.Pattern]]:
    """(분류, 정규식) 목록 · 순서 = 암 어간 → 건강인·약동학 어간 → 약어 (WP82-3) → 나머지 어간."""
    p = path or _P.find("auto_category_stems.json")
    if p is None or not p.exists():
        return []
    d = json.loads(p.read_text())
    stems = d.get("stems", {})
    rest = [c for c in d.get("rest_order", list(stems)) if c not in FIRST_STEM_ORDER]
    out = [(c, re.compile(stems[c], re.I)) for c in FIRST_STEM_ORDER if c in stems]
    out += [(cat, _abbr_rx(ab)) for ab, cat in sorted(d.get("abbreviations", {}).items())]
    out += [(c, re.compile(stems[c], re.I)) for c in rest if c in stems]
    return out


def stem_category(name: str, stems: list[tuple[str, re.Pattern]]) -> tuple[str, str] | None:
    for cat, rx in stems:
        m = rx.search(name or "")
        if m:
            return cat, m.group(0)
    return None


# ── NLM 조회 (주간 잡에서만) ─────────────────────────────────────────

def norm_term(t: str) -> str:
    """소문자 · 괄호 제거 · 공백 정리."""
    t = re.sub(r"\([^)]*\)", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip(" ,;.-")


class NlmBlocked(RuntimeError):
    pass


class NlmClient:
    def __init__(self, get: Callable[..., Any] | None = None) -> None:
        self._client = None if get else httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM}, timeout=30)
        self._get = get or self._client.get
        self._last = 0.0
        self.requests = 0

    def _req(self, url: str, params: dict) -> Any:
        wait = NLM_MIN_INTERVAL - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.requests += 1
        r = self._get(url, params=params)
        if r.status_code in (403, 429):
            raise NlmBlocked(f"NLM HTTP {r.status_code}")
        return r.json() if r.status_code == 200 else None

    def trees(self, term: str) -> dict:
        """기술어 이름 완전 일치 → 없으면 정규화 후 동의어 (entry term) → 기술어 tree_number."""
        hit = self._req(f"{NLM_LOOKUP}/descriptor", {"label": term, "match": "exact", "limit": 1}) or []
        if hit:
            uid = hit[0]["resource"].rsplit("/", 1)[-1]
            d = self._req(f"https://id.nlm.nih.gov/mesh/{uid}.json", {}) or {}
            return {"descriptor": uid, "trees": sorted(set(_tree_numbers(d))), "method": "descriptor"}
        key = norm_term(term)
        th = self._req(f"{NLM_LOOKUP}/term", {"label": key, "match": "exact", "limit": 1}) if key else []
        if not th:
            return {"descriptor": None, "trees": [], "method": "none"}
        tid = th[0]["resource"].rsplit("/", 1)[-1]
        res = self._req(NLM_SPARQL, {"query": SPARQL_Q.format(t=tid), "format": "JSON"}) or {}
        b = res.get("results", {}).get("bindings", [])
        return {"descriptor": b[0]["d"]["value"].rsplit("/", 1)[-1] if b else None,
                "trees": sorted({x["tn"]["value"].rsplit("/", 1)[-1] for x in b}), "method": "synonym"}


def _tree_numbers(d: Any) -> list[str]:
    out: list[str] = []
    if isinstance(d, dict):
        for k, v in d.items():
            if k.endswith("treeNumber"):
                vals = v if isinstance(v, list) else [v]
                out += [x.rsplit("/", 1)[-1] for x in vals if isinstance(x, str) and x.startswith("http")]
            else:
                out += _tree_numbers(v)
    elif isinstance(d, list):
        for x in d:
            out += _tree_numbers(x)
    return out


# ── 주간 실행 ──────────────────────────────────────────────────────

def load_manual() -> set[str]:
    p = _P.find("condition_categories.csv")
    if p is None:
        return set()
    with p.open() as f:
        return {r["term"].strip().lower() for r in csv.DictReader(f)}


def unmapped_terms(snapshot: dict, manual: set[str]) -> Counter:
    """스냅샷 질환 용어 (MeSH + 원문) 중 수동 사전에 없는 것 · 시험 수."""
    c: Counter = Counter()
    for m in snapshot.get("matches", []):
        for t in set(m.get("mesh_terms", []) + m.get("conditions", [])):
            if t and t.strip().lower() not in manual:
                c[t] += 1
    return c


def example_tickers(snapshot: dict) -> dict[str, str]:
    """용어 → 처음 나온 시험의 종목 (제안 파일 example_ticker)."""
    out: dict[str, str] = {}
    for m in snapshot.get("matches", []):
        for t in m.get("mesh_terms", []) + m.get("conditions", []):
            if t and t not in out and m.get("ticker"):
                out[t] = m["ticker"]
    return out


CACHE_SAVE_EVERY = 50      # WP98-3 · 캐시 중간 저장 간격 (새로 받은 용어 수)


class AutoCategoryFailed(RuntimeError):
    """WP98-3 · 요청의 절반 이상이 실패하면 단계 실패 (캐시는 이미 저장됨)."""


def build(snapshot: dict, manual: set[str], cache: dict, stems: list, client: NlmClient | None, today: str,
          save: Callable[[], None] | None = None) -> tuple[dict, list[dict], dict]:
    """(auto_categories, 제안 행, 통계) · client=None 이면 NLM 요청 없음 (캐시만).

    WP98-3 · 용어마다 예외를 잡아 그 용어만 skipped (캐시에 넣지 않음 → 다음 실행에서 다시 시도) · 403·429 는 즉시 중단 ·
    새로 받은 용어 50개마다와 끝날 때 (예외 포함) 캐시 저장.
    """
    terms = unmapped_terms(snapshot, manual)
    blocked = False
    skipped: dict[str, str] = {}
    fetched = 0
    try:
        for t in sorted(terms):
            if t in cache or client is None or blocked:
                continue
            try:
                cache[t] = {**client.trees(t), "date": today}
                fetched += 1
                if save and fetched % CACHE_SAVE_EVERY == 0:
                    save()
            except NlmBlocked as e:
                LOG.error("%s · NLM 조회 즉시 중단 (이번 주는 캐시·어간만)", e)
                blocked = True
            except Exception as e:  # noqa: BLE001 · 접속 오류 등 · 그 용어만 건너뜀
                skipped[t] = e.__class__.__name__
    finally:
        if save:
            save()
    examples = example_tickers(snapshot)
    auto: dict[str, dict] = {}
    rows: list[dict] = []
    for t, n in terms.most_common():
        trees = cache.get(t, {}).get("trees", [])
        cat = mesh_category(t, trees)
        if cat:
            basis, evidence = "auto-mesh", " ".join(trees[:6])
            reason = f"MeSH 트리 {' '.join(trees[:3])}"
        else:
            hit = stem_category(t, stems)
            if not hit:
                continue
            cat, basis, evidence = hit[0], "auto-stem", hit[1]
            reason = f"어간 '{hit[1]}'"
        review = (_has(trees, "C16") and cat != RARE)
        if review:
            reason += " · 검수 요망 (C16 유전 트리인데 희귀 유전 아님)"
        auto[t] = {"category": cat, "basis": basis, "evidence": evidence, "date": today}
        rows.append({"term": t, "n_trials": n, "example_ticker": examples.get(t, ""), "auto_category": cat, "basis": basis,
                     "tree_numbers": " ".join(trees), "reason": reason, "검수 요망": "검수 요망" if review else "",
                     "reviewer_decision": ""})
    requests = client.requests if client else 0
    stats = {"unmapped_terms": len(terms), "auto": len(auto),
             "by_basis": dict(Counter(v["basis"] for v in auto.values())),
             "by_category": dict(Counter(v["category"] for v in auto.values()).most_common()),
             "review_needed": sum(1 for r in rows if r["검수 요망"]),
             "nlm_requests": requests, "nlm_blocked": blocked, "skipped_terms": len(skipped),
             "skipped_reasons": dict(Counter(skipped.values()))}
    return auto, rows, stats


PROPOSAL_FIELDS = ["term", "n_trials", "example_ticker", "auto_category", "basis", "tree_numbers", "reason", "검수 요망", "reviewer_decision"]


def run_weekly(snapshot_path: Path, fetch: bool = True, client: NlmClient | None = None) -> dict:
    """주간 AACT 잡 끝에서 호출 · 실패해도 주간 잡은 계속 (호출부가 예외 처리)."""
    t0 = time.time()
    today = _P.today_kst_str()
    root = _P.RUNTIME_DIR or (_P.DATA_DIR / "biotech")
    root.mkdir(parents=True, exist_ok=True)
    cache_p = root / "mesh_cache.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    snapshot = json.loads(snapshot_path.read_text())
    client = client or (NlmClient() if fetch else None)

    def save() -> None:
        tmp = cache_p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False))
        tmp.replace(cache_p)

    auto, rows, stats = build(snapshot, load_manual(), cache, load_stems(), client, today, save=save)
    (root / "auto_categories.json").write_text(json.dumps(
        {"generated": today, "rule": "WP81 MeSH 두 단계 + 어간 v0", "terms": auto}, ensure_ascii=False, indent=1))
    prop = root / f"auto_category_proposals_{today}.csv"
    with prop.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PROPOSAL_FIELDS)
        w.writeheader()
        w.writerows(rows)
    stats["proposals"] = str(prop)
    stats["proposal_rows"] = len(rows)
    stats["cache_items"] = len(cache)
    stats["elapsed_sec"] = round(time.time() - t0, 1)
    LOG.info("자동 분류 · %s", json.dumps(stats, ensure_ascii=False))
    if stats["nlm_requests"] and stats["skipped_terms"] * 2 >= stats["nlm_requests"]:
        raise AutoCategoryFailed(f"요청 {stats['nlm_requests']} 중 건너뜀 {stats['skipped_terms']} (절반 이상)")
    return stats


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", help="ctgov_snapshot.json (미지정 시 해석기로)")
    ap.add_argument("--no-fetch", action="store_true", help="NLM 요청 없이 캐시만 사용")
    args = ap.parse_args()
    snap = Path(args.snapshot) if args.snapshot else _P.find("ctgov_snapshot.json")
    if snap is None or not snap.exists():
        raise SystemExit("ctgov_snapshot.json 없음")
    print(json.dumps(run_weekly(snap, fetch=not args.no_fetch), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
