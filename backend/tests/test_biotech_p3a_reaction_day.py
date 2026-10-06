"""P3a ⑤ · 반응일 (FR-6b 표 · NYSE 거래일 달력) · WP39 명부 주말 d_day 232건 재계산 = 주말 · 휴장일 0건 (명부 무변경)."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from backend.scripts import biotech_reaction_day as rd

CHECKPOINT = Path(__file__).resolve().parents[2] / "docs" / "plans" / "biotech" / "data" / "h39_readouts_checkpoint.json"
CHECKPOINT_SHA = "7de3afdea1a101090a88bc8804d824be0da84f228065bd8965c7d8bc96496a62"   # 2026-10-04 · P3a 시작 시점


def test_holiday_file_87_days():
    h = rd.holidays()
    assert len(h) == 87 and "2025-01-09" in h and "2027-12-24" in h and "2021-12-31" not in h   # 2022-01-01 토요일 · 대체 휴장 없음


@pytest.mark.parametrize("accept,session,base,react", [
    ("2026-09-29T11:05:31.000Z", "pre_open", "2026-09-28", "2026-09-29"),       # 07:05 ET
    ("2026-09-29T13:30:00.000Z", "intraday", "2026-09-28", "2026-09-30"),       # 09:30 ET 정각 = 장중
    ("2026-09-29T19:59:59.000Z", "intraday", "2026-09-28", "2026-09-30"),       # 15:59:59 ET
    ("2026-09-29T20:00:00.000Z", "after_close", "2026-09-29", "2026-09-30"),    # 16:00 ET 정각 = 마감 뒤
    ("2026-07-17T16:10:00", "after_close", "2026-07-17", "2026-07-20"),         # VXRT 금 16:10 (명부 동부값) · 명부 d_day 7/18 (토)
    ("2026-07-17T20:10:00.000Z", "after_close", "2026-07-17", "2026-07-20"),    # 같은 시각 UTC 표기
    ("2026-07-03T10:00:00", "non_trading_day", "2026-07-02", "2026-07-06"),     # 휴장일 (독립기념일 대체)
    ("2026-01-15T21:30:00.000Z", "after_close", "2026-01-15", "2026-01-16"),    # 겨울 UTC−5
])
def test_fr6b_table(accept, session, base, react):
    r = rd.reaction(accept)
    assert (r["session"], r["base_date"], r["reaction_date"]) == (session, base, react)


def test_outside_calendar_raises():
    with pytest.raises(ValueError):
        rd.reaction("2018-12-31T10:00:00")


def test_wp39_weekend_dday_recomputed_all_trading_days():
    raw = CHECKPOINT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == CHECKPOINT_SHA                   # 명부는 읽기만 · 고치지 않음
    ev = json.loads(raw)["events"]
    weekend = [e for e in ev if e.get("d_day") and date.fromisoformat(e["d_day"]).weekday() >= 5]
    assert len(weekend) == 232                                                 # P2 이상 2
    out = [rd.reaction(e["accept_datetime_et"]) for e in weekend]
    bad = [r for r in out if not rd.is_trading_day(date.fromisoformat(r["reaction_date"]))
           or not rd.is_trading_day(date.fromisoformat(r["base_date"]))]
    assert bad == []
    # 전체 7,351건도 주말 · 휴장일 0건
    allr = [rd.reaction(e["accept_datetime_et"]) for e in ev if e.get("accept_datetime_et")]
    assert len(allr) == 7351 and all(rd.is_trading_day(date.fromisoformat(r["reaction_date"])) for r in allr)
