"""알림 설정 화면 표시 함수 (frontend/lib/notifications-display.check.ts · tsx · 없으면 건너뜀)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_notifications_display_check():
    fe = Path(__file__).resolve().parents[2] / "frontend"
    if shutil.which("npx") is None or not (fe / "node_modules").exists():
        pytest.skip("npx 또는 node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/notifications-display.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert "notifications-display ok" in r.stdout
