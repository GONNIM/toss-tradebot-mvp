"""실체 검증 태깅 (gate-design-v1 §3-3 · 세션 B · 2026-08-23).

PASS 종목이라도 TTM 구성 분기의 이상 패턴을 자동 태깅해 게이트가 자동 매수를
보류하고 사용자 확인 요구.

태그 규칙 (charter v1.0.9 후보 · 사용자 승인 완료):
  (a) single_quarter_outlier · 단분기 이례
      · 최근 8Q 단독 시리즈에서 · |q_standalone − prev_4q_avg| > prev_4q_avg × 1.0
      · SJG세종 Q4'25 +6.9억 (직전 4Q 평균 227억 대비 3% · 편차 220억 > 227억) 실증
      · 두올 Q4'25 -13.8억 (직전 4Q 평균 100억 · 편차 113억 > 100억) 실증
  (b) ttm_concentration · TTM 특정 분기 의존
      · max(recent_4q_standalone) / TTM > 0.50
      · 단일 분기가 TTM 의 50% 초과 → 지속성 결함 의심

태깅 시 verdict 는 PASS 유지 · PrinciplesResult.verification_tags 저장
· 게이트에서 태깅 종목의 자동 매수 보류 (verification_required) + 사용자 확인 요구.

확인 스코프 (사용자 지시 2026-08-23):
  키 = (ticker, tags_hash) 이중키. run_id 는 감사 필드로만.
  이유: recompute 마다 실효 시 재확인 피로 → 기계적 승인 유도 (보호 장치 자기 무력화).
  태그 구성 동일 → 확인 유지 · 구성 변경 → hash 불일치 자동 실효 (설계 의도).
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable, Optional

TAG_SINGLE_QUARTER_OUTLIER = "single_quarter_outlier"
TAG_TTM_CONCENTRATION = "ttm_concentration"

# 규칙 임계 (charter v1.0.9 후보 · 사용자 승인)
SINGLE_QUARTER_DEVIATION_MULTIPLIER = 1.0  # |dev| > avg × 1.0
TTM_CONCENTRATION_RATIO_THRESHOLD = 0.50   # max(4Q) / TTM > 0.50


def _prev_4q_avg(series: list[Optional[float]], idx: int) -> Optional[float]:
    """series[idx-4:idx] 평균 · None 하나라도 있으면 None."""
    if idx < 4:
        return None
    window = series[idx - 4 : idx]
    if any(v is None for v in window):
        return None
    return sum(window) / 4.0  # type: ignore[operator]


def check_single_quarter_outlier(
    standalone_series: list[Optional[float]],
) -> bool:
    """최근 8Q 단독 시리즈 중 · 어느 분기라도 직전 4Q 평균 대비 |편차| > 평균×1.0 이면 True.

    조건 검사 범위: idx=4..len(series)-1 (직전 4Q 확보 가능한 인덱스만).
    평균 계산 시 None 있으면 해당 인덱스 skip.
    평균이 0 근사 (|avg| < 1) 시 편차 판정 불가 skip (제로 나눗셈 방지 · 이슈 감소).
    """
    if len(standalone_series) < 5:
        return False
    for i in range(4, len(standalone_series)):
        v = standalone_series[i]
        if v is None:
            continue
        avg = _prev_4q_avg(standalone_series, i)
        if avg is None:
            continue
        if abs(avg) < 1.0:
            continue  # 평균 근사 0 · 판정 불가 (모든 편차가 무한 배)
        deviation = abs(v - avg)
        if deviation > abs(avg) * SINGLE_QUARTER_DEVIATION_MULTIPLIER:
            return True
    return False


def check_ttm_concentration(
    recent_4q_standalone: list[Optional[float]],
    ttm: Optional[float],
) -> bool:
    """최근 4Q 단독 시리즈에서 max 값이 TTM 의 50% 초과 → True.

    TTM=None 또는 |TTM|<1 (근사 0) 시 판정 불가 · False (제로 나눗셈 방지).
    None 값 있으면 max 계산 불가 · False (안전측).
    """
    if ttm is None or abs(ttm) < 1.0:
        return False
    if len(recent_4q_standalone) < 4:
        return False
    if any(v is None for v in recent_4q_standalone):
        return False
    max_q = max(recent_4q_standalone)  # type: ignore[type-var]
    if max_q is None:
        return False
    return abs(max_q) / abs(ttm) > TTM_CONCENTRATION_RATIO_THRESHOLD


def compute_tags(
    *,
    ttm: Optional[float],
    recent_standalone_series: list[Optional[float]],
) -> list[str]:
    """PASS 종목의 verification 태그 리스트 계산.

    Args:
      ttm: 최근 4Q 단독 합 (net_income_owner)
      recent_standalone_series: 최근 8Q 단독 시리즈 (시간순 · 마지막이 최신)

    Returns:
      태그 리스트 (예: ["single_quarter_outlier"] · [] 이면 태그 없음)
    """
    tags: list[str] = []
    if check_single_quarter_outlier(recent_standalone_series):
        tags.append(TAG_SINGLE_QUARTER_OUTLIER)
    # 최근 4Q = 시리즈 마지막 4개
    recent_4q = recent_standalone_series[-4:] if len(recent_standalone_series) >= 4 else []
    if check_ttm_concentration(recent_4q, ttm):
        tags.append(TAG_TTM_CONCENTRATION)
    return sorted(tags)  # 정렬 · hash 안정성 보장


def tags_hash(tags: Iterable[str]) -> str:
    """확인 키용 태그 집합 해시 (16자 sha256 축약 · hex).

    정렬 후 JSON 직렬화 → sha256[:16]. 태그 구성 다르면 hash 자동 불일치.
    """
    canonical = json.dumps(sorted(tags), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
