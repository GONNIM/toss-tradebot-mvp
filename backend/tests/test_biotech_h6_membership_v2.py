"""Phase C 3 · H6 소속 v2 · 추출기·매칭기·소속표 단위 검증 (합성 AACT zip · 네트워크 없음)."""
from __future__ import annotations

import zipfile
from datetime import date

from backend.scripts import biotech_h6_aact_theme_extract as ex
from backend.scripts import biotech_h6_membership_v2 as mv


def _zip(tmp_path):
    p = tmp_path / "2026-09-27_daily-clinical-trials.zip"
    studies = (
        "nct_id|brief_title|official_title|phase|overall_status|study_first_posted_date|primary_completion_date\n"
        "NCT1|Semaglutide in Obesity|x|PHASE3|COMPLETED|2016-02-10|2017-01-01\n"
        "NCT2|GLP-1 combination for weight|x|PHASE2|RECRUITING|2019-05-01|2027-01-01\n"
        "NCT3|Smash study|x|PHASE1|COMPLETED|2018-01-01|2018-06-01\n"
        "NCT4|Heart failure|x|PHASE2|COMPLETED|2020-08-01|2021-01-01\n"
        "NCT5|Hair study|x|PHASE2|COMPLETED|2021-11-01|2022-01-01\n"
    )
    conditions = "id|nct_id|name|downcase_name\n1|NCT4|NASH|nash\n2|NCT5|Androgenetic Alopecia|x\n"
    interventions = "id|nct_id|intervention_type|name|description\n1|NCT4|DRUG|Resmetirom|d\n"
    sponsors = (
        "id|nct_id|agency_class|lead_or_collaborator|name\n"
        "1|NCT1|INDUSTRY|lead|Gamma Obesity Therapeutics, Inc.\n"
        "2|NCT2|OTHER|lead|Harvard University\n"
        "3|NCT3|INDUSTRY|lead|Acme Bio Inc.\n"
        "4|NCT4|INDUSTRY|lead|Madrigal Pharmaceuticals, Inc.\n"
        "5|NCT4|INDUSTRY|collaborator|Someone Else\n"
        "6|NCT5|INDUSTRY|lead|Kintor Pharmaceutical Co., Ltd.\n"
    )
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("studies.txt", studies)
        zf.writestr("conditions.txt", conditions)
        zf.writestr("interventions.txt", interventions)
        zf.writestr("sponsors.txt", sponsors)
    return p


def test_keyword_word_boundary_and_disjoint_rule():
    pats = ex.compile_themes(ex.THEMES)
    assert "control_nash" not in ex.match_text("Smash trial", pats)          # 단어 경계
    h = ex.match_text("GLP-1 combination therapy", pats)
    assert "meal_replacement_metabolic" in h and "obesity_glp1" not in h     # 서로소 규칙
    assert "obesity_glp1" in ex.match_text("GLP-1 receptor agonist", pats)


def test_extract_all_sources(tmp_path):
    rows, stats = ex.extract(_zip(tmp_path))
    by = {(r["nct_id"], r["theme"]): r for r in rows}
    assert ("NCT1", "obesity_glp1") in by and by[("NCT1", "obesity_glp1")]["matched_in"] == "title"
    assert ("NCT2", "meal_replacement_metabolic") in by and ("NCT2", "obesity_glp1") not in by
    assert by[("NCT4", "control_nash")]["matched_in"] == "condition|intervention"
    assert by[("NCT4", "control_nash")]["lead_sponsor"] == "Madrigal Pharmaceuticals, Inc."  # lead 만
    assert ("NCT5", "hair_loss") in by
    assert not any(r["nct_id"] == "NCT3" for r in rows)
    assert by[("NCT1", "obesity_glp1")]["study_first_posted"] == "2016-02-10"
    assert stats["matched_studies"] == 4


def _matcher():
    sec = [{"ticker": "MDGL", "name": "Madrigal Pharmaceuticals, Inc.", "exchange": ""},
           {"ticker": "NVO", "name": "NOVO NORDISK A S", "exchange": ""},
           {"ticker": "GAMA", "name": "GAMMA OBESITY THERAPEUTICS INC", "exchange": ""},
           {"ticker": "ACMB", "name": "Acme Bio Therapeutics", "exchange": ""},
           {"ticker": "FGN", "name": "Foreign Listed Inc", "exchange": ""}]
    uni = {"MDGL": {"first_bar_date": "2016-07-22", "last_bar_date": "2026-09-04"},
           "NVO": {"first_bar_date": "1990-01-02", "last_bar_date": "2026-09-04"},
           "GAMA": {"first_bar_date": "1990-01-02", "last_bar_date": "2026-09-04"}}
    return mv.SponsorMatcher(sec, uni), uni


def test_matcher_reasons():
    m, _ = _matcher()
    assert m.match("Madrigal Pharmaceuticals, Inc.", "INDUSTRY")["ticker"] == "MDGL"
    # 매칭기 v2 한계 (규칙 그대로 유지): SEC 표기 "A S" 는 접미어로 안 지워짐 → 해외 분류 (보고서 명시)
    assert m.match("Novo Nordisk A/S", "INDUSTRY")["reason"] == "해외"
    assert m.match("Harvard University", "OTHER")["reason"] == "대학·병원"
    assert m.match("Foreign Listed Inc", "INDUSTRY")["reason"] == "해외"            # SEC 있음 · 미 거래소 밖
    r = m.match("Acme Bio Therapeutics Group Holdings", "INDUSTRY")
    assert r["status"] == "unmatched"                                               # Jaccard 자동 채택 금지
    assert m.match("Kintor Pharmaceutical Co., Ltd.", "INDUSTRY")["reason"] == "해외"
    assert m.match("Tiny Private Bio", "INDUSTRY")["reason"] == "비상장"


def test_membership_point_in_time(tmp_path):
    rows, _ = ex.extract(_zip(tmp_path))
    m, uni = _matcher()
    mb = {s["lead_sponsor"]: m.match(s["lead_sponsor"], s["agency_class"]) for s in rows}
    memb = mv.build_membership(rows, mb)
    e = {(r["ticker"], r["theme"]): r["entry_quarter"] for r in memb}
    assert e[("GAMA", "obesity_glp1")] == "2016Q1"
    assert e[("MDGL", "control_nash")] == "2020Q3"
    assert "MDGL" not in mv.members_at(memb, uni, 2020, 2).get("control_nash", set())   # 편입 전
    assert "MDGL" in mv.members_at(memb, uni, 2024, 1)["control_nash"]                  # 이탈 없음
    assert "GAMA" in mv.members_at(memb, uni, 2016, 1)["obesity_glp1"]


def test_trading_window_excludes_unlisted_quarter():
    uni = {"X": {"first_bar_date": "2019-01-02", "last_bar_date": "2020-03-31"}}
    assert not mv.trading_in(uni["X"], 2018, 4)
    assert mv.trading_in(uni["X"], 2020, 1)
    assert not mv.trading_in(uni["X"], 2020, 2)
    assert mv.q_bounds(2024, 4) == (date(2024, 10, 1), date(2024, 12, 31))


def test_gate_counts_definition():
    qm = {(2020, 1): {"obesity_glp1": {"A", "B"}, "hair_loss": {"C"}, "cognitive_memory": {"D"}}}
    terc = {(2020, 1, "obesity_glp1"): "top", (2020, 1, "hair_loss"): "top", (2020, 1, "cognitive_memory"): "bot"}
    g = mv.gate_counts(qm, terc)
    assert g["good_quarters_top_ge3"] == 1 and g["good_quarters_top_and_bot_ge3"] == 0


def test_price_plan_budget_split():
    memb = [{"ticker": f"T{i}", "n_studies": 1} for i in range(1000)]
    p = mv.price_plan({f"T{i}" for i in range(1000)}, {"T0"}, memb)
    assert p["need_tiingo"] == 999 and p["months_needed"] == 3 and p["allocatable_per_month"] == 450
