"""계획 화면 「언제」 칸 값 · 1116-01 S5 (읽기 전용 · params 에 저장하지 않는다).

날짜 계산은 서버 한 곳에서 한다. 시간 손절 시작일은 엔진과 같은 함수(`sessions.add_trading_days`)와 같은 휴장일 묶음으로 낸다.
- 시간 손절 시작 = add_trading_days(발표 시각의 UTC 날짜, 5, 휴장일) 의 다음 거래일 · 그날 미국 정규장 시작(09:30 뉴욕) 30분 뒤.
- 화면에 보이는 날짜 기준은 한국 날짜(KST) 한 가지다. D-n 은 (발표 한국 날짜 − 오늘 한국 날짜).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import sessions as sess
from . import state, us_holidays
from .engine import params_of, parse_dt

_KST = ZoneInfo("Asia/Seoul")
_NY = ZoneInfo("America/New_York")
_UTC = timezone.utc
_EST_WARN = "촉매 날짜는 추정입니다"
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _kst(dt_utc: datetime) -> datetime:
    return dt_utc.replace(tzinfo=_UTC).astimezone(_KST)


def _iso(dt_utc: Optional[datetime]) -> Optional[str]:
    return _kst(dt_utc).isoformat(timespec="minutes") if dt_utc else None


def _kdate(dt_utc: Optional[datetime]) -> Optional[str]:
    return _kst(dt_utc).date().isoformat() if dt_utc else None


def _read_dt(raw) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return parse_dt(raw)
    except (ValueError, TypeError):
        return None


def timestop_start(announce_utc: datetime, holidays: frozenset) -> datetime:
    """시간 손절 시작 시각 (UTC · 시간대 없음). 서머타임은 뉴욕 시간대로 바꾼다."""
    last = sess.add_trading_days(announce_utc.date(), 5, holidays)
    first = sess.add_trading_days(last, 1, holidays)
    ny = datetime(first.year, first.month, first.day, 10, 0, tzinfo=_NY)       # 정규장 시작 09:30 + 30분
    return ny.astimezone(_UTC).replace(tzinfo=None)


def _catalyst(plan, p: dict, announce_utc: Optional[datetime]) -> dict:
    """(kind, confirmed, basis, stale) · kind = confirmed | estimated | unknown | manual | edited."""
    rat = p.get("rationale") if isinstance(p.get("rationale"), dict) else None
    if plan.source != "draft" or not rat or not rat.get("catalyst"):
        return {"kind": "manual", "confirmed": None, "basis": "직접 입력", "stale": False, "day": None}
    basis = str(rat.get("catalyst"))
    day: Optional[date] = None
    try:
        if rat.get("catalyst_day"):
            day = date.fromisoformat(str(rat["catalyst_day"]))
        else:
            m = _DATE_RE.findall(basis)
            day = date.fromisoformat(m[-1]) if m else None
    except ValueError:
        day = None
    conf = rat.get("catalyst_confirmed")
    if not isinstance(conf, bool):          # 새 초안 이전 값 · 글자열로만 읽는다 (못 읽으면 확정으로 적지 않는다)
        warns = " ".join(str(x) for x in (p.get("warnings") or []))
        if _EST_WARN in warns or "(추정)" in basis or "범위(" in basis:
            conf = False
        elif "대표 입력" in basis or "회사 8-K" in basis:
            conf = True
        else:
            conf = None
    stale = bool(day and announce_utc and announce_utc.date() != day)
    if stale:
        return {"kind": "edited", "confirmed": None, "basis": basis, "stale": True, "day": day.isoformat()}
    kind = "confirmed" if conf is True else "estimated" if conf is False else "unknown"
    return {"kind": kind, "confirmed": conf, "basis": basis, "stale": False, "day": day.isoformat() if day else None}


def _applies(plan, p: dict, has_announce: bool) -> dict:
    if not has_announce:
        return {"applies": False, "text": "발표 시각이 없어 시간 손절이 없습니다."}
    if plan.timestop_stage == "stopped" and plan.state not in state.TERMINAL:
        return {"applies": False, "text": "시간 손절이 멈춤 상태입니다. 대표가 중지해 이 날짜가 지나도 시작하지 않습니다."}
    st = plan.state
    if st in state.TERMINAL:
        return {"applies": False, "text": "끝난 계획이라 시간 손절은 시작하지 않습니다."}
    if st in (state.TP1_WAIT, state.TRAILING):
        return {"applies": False, "text": "첫 매도 목표(TP1)가 이미 체결되어 시간 손절은 적용되지 않습니다."}
    if st == state.HALTED:
        return {"applies": None, "text": "계획이 정지 중입니다. 재개해 보유 중이 되고 첫 매도 목표가 체결되지 않았을 때만 적용됩니다."}
    if st == state.HOLDING:
        return {"applies": True, "text": "보유 중이고 첫 매도 목표(TP1)가 체결되지 않았으므로, 이 날짜 이후 정규장에서 시간 손절이 시작됩니다."}
    return {"applies": None, "text": "보유 중이고 첫 매도 목표(TP1)가 체결되지 않았을 때만 적용됩니다. 지금은 보유 전입니다."}


def build_when(plan, now_utc: datetime, holidays_fn: Callable[[], frozenset] = us_holidays.current) -> dict:
    """응답 전용 `when` 칸. 읽을 수 없는 값은 None 으로 두고 경고에 적는다."""
    p = params_of(plan)
    hol = holidays_fn()
    announce = _read_dt(p.get("announce_at"))
    close = _read_dt(p.get("entry_close_at"))
    cat = _catalyst(plan, p, announce)
    opens: Optional[datetime] = None
    rat = p.get("rationale") if isinstance(p.get("rationale"), dict) else {}
    if plan.source == "draft":
        raw = rat.get("window_open")
        if not raw:                                       # 옛 초안 · 진입 창 문장 「(시작 ~ 끝)」 에서 읽는다
            m = _DATE_RE.findall(str(rat.get("window") or ""))
            raw = m[0] if m else None
        try:
            d0 = date.fromisoformat(str(raw)) if raw else None
        except ValueError:
            d0 = None
        opens = datetime(d0.year, d0.month, d0.day, 21, 0) if d0 else None      # 초안의 날짜 기준과 같은 21:00(UTC)
    ts_from = timestop_start(announce, hol) if announce else None
    warnings = [str(w) for w in (p.get("warnings") or []) if w]
    if cat["stale"]:
        warnings.append("발표 시각을 고친 뒤라 아래 근거는 초안을 만들 때의 것입니다.")
    for label, dt in (("발표", announce), ("시간 손절 시작", ts_from)):
        if dt and not us_holidays.is_verified_year(dt.year):
            warnings.append(f"{dt.year}년은 미국 휴장일을 확인하지 못했습니다 · {label} 날짜가 하루쯤 어긋날 수 있습니다.")
            break
    today = _kst(now_utc).date()
    steps = [("window_open", opens), ("entry_close", close), ("announce", announce), ("timestop", ts_from)]
    rows = sorted(((k, dt) for k, dt in steps if dt), key=lambda kv: kv[1])     # 확정 발표는 마감이 발표 앞 · 추정은 뒤 → 날짜순
    step_list = [{"key": k, "at": _iso(dt), "date": _kdate(dt), "passed": _kst(dt).date() <= today} for k, dt in rows]
    d_day = (_kst(announce).date() - today).days if announce else None
    return {
        "today": today.isoformat(),
        "window_open": _iso(opens), "window_open_date": _kdate(opens),
        "entry_close_at": _iso(close), "entry_close_date": _kdate(close),
        "announce_at": _iso(announce), "announce_date": _kdate(announce), "d_day": d_day,
        "timestop_from": _iso(ts_from), "timestop_from_date": _kdate(ts_from),
        "steps": step_list,                                # 날짜순 · passed = 오늘(한국 날짜)까지 지났는가 (오늘 위치 표시용)
        "catalyst_kind": cat["kind"], "catalyst_confirmed": cat["confirmed"],
        "basis": cat["basis"], "basis_stale": cat["stale"],
        "window_text": rat.get("window") if plan.source == "draft" else None,
        "warnings": warnings,
        "timestop_applies": _applies(plan, p, announce is not None),
        "tz": "KST", "estimate": True,
    }
