"""미국 정규장(NYSE) 종일 휴장일 계산 · 1116-01 서버 단계 S4 (사용자 11/25 ㉡ 가).

- 새 의존성 없이 규칙으로 계산한다. 조기 마감일(예: 11/27 · 12/24)은 정규장이 열리므로 휴장일이 아니다.
- 규칙: 신정(토요일이면 대체 휴장 없음 · 일요일이면 월요일) · MLK(1월 3째 월) · 대통령의 날(2월 3째 월) · 성금요일 ·
  메모리얼데이(5월 마지막 월) · 준틴스(2022~ · 토요일이면 금 · 일요일이면 월) · 독립기념일(토→금 · 일→월) ·
  노동절(9월 첫 월) · 추수감사절(11월 4째 목) · 성탄절(토→금 · 일→월).
- 임시 휴장(국가 애도일 등)과 시험하지 않은 해는 규칙이 잡지 못한다 → `backend/data/us_holidays_extra.json` 에 날짜를 덧붙인다.
  형식: {"dates": ["YYYY-MM-DD", ...], "verified_years": [2029, ...]}  (파일이 없거나 깨지면 무시)
- 계산이 실패하면 엔진은 멈추지 않고 주말만 빼는 지금 동작으로 간다(경고 기록). 해마다 한 번만 계산한다(캐시).

시험 표 출처 (2026~2028): NYSE 공식 「Holidays & Trading Hours」 https://www.nyse.com/markets/hours-calendars
  확인 시각: 2026-11-25 11:40 KST (WebFetch 로 페이지를 열어 대조). 조기 마감: 2026-11-27 · 2026-12-24 · 2027-11-26 · 2028-07-03 · 2028-11-24.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

VERIFIED_YEARS = frozenset({2026, 2027, 2028})      # 공식 표와 시험으로 대조한 해
EXTRA_FILE = Path(__file__).resolve().parents[2] / "data" / "us_holidays_extra.json"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    """토요일이면 금요일 · 일요일이면 월요일."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def rule_holidays(year: int) -> frozenset[date]:
    out = {
        _nth_weekday(year, 1, 0, 3), _nth_weekday(year, 2, 0, 3), _easter(year) - timedelta(days=2),
        _last_weekday(year, 5, 0), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 7, 4)), _observed(date(year, 12, 25)),
    }
    if date(year, 1, 1).weekday() != 5:               # 토요일 새해는 대체 휴장 없음 (12/31 은 열림)
        out.add(_observed(date(year, 1, 1)))
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))
    return frozenset(out)


def _extra() -> tuple[frozenset[date], frozenset[int]]:
    try:
        raw = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))
        dates = frozenset(date.fromisoformat(str(x)) for x in raw.get("dates", []))
        years = frozenset(int(y) for y in raw.get("verified_years", []))
        return dates, years
    except FileNotFoundError:
        return frozenset(), frozenset()
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("[us_holidays] 덧붙임 파일을 읽지 못해 무시합니다 · %s", exc.__class__.__name__)
        return frozenset(), frozenset()


@lru_cache(maxsize=16)
def holidays_for_year(year: int) -> frozenset[date]:
    """그 해의 휴장일 (규칙 + 덧붙임 파일). 해마다 한 번만 계산한다."""
    return rule_holidays(year) | frozenset(d for d in _extra()[0] if d.year == year)


def is_verified_year(year: int) -> bool:
    return year in VERIFIED_YEARS or year in _extra()[1]


def holidays_around(today: date) -> frozenset[date]:
    """엔진 · 초안이 쓰는 묶음: 올해 앞뒤 (작년 ~ 내후년). 실패하면 빈 집합 = 주말만 빼는 동작."""
    try:
        out: frozenset[date] = frozenset()
        for y in range(today.year - 1, today.year + 3):
            out |= holidays_for_year(y)
        return out
    except Exception as exc:  # noqa: BLE001 — 휴장일 계산 실패가 엔진 틱을 멈추지 않는다
        logger.warning("[us_holidays] 계산 실패 · 주말만 뺍니다 · %s", exc.__class__.__name__)
        return frozenset()


def provider(today_fn: Callable[[], date] = date.today) -> Callable[[], frozenset]:
    """PlanEngine(holidays=…) 에 넘기는 호출 가능 값."""
    return lambda: holidays_around(today_fn())


def current() -> frozenset[date]:
    return holidays_around(date.today())
