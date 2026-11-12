"""P3a ④ · AACT 주간 · 날짜 종류 필드 3개 · 머리글 없으면 로그+빈값 · 날짜별 사본 26주 · 스폰서별 진행 중 임상 수 (FR-6a)."""
from __future__ import annotations

import logging
import zipfile
from datetime import date

from backend.scripts import biotech_h69_aact_weekly as w

SPONSORS = "id|nct_id|agency_class|lead_or_collaborator|name\n1|NCT1|INDUSTRY|lead|Acme Bio, Inc.\n"


def _zip(tmp_path, studies: str):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("studies.txt", studies)
        z.writestr("sponsors.txt", SPONSORS)
    return p


def test_date_type_fields_saved(tmp_path, caplog):
    studies = ("nct_id|phase|overall_status|primary_completion_date|primary_completion_date_type|last_update_posted_date|"
               "completion_date_type|brief_title\n"
               "NCT1|PHASE2|RECRUITING|2026-12-01|ESTIMATED|2026-09-15|ESTIMATED|T\n")
    with caplog.at_level(logging.INFO):
        res = w._parse_studies_and_sponsors(_zip(tmp_path, studies), {w._norm("Acme Bio, Inc."): "ACME"})
    assert res[0]["primary_completion_date_type"] == "ESTIMATED" and res[0]["last_update_posted_date"] == "2026-09-15"
    assert res[0]["completion_date_type"] == "ESTIMATED"
    assert "날짜 종류 필드 3개 있음" in caplog.text


def test_missing_header_logged_and_blank(tmp_path, caplog):
    studies = "nct_id|phase|overall_status|primary_completion_date|brief_title\nNCT1|PHASE2|RECRUITING|2026-12-01|T\n"
    with caplog.at_level(logging.WARNING):
        res = w._parse_studies_and_sponsors(_zip(tmp_path, studies), {w._norm("Acme Bio, Inc."): "ACME"})
    assert res[0]["primary_completion_date_type"] == "" and res[0]["completion_date_type"] == ""
    assert "studies.txt 머리글에 primary_completion_date_type 없음" in caplog.text
    assert caplog.text.count("머리글에") == 3


def test_snapshot_copy_name_and_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "OUT_DIR", tmp_path)
    assert w.snapshot_copy_path("2026-10-01").name == "ctgov_snapshot_20261001.json"
    for d in ("20260301", "20260405", "20260406", "20261001"):
        (tmp_path / f"ctgov_snapshot_{d}.json").write_text("{}")
    (tmp_path / "ctgov_snapshot.json").write_text("{}")
    n = w.prune_snapshot_copies(date(2026, 10, 5))            # 182일 전 = 2026-04-06
    assert n == 2 and sorted(p.name for p in tmp_path.iterdir()) == [
        "ctgov_snapshot.json", "ctgov_snapshot_20260406.json", "ctgov_snapshot_20261001.json"]


def _m(tk, nct, role, phase, status):
    return {"ticker": tk, "nct_id": nct, "role": role, "phase": phase, "overall_status": status}


def test_sponsor_active_counts_fr6a_scope():
    ms = [
        _m("IOVA", "N1", "lead", "PHASE2", "RECRUITING"),
        _m("IOVA", "N2", "lead", "PHASE2/PHASE3", "ACTIVE_NOT_RECRUITING"),
        _m("IOVA", "N3", "lead", "PHASE3", "NOT_YET_RECRUITING"),
        _m("IOVA", "N4", "lead", "PHASE1/PHASE2", "ENROLLING_BY_INVITATION"),
        _m("IOVA", "N5", "lead", "PHASE3", "COMPLETED"),              # 진행 중 아님
        _m("IOVA", "N6", "lead", "PHASE1", "RECRUITING"),             # 1상 · 세지 않음
        _m("IOVA", "N7", "collaborator", "PHASE2", "RECRUITING"),
        _m("EDIT", "N8", "lead", "PHASE1/PHASE2", "RECRUITING"),
    ]
    c = w.sponsor_active_counts(ms)
    assert c["IOVA"] == {"lead_phase2_plus": 3, "lead_phase1_2": 1, "collaborator": 1, "lead_phase2_plus_ncts": ["N1", "N2", "N3"]}
    assert c["EDIT"]["lead_phase2_plus"] == 0 and c["EDIT"]["lead_phase1_2"] == 1


# ── 1112-03 · AACT 있는지 확인을 HEAD 대신 1바이트 범위 GET 으로 (서명 저장소는 HEAD 403) ──
import httpx  # noqa: E402

_SIGNED = "https://ctti-aact.nyc3.digitaloceanspaces.com/signed"


class _NoReadStream(httpx.SyncByteStream):
    """본문을 읽으면 실패 · Range 무시 200 응답에서 2.4GB 를 읽지 않는지 확인용."""

    def __iter__(self):
        raise AssertionError("본문을 읽으면 안 됨")

    def close(self):
        pass


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _day(i: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()


def test_probe_follows_redirect_and_reads_size_from_content_range():
    seen = []

    def h(req):
        seen.append((req.method, req.headers.get("range")))
        if req.url.host.startswith("aact"):
            return httpx.Response(302, headers={"location": _SIGNED})
        return httpx.Response(206, headers={"content-range": "bytes 0-0/2574652840"}, content=b"P")

    with _client(h) as c:
        got = w._pick_aact_url(client=c)
    assert got is not None and got[0] == _day(0)
    assert len(seen) == 2 and all(m == "GET" and rg == "bytes=0-0" for m, rg in seen)
    assert w.LAST_PROBE_STOP is None


def test_probe_404_then_previous_day():
    def h(req):
        if _day(0) in str(req.url):
            return httpx.Response(404)
        return httpx.Response(206, headers={"content-range": "bytes 0-0/10"}, content=b"P")

    with _client(h) as c:
        got = w._pick_aact_url(client=c)
    assert got is not None and got[0] == _day(1)


def test_probe_403_stops_and_records_reason():
    calls = []

    def h(req):
        calls.append(str(req.url))
        return httpx.Response(403)

    with _client(h) as c:
        assert w._pick_aact_url(client=c) is None
    assert len(calls) == 1
    assert w.LAST_PROBE_STOP and "접근 거부 403" in w.LAST_PROBE_STOP


def test_probe_range_ignored_200_does_not_read_body():
    def h(req):
        return httpx.Response(200, headers={"content-length": "2574652840"}, stream=_NoReadStream())

    with _client(h) as c:
        got = w._pick_aact_url(client=c)
    assert got is not None and got[0] == _day(0)


def test_probe_missing_content_range_gives_zero_size_without_error():
    assert w._content_range_total(None) == 0
    assert w._content_range_total("bytes 0-0/*") == 0
    assert w._content_range_total("bytes 0-0/123") == 123

    def h(req):
        return httpx.Response(206, content=b"P")

    with _client(h) as c:
        assert w._pick_aact_url(client=c) is not None
