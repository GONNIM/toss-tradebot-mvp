"""WP97-2 · 한국어 v4 (ALS → 루게릭병(ALS)) · 일반어 2건 '무시' (카드 분류에 쓰지 않음)."""
from __future__ import annotations

from backend.api.routes import biotech as api


def test_als_korean():
    assert api._ko("ALS") == "루게릭병(ALS)"


def _with_trial(monkeypatch, conds, mesh=()):
    monkeypatch.setattr(api, "_snapshot_by_nct", lambda: {"NCT00000001": {"conditions": list(conds), "mesh_terms": list(mesh)}})
    monkeypatch.setattr(api, "_auto_categories", lambda: {"Lesion Skin": {"category": "피부"}})   # 자동 분류에 있어도 쓰지 않아야 함
    return api._trial_display("NCT00000001")


def test_lesion_skin_not_used_for_card_category(monkeypatch):
    d = _with_trial(monkeypatch, ["Lesion Skin", "Hailey Hailey Disease"])
    assert d["category"] == "희귀 유전" and d["category_source"] == "Hailey Hailey Disease"
    d2 = _with_trial(monkeypatch, ["Lesion Skin", "Some Unlisted Condition"])
    assert d2["category"] == "기타 (Some Unlisted Condition)" and "Lesion Skin" not in d2["category"]
    d3 = _with_trial(monkeypatch, ["Neoplasms by Histologic Type", "Hailey Hailey Disease"])
    assert d3["category_source"] == "Hailey Hailey Disease"


def test_conditions_carry_ignored_flag(monkeypatch):
    """WP97-3 · 화면이 '무시' 용어를 뺄 수 있게 API 가 표시."""
    d = _with_trial(monkeypatch, ["Lesion Skin", "Hailey Hailey Disease"])
    assert [(c["en"], c["ignored"]) for c in d["conditions"]] == [("Lesion Skin", True), ("Hailey Hailey Disease", False)]
