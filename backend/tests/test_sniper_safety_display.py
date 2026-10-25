"""실주문 안전 결론 한 줄 (frontend/lib/sniper-safety.check.ts · tsx · 없으면 건너뜀 · 1025-01)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_sniper_safety_display_check():
    fe = Path(__file__).resolve().parents[2] / "frontend"
    if shutil.which("npx") is None or not (fe / "node_modules").exists():
        pytest.skip("npx 또는 node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/sniper-safety.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "sniper-safety ok" in r.stdout
