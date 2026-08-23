"""유니버스 우선주 자동 제외 필터 (charter v1.0.8 · 2026-08-23).

원칙: 기업 단위 재무는 보통주 티커로 단일 판정 · 우선주는 중복 판정 회피 자동 제외.
단 우선주 배당은 P2 (shareholder_return · dividend_total) 에 계속 포함 (공시 총액 기준).

실증: 2026-08-22 run_id 10 재수집에서 corp_code 매핑 실패 110종 조사 결과
100% 우선주 (일반 107 + 전환 우선주 3) 확인. 조용한 누락 방지 위해 명시 제외.

교차 검증 (v1.0.8 보정 · 오탐 방어):
  이름 규칙 배제 판정된 티커 중 DART corp_code 매핑 존재 시 배제 안 함 +
  preferred_filter_conflict 로그. 우선주는 corp_code 매핑이 없다는 110종
  실증 성질을 안전장치로 사용.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# charter v1.0.8 · universe.exclude.preferred_stock 참조.
# Name 접미어 (가장 긴 매치 우선 배치 · endswith 순서 무관하나 명시성).
_PREFERRED_NAME_SUFFIXES: tuple[str, ...] = (
    "우전환",
    "우C",
    "2우B",
    "3우B",
    "1우",
    "우B",
    "우",
)
# 6자리 종목코드 특수 접미 (전환 우선주 등 · 예: 00104K CJ4우(전환) · 37550L DL이앤씨2우(전환))
_PREFERRED_SPECIAL_CODE_SUFFIXES: tuple[str, ...] = ("K", "L")


def is_preferred_stock(ticker: str, name: str) -> bool:
    """우선주 여부 판정 · Name 접미어 OR 6자리 종목코드 특수 접미 매치.

    Args:
      ticker: 6자리 종목코드 (문자열)
      name: 종목명 (예: '삼성전자우' · '두산' · '00104K CJ4우(전환)' 는 name='CJ4우(전환)')

    Returns:
      True = 우선주 · False = 보통주
    """
    if not name:
        return False
    for suf in _PREFERRED_NAME_SUFFIXES:
        if name.endswith(suf):
            return True
    if len(ticker) == 6 and ticker[-1] in _PREFERRED_SPECIAL_CODE_SUFFIXES:
        return True
    return False


def filter_common_stock(
    df: pd.DataFrame,
    corp_map: Optional[dict[str, Optional[str]]] = None,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """KOSPI DataFrame (Code, Name) → 보통주만 반환 + conflict 리스트.

    charter v1.0.8 universe 제외 규칙 적용. 인덱스 재설정.

    Args:
      df: raw 유니버스 (Code, Name)
      corp_map: DART corp_code 매핑 · 있으면 conflict 방어 (이름 우선주 매치 but
        corp_code 있음 → 배제 안 함 + conflict 리스트에 등재)

    Returns:
      (filtered_df, conflicts): 필터된 DF · conflicts=[(ticker, name), ...]
        conflicts 는 이름은 우선주 매치이지만 corp_code 있어 보통주로 유지된 종목.
    """
    conflicts: list[tuple[str, str]] = []
    if df is None or len(df) == 0:
        return df, conflicts
    if corp_map is None:
        # fallback 경로 · 교차 검증 불가 · 조용히 지나가면 안 됨 (사용자 지시 · 오탐 방어)
        logger.warning(
            "[universe_filter] corp_map_unavailable · 교차 검증 불가 · "
            "이름 규칙 단독 동작 · conflict 감지 불능"
        )
    codes = df["Code"].astype(str)
    names = df["Name"].astype(str)
    keep = []
    for t, n in zip(codes, names):
        if not is_preferred_stock(t, n):
            keep.append(True)
            continue
        # 이름은 우선주 매치. corp_map 있으면 교차 검증.
        if corp_map is not None and corp_map.get(t):
            # 이름은 우선주 접미어이지만 DART corp_code 매핑 존재 → conflict · 배제 안 함
            conflicts.append((t, n))
            logger.warning(
                f"[universe_filter] preferred_filter_conflict · {t} {n} · "
                f"이름 우선주 매치 but corp_code 존재 · 배제 안 함 (오탐 방어)"
            )
            keep.append(True)
        else:
            keep.append(False)  # 배제
    mask = pd.Series(keep, index=df.index)
    return df[mask].reset_index(drop=True), conflicts


def count_excluded(df: pd.DataFrame) -> int:
    """디버그·리포트용 · 제외된 우선주 개수 (corp_map 없이 이름만 판정)."""
    if df is None or len(df) == 0:
        return 0
    codes = df["Code"].astype(str)
    names = df["Name"].astype(str)
    return sum(1 for t, n in zip(codes, names) if is_preferred_stock(t, n))
