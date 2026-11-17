"""1112-03 · 임상 자료 공식 API(ClinicalTrials.gov v2) 주간 받기 · 네트워크 없이 가짜 응답 (httpx.MockTransport).

가짜 자료는 가상 회사 이름 · 가상 NCT 번호만 쓴다 (공개 저장소).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from backend.scripts import biotech_ctgov_api as api
from backend.scripts import biotech_h69_aact_weekly as w

TODAY = date(2026, 11, 17)


def _study(nct="NCT90000001", lead="Acme Bio, Inc.", collabs=(), phases=("PHASE2",), status="RECRUITING",
           pcd="2026-12-01", pcd_type="ESTIMATED", cd="2027-03", cd_type="ESTIMATED", upd="2026-11-10",
           enroll=120, enroll_type="ESTIMATED", **over):
    ps = {
        "identificationModule": {"nctId": nct, "briefTitle": "B" * 400, "officialTitle": "O" * 700},
        "statusModule": {
            "overallStatus": status,
            "primaryCompletionDateStruct": {"date": pcd, "type": pcd_type} if pcd else {},
            "completionDateStruct": {"date": cd, "type": cd_type},
            "lastUpdatePostDateStruct": {"date": upd},
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": lead, "class": "INDUSTRY"},
            "collaborators": [{"name": c, "class": "INDUSTRY"} for c in collabs],
        },
        "conditionsModule": {"conditions": ["Zeta Disease", "Alpha Disease"]},
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": list(phases),
            "designInfo": {"allocation": "RANDOMIZED", "maskingInfo": {"masking": "DOUBLE"}},
            "enrollmentInfo": {"count": enroll, "type": enroll_type},
        },
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Drug A", "description": "x"}]},
        "outcomesModule": {"primaryOutcomes": [
            {"measure": f"M{i}" + "m" * 400, "description": "d", "timeFrame": "T" * 300} for i in range(5)]},
    }
    ps.update(over)
    return {"protocolSection": ps, "derivedSection": {"conditionBrowseModule": {
        "meshes": [{"id": "D1", "term": "Mesh Z"}, {"id": "D2", "term": "Mesh A"}],
        "ancestors": [{"id": "D9", "term": "Ancestor"}]}}}


class FakeApi:
    """query.spons → 쪽 목록. version 응답과 상태 코드 덮어쓰기 지원."""

    def __init__(self, pages=None, version="2026-11-16T10:00:05", force=None):
        self.pages = pages or {}          # term → [study 목록, ...] (쪽별)
        self.version = version
        self.force = force                # (조건함수, Response 만들기)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        params = dict(req.url.params)
        self.calls.append((req.url.path, params))
        if self.force:
            resp = self.force(req, len(self.calls))
            if resp is not None:
                return resp
        if req.url.path.endswith("/version"):
            return httpx.Response(200, json={"apiVersion": "2.0.5", "dataTimestamp": self.version})
        term = params.get("query.spons", "")
        pages = self.pages.get(term.lower(), [])
        idx = int(params["pageToken"].split("-")[1]) if "pageToken" in params else 0
        studies = pages[idx] if idx < len(pages) else []
        body = {"studies": studies}
        if idx + 1 < len(pages):
            body["nextPageToken"] = f"tok-{idx + 1}"
        return httpx.Response(200, json=body)


def _client(fake, sleeps=None):
    http = httpx.Client(transport=httpx.MockTransport(fake), base_url=api.API_BASE)
    return api.CtgovClient(http=http, sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


NAMES = {"ACME": "Acme Bio, Inc. /DE/", "VRTX": "Vertex Example Pharmaceuticals Inc /MA/", "ZZZ": "Zeta Nothing Corp"}
ALIASES = [{"alias": "Acme Biopharma Ltd", "ticker": "ACME", "basis": "자체명 변형"},
           {"alias": "Vertex Sub LLC", "ticker": "VRTX", "basis": "자회사"},
           {"alias": "Other Co", "ticker": "NOTCAND", "basis": "자체명 변형"}]

# ── 1. 값 옮기기 ──────────────────────────────────────────────────────────────

def test_month_date_becomes_last_day():
    assert api.norm_date("2026-02") == "2026-02-28"
    assert api.norm_date("2028-02") == "2028-02-29"
    assert api.norm_date("2026-12") == "2026-12-31"
    assert api.norm_date("2026-04") == "2026-04-30"
    assert api.norm_date("2026-12-01") == "2026-12-01"
    assert api.norm_date("") == "" and api.norm_date(None) == ""


def test_phase_join_blank_and_na():
    assert api.join_phase(["PHASE2", "PHASE3"]) == "PHASE2/PHASE3"
    assert api.join_phase(["PHASE1", "PHASE2"]) == "PHASE1/PHASE2"
    assert api.join_phase(["NA"]) == "NA"
    assert api.join_phase([]) == "" and api.join_phase(None) == ""
    assert api.join_phase(["PHASE3"]) == "PHASE3"


def test_convert_values_and_lengths():
    m = api.convert_study(_study(), "ACME", "lead", "legacy", TODAY)
    assert m["phase"] == "PHASE2" and m["overall_status"] == "RECRUITING"
    assert m["primary_completion_date"] == "2026-12-01" and m["days_to"] == (date(2026, 12, 1) - TODAY).days
    assert m["primary_completion_date_type"] == "ESTIMATED" and m["completion_date_type"] == "ESTIMATED"
    assert m["last_update_posted_date"] == "2026-11-10"
    assert m["enrollment"] == "120" and isinstance(m["enrollment"], str) and m["enrollment_type"] == "ESTIMATED"
    assert m["study_type"] == "INTERVENTIONAL"
    assert len(m["brief_title"]) == 300 and len(m["official_title"]) == 500
    assert m["allocation"] == "RANDOMIZED" and m["masking"] == "DOUBLE"
    assert m["conditions"] == ["Zeta Disease", "Alpha Disease"]            # API 순서 그대로
    assert m["mesh_terms"] == ["Mesh Z", "Mesh A"]                          # 상위 개념(ancestors) 제외 · 순서 그대로
    assert m["interventions"] == [{"name": "Drug A", "type": "DRUG"}]
    assert len(m["primary_outcomes"]) == 3
    assert len(m["primary_outcomes"][0]["measure"]) == 300 and len(m["primary_outcomes"][0]["time_frame"]) == 200


def test_convert_month_only_dates_and_missing():
    m = api.convert_study(_study(pcd="2026-12", upd="2026-11"), "ACME", "lead", "v2", TODAY)
    assert m["primary_completion_date"] == "2026-12-31"
    assert m["days_to"] == (date(2026, 12, 31) - TODAY).days
    assert m["last_update_posted_date"] == "2026-11-30"
    m2 = api.convert_study(_study(pcd=""), "ACME", "lead", "v2", TODAY)
    assert m2["primary_completion_date"] == "" and m2["days_to"] is None and m2["primary_completion_date_type"] == ""
    s = _study(phases=())
    s["protocolSection"]["designModule"]["designInfo"] = {}
    m3 = api.convert_study(s, "ACME", "lead", "v2", TODAY)
    assert m3["phase"] == "" and m3["allocation"] == "" and m3["masking"] == ""


def test_output_fields_match_aact_output_fields():
    """AACT 쪽이 내던 칸 이름이 모두 새 출력에 있다 (읽는 곳 5곳이 쓰는 칸 포함)."""
    aact_cols = {"ticker", "nct_id", "role", "match_method", "phase", "overall_status", "primary_completion_date",
                 "primary_completion_date_type", "last_update_posted_date", "completion_date_type", "days_to",
                 "brief_title", "official_title", "enrollment", "enrollment_type", "study_type",
                 "conditions", "mesh_terms", "interventions", "primary_outcomes", "allocation", "masking"}
    m = api.convert_study(_study(), "ACME", "lead", "legacy", TODAY)
    assert aact_cols <= set(m)
    assert set(m) - aact_cols == set()



def test_text_quotes_removed_like_aact():
    """11/12 비교: AACT 글에는 큰따옴표가 없다 (제목 · 1차 목표) · 새 출력도 뺀다."""
    s = _study()
    s["protocolSection"]["identificationModule"]["briefTitle"] = '"Natural History" Study'
    s["protocolSection"]["outcomesModule"]["primaryOutcomes"] = [{"measure": 'graded per "CTCAE"', "timeFrame": '"6" months'}]
    m = api.convert_study(s, "ACME", "lead", "legacy", TODAY)
    assert m["brief_title"] == "Natural History Study"
    assert m["primary_outcomes"] == [{"measure": "graded per CTCAE", "time_frame": "6 months"}]


def test_no_design_info_has_no_allocation_keys():
    """11/12 비교: AACT 는 설계 행이 없으면 allocation · masking 칸이 없었다 · 설계가 있고 값만 비면 빈칸."""
    s = _study()
    del s["protocolSection"]["designModule"]["designInfo"]
    m = api.convert_study(s, "ACME", "lead", "legacy", TODAY)
    assert "allocation" not in m and "masking" not in m
    s2 = _study()
    s2["protocolSection"]["designModule"]["designInfo"] = {"allocation": "NA"}
    m2 = api.convert_study(s2, "ACME", "lead", "legacy", TODAY)
    assert m2["allocation"] == "NA" and m2["masking"] == ""

# ── 2. 쪽 넘기기 ──────────────────────────────────────────────────────────────

def test_follow_next_page_token_three_pages():
    pages = {"acme bio": [[_study("NCT90000001")], [_study("NCT90000002")], [_study("NCT90000003")]]}
    fake = FakeApi(pages)
    got = api.fetch_term(_client(fake), "acme bio")
    assert [s["protocolSection"]["identificationModule"]["nctId"] for s in got] == [
        "NCT90000001", "NCT90000002", "NCT90000003"]
    studies_calls = [p for path, p in fake.calls if path.endswith("/studies")]
    assert len(studies_calls) == 3 and studies_calls[0]["pageSize"] == "1000"
    assert "pageToken" not in studies_calls[0] and studies_calls[2]["pageToken"] == "tok-2"
    assert "ResultsSection" not in studies_calls[0]["fields"] and "NCTId" in studies_calls[0]["fields"]


def test_page_limit_stops_whole_job(tmp_path, monkeypatch):
    many = [[_study(f"NCT9{i:07d}")] for i in range(api.MAX_PAGES + 3)]
    fake = FakeApi({"acme bio": many})
    with pytest.raises(api.CtgovStop) as e:
        api.fetch_term(_client(fake), "acme bio")
    assert "쪽" in e.value.detail


def _setup_out(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "OUT_DIR", tmp_path)
    monkeypatch.setattr(w, "OUT_JSON", tmp_path / "ctgov_snapshot.json")
    calls = {"fail": [], "warn": []}
    monkeypatch.setattr(w, "_notify_failure_sync", lambda step, detail: calls["fail"].append((step, detail)))
    monkeypatch.setattr(w, "_notify_warning_sync", lambda step, detail: calls["warn"].append((step, detail)))
    return calls


def _run(fake, tmp_path, allow=(), names=None):
    return api.run_snapshot(names or NAMES, ALIASES, n_cand=len(names or NAMES), client=_client(fake), today=TODAY,
                            allow_missing=allow)


def test_page_limit_writes_no_file(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    many = [[_study(f"NCT9{i:07d}")] for i in range(api.MAX_PAGES + 3)]
    with pytest.raises(SystemExit):
        _run(FakeApi({"acme bio": many}), tmp_path)
    assert list(tmp_path.iterdir()) == [] and calls["fail"] and "쪽" in calls["fail"][0][1]


# ── 3. 검색어 · 맞추기 ────────────────────────────────────────────────────────

def test_search_term_strips_state_and_suffix():
    assert api.search_term("Vertex Example Pharmaceuticals Inc / MA") == "vertex example pharmaceuticals"
    assert api.search_term("Acme Bio, Inc. /DE/") == "acme bio"
    assert api.search_term("Novo Example A/S") == "novo example"
    assert api.search_term("") == ""


def test_build_queries_names_aliases_dedupe():
    q = api.build_queries(NAMES, ALIASES)
    assert q == ["acme bio", "vertex example pharmaceuticals", "zeta nothing", "acme biopharma", "vertex sub"]
    assert len(q) == len(set(q))                                   # 같은 검색어는 한 번만
    assert "other" not in " ".join(q)                               # 후보 아닌 티커 별칭은 보내지 않음


def _matcher():
    return w.SponsorMatcher(NAMES, ALIASES)


def test_match_lead_collab_and_discard():
    raw = {
        "NCT90000001": _study("NCT90000001", lead="Acme Bio, Inc."),
        "NCT90000002": _study("NCT90000002", lead="Big University", collabs=("Vertex Example Pharmaceuticals, Inc.",)),
        "NCT90000003": _study("NCT90000003", lead="Acme Biopharma Ltd"),
        "NCT90000004": _study("NCT90000004", lead="Unrelated Acme Bio Holdings Group"),   # 검색엔 걸렸으나 규칙 불일치
        "NCT90000005": _study("NCT90000005", lead="Vertex Sub LLC"),
    }
    matches, diag = api.match_studies(raw, _matcher(), TODAY)
    by = {m["nct_id"]: m for m in matches}
    assert set(by) == {"NCT90000001", "NCT90000002", "NCT90000003", "NCT90000005"}
    assert by["NCT90000001"]["role"] == "lead" and by["NCT90000001"]["ticker"] == "ACME"
    assert by["NCT90000002"]["role"] == "collaborator" and by["NCT90000002"]["ticker"] == "VRTX"
    assert by["NCT90000003"]["match_method"] == "alias" and by["NCT90000005"]["match_method"] == "alias_sub"
    assert diag["reasons"]["ZZZ"]["reason"].startswith("임상 없음")


def test_same_nct_from_two_queries_once(tmp_path, monkeypatch):
    _setup_out(tmp_path, monkeypatch)
    s = _study("NCT90000001", lead="Acme Bio, Inc.")
    pages = {"acme bio": [[s]], "acme biopharma": [[s]]}
    out = _run(FakeApi(pages), tmp_path)
    assert out["study_matches"] == 1


def test_zero_result_names_counted(tmp_path, monkeypatch, caplog):
    _setup_out(tmp_path, monkeypatch)
    pages = {"acme bio": [[_study()]]}
    with caplog.at_level(logging.INFO):
        out = _run(FakeApi(pages), tmp_path)
    assert out["api_zero_result_names"] == 4          # 5개 검색어 중 1개만 결과 있음
    assert "0건 이름 4" in caplog.text


# ── 4. 실패 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [401, 403, 404, 410, 429])
def test_4xx_stops_without_retry(tmp_path, monkeypatch, code):
    calls = _setup_out(tmp_path, monkeypatch)
    fake = FakeApi({}, force=lambda req, n: httpx.Response(code) if req.url.path.endswith("/studies") else None)
    with pytest.raises(SystemExit):
        _run(fake, tmp_path)
    assert sum(1 for p, _ in fake.calls if p.endswith("/studies")) == 1
    assert list(tmp_path.iterdir()) == []
    assert str(code) in calls["fail"][0][1]


def test_5xx_retries_three_times_then_stops(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    sleeps: list[float] = []
    fake = FakeApi({}, force=lambda req, n: httpx.Response(503) if req.url.path.endswith("/studies") else None)
    with pytest.raises(SystemExit):
        api.run_snapshot(NAMES, ALIASES, n_cand=3, client=_client(fake, sleeps), today=TODAY)
    assert sum(1 for p, _ in fake.calls if p.endswith("/studies")) == 3
    assert api.RETRY_WAIT in sleeps
    assert "503" in calls["fail"][0][1] and list(tmp_path.iterdir()) == []


def test_5xx_then_ok_recovers():
    state = {"n": 0}

    def force(req, n):
        if req.url.path.endswith("/studies") and state["n"] < 2:
            state["n"] += 1
            return httpx.Response(502)
        return None

    fake = FakeApi({"acme bio": [[_study()]]}, force=force)
    got = api.fetch_term(_client(fake), "acme bio")
    assert len(got) == 1


def test_connection_error_retries_then_stops():
    def force(req, n):
        raise httpx.ConnectError("boom")

    fake = FakeApi({}, force=force)
    with pytest.raises(api.CtgovStop):
        api.fetch_term(_client(fake), "acme bio")
    assert len(fake.calls) == 3


def test_not_json_and_missing_studies(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    fake = FakeApi({}, force=lambda req, n: httpx.Response(200, text="<html>nope</html>")
                   if req.url.path.endswith("/studies") else None)
    with pytest.raises(SystemExit):
        _run(fake, tmp_path)
    fake2 = FakeApi({}, force=lambda req, n: httpx.Response(200, json={"error": "x"})
                    if req.url.path.endswith("/studies") else None)
    with pytest.raises(SystemExit):
        _run(fake2, tmp_path)
    assert len(calls["fail"]) == 2 and list(tmp_path.iterdir()) == []


def test_version_failure_stops_with_code(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    fake = FakeApi({}, force=lambda req, n: httpx.Response(410) if req.url.path.endswith("/version") else None)
    with pytest.raises(SystemExit):
        _run(fake, tmp_path)
    assert "410" in calls["fail"][0][1]


def test_pacing_sleeps_between_requests():
    sleeps: list[float] = []
    fake = FakeApi({"acme bio": [[_study()], [_study("NCT90000002")]]})
    api.fetch_term(_client(fake, sleeps), "acme bio")
    assert sleeps and max(sleeps) <= api.MIN_INTERVAL and api.MIN_INTERVAL >= 1.5


# ── 5. 줄어듦 가드 · 바꿔치기 ─────────────────────────────────────────────────

def _prev(tmp_path, tickers_ncts):
    matches = [{"ticker": tk, "nct_id": n, "role": "lead"} for tk, n in tickers_ncts]
    (tmp_path / "ctgov_snapshot.json").write_text(json.dumps({"matches": matches}))
    return (tmp_path / "ctgov_snapshot.json").read_text()


def test_zero_study_not_written(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        _run(FakeApi({}), tmp_path)
    assert list(tmp_path.iterdir()) == [] and "0" in calls["fail"][0][1]


def test_drop_over_30_percent_not_written(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    before = _prev(tmp_path, [("ACME", f"NCT8{i:07d}") for i in range(10)])
    with pytest.raises(SystemExit):
        _run(FakeApi({"acme bio": [[_study()]]}), tmp_path)
    assert (tmp_path / "ctgov_snapshot.json").read_text() == before        # 지난 사본 그대로
    assert [p.name for p in tmp_path.iterdir()] == ["ctgov_snapshot.json"]
    assert "30%" in calls["fail"][0][1]


def test_missing_ticker_blocks_and_lists_tickers(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    prev = [("ACME", "NCT80000001"), ("VRTX", "NCT80000002")]
    before = _prev(tmp_path, prev)
    # 새 결과: ACME 2건 · VRTX 0건 → 총수는 안 줄었지만 종목이 통째로 빠짐
    pages = {"acme bio": [[_study("NCT90000001"), _study("NCT90000002")]]}
    with pytest.raises(SystemExit):
        _run(FakeApi(pages), tmp_path)
    assert (tmp_path / "ctgov_snapshot.json").read_text() == before
    detail = calls["fail"][0][1]
    assert "VRTX" in detail and "ACME" not in detail.split("빠진 종목")[1]
    assert "--allow-missing-tickers" in detail                            # 수동 확인 뒤 다시 돌리는 길


def test_missing_ticker_allowed_after_manual_check(tmp_path, monkeypatch):
    _setup_out(tmp_path, monkeypatch)
    _prev(tmp_path, [("ACME", "NCT80000001"), ("VRTX", "NCT80000002")])
    pages = {"acme bio": [[_study("NCT90000001"), _study("NCT90000002")]]}
    out = _run(FakeApi(pages), tmp_path, allow=("VRTX",))
    assert out["study_matches"] == 2



def test_ticker_left_candidates_is_not_missing(tmp_path, monkeypatch):
    """Fable 1112-03-03 막음 1: 이번 후보에서 나간 종목은 「빠짐」이 아니다 · 막지 않고 쓴다."""
    calls = _setup_out(tmp_path, monkeypatch)
    _prev(tmp_path, [("ACME", "NCT80000001")] + [("GONE", f"NCT7{i:07d}") for i in range(10)])
    out = _run(FakeApi({"acme bio": [[_study("NCT90000001")]]}), tmp_path)
    assert out["study_matches"] == 1 and not calls["fail"]          # 30% 가드도 후보에 남은 종목(ACME 1건)만으로 본다


def test_ticker_still_candidate_but_zero_blocks(tmp_path, monkeypatch):
    """후보에 남아 있는데 0건이면 여전히 막는다 (후보 밖 종목이 섞여 있어도)."""
    calls = _setup_out(tmp_path, monkeypatch)
    _prev(tmp_path, [("ACME", "NCT80000001"), ("VRTX", "NCT80000002"), ("GONE", "NCT70000001")])
    with pytest.raises(SystemExit):
        _run(FakeApi({"acme bio": [[_study("NCT90000001"), _study("NCT90000002")]]}), tmp_path)
    detail = calls["fail"][0][1]
    assert "VRTX" in detail and "GONE" not in detail


def test_happy_path_writes_atomically_and_extra_fields(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    (tmp_path / "ctgov_snapshot.json").write_text(json.dumps({"matches": []}))
    pages = {"acme bio": [[_study("NCT90000001"), _study("NCT90000002", status="COMPLETED")]]}
    out = _run(FakeApi(pages), tmp_path)
    saved = json.loads((tmp_path / "ctgov_snapshot.json").read_text())
    assert saved["source"] == "ctgov_api_v2" and saved["api_data_timestamp"] == "2026-11-16T10:00:05"
    assert saved["aact_snapshot_date"] == "2026-11-16"
    for k in ("generated_utc", "candidates_v3_count", "candidate_matches", "study_matches", "matches", "sponsor_active_counts"):
        assert k in saved
    assert saved["study_matches"] == 2 and saved["sponsor_active_counts"]["ACME"]["lead_phase2_plus"] == 1
    assert (tmp_path / "ctgov_snapshot_20261116.json").exists()
    assert not list(tmp_path.glob("*.tmp"))                                 # 임시 파일 남지 않음
    assert (tmp_path / "aact_match_report_2026-11-16.json").exists()
    assert out["source"] == "ctgov_api_v2" and not calls["fail"] and not calls["warn"]


def test_write_atomic_leaves_old_file_if_replace_fails(tmp_path, monkeypatch):
    p = tmp_path / "x.json"
    p.write_text("OLD")
    import os
    monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        api.write_atomic(p, "NEW")
    assert p.read_text() == "OLD"


def test_stale_data_timestamp_warns_but_writes(tmp_path, monkeypatch):
    calls = _setup_out(tmp_path, monkeypatch)
    now = datetime(2026, 11, 17, 6, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S")
    pages = {"acme bio": [[_study()]]}
    api.run_snapshot(NAMES, ALIASES, n_cand=3, client=_client(FakeApi(pages, version=old)), today=TODAY, now=now)
    assert (tmp_path / "ctgov_snapshot.json").exists() and len(calls["warn"]) == 1
    # 7일 이내면 경고 없음
    calls["warn"].clear()
    fresh = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    api.run_snapshot(NAMES, ALIASES, n_cand=3, client=_client(FakeApi(pages, version=fresh)), today=TODAY, now=now)
    assert not calls["warn"]


# ── 5-1. 판정 경로 ────────────────────────────────────────────────────────────

def test_attribute_stage_works_on_new_output(tmp_path, monkeypatch):
    from backend.scripts import biotech_fr6c as fr6c
    _setup_out(tmp_path, monkeypatch)
    pages = {"acme bio": [[_study("NCT90000001", phases=("PHASE2", "PHASE3"), pcd="2026-11"),
                           _study("NCT90000002", phases=("PHASE1",), pcd="2026-11-25")]]}
    out = _run(FakeApi(pages), tmp_path)
    r = fr6c.attribute_stage("ACME", "2026-11-20T10:00:00", [], out)
    assert r["stage_src"] == "AACT" and r["aact_nct"] == "NCT90000001" and r["aact_pcd"] == "2026-11-30"
    assert r["aact_phase"] == "PHASE2/PHASE3"


def test_month_date_days_to_same_as_aact_parse():
    """AACT 파서는 월 단위를 그 달 마지막 날로 사본에 넣었다 (9/28 사본 · 계획 3절) · days_to 도 같다."""
    m = api.convert_study(_study(pcd="2026-11"), "ACME", "lead", "v2", TODAY)
    assert m["days_to"] == (date(2026, 11, 30) - TODAY).days == 13


# ── 6. 출력 모양 · 가져다 쓰는 이름 ───────────────────────────────────────────

def test_consumer_fields_present_in_output():
    """읽는 곳 5곳이 쓰는 칸 (h50 · biotech.py · h6 · auto_category) 이 새 출력 행에 있다."""
    m = api.convert_study(_study(), "ACME", "lead", "legacy", TODAY)
    for k in ("ticker", "nct_id", "role", "phase", "overall_status", "primary_completion_date", "days_to",
              "last_update_posted_date", "conditions", "mesh_terms", "interventions", "brief_title"):
        assert k in m


def test_h6_imported_names_still_exist():
    """biotech_h6_aact_theme_extract.py:50-51 이 h69 에서 가져오는 이름 · 지우거나 바꾸면 안 됨 (Fable 2차 권고 4)."""
    for name in ("_download_zip", "_notify_failure_sync", "_pick_aact_url", "_unzip_test"):
        assert callable(getattr(w, name)), name
    import ast
    import pathlib
    src = pathlib.Path(w.__file__).with_name("biotech_h6_aact_theme_extract.py").read_text()
    imported = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)
                and n.module == "backend.scripts.biotech_h69_aact_weekly" for a in n.names}
    assert {"_download_zip", "_notify_failure_sync"} <= imported
    for name in imported:
        assert hasattr(w, name), name


def test_main_does_not_call_aact_functions(monkeypatch):
    """주간 main() 이 AACT 받기 함수를 부르지 않는다 (코드는 남김)."""
    import inspect
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(w.main)))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    called |= {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for forbidden in ("_pick_aact_url", "_download_zip", "_unzip_test", "_parse_studies_and_sponsors"):
        assert forbidden not in called
    assert "run_snapshot" in called


# ── 비교 스크립트 (실행하지 않고 계산 함수만 시험) ─────────────────────────────

def test_compare_criteria_with_synthetic_data():
    from backend.scripts import biotech_ctgov_compare as cmp
    ref = date(2026, 11, 12)

    def row(nct, tk, role="lead", pcd="2026-12-31", upd="2026-10-01", status="RECRUITING", conds=("A", "B")):
        return {"ticker": tk, "nct_id": nct, "role": role, "primary_completion_date": pcd, "days_to": 49,
                "last_update_posted_date": upd, "overall_status": status, "conditions": list(conds), "mesh_terms": []}

    old = {"matches": [row("N1", "AAA"), row("N2", "AAA", pcd="2027-01-31"), row("N3", "BBB"), row("N4", "CCC", role="collaborator")],
           "sponsor_active_counts": {"AAA": {"lead_phase2_plus": 2}}}
    new = [row("N1", "AAA", status="COMPLETED", upd="2026-11-14"),        # 11/12 뒤 갱신 → 인정
           row("N2", "AAA", pcd="2027-01-31", conds=("B", "A")),          # 순서만 다름 → 차이로 셈
           row("N5", "AAA")]                                              # 새로 잡힘
    res = cmp.compare(old, new, {"AAA": {"lead_phase2_plus": 2}}, {"N1", "N2", "N5", "N4"}, ref)
    assert res["c1_missing"] == [{"nct_id": "N3", "ticker": "BBB", "reason": "받은 결과에 없음 (검색에 안 걸림)"}] and not res["c1_pass"]
    assert res["c2_recapture"] == 2 and not res["c2_pass"] and res["c2_missing_rule_dropped"] == ["N4"]
    assert res["c3_only_old"] == ["BBB", "CCC"] and res["c7_new_only"] == ["N5"]
    assert res["c6_updated_after_ref_counts"] == {"overall_status": 1, "last_update_posted_date": 1}
    assert res["c6_counts"] == {"conditions": 1} and res["c6_diff"]["conditions"][0]["same_set_different_order"] is True
    assert "미달" in cmp.render_md(res)
