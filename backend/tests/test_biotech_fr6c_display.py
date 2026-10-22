"""P4-3 · /biotech 과거 기록 표 · tsx 문구 · 금지어 검사 + /fr6c.json 경로."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SNIPER_API_TOKEN", "test-token-biotech-router")

from backend.api.main import app  # noqa: E402
from backend.api.routes import biotech as rt  # noqa: E402

FE = Path(__file__).resolve().parents[2] / "frontend"


def test_fr6c_tsx_wording_and_forbidden_words():
    if not shutil.which("npx") or not (FE / "node_modules").exists():
        pytest.skip("npx/node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/biotech-fr6c.check.ts"], cwd=FE, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "biotech-fr6c.check OK" in r.stdout


def _get(client):
    return client.get("/api/v1/biotech/fr6c.json", headers={"X-API-Token": os.environ["SNIPER_API_TOKEN"]})


def test_fr6c_json_requires_auth():
    assert TestClient(app).get("/api/v1/biotech/fr6c.json").status_code == 401


def test_fr6c_json_not_ready_then_latest_month(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "DATA_DIR_RUNTIME", tmp_path)
    monkeypatch.setattr(rt, "DATA_DIR_DOCS", tmp_path / "none")
    monkeypatch.setattr(rt, "DATA_DIR", tmp_path / "none2")
    client = TestClient(app)
    assert _get(client).json()["ready"] is False
    d = tmp_path / "fr6c"
    d.mkdir()
    (d / "cells_202610.json").write_text(json.dumps({"asof": "2026-10-16", "cells": [], "display_rows": ["전체"]}))
    (d / "cells_202611.json").write_text(json.dumps({"asof": "2026-11-01", "window": {"months": 24}, "events_in_window": 68,
                                                      "missing_price": 0, "cells": [{"label": "전체", "status": "표시"}],
                                                      "display_rows": ["전체", "긍정"]}))
    j = _get(client).json()
    assert j["ready"] is True and j["file"] == "cells_202611.json" and j["display_rows"] == ["전체", "긍정"]
