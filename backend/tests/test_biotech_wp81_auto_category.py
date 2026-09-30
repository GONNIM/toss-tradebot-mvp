"""WP81 · 질환 분류 자동화 · MeSH 두 단계 규칙 · 어간 순서 · 수동 사전 우선 · NLM 요청 규칙."""
from __future__ import annotations

import json

import pytest

from backend.scripts import biotech_auto_category as ac

# ── 1단계 예외 표 · 각 줄 1건 이상 ───────────────────────────────────
EXCEPTION_CASES = [
    ("Muscular Dystrophy, Hereditary X", ["C05.651", "C16.320.577.100"], "희귀 유전"),     # 표지어 + C16
    ("Anemia, Sickle Cell", ["C15.378.050.141.150.150", "C16.320.070.150"], "희귀 유전"),   # C16.320.070
    ("Cystic Fibrosis", ["C06.689.202", "C08.381.187", "C16.320.190"], "희귀 유전"),         # C16.320.190
    ("Choroideremia", ["C11.270.142", "C16.320.290.142"], "희귀 유전"),                     # C16.320.290 / C11.270
    ("Hemoglobinopathies", ["C15.378.420", "C16.320.365"], "희귀 유전"),                     # C16.320.365
    ("Friedreich Ataxia", ["C10.228.140.252.700.150", "C16.320.400.780.200"], "희귀 유전"),  # C16.320.400
    ("Muscular Dystrophies", ["C05.651.534.500", "C16.320.577"], "희귀 유전"),               # C16.320.577
    ("Leber Congenital Amaurosis", ["C11.270.516", "C11.768.364"], "희귀 유전"),              # C11.270
    ("Lupus Erythematosus, Systemic", ["C17.300.480", "C20.111.590"], "면역·염증"),          # C17.300
    ("Myelodysplastic Syndromes", ["C15.378.190.625"], "암"),                                # C15.378.190.625
    ("Primary Myelofibrosis", ["C15.378.190.636.765"], "암"),                               # C15.378.190.636
    ("Neuralgia", ["C10.668.829.600", "C23.888.592.612.664"], "통증"),                        # C23.888.592.612
    ("Systemic Inflammatory Response Syndrome", ["C23.550.470.790"], "면역·염증"),           # C23.550.470
    ("Fractures, Bone", ["C26.404"], "근골격"),                                              # C26.404
    ("Non-alcoholic Fatty Liver Disease", ["C06.552.241.519"], "비만·대사"),                  # C06.552.241
    ("Pulmonary Arterial Hypertension", ["C08.381.423.847"], "심혈관"),                       # C08.381.423
    ("Cytomegalovirus", ["B04.280.382.150.150"], "감염"),                                     # B04
    ("Staphylococcus aureus", ["B03.300.390.400.800.750"], "감염"),                           # B03
    ("Pharmacokinetics", ["G03.787", "G07.690.725"], "건강인·약동학"),                         # G07.690.725
    ("Healthy Volunteers", ["M01.774.500", "M01.955.236"], "건강인·약동학"),                   # M01.774
    ("Volunteers", ["M01.955"], "건강인·약동학"),                                              # M01.955
    ("Delusions", ["F01.145.126.200"], "신경·정신"),                                           # F01.145.126
]


@pytest.mark.parametrize("name,trees,expected", EXCEPTION_CASES, ids=[c[0] for c in EXCEPTION_CASES])
def test_exceptions(name, trees, expected):
    assert ac.mesh_category(name, trees) == expected


def test_c04_588_614_550_not_counted_as_cancer():
    # 이 가지만 있으면 C04 로 보지 않고 순서 단계로 넘어간다 (C10 → 신경·정신)
    assert ac.mesh_category("Myasthenia X", ["C04.588.614.550.500", "C10.114.656"]) == "신경·정신"


def test_other_f01_branches_unmapped_then_none():
    assert ac.mesh_category("Recreational Drug Use", ["F01.145.683"]) is None


# ── 2단계 순서 규칙 5건 (2026-09-29 NLM 실측 트리) ─────────────────────
ORDER_CASES = [
    ("Vision Disorders", ["C10.597.751.941", "C11.966", "C23.888.592.763.941"], "안과"),
    ("Supranuclear Palsy, Progressive", ["C10.228.140.079.882", "C10.228.662.700", "C10.292.562.750.500",
                                          "C10.574.945.500", "C10.597.622.447.690", "C11.590.472.500",
                                          "C23.888.592.636.447.690"], "신경·정신"),
    ("Diabetes Mellitus, Type 1", ["C18.452.394.750.124", "C19.246.267", "C20.111.327"], "비만·대사"),
    ("Multiple Sclerosis", ["C10.114.375.500", "C10.314.350.500", "C20.111.258.250.500"], "신경·정신"),
    ("Hepatitis B", ["C01.221.250.500", "C01.925.256.430.400", "C01.925.440.435", "C06.552.380.705.437"], "감염"),
]


@pytest.mark.parametrize("name,trees,expected", ORDER_CASES, ids=[c[0] for c in ORDER_CASES])
def test_order(name, trees, expected):
    assert ac.mesh_category(name, trees) == expected


# ── 어간 · 순서 강제 ──────────────────────────────────────────────────

def test_stem_lung_cancer_and_forced_order():
    stems = ac.load_stems()
    assert ac.stem_category("Lung Cancer", stems)[0] == "암"
    assert ac.stem_category("Cancer Pain", stems)[0] == "암"                                  # 암 어간이 통증보다 먼저
    assert ac.stem_category("Renal Impairment Healthy Volunteer", stems)[0] == "건강인·약동학"  # 건강인이 신장보다 먼저


def test_stem_order_forced_even_if_json_order_differs(tmp_path):
    p = tmp_path / "stems.json"
    p.write_text(json.dumps({"stems": {"통증": "pain", "암": "cancer", "건강인·약동학": "healthy"},
                             "rest_order": ["통증", "암", "건강인·약동학"]}))
    order = [c for c, _ in ac.load_stems(p)]
    assert order[:2] == ["암", "건강인·약동학"]


# ── 수동 사전 우선 · 검수 요망 · NLM 요청 규칙 ─────────────────────────

def _snap(*terms):
    return {"matches": [{"nct_id": f"N{i}", "mesh_terms": [], "conditions": [t]} for i, t in enumerate(terms)]}


def test_manual_dictionary_wins_and_is_never_auto_classified():
    cache = {"Obesity": {"trees": ["C18.654.726.500"]}, "Weird Term": {"trees": ["C10.114"]}}
    auto, rows, _ = ac.build(_snap("Obesity", "Weird Term"), {"obesity"}, cache, ac.load_stems(), None, "20260930")
    assert "Obesity" not in auto and auto["Weird Term"]["category"] == "신경·정신"


def test_api_manual_before_auto(tmp_path, monkeypatch):
    from backend.api.routes import biotech as b
    (tmp_path / "ctgov_snapshot.json").write_text(json.dumps(
        {"matches": [{"nct_id": "NCT00000001", "mesh_terms": [], "conditions": ["Obesity"]},
                     {"nct_id": "NCT00000002", "mesh_terms": [], "conditions": ["Zzz Unlisted Neuro"]}]}))
    (tmp_path / "auto_categories.json").write_text(json.dumps(
        {"terms": {"Obesity": {"category": "암", "basis": "auto-stem"},
                   "Zzz Unlisted Neuro": {"category": "신경·정신", "basis": "auto-mesh"}}}))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    t1, t2 = b._trial_display("NCT00000001"), b._trial_display("NCT00000002")
    assert (t1["category"], t1["category_auto"]) == ("비만·대사", False)     # 수동 사전 값 · 자동이 덮지 않음
    assert (t2["category"], t2["category_auto"]) == ("신경·정신", True)


def test_review_flag_for_c16_non_rare():
    cache = {"Dermatitis, Atopic X": {"trees": ["C16.320.850.210", "C17.800.174.193"]}}
    _, rows, stats = ac.build(_snap("Dermatitis, Atopic X"), set(), cache, ac.load_stems(), None, "20260930")
    assert rows[0]["auto_category"] == "피부" and rows[0]["검수 요망"] == "검수 요망" and stats["review_needed"] == 1


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


def test_nlm_stops_on_429_and_uses_cache_without_requests():
    calls = []

    def get(url, params=None):
        calls.append(url)
        return _Resp(429)

    client = ac.NlmClient(get=get)
    cache = {"Cached Term": {"trees": ["C04.1"]}}
    auto, _, stats = ac.build(_snap("Cached Term", "New A", "New B"), set(), cache, [], client, "20260930")
    assert stats["nlm_blocked"] is True and len(calls) == 1          # 첫 429 에서 즉시 중단
    assert auto["Cached Term"]["category"] == "암"                    # 캐시 용어는 요청 없이 분류


def test_nlm_interval_is_at_most_3_per_second():
    assert ac.NLM_MIN_INTERVAL >= 1 / 3



def test_weekly_step_failure_sends_one_warning_and_does_not_raise(tmp_path, monkeypatch):
    from backend.scripts import biotech_h69_aact_weekly as w

    def boom(*a, **k):
        raise RuntimeError("nlm down")

    monkeypatch.setattr(ac, "run_weekly", boom)
    sent = []
    assert w.run_auto_category_step(tmp_path / "snap.json", notify=lambda s, d: sent.append((s, d))) is None
    assert sent == [("auto_category", "RuntimeError · 주간 잡은 계속 진행")]


def test_stems_file_found_via_resolver_in_docs_data():
    from backend.scripts import _biotech_paths as _P
    p = _P.find("auto_category_stems.json")
    assert p is not None and p.parent.name == "data" and p.parent.parent.name == "biotech"   # docs/plans/biotech/data



# ── WP82 · "먼저 적용" 가지 추가 (C16.320.565 · C16.320.322 · C16.320.144 · C18.452.811) · 2026-09-29 NLM 실측 트리 ──
WP82_CASES = [
    ("Fabry Disease", ["C10.228.140.163.100.435.825.200", "C10.228.140.300.275.374", "C14.907.253.329.374",
                       "C16.320.322.124", "C16.320.565.189.435.825.200", "C18.452.132.100.435.825.200"]),
    ("Camurati-Engelmann Syndrome", ["C05.116.099.708.180", "C16.320.144"]),
    ("Erythropoietic Protoporphyria", ["C06.552.830.812", "C16.320.850.742.812", "C17.800.827.742.812", "C18.452.811.400.812"]),
    ("McArdle Disease", ["C16.320.565.202.449.560", "C18.452.648.202.449.560"]),
]


@pytest.mark.parametrize("name,trees", WP82_CASES, ids=[c[0] for c in WP82_CASES])
def test_wp82_first_applied_branches(name, trees):
    assert ac.mesh_category(name, trees) == "희귀 유전"



# ── WP82-3 · 약어 구역 (어간 사전 v2) ─────────────────────────────────

def test_abbreviation_in_parentheses():
    assert ac.stem_category("Acute Myelogenous Leukaemia Variant (AML)", ac.load_stems())[0] == "암"
    assert ac.stem_category("Relapsed (AML)", ac.load_stems()) == ("암", "AML")        # 괄호 안 약어 자체로 잡힘


def test_cancer_stem_wins_over_abbreviation():
    hit = ac.stem_category("EBV-induced Lymphomas", ac.load_stems())
    assert hit[0] == "암" and hit[1].lower().startswith("lymphom")                      # EBV (감염) 가 아니라 암 어간


def test_abbreviation_case_sensitive():
    stems = ac.load_stems()
    assert ac.stem_category("IgAN", stems) == ("신장", "IgAN")
    assert ac.stem_category("IGAN", stems) is None


def test_order_cancer_healthy_abbreviation_rest(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"stems": {"통증": "pain", "암": "cancer", "건강인·약동학": "healthy"},
                             "rest_order": ["통증", "암", "건강인·약동학"], "abbreviations": {"HCV": "감염"}}))
    kinds = [(c, r.pattern) for c, r in ac.load_stems(p)]
    assert [c for c, _ in kinds] == ["암", "건강인·약동학", "감염", "통증"]
    assert ac.stem_category("HCV pain", ac.load_stems(p))[0] == "감염"                   # 약어가 나머지 어간보다 먼저
    assert ac.stem_category("healthy HCV", ac.load_stems(p))[0] == "건강인·약동학"        # 건강인 어간이 약어보다 먼저
