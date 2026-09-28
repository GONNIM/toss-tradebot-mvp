"""WP78 · 급등 경보 판정 규칙 (한 곳 정의 · kpi.json 과 급등 브리핑이 함께 사용).

규칙 (표시 계층 · h_radar_params alerts_definition_wp78 · 2026-09-28 사용자 지시):
  (a) 기준선 (st_baseline_n) 7일 미만 종목은 판정 제외 → "수집 중" (표 3 과 같은 7일 규칙)
  (b) apewisdom 평소 대비 배수 ≥ 5  AND  오늘 apewisdom 언급 ≥ 5건 (최소 절대량)
      근거: 2026-09-28 IOVA · 어제 1 · 오늘 1 · 6.0배로 경보 (1건으로 5배는 잡음)
  (c) OR 레딧 RSS 제목 매치 ≥ 3건 (그대로)
점수·단계·후보 선정에는 쓰지 않는다.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · biotech 스크립트 규약 (WP8)
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401 · 규약 (main 없음)

BASELINE_MIN_DAYS = 7
MULT_MIN = 5.0
TODAY_MIN_MENTIONS = 5
RSS_MIN = 3


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def judge(row: dict) -> tuple[bool, str]:
    """(경보 여부, 사유) · 사유 = collecting | mult | rss | none."""
    if int(_num(row.get("st_baseline_n"))) < BASELINE_MIN_DAYS:
        return False, "collecting"
    mult_raw = row.get("st_baseline_mult")
    mult = 0.0 if mult_raw in (None, "", "collecting") else _num(mult_raw)
    if mult >= MULT_MIN and _num(row.get("apewisdom_24h")) >= TODAY_MIN_MENTIONS:
        return True, "mult"
    if int(_num(row.get("reddit_rss_matches"))) >= RSS_MIN:
        return True, "rss"
    return False, "none"
