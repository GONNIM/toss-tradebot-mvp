"""강도 스코어링 · Wolf Pack 감지 · 13G→13D 전환 명시 · Phase C + D.

공식:
    score = base_form_score
          × activist_tier_multiplier
          × market_cap_bonus         # 아직 데이터 없음 (기본 1.0)
          × wolf_pack_bonus
          × momentum_bonus           # 지분 증가 속도 (기본 1.0)

임계값:
    REGIME_CHANGE → 13G→13D 태세 전환 (Phase D · CRITICAL 100 강제)
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

# type-checking only import 회피
try:
    from backend.discovery.data_sources.dart.client import DartMajorStock
except ImportError:   # pragma: no cover
    DartMajorStock = None  # type: ignore


_BASE_FORM_SCORE = {
    # 미국 SEC
    "SC 13D": 80,           # 신규 SC 13D — 강 신호
    "SCHEDULE 13D": 80,
    "SC 13D/A": 60,         # 수정 (지분 변동)
    "SCHEDULE 13D/A": 60,
    "SC 13G": 50,           # passive · 참고
    "SCHEDULE 13G": 50,
    "SC 13G/A": 45,
    "SCHEDULE 13G/A": 45,
    # 13G → 13D 전환은 별도 로직에서 +30 boost

    # 한국 DART · report_nm 문자열 매칭
    "KR_D001_MANAGEMENT": 80,   # 대량보유(일반/변동보고) — 경영참여
    "KR_D001_PASSIVE": 45,      # 대량보유(약식) — 단순투자
    "KR_D001_UNKNOWN": 55,      # 판정 실패 · 중간 (사용자 확인 필요)
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


def kr_majorstock_bonus(m, direction: str) -> int:
    """DART majorstock 정밀 필드 → 강도 보정.

    지분율 (stkrt) · 증감 (stkrt_irds) · 방향 (BUY/SELL/NEW).
    최종 score 에 더한다 (base × tier × wolf 위에 추가 조정).
    """
    if m is None:
        return 0
    bonus = 0
    # 지분율 수준
    if m.stkrt is not None:
        if m.stkrt >= 10.0:
            bonus += 15    # 10% 초과 = 경영권 실질 위협
        elif m.stkrt >= 7.0:
            bonus += 8
        elif m.stkrt >= 5.0:
            bonus += 3
    # 지분율 증감 (momentum)
    if m.stkrt_irds is not None:
        if m.stkrt_irds >= 3.0:
            bonus += 15   # 급증
        elif m.stkrt_irds >= 1.5:
            bonus += 10
        elif m.stkrt_irds >= 0.5:
            bonus += 5
        elif m.stkrt_irds <= -1.5:
            bonus -= 10   # 대량 매도
        elif m.stkrt_irds <= -0.5:
            bonus -= 5
    # 방향
    if direction == "BUY":
        bonus += 5
    elif direction == "SELL":
        bonus -= 10
    elif direction == "NEW":
        bonus += 10
    return bonus


def _is_regime_change(prior_forms: List[str], current_form: str) -> bool:
    """13G/A 이력이 있는 filer 가 이번에 13D 계열을 낸 경우 (passive → active 전환).

    prior_forms: 같은 filer 가 이 대상에 대해 이전에 낸 form 이력
    current_form: 이번 신규 form
    """
    if not prior_forms:
        return False
    had_13g = any(("13G" in p) for p in prior_forms)
    is_13d_now = ("13D" in current_form) and ("G" not in current_form)
    return had_13g and is_13d_now


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
    """이벤트 강도 계산 · (score, label, wolf_pack) 반환.

    Phase D: 13G→13D 전환은 별도 REGIME_CHANGE 라벨로 승격 (score 100).
    """
    base = _BASE_FORM_SCORE.get(form, 30)
    prior = prior_forms_by_this_filer_on_target or []

    # ── Phase D · 13G→13D 태세 전환 감지 (명시적 라벨) ──
    if _is_regime_change(prior, form):
        wolf_pack = detect_wolf_pack(state, target_desc, activist.key)
        return 100, "REGIME_CHANGE", wolf_pack

    tier_mult = _TIER_MULTIPLIER.get(activist.tier, 1.0)

    wolf_pack = detect_wolf_pack(state, target_desc, activist.key)
    n_others = len(wolf_pack)
    wolf_mult = 1.0
    if n_others >= 2:
        wolf_mult = _WOLF_BONUS.get(min(n_others + 1, 4), 1.7)
    elif n_others == 1:
        wolf_mult = 1.15

    score = int(round(base * tier_mult * wolf_mult))
    score = max(0, min(100, score))
    return score, _label(score), wolf_pack
