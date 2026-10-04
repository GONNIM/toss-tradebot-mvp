"""P3a ⑤ · 반응일 계산 (PRD v0.5 FR-6b 표 · 뉴욕 증권거래소 거래일 달력).

접수 시각 (SEC acceptanceDateTime · UTC → 미국 동부) 으로 기준가 날짜와 반응가 날짜를 정한다. 제출일 (filingDate) 은 쓰지 않는다.

| 접수 시각 (미국 동부) | 기준가          | 반응가          |
|-----------------------|-----------------|-----------------|
| 09:30 전              | 직전 거래일 종가 | 당일 종가        |
| 09:30 ~ 16:00 (16:00 미포함) | 직전 거래일 종가 | 다음 거래일 종가 |
| 16:00 부터            | 당일 종가        | 다음 거래일 종가 |

- 접수일이 거래일이 아니면 (주말 · 휴장일) 다음 거래일의 "09:30 전" 과 같다 (기준가 = 직전 거래일 · 반응가 = 다음 거래일).
- 거래일 = 월~금 중 휴장일이 아닌 날. 휴장일 = docs/plans/biotech/data/nyse_holidays_2019_2027.csv
  (2019-01 ~ 2026-09 = XBI Tiingo 일봉 평일 결측 75일과 대조 · 2026-10 이후 = nyse.com/markets/hours-calendars).
- 달력 범위 (2019-01-01 ~ 2027-12-31) 밖 날짜는 ValueError.
- 단축 거래일 (13:00 마감) 은 표의 16:00 경계를 그대로 쓴다 (P2b 설계 파일에서 확정할 사항).
- WP39 명부 (h39_readouts_checkpoint.json) 와 그 코드는 고치지 않는다 · 명부의 d_day 는 쓰지 않고 이 모듈로 다시 계산한다.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import sys
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from backend.scripts import _biotech_paths as _P

ET = ZoneInfo("America/New_York")
HOLIDAY_FILE = "nyse_holidays_2019_2027.csv"
CAL_START, CAL_END = date(2019, 1, 1), date(2027, 12, 31)
OPEN, CLOSE = time(9, 30), time(16, 0)


@lru_cache(maxsize=1)
def holidays() -> frozenset[str]:
    p = _P.find(HOLIDAY_FILE)
    if p is None:
        raise FileNotFoundError(HOLIDAY_FILE)
    with p.open() as f:
        return frozenset(r["date"] for r in csv.DictReader(f))


def _check(d: date) -> None:
    if not (CAL_START <= d <= CAL_END):
        raise ValueError(f"거래일 달력 범위 밖 · {d} (2019-01-01 ~ 2027-12-31)")


def is_trading_day(d: date) -> bool:
    _check(d)
    return d.weekday() < 5 and d.isoformat() not in holidays()


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def prev_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def to_et(accept: str) -> datetime:
    """'2026-09-29T11:05:31.000Z' (UTC) → 동부 시각 · 시간대 없는 값 ('2026-08-06T16:17:59') 은 이미 동부 시각으로 본다."""
    t = datetime.fromisoformat(accept.replace("Z", "+00:00"))
    if t.tzinfo is None:
        return t
    return t.astimezone(ET).replace(tzinfo=None)


def reaction(accept: str) -> dict:
    """접수 시각 → 세션 · 기준가 날짜 · 반응일 (0~+1 거래일)."""
    t = to_et(accept)
    d, hm = t.date(), t.time()
    if not is_trading_day(d):
        session, base, react = "non_trading_day", prev_trading_day(d), next_trading_day(d)
    elif hm < OPEN:
        session, base, react = "pre_open", prev_trading_day(d), d
    elif hm < CLOSE:
        session, base, react = "intraday", prev_trading_day(d), next_trading_day(d)
    else:
        session, base, react = "after_close", d, next_trading_day(d)
    return {"accept_et": t.isoformat(timespec="seconds"), "session": session,
            "base_date": base.isoformat(), "reaction_date": react.isoformat()}


def main():
    """확인용 · python -m backend.scripts.biotech_reaction_day <접수 시각>..."""
    require_secure_logging()
    for a in sys.argv[1:]:
        print(json.dumps(reaction(a), ensure_ascii=False))


if __name__ == "__main__":
    main()
