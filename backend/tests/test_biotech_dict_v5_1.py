"""사전 v5-1 (2026-10-06 · PRD 19절) · 자동 분류 제안 4건 판정 반영 · 'Mild Hepatic Imparement' 는 소화기가 아니라 건강인·약동학."""
from __future__ import annotations

import json

from backend.api.routes import biotech as b

TERMS = {"Generalized Myasthenia Gravis": "신경·정신", "Graves' Ophthalmopathy": "안과",
         "Graves' Ophthalmopathy (GO)": "안과", "Mild Hepatic Imparement": "건강인·약동학"}


def test_v5_1_four_terms_category(tmp_path, monkeypatch):
    terms = list(TERMS)
    snap = {"matches": [{"nct_id": f"NCT2000000{i}", "conditions": [t], "mesh_terms": []} for i, t in enumerate(terms)]}
    (tmp_path / "ctgov_snapshot.json").write_text(json.dumps(snap))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    got = [b._trial_display(f"NCT2000000{i}")["category"] for i in range(len(terms))]
    assert got == [TERMS[t] for t in terms]
