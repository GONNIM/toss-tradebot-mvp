"""강도 스코어링 · Wolf Pack 감지 · Phase C.

공식 (기획서 [[00-vision-and-signal-taxonomy]] §4):
    score = base_form_score
          × activist_tier_multiplier
          × market_cap_bonus         # 아직 데이터 없음 (기본 1.0)
          × wolf_pack_bonus
          × momentum_bonus           # 지분 증가 속도 (기본 1.0)

임계값:
    80+  → CRITICAL   (즉시 Telegram + UI 최상단)
    60~79 → STRONG    (Telegram)
    40~59 → WATCH     (UI 만)
    <40   → NOTE      (기록만)
"""
from __future__ import annotations

import time
from typing import List, Tuple

from .state import ActivistEvent, ActivistState
from .universe import Activist


_BASE_FORM_SCORE = {
    "SC 13D": 80,           # 신규 SC 13D — 강 신호
    "SCHEDULE 13D": 80,
    "SC 13D/A": 60,         # 수정 (지분 변동)
    "SCHEDULE 13D/A": 60,
    "SC 13G": 50,           # passive · 참고
    "SCHEDULE 13G": 50,
    "SC 13G/A": 45,
    "SCHEDULE 13G/A": 45,
    # 13G → 13D 전환은 별도 로직에서 +30 boost
}

_TIER_MULTIPLIER = {1: 1.2, 2: 1.0, 3: 0.9}
_WOLF_WINDOW_SEC = 30 * 86400   # 30일
_WOLF_BONUS = {2: 1.3, 3: 1.5, 4: 1.7}  # 30일 내 activist 수


def _label(score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "STRONG"
    if score >= 40:
        return "WATCH"
    return "NOTE"


def detect_wolf_pack(
    state: ActivistState, target_desc: str, current_filer_key: str
) -> List[str]:
    """30일 window 에 동일 target 에 진입한 다른 activist filer_key 리스트 반환."""
    since = time.time() - _WOLF_WINDOW_SEC
    others = state.events_by_target(target_desc, since)
    seen: List[str] = []
    for e in others:
        if e.filer_key == current_filer_key:
            continue
        if e.filer_key not in seen:
            seen.append(e.filer_key)
    return seen


def score_event(
    activist: Activist,
    form: str,
    target_desc: str,
    state: ActivistState,
    prior_forms_by_this_filer_on_target: List[str] = None,
) -> Tuple[int, str, List[str]]:
    """이벤트 강도 계산 · (score, label, wolf_pack) 반환."""
    base = _BASE_FORM_SCORE.get(form, 30)

    # 13G → 13D 전환 boost
    prior = prior_forms_by_this_filer_on_target or []
    was_13g = any("13G" in p for p in prior)
    is_13d = "13D" in form and "G" not in form
    if was_13g and is_13d:
        base += 30  # 태세 변경 — CRITICAL 초과 가능

    tier_mult = _TIER_MULTIPLIER.get(activist.tier, 1.0)

    wolf_pack = detect_wolf_pack(state, target_desc, activist.key)
    n_others = len(wolf_pack)
    wolf_mult = 1.0
    if n_others >= 2:
        wolf_mult = _WOLF_BONUS.get(min(n_others + 1, 4), 1.7)
    elif n_others == 1:
        wolf_mult = 1.15  # 두 번째 activist 진입

    score = int(round(base * tier_mult * wolf_mult))
    score = max(0, min(100, score))  # clamp
    return score, _label(score), wolf_pack
