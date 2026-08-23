"""실체 검증 태깅 규칙 단위 테스트 (gate-design-v1 §3-3 · 세션 B).

실증 픽스처 회귀 고정:
  - SJG세종 (033530) TTM 963억 · 2025 Q4 단독 +6.9억 (직전 4Q 평균 227억 대비
    편차 220억 > 227억) → single_quarter_outlier 태깅 예상
  - 두올 (016740) TTM 211억 · 2025 Q4 단독 -13.8억 (직전 4Q 평균 ~100억 ·
    편차 113억 > 100억) → single_quarter_outlier 태깅 예상
"""
from __future__ import annotations

from backend.principles.verification_tagger import (
    TAG_SINGLE_QUARTER_OUTLIER,
    TAG_TTM_CONCENTRATION,
    check_single_quarter_outlier,
    check_ttm_concentration,
    compute_tags,
    tags_hash,
)


def test_sjg세종_single_quarter_outlier_fixture():
    """SJG세종 2025 Q4 +6.9억 (직전 4Q 평균 227억) · 편차 220억 > 227억 · 태깅."""
    # 실증: 최근 8Q 단독 (2024Q3 이후 · 순서상)
    series = [
        None,          # 2024Q3 이전 결측
        223.9e8,       # 2024Q4
        223.9e8,       # 2025Q1
        221.0e8,       # 2025Q2
        235.7e8,       # 2025Q3
        6.9e8,         # 2025Q4 ← 이례
        384.0e8,       # 2026Q1 ← 급증
        336.4e8,       # 2026Q2
    ]
    assert check_single_quarter_outlier(series) is True


def test_dooul_single_quarter_outlier_fixture():
    """두올 2025 Q4 -13.8억 (직전 4Q 흑자 대비 음전환) · 태깅.

    직전 4Q 확보 위해 2024 Q3·Q4 안정 시드 (실측 근사 · 두올 2024 규모).
    idx=5 (2025Q4) 직전 4Q = [2024Q3, 2024Q4, 2025Q1, 2025Q2] · avg 90+ ·
    |-13.8 - avg| > avg · True.
    """
    series = [
        60e8,          # 2024Q3 시드 (안정)
        80e8,          # 2024Q4 시드
        123.4e8,       # 2025Q1
        66.9e8,        # 2025Q2
        111.9e8,       # 2025Q3
        -13.8e8,       # 2025Q4 ← 음전환 이례
        37.2e8,        # 2026Q1
        76.0e8,        # 2026Q2
    ]
    assert check_single_quarter_outlier(series) is True


def test_stable_series_no_outlier():
    """안정 시리즈 · 편차 100% 이내 · 태깅 없음."""
    series = [100e8, 110e8, 105e8, 108e8, 112e8, 106e8, 111e8, 109e8]
    assert check_single_quarter_outlier(series) is False


def test_ttm_concentration_above_50pct():
    """최근 4Q 중 단일 분기가 TTM 의 60% · 태깅."""
    recent_4q = [10e8, 60e8, 20e8, 10e8]  # max=60 · TTM=100
    ttm = 100e8
    assert check_ttm_concentration(recent_4q, ttm) is True


def test_ttm_concentration_below_50pct():
    """최근 4Q 균등 · 25% 각 · 태깅 없음."""
    recent_4q = [25e8, 25e8, 25e8, 25e8]
    ttm = 100e8
    assert check_ttm_concentration(recent_4q, ttm) is False


def test_ttm_concentration_zero_ttm_no_flag():
    """TTM 0 근사 · 판정 불가 · 태깅 없음 (제로 나눗셈 방지)."""
    assert check_ttm_concentration([10e8, 20e8, 30e8, 40e8], 0.0) is False
    assert check_ttm_concentration([10e8, 20e8, 30e8, 40e8], None) is False


def test_ttm_concentration_none_in_series_no_flag():
    """4Q 중 None 있으면 안전측 · 태깅 없음."""
    assert check_ttm_concentration([25e8, None, 25e8, 25e8], 100e8) is False


def test_compute_tags_sjg세종_both_conditions():
    """SJG세종 시리즈 · single_quarter_outlier 태깅 + TTM concentration 확인."""
    series = [
        None, 223.9e8, 223.9e8, 221.0e8,
        235.7e8, 6.9e8, 384.0e8, 336.4e8,
    ]
    # TTM = 최근 4Q (2025Q3~2026Q2) = 235.7 + 6.9 + 384 + 336.4 = 963.0억
    ttm = 963.0e8
    tags = compute_tags(ttm=ttm, recent_standalone_series=series)
    assert TAG_SINGLE_QUARTER_OUTLIER in tags
    # Q1 384/963 = 39.9% · Q2 336.4/963 = 34.9% · 50% 미만 · concentration 태깅 없음
    assert TAG_TTM_CONCENTRATION not in tags


def test_compute_tags_stable_no_tags():
    """안정 시리즈 · 태그 없음."""
    series = [100e8, 105e8, 108e8, 110e8, 112e8, 108e8, 111e8, 109e8]
    ttm = 440e8
    assert compute_tags(ttm=ttm, recent_standalone_series=series) == []


def test_tags_hash_stable_across_order():
    """tags_hash · 순서 무관 · 정렬 후 hash."""
    h1 = tags_hash(["single_quarter_outlier", "ttm_concentration"])
    h2 = tags_hash(["ttm_concentration", "single_quarter_outlier"])
    assert h1 == h2
    assert len(h1) == 16


def test_tags_hash_different_composition():
    """tags 구성 다르면 hash 다름 (실효 트리거)."""
    h1 = tags_hash(["single_quarter_outlier"])
    h2 = tags_hash(["single_quarter_outlier", "ttm_concentration"])
    assert h1 != h2


def test_tags_hash_empty_list_stable():
    """빈 태그도 hash 계산 가능 (구조 안정성)."""
    h = tags_hash([])
    assert len(h) == 16
