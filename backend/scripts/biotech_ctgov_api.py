"""1112-03 · 임상 등록부 주간 자료를 공식 API(ClinicalTrials.gov v2)로 받는다 (AACT 내려받기 대체).

배경: AACT 사본 내려받기가 계정 로그인 뒤로 옮겨 갔다 (교훈 #10 · 2026-11-16 · 옛 주소 410).
계획: docs/plans/biotech/1112-03-ctgov-api-plan.md (사용자 승인 · Fable 2차 GO)

- 후보 이름(설립 주 표기 · 법인 접미어를 뗀 것) + 별칭 두 파일로 `query.spons` 검색 · 같은 검색어는 한 번만
- 받은 후원사 이름에 지금과 같은 SponsorMatcher 를 적용 (lead 우선 → collaborator) · 안 맞으면 버림
- 출력 칸 · 값 모양은 AACT 때와 같게 옮긴다 (`source` · `api_data_timestamp` 칸만 더함)
- 실패 · 가드에 걸리면 새 파일을 쓰지 않는다 (지난 사본 그대로) · 저장은 임시 파일 → 바꿔치기

이 모듈은 AACT 코드를 지우지 않은 `biotech_h69_aact_weekly` 의 매칭기 · 저장 함수를 가져다 쓴다
(h69 의 main() 이 이 모듈의 run_snapshot 을 부른다 · 순환 가져오기를 피하려고 main() 안에서 가져옴).
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401  (main 은 h69 · 구조 검사용)

import calendar
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from backend.scripts import biotech_h69_aact_weekly as w
from backend.scripts.biotech_name_match import normalize_name

LOG = logging.getLogger("biotech_ctgov_api")

API_BASE = "https://clinicaltrials.gov/api/v2"
PAGE_SIZE = 1000                 # 공식 최대 쪽 크기
MAX_PAGES = 20                   # 질의당 쪽 상한 · 넘으면 잡 전체 멈춤 (계획 2절)
# 요청 간격 1.5초 = 분당 40회.
# 분당 한도 근거: 공식 문서(clinicaltrials.gov/data-api/api · /about-api/api-migration)는 쪽 내용이 스크립트 렌더라
#   2026-11-17 에 읽어도 한도 문장이 나오지 않았다 (확인 못 함 · 추정). 제3자 자료가 「IP 당 분당 약 50회 · 초과 시 429」
#   라고 적는다 (2026-11-17 웹 검색 · 공식 아님). 그래서 추정치 50 아래인 40 으로 유지하고 429 는 즉시 멈춘다.
MIN_INTERVAL = 1.5
RETRY_TRIES = 3                  # 5xx · 연결 오류만 · 4xx 는 다시 시도하지 않음
RETRY_WAIT = 10.0
REQUEST_TIMEOUT = 60.0
STALE_DAYS = 7                   # dataTimestamp 가 이보다 더 늦으면 warning (파일은 씀)
DROP_RATIO = 0.7                 # 지난 사본 대비 study 수가 30% 넘게 줄면 쓰지 않음
SOURCE = "ctgov_api_v2"

# 칸 이름은 2026-11-17 실제 응답으로 확인한 것만 쓴다 (결과 칸 resultsSection 은 받지 않음)
FIELDS = "|".join([
    "NCTId", "BriefTitle", "OfficialTitle", "OverallStatus", "Phase",
    "PrimaryCompletionDate", "PrimaryCompletionDateType", "CompletionDate", "CompletionDateType",
    "LastUpdatePostDate", "EnrollmentCount", "EnrollmentType", "StudyType",
    "LeadSponsor", "Collaborator", "Condition", "ConditionBrowseModule", "Intervention",
    "DesignAllocation", "DesignMasking", "PrimaryOutcome",
])


class CtgovStop(Exception):
    """잡 전체를 멈춘다 (파일을 쓰지 않음 · critical 알림 1통)."""

    def __init__(self, step: str, detail: str, exit_code: int = 22) -> None:
        super().__init__(f"{step} · {detail}")
        self.step = step
        self.detail = detail
        self.exit_code = exit_code


# ── 받기 ─────────────────────────────────────────────────────────────────────

class CtgovClient:
    """요청 사이 MIN_INTERVAL · 5xx/연결 오류만 RETRY_TRIES 번 · 4xx 즉시 멈춤 · 응답 코드별 개수."""

    def __init__(self, http: httpx.Client | None = None, sleep=time.sleep, clock=time.monotonic) -> None:
        self.http = http or httpx.Client(headers=dict(w.HEADERS), timeout=REQUEST_TIMEOUT)
        self._sleep = sleep
        self._clock = clock
        self._last = None
        self.codes: Counter = Counter()
        self.requests = 0
        self.where = ""              # 알림 문구용 · 마지막 질의 순번

    def _pace(self) -> None:
        if self._last is not None:
            wait = MIN_INTERVAL - (self._clock() - self._last)
            if wait > 0:
                self._sleep(min(wait, MIN_INTERVAL))
        self._last = self._clock()

    def get_json(self, path: str, params: dict | None = None, step: str = "fetch") -> dict:
        last = ""
        for attempt in range(1, RETRY_TRIES + 1):
            self._pace()
            self.requests += 1
            try:
                r = self.http.get(API_BASE + path, params=params)
            except httpx.HTTPError as e:
                self.codes["연결오류"] += 1
                last = f"연결 오류 {e.__class__.__name__}"
                LOG.warning("API %s · %s · 시도 %d/%d", path, last, attempt, RETRY_TRIES)
                if attempt < RETRY_TRIES:
                    self._sleep(RETRY_WAIT)
                continue
            self.codes[r.status_code] += 1
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    raise CtgovStop(step, f"HTTP 200 인데 JSON 이 아님 · {self.where}")
                if not isinstance(data, dict):
                    raise CtgovStop(step, f"HTTP 200 인데 JSON 모양이 다름 · {self.where}")
                return data
            if r.status_code < 500:
                raise CtgovStop(step, f"HTTP {r.status_code} · 다시 시도하지 않음 · {self.where}")
            last = f"HTTP {r.status_code}"
            LOG.warning("API %s · %s · 시도 %d/%d", path, last, attempt, RETRY_TRIES)
            if attempt < RETRY_TRIES:
                self._sleep(RETRY_WAIT)
        raise CtgovStop(step, f"{last} · {RETRY_TRIES}회 시도 뒤 멈춤 · {self.where}")


def get_data_timestamp(client: CtgovClient) -> str:
    data = client.get_json("/version", step="version")
    ts = data.get("dataTimestamp")
    if not isinstance(ts, str) or len(ts) < 10:
        raise CtgovStop("version", "응답에 dataTimestamp 없음", 21)
    return ts


def fetch_term(client: CtgovClient, term: str) -> list[dict]:
    """한 검색어의 모든 쪽 · nextPageToken 을 끝까지 따른다 · MAX_PAGES 넘으면 멈춤."""
    out: list[dict] = []
    token = None
    for _page in range(1, MAX_PAGES + 1):
        params = {"query.spons": term, "pageSize": str(PAGE_SIZE), "fields": FIELDS}
        if token:
            params["pageToken"] = token
        data = client.get_json("/studies", params, step="fetch")
        studies = data.get("studies")
        if not isinstance(studies, list):
            raise CtgovStop("fetch", f"200 응답에 studies 열쇠 없음 · {client.where}")
        out.extend(studies)
        token = data.get("nextPageToken")
        if not token:
            return out
    raise CtgovStop("fetch", f"한 검색어가 {MAX_PAGES}쪽을 넘음 (쪽 상한) · {client.where}")


def search_term(name: str) -> str:
    """후보 이름 → 검색어 · 설립 주 표기(/DE/ · / MA)와 법인 접미어를 뗀다 (`normalize_name` 과 같은 규칙).

    API 검색은 낱말이 모두 들어 있어야 걸린다 (「VERTEX … INC / MA」 0건 · 계획 2절)."""
    s = re.sub(r"\s*/\s*[A-Za-z]{2,3}\s*/?\s*$", "", name or "")
    return normalize_name(s)


def build_queries(names: dict[str, str], aliases: list[dict]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        if t and t not in seen:
            seen.add(t)
            terms.append(t)

    for n in names.values():
        add(search_term(n))
    for a in aliases:
        if (a.get("ticker") or "").upper() in names and a.get("alias"):
            add(search_term(a["alias"]))
    return terms


def fetch_all(client: CtgovClient, queries: list[str]) -> tuple[dict[str, dict], list[str]]:
    """같은 NCT 는 한 번만 둔다 · 결과 0건 검색어 목록도 돌려준다."""
    raw: dict[str, dict] = {}
    zero: list[str] = []
    for i, term in enumerate(queries, 1):
        client.where = f"질의 {i}/{len(queries)}"
        got = fetch_term(client, term)
        if not got:
            zero.append(term)
        for s in got:
            nct = ((s.get("protocolSection") or {}).get("identificationModule") or {}).get("nctId")
            if nct and nct not in raw:
                raw[nct] = s
    return raw, zero


# ── 값 옮기기 ─────────────────────────────────────────────────────────────────

def norm_date(s) -> str:
    """API `YYYY-MM` → 그 달 마지막 날 `YYYY-MM-DD` (AACT 사본 규칙 · 계획 3절). `YYYY-MM-DD` 는 그대로.

    `YYYY` 만 오는 경우는 API 에서 보지 못했다 · 그 해 12월 31일로 둔다 (판정 경로가 오류 없이 읽게)."""
    s = (s or "").strip()
    if len(s) == 7:
        y, m = int(s[:4]), int(s[5:7])
        return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
    if len(s) == 4 and s.isdigit():
        return f"{s}-12-31"
    return s


def join_phase(phases) -> str:
    """["PHASE2","PHASE3"] → PHASE2/PHASE3 · 빈칸은 빈칸 · NA 는 NA (AACT 값과 같음)."""
    return "/".join(p for p in (phases or []) if p)


def _g(d, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def convert_study(study: dict, ticker: str, role: str, method: str, today: date) -> dict:
    ps = study.get("protocolSection") or {}
    ident, status, design = ps.get("identificationModule") or {}, ps.get("statusModule") or {}, ps.get("designModule") or {}
    pcd_s = status.get("primaryCompletionDateStruct") or {}
    cd_s = status.get("completionDateStruct") or {}
    pcd = norm_date(pcd_s.get("date"))
    days_to = None
    if pcd:
        try:
            days_to = (date.fromisoformat(pcd) - today).days
        except ValueError:
            pcd, days_to = "", None
    enroll = _g(design, "enrollmentInfo", "count")
    outcomes = [{"measure": (o.get("measure") or "")[:300], "time_frame": (o.get("timeFrame") or "")[:200]}
                for o in (_g(ps, "outcomesModule", "primaryOutcomes") or [])][:3]
    meshes = _g(study, "derivedSection", "conditionBrowseModule", "meshes") or []
    return {
        "ticker": ticker,
        "nct_id": ident.get("nctId", ""),
        "role": role,
        "match_method": method,
        "phase": join_phase(design.get("phases")),
        "overall_status": status.get("overallStatus") or "",
        "primary_completion_date": pcd,
        "primary_completion_date_type": pcd_s.get("type") or "",
        "last_update_posted_date": norm_date(_g(status, "lastUpdatePostDateStruct", "date")),
        "completion_date_type": cd_s.get("type") or "",
        "days_to": days_to,
        "brief_title": (ident.get("briefTitle") or "")[:300],
        "official_title": (ident.get("officialTitle") or "")[:500],
        "enrollment": "" if enroll is None else str(enroll),
        "enrollment_type": _g(design, "enrollmentInfo", "type") or "",
        "study_type": design.get("studyType") or "",
        "conditions": list(_g(ps, "conditionsModule", "conditions") or []),
        "mesh_terms": [m.get("term", "") for m in meshes if isinstance(m, dict)],
        "interventions": [{"name": i.get("name", ""), "type": i.get("type", "")}
                          for i in (_g(ps, "armsInterventionsModule", "interventions") or [])],
        "allocation": _g(design, "designInfo", "allocation") or "",
        "masking": _g(design, "designInfo", "maskingInfo", "masking") or "",
        "primary_outcomes": outcomes,
    }


# ── 맞추기 ────────────────────────────────────────────────────────────────────

def match_studies(raw: dict[str, dict], matcher: "w.SponsorMatcher", today: date) -> tuple[list[dict], dict]:
    """받은 시험마다 lead 후원사 → SponsorMatcher · 안 맞으면 collaborator 이름들 (AACT 때와 같은 순서) · 불일치는 버림."""
    matches: list[dict] = []
    lead_names: set[str] = set()
    for _nct, st in raw.items():
        spons = _g(st, "protocolSection", "sponsorCollaboratorsModule") or {}
        lead = _g(spons, "leadSponsor", "name") or ""
        collabs = [c.get("name", "") for c in (spons.get("collaborators") or []) if isinstance(c, dict)]
        tk, method = (matcher.match(lead) if lead else (None, ""))
        if lead:
            lead_names.add(lead)
        if tk:
            matcher.hits[tk].add(("lead", method))
        c_hit = None
        for c in collabs:                       # 공동연구 이름은 모두 진단에 남긴다 (AACT 때와 같음)
            ctk, cm = matcher.match(c)
            if ctk:
                matcher.hits[ctk].add(("collaborator", cm))
                c_hit = c_hit or (ctk, cm)
        if tk:
            matches.append(convert_study(st, tk, "lead", method, today))
        elif c_hit:
            matches.append(convert_study(st, c_hit[0], "collaborator", c_hit[1], today))
    matches.sort(key=lambda m: (m["ticker"], m["nct_id"]))
    unmatched = [t for t in matcher.names if not any(r == "lead" for r, _ in matcher.hits.get(t, set()))]
    diag = {"reasons": w.match_reasons(matcher, w._jaccard_review(matcher, lead_names, unmatched)),
            "note": "공식 API 로 받은 후원사 이름 안에서만 만든 진단 (AACT 전체 훑기보다 범위가 좁음 · 판정 영향 없음)"}
    return matches, diag


# ── 가드 · 저장 ───────────────────────────────────────────────────────────────

def _load_prev(path: Path) -> list[dict] | None:
    try:
        data = json.loads(path.read_text())
        m = data.get("matches")
        return m if isinstance(m, list) else None
    except (OSError, ValueError, AttributeError):
        return None


def check_guards(matches: list[dict], prev: list[dict] | None, allow_missing=()) -> None:
    if not matches:
        raise CtgovStop("guard", "받은 결과가 0 study · 이름 검색이 통째로 깨졌을 수 있어 쓰지 않음", 25)
    if not prev:
        return
    if len(matches) < len(prev) * DROP_RATIO:
        raise CtgovStop("guard", f"study 수가 지난 사본 {len(prev)} → {len(matches)} 로 30% 넘게 줄어 쓰지 않음", 25)
    before = {m.get("ticker") for m in prev if m.get("ticker")}
    after = {m["ticker"] for m in matches}
    allowed = {t.strip().upper() for t in allow_missing if t.strip()}
    gone = sorted(before - after - allowed)
    if gone:
        raise CtgovStop(
            "guard",
            f"지난 사본에 시험이 있던 종목 {len(gone)}개가 0건이 되어 쓰지 않음 · 빠진 종목 {', '.join(gone)} · "
            "각 종목을 CT.gov 에서 직접 확인한 뒤 의도한 것이면 "
            "`--allow-missing-tickers " + ",".join(gone) + "` 를 붙여 다시 실행", 25)


def write_atomic(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 바꿔치기 (SEC 명부 방식) · 실패하면 옛 파일이 그대로 남는다."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _parse_ts(ts: str) -> datetime:
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ── 주간 잡 본체 ──────────────────────────────────────────────────────────────

def run_snapshot(names: dict[str, str], aliases: list[dict], n_cand: int, client: CtgovClient | None = None,
                 today: date | None = None, now: datetime | None = None, allow_missing=()) -> dict:
    """받기 → 맞추기 → 가드 → 저장. 멈추면 critical 알림 1통 후 SystemExit (파일은 쓰지 않음)."""
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    client = client or CtgovClient()
    try:
        return _run(names, aliases, n_cand, client, today, now, allow_missing)
    except CtgovStop as e:
        LOG.error("CT.gov API 중단 · %s · 응답 코드별 %s · 요청 %d", e, dict(client.codes), client.requests)
        w._notify_failure_sync(e.step, e.detail)
        raise SystemExit(e.exit_code)


def _run(names, aliases, n_cand, client, today, now, allow_missing) -> dict:
    ts = get_data_timestamp(client)
    date_str = ts[:10]
    if now - _parse_ts(ts) > timedelta(days=STALE_DAYS):
        LOG.warning("API 자료 시각 %s · 실행보다 %d일 넘게 늦음", ts, STALE_DAYS)
        w._notify_warning_sync("data_timestamp", f"API 자료 시각 {ts} 가 실행 시각보다 {STALE_DAYS}일 넘게 늦음 · 파일은 씀")

    queries = build_queries(names, aliases)
    raw, zero = fetch_all(client, queries)
    matcher = w.SponsorMatcher(names, aliases)
    matches, diag = match_studies(raw, matcher, today)
    prev = _load_prev(w.OUT_JSON)
    check_guards(matches, prev, allow_missing)

    w.OUT_DIR.mkdir(parents=True, exist_ok=True)
    w._write_match_report(date_str, matches, diag)
    out = {
        "generated_utc": now.isoformat(),
        "aact_snapshot_date": date_str,
        "source": SOURCE,
        "api_data_timestamp": ts,
        "candidates_v3_count": n_cand,
        "candidate_matches": len({m["ticker"] for m in matches}),
        "study_matches": len(matches),
        "api_zero_result_names": len(zero),
        "matches": matches,
        "sponsor_active_counts": w.sponsor_active_counts(matches),
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    write_atomic(w.OUT_JSON, text)
    write_atomic(w.snapshot_copy_path(date_str), text)
    LOG.info("출처 %s · study %d · ticker %d · 검색어 %d · 받은 시험 %d · 0건 이름 %d · 응답 코드별 %s · 총 요청 %d · 자료 시각 %s",
             SOURCE, len(matches), out["candidate_matches"], len(queries), len(raw), len(zero),
             dict(client.codes), client.requests, ts)
    return out
