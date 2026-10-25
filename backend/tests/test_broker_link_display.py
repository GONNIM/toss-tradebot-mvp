"""「토스증권에서 열기」 화면 규칙 (frontend/lib/broker-link.check.ts · tsx · 없으면 건너뜀 · 1025-06)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_broker_link_display_check():
    fe = Path(__file__).resolve().parents[2] / "frontend"
    if shutil.which("npx") is None or not (fe / "node_modules").exists():
        pytest.skip("npx 또는 node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/broker-link.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "broker-link ok" in r.stdout
