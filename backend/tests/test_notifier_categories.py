"""모든 알림 호출처가 종류(category)를 넘기는지 (1022-09 Task 4)."""
from __future__ import annotations

import ast
from pathlib import Path

from backend.services import notification_settings as ns

BACKEND = Path(__file__).resolve().parents[1]
SEND_NAMES = {"send_info", "send_warning", "send_critical"}


def _send_calls():
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("venv/", ".venv/", "tests/")) or rel == "services/notifier.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                name = node.func.attr
                if name in SEND_NAMES or (name == "send" and any(k.arg == "force" for k in node.keywords)):
                    yield rel, node


def test_every_send_call_passes_category():
    missing = [f"{rel}:{node.lineno}" for rel, node in _send_calls() if not any(k.arg == "category" for k in node.keywords)]
    assert missing == []


def test_literal_categories_are_known():
    unknown = []
    for rel, node in _send_calls():
        for k in node.keywords:
            if k.arg == "category" and isinstance(k.value, ast.Constant) and k.value.value not in ns.CATEGORIES:
                unknown.append(f"{rel}:{node.lineno} {k.value.value}")
    assert unknown == []


def test_powderkeg_category_mapping():
    assert ns.powderkeg_category("B1") == "powderkeg_dnt"
    assert ns.powderkeg_category("A1") == "powderkeg_a1"
    assert ns.powderkeg_category("A3") == "powderkeg_a3"
    assert ns.powderkeg_category("A4") == "unknown"   # 목록 밖 → 항상 발송
    assert ns.powderkeg_category("Z9") == "unknown"


def test_activist_category_mapping():
    for strong in ("CRITICAL", "REGIME_CHANGE", "STRONG", "CRITICAL_PACK", "STRONG_PACK"):
        assert ns.activist_category(strong) == "activist_strong"
    for info in ("WATCH", "NOTE", "INSIDER", "PACK", ""):
        assert ns.activist_category(info) == "activist_info"
