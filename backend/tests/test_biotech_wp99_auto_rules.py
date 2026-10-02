"""WP99 · 자동 분류 규칙 · 얕은 트리 = 무시 · 어간 단어 시작 (retin ≠ Transthyretin) · 수동 사전 변형 · 수동 사전 우선."""
from __future__ import annotations

import json

from backend.scripts import biotech_auto_category as ac


def test_shallow_trees_only_are_ignored():
    assert ac.classify("Heart Diseases", ["C14"], [], {})[0] == ac.IGNORE
    assert ac.classify("Genetic Diseases, Inborn", ["C16.320"], [], {})[0] == ac.IGNORE
    assert ac.classify("Lupus", ["C17.300.475"], [], {})[0] == "면역·염증"        # 점 2개면 트리 규칙 그대로


def test_stem_word_start_only():
    stems = ac.load_stems()
    assert ac.stem_category("Transthyretin Amyloid Cardiomyopathy", stems)[0] != "안과"
    assert ac.stem_category("Retinal Vein Occlusion", stems)[0] == "안과"
    assert ac.stem_category("Prostate Adenocarcinoma", stems)[0] == "암"          # 암 어간은 단어 안에서도


def test_manual_variant_longest_match():
    manual = {"lupus nephritis": "면역·염증", "nephritis": "신장", "lesion skin": "무시"}
    got = ac.classify("Pediatric Lupus Nephritis", [], [], manual)
    assert got[0] == "면역·염증" and got[1] == "manual-variant"
    assert ac.classify("Pulmonary Arterial Hypertension (WHO Class III)", [], [], {"pulmonary arterial hypertension": "심혈관"})[0] == "심혈관"


def test_manual_dictionary_beats_auto_on_screen(tmp_path, monkeypatch):
    """사전 v5 · 수동 사전에 있는 용어는 auto_categories.json 값이 있어도 쓰이지 않음."""
    from backend.api.routes import biotech as b
    (tmp_path / "ctgov_snapshot.json").write_text(json.dumps(
        {"matches": [{"nct_id": "NCT00000009", "mesh_terms": [], "conditions": ["Colorectal Cancer"]}]}))
    (tmp_path / "auto_categories.json").write_text(json.dumps({"terms": {"Colorectal Cancer": {"category": "소화기"}}}))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    t = b._trial_display("NCT00000009")
    assert t["category"] == "암" and t["category_auto"] is False
