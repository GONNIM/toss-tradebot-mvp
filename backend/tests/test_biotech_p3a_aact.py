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
