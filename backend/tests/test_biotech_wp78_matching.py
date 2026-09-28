"""WP78 · AACT 역방향 매칭 · 별칭 · 공동연구 · 사유 분해 · Jaccard 검수 전용."""
from __future__ import annotations

import zipfile

from backend.scripts import biotech_h69_aact_weekly as w


def _zip(tmp_path):
    p = tmp_path / "aact.zip"
    studies = "nct_id|brief_title|official_title|phase|overall_status|primary_completion_date|enrollment|enrollment_type|study_type\n"
    studies += "\n".join(f"NCT{i}|t|o|PHASE2|RECRUITING|2026-12-01|10|ACTUAL|INTERVENTIONAL" for i in range(1, 7)) + "\n"
    sponsors = ("id|nct_id|agency_class|lead_or_collaborator|name\n"
                "1|NCT1|INDUSTRY|lead|Acme Bio, Inc.\n2|NCT2|INDUSTRY|lead|Beta Therapeutics\n"
                "3|NCT3|OTHER|lead|Some University\n4|NCT3|INDUSTRY|collaborator|Gamma Pharma Inc\n"
                "5|NCT4|INDUSTRY|lead|Janssen Research & Development, LLC\n"
                "6|NCT5|INDUSTRY|lead|Alpha Beta Gamma Delta Epsilon\n")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("studies.txt", studies)
        z.writestr("sponsors.txt", sponsors)
    return p


def test_reverse_matching_roles_and_reasons(tmp_path):
    cands = {"ACME": "ACME BIO INC", "BETA": "BETA THERAPEUTICS, INC.", "GAMA": "GAMMA PHARMA INC",
             "JNJ": "JOHNSON & JOHNSON", "ABGD": "ALPHA BETA GAMMA DELTA", "ZZZ": "ZETA NOTHING CORP"}
    m = w.SponsorMatcher(cands, [{"alias": "Janssen Research & Development, LLC", "ticker": "JNJ", "basis": "J&J 자회사"}])
    diag: dict = {}
    res = w._parse_studies_and_sponsors(_zip(tmp_path), {}, matcher=m, diag=diag)
    got = {(r["nct_id"], r["ticker"], r["role"], r["match_method"]) for r in res}
    assert got == {("NCT1", "ACME", "lead", "legacy"), ("NCT2", "BETA", "lead", "v2"),
                   ("NCT3", "GAMA", "collaborator", "legacy"), ("NCT4", "JNJ", "lead", "alias_sub")}
    r = diag["reasons"]
    assert r["ACME"]["reason"] == "기존 매칭" and r["BETA"]["reason"] == "표기 차이"
    assert r["GAMA"]["reason"].startswith("스폰서 아님") and r["JNJ"]["reason"] == "자회사명"
    assert r["ABGD"]["reason"].startswith("기타") and r["ABGD"]["jaccard_review"][0][0] >= 0.8   # 검수 표로만
    assert not any(x["ticker"] == "ABGD" for x in res)                                               # 자동 채택 금지
    assert r["ZZZ"]["reason"].startswith("임상 없음")


def test_legacy_path_unchanged_without_matcher(tmp_path):
    res = w._parse_studies_and_sponsors(_zip(tmp_path), {w._norm("Acme Bio, Inc."): "ACME"})
    assert [(x["nct_id"], x["role"]) for x in res] == [("NCT1", "lead")]
