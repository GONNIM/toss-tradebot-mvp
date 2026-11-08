"""정규장·자동 진입 시간 검사 — 고정 시각으로 시험 (1108-03).

시험이 실행되는 날의 요일·시각에 기대지 않게 각 모듈의 datetime.now 를 고정한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import backend.discovery.live_tape.entry as entry_mod
import backend.discovery.watchlist.execute as exec_mod

KST = timezone(timedelta(hours=9))
WEEKDAY_10 = datetime(2026, 11, 9, 10, 0, tzinfo=KST)    # 월요일 10:00
WEEKDAY_0915 = datetime(2026, 11, 9, 9, 15, tzinfo=KST)  # 월요일 09:15
WEEKDAY_16 = datetime(2026, 11, 9, 16, 0, tzinfo=KST)    # 월요일 16:00
SATURDAY_10 = datetime(2026, 11, 7, 10, 0, tzinfo=KST)   # 토요일
SUNDAY_0915 = datetime(2026, 11, 8, 9, 15, tzinfo=KST)   # 일요일


def _freeze(monkeypatch, module, fixed: datetime) -> None:
    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D401
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(module, "datetime", _Fixed)


@pytest.mark.parametrize("fixed, expected", [
    (WEEKDAY_10, True),
    (WEEKDAY_16, False),
    (datetime(2026, 11, 9, 9, 0, tzinfo=KST), True),     # 시작 시각은 포함
    (datetime(2026, 11, 9, 15, 20, tzinfo=KST), False),  # 끝 시각은 제외
    (SATURDAY_10, False),
    (SUNDAY_0915, False),
])
def test_entry_active_window(monkeypatch, fixed, expected):
    _freeze(monkeypatch, entry_mod, fixed)
    params = SimpleNamespace(active_start_kst="09:00", active_end_kst="15:20")
    assert entry_mod._is_in_active_window(params) is expected


@pytest.mark.parametrize("fixed, expected", [
    (WEEKDAY_0915, True),
    (WEEKDAY_10, False),
    (datetime(2026, 11, 9, 9, 30, tzinfo=KST), False),  # 끝 시각은 제외
    (SUNDAY_0915, False),
])
def test_watchlist_execute_window(monkeypatch, fixed, expected):
    _freeze(monkeypatch, exec_mod, fixed)
    params = SimpleNamespace(watchlist_execute_start_kst="09:00", watchlist_execute_end_kst="09:30")
    assert exec_mod._is_in_execute_window(params) is expected
