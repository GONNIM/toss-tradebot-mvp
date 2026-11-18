"""상태 기계 · 계획서 8절.

DRAFT → (대표 승인 · 쿠키 + 확인 코드 · 모의는 쿠키만) APPROVED → ENTRY_ARMED → HOLDING
       → (TP1 체결) TP1_WAIT 또는 TRAILING → CLOSED
ENTRY_ARMED → (마감 처리) ENTRY_RETRY → HOLDING / CANCELLED
ADOPT_PENDING → HOLDING / TRAILING
어느 상태든(끝난 계획 제외) → HALTED (재개 = 쿠키 + 확인 코드(모의는 쿠키만) · 다시 맞추기 뒤 불변식 통과)
"""
from __future__ import annotations

import json
from typing import Optional

from .models import Plan, PlanEvent, utcnow

DRAFT, APPROVED, ENTRY_ARMED, ENTRY_RETRY = "DRAFT", "APPROVED", "ENTRY_ARMED", "ENTRY_RETRY"
HOLDING, TP1_WAIT, TRAILING = "HOLDING", "TP1_WAIT", "TRAILING"
CLOSED, CANCELLED, ADOPT_PENDING, HALTED = "CLOSED", "CANCELLED", "ADOPT_PENDING", "HALTED"

TERMINAL = (CLOSED, CANCELLED)

_ALLOWED: dict[str, set[str]] = {
    DRAFT: {APPROVED, CANCELLED},
    APPROVED: {ENTRY_ARMED, CANCELLED, ADOPT_PENDING, HOLDING, TRAILING, HALTED},
    ENTRY_ARMED: {HOLDING, ENTRY_RETRY, CANCELLED, HALTED},
    ENTRY_RETRY: {HOLDING, CANCELLED, HALTED},
    HOLDING: {TP1_WAIT, TRAILING, CLOSED, HALTED},
    TP1_WAIT: {TRAILING, CLOSED, HALTED},
    TRAILING: {CLOSED, HALTED},
    ADOPT_PENDING: {HOLDING, TRAILING, CANCELLED, HALTED},
    HALTED: {HOLDING, TP1_WAIT, TRAILING, ENTRY_ARMED, ENTRY_RETRY, ADOPT_PENDING, CLOSED, CANCELLED},
    CLOSED: set(),
    CANCELLED: set(),
}

# 승인 이후 시간이 지나도 값(가격 · 수량 · 날짜)을 고칠 수 있는 상태는 DRAFT 뿐 (3절)
EDITABLE = (DRAFT,)


class TransitionError(Exception):
    pass


def can_transition(src: str, dst: str) -> bool:
    return dst in _ALLOWED.get(src, set())


async def event(session, plan_id: Optional[int], kind: str, detail: str = "") -> None:
    session.add(PlanEvent(plan_id=plan_id, kind=kind, detail=detail[:2000], ts=utcnow()))
    await session.flush()


async def transition(session, plan: Plan, dst: str, *, reason: str = "") -> None:
    src = plan.state
    if src == dst:
        return
    if not can_transition(src, dst):
        raise TransitionError(f"{src} → {dst} 는 허용되지 않습니다")
    if dst == HALTED:
        plan.prev_state = src
        plan.halted_reason = reason[:200]
    plan.state = dst
    plan.updated_at = utcnow()
    await event(session, plan.id, "state", json.dumps({"from": src, "to": dst, "reason": reason}, ensure_ascii=False))


async def halt(session, plan: Plan, reason: str) -> bool:
    """HALTED 로. 이미 HALTED · 끝난 계획이면 False."""
    if plan.state in TERMINAL or plan.state == HALTED or plan.state == DRAFT:
        return False
    await transition(session, plan, HALTED, reason=reason)
    return True


async def resume(session, plan: Plan) -> str:
    """HALTED → 정지 직전 상태. 호출 측이 다시 맞추기 · 불변식 통과를 확인한 뒤 부른다."""
    if plan.state != HALTED:
        raise TransitionError("정지 상태가 아닙니다")
    dst = plan.prev_state or HOLDING
    if dst == HALTED or not can_transition(HALTED, dst):
        dst = HOLDING
    plan.halted_reason = None
    await transition(session, plan, dst, reason="resume")
    return dst
