"""유니버스 우선주 필터 단위 테스트 (charter v1.0.8 · 2026-08-23).

실측 근거: 2026-08-22 run_id 10 재수집에서 corp_code 매핑 실패 110종 조사
결과 100% 우선주 (일반 107 · 전환 3) 확인. 필터가 이 110종을 정확히
제외하는지 검증.
"""
from __future__ import annotations

import pandas as pd

from backend.principles.universe_filter import (
    count_excluded,
    filter_common_stock,
    is_preferred_stock,
)


# ─── is_preferred_stock ──────────────────────────────────────────


def test_general_preferred_suffix_woo():
    """일반 우선주 · 접미어 '우'."""
    assert is_preferred_stock("005935", "삼성전자우") is True
    assert is_preferred_stock("005385", "현대차우") is True
    assert is_preferred_stock("003555", "LG우") is True


def test_general_preferred_suffix_woo_b():
    """우선주 접미어 '우B' (배당형 우선주)."""
    assert is_preferred_stock("051915", "LG화학우") is True  # '우' 매치
    assert is_preferred_stock("00088K", "샘플우B") is True


def test_general_preferred_suffix_num_woo():
    """번호 접미 우선주 · 1우 · 2우B · 3우B."""
    assert is_preferred_stock("011045", "샘플1우") is True
    assert is_preferred_stock("034735", "샘플2우B") is True
    assert is_preferred_stock("037465", "샘플3우B") is True


def test_special_code_suffix_K():
    """실측 · 전환 우선주 · 특수 코드 K."""
    assert is_preferred_stock("00104K", "CJ4우(전환)") is True
    assert is_preferred_stock("00279K", "아모레퍼시픽홀딩스3우C") is True


def test_special_code_suffix_L():
    """실측 · 전환 우선주 · 특수 코드 L."""
    assert is_preferred_stock("37550L", "DL이앤씨2우(전환)") is True


def test_common_stock_not_preferred():
    """보통주 · 필터 통과."""
    assert is_preferred_stock("005930", "삼성전자") is False
    assert is_preferred_stock("000660", "SK하이닉스") is False
    assert is_preferred_stock("035420", "NAVER") is False
    assert is_preferred_stock("068270", "셀트리온") is False
    assert is_preferred_stock("016740", "두올") is False


def test_empty_name_returns_false():
    """이름 결측 · False (안전 · 조용한 오필터 방지)."""
    assert is_preferred_stock("005930", "") is False
    assert is_preferred_stock("005930", None) is False  # type: ignore[arg-type]


def test_short_ticker_no_special_suffix():
    """5자리 이하 티커 · 특수 코드 규칙 미적용 (길이 6 확인 조건)."""
    assert is_preferred_stock("00104", "샘플") is False
    assert is_preferred_stock("K", "샘플") is False


# ─── filter_common_stock ─────────────────────────────────────────


def test_filter_common_stock_mixed_sample():
    """실측 5종 이상 혼합 표본 · 보통주 3 · 우선주 5 · 필터 3만 반환."""
    df = pd.DataFrame({
        "Code": [
            "005930",  # 삼전 보통주
            "005935",  # 삼전 우선주
            "000660",  # SK하이닉스 보통주
            "005385",  # 현대차 우선주
            "016740",  # 두올 보통주
            "00104K",  # CJ4우(전환)
            "00279K",  # 아모레3우C
            "37550L",  # DL이앤씨2우(전환)
        ],
        "Name": [
            "삼성전자",
            "삼성전자우",
            "SK하이닉스",
            "현대차우",
            "두올",
            "CJ4우(전환)",
            "아모레퍼시픽홀딩스3우C",
            "DL이앤씨2우(전환)",
        ],
    })
    filtered, conflicts = filter_common_stock(df)
    assert len(filtered) == 3
    assert set(filtered["Code"].tolist()) == {"005930", "000660", "016740"}
    assert conflicts == []


def test_count_excluded_reports_preferred_count():
    """count_excluded · 우선주 개수 리포트 정확 (corp_map 무관)."""
    df = pd.DataFrame({
        "Code": ["005930", "005935", "005385", "00104K", "37550L"],
        "Name": ["삼성전자", "삼성전자우", "현대차우", "CJ4우(전환)", "DL이앤씨2우(전환)"],
    })
    assert count_excluded(df) == 4


def test_filter_empty_df_safe():
    """빈 DataFrame · 안전 반환."""
    df = pd.DataFrame({"Code": [], "Name": []})
    filtered, conflicts = filter_common_stock(df)
    assert len(filtered) == 0
    assert conflicts == []


def test_filter_reindex_after_removal():
    """필터 후 인덱스 재설정 확인 (0-based · 연속)."""
    df = pd.DataFrame({
        "Code": ["005930", "005935", "000660"],
        "Name": ["삼성전자", "삼성전자우", "SK하이닉스"],
    })
    filtered, conflicts = filter_common_stock(df)
    assert list(filtered.index) == [0, 1]
    assert conflicts == []


# ─── 교차 검증 (v1.0.8 보정 · 오탐 방어) ─────────────────────────


def test_conflict_named_woo_but_has_corp_code_not_excluded():
    """이름 '우' 접미이지만 DART corp_code 매핑 있음 → 배제 안 됨 + conflicts 등재.

    가상 보통주 · 사명이 '한전KPS우' 등 우연히 우로 끝나는 케이스 방어.
    실 우선주는 corp_code 매핑 없다 (110종 실증) · 매핑 있으면 conflict 로그.
    """
    df = pd.DataFrame({
        "Code": ["999999", "005930", "005935"],
        "Name": ["가상보통주우", "삼성전자", "삼성전자우"],
    })
    # corp_map: 가상보통주우 (999999) 는 실 DART 매핑 존재 · 삼전 정상 · 삼전우 매핑 없음
    corp_map = {
        "999999": "01234567",  # 가상 보통주 · corp_code 있음
        "005930": "00126380",  # 실 삼전 매핑
        # "005935" 매핑 없음 (실제 우선주)
    }
    filtered, conflicts = filter_common_stock(df, corp_map=corp_map)
    # 가상보통주우 는 conflict 방어로 배제 안 됨
    assert "999999" in filtered["Code"].tolist()
    assert conflicts == [("999999", "가상보통주우")]
    # 삼전 통과 · 삼전우 배제
    assert "005930" in filtered["Code"].tolist()
    assert "005935" not in filtered["Code"].tolist()


def test_conflict_special_code_K_but_has_corp_code_not_excluded():
    """특수 코드 K 인데 corp_code 매핑 있으면 conflict 방어."""
    df = pd.DataFrame({
        "Code": ["88888K"],
        "Name": ["가상보통주"],
    })
    corp_map = {"88888K": "99999999"}
    filtered, conflicts = filter_common_stock(df, corp_map=corp_map)
    assert "88888K" in filtered["Code"].tolist()
    assert conflicts == [("88888K", "가상보통주")]


def test_no_corp_map_falls_back_to_name_rule_only(caplog):
    """corp_map=None · 이름 규칙만으로 판정 (기존 동작 유지) + 경고 로그 발동."""
    import logging as _logging
    df = pd.DataFrame({
        "Code": ["999999"],
        "Name": ["가상보통주우"],
    })
    with caplog.at_level(_logging.WARNING, logger="backend.principles.universe_filter"):
        filtered, conflicts = filter_common_stock(df, corp_map=None)
    assert len(filtered) == 0  # 이름만으로 배제 (corp_map 없어 방어 불가)
    assert conflicts == []
    # 조용한 fallback 방지 · 경고 로그 실증
    assert any("corp_map_unavailable" in r.message for r in caplog.records), \
        f"corp_map=None fallback 시 경고 로그 없음 · records={[r.message for r in caplog.records]}"


def test_corp_map_present_no_unavailable_warning(caplog):
    """corp_map 있으면 corp_map_unavailable 경고 없음 (idempotent)."""
    import logging as _logging
    df = pd.DataFrame({"Code": ["005930"], "Name": ["삼성전자"]})
    with caplog.at_level(_logging.WARNING, logger="backend.principles.universe_filter"):
        filtered, conflicts = filter_common_stock(df, corp_map={"005930": "00126380"})
    assert len(filtered) == 1
    assert not any("corp_map_unavailable" in r.message for r in caplog.records)
