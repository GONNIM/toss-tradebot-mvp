"""Activist Radar 알림 우선순위 3단계.

URGENT (🚨): 즉시 확인 필요 · REGIME_CHANGE · CRITICAL · CRITICAL_PACK · 대량 매수
NORMAL (🔔): 표준 알림 · STRONG · STRONG_PACK · PACK · INSIDER(매수)
INFO   (📎): 참고 · INSIDER(매도) · WATCH
skip:        NOTE · NON_TRADE (Form 4 옵션 행사·수여) — 발송하지 않음

env `ACTIVIST_ALERT_MIN_LEVEL` 로 필터 (기본 NORMAL).
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Optional


class Priority(str, Enum):
    URGENT = "URGENT"
    NORMAL = "NORMAL"
    INFO = "INFO"
    SKIP = "SKIP"    # 저장은 하되 알림 skip


_PRIORITY_ORDER = {
    Priority.URGENT: 3,
    Priority.NORMAL: 2,
    Priority.INFO: 1,
    Priority.SKIP: 0,
}


PRIORITY_ICON = {
    Priority.URGENT: "🚨",
    Priority.NORMAL: "🔔",
    Priority.INFO: "📎",
    Priority.SKIP: "🔕",
}


def intensity_to_priority(label: str, direction: Optional[str] = None) -> Priority:
    """강도 라벨 → 우선순위 매핑.

    Args:
        label: intensity_label (REGIME_CHANGE · CRITICAL · STRONG · INSIDER · WATCH · NOTE ·
               CRITICAL_PACK · STRONG_PACK · PACK)
        direction: (선택) INSIDER 세분화 · BUY / SELL / MIXED / NON_TRADE / NEW
    """
    if not label:
        return Priority.SKIP

    if label in ("REGIME_CHANGE", "CRITICAL", "CRITICAL_PACK"):
        return Priority.URGENT
    if label in ("STRONG", "STRONG_PACK", "PACK"):
        return Priority.NORMAL
    if label == "INSIDER":
        # 방향으로 세분화
        d = (direction or "").upper()
        if d in ("BUY", "NEW", "MIXED", "UNKNOWN", ""):
            return Priority.NORMAL
        if d in ("SELL",):
            return Priority.INFO
        return Priority.NORMAL
    if label == "WATCH":
        return Priority.INFO
    if label in ("NOTE", "NON_TRADE"):
        return Priority.SKIP
    return Priority.INFO


def get_min_level() -> Priority:
    """env `ACTIVIST_ALERT_MIN_LEVEL` 로드 · 기본 NORMAL."""
    raw = (os.environ.get("ACTIVIST_ALERT_MIN_LEVEL") or "NORMAL").strip().upper()
    try:
        return Priority(raw)
    except ValueError:
        return Priority.NORMAL


def should_send(priority: Priority, min_level: Optional[Priority] = None) -> bool:
    """min_level 이상 우선순위만 발송. SKIP 은 무조건 skip."""
    if priority == Priority.SKIP:
        return False
    min_level = min_level or get_min_level()
    return _PRIORITY_ORDER[priority] >= _PRIORITY_ORDER[min_level]
