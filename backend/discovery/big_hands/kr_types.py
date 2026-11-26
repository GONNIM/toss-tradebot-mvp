"""국내 큰손 유형 판정 KR-I1 · KR-I2 · KR-M1 · KR-M2 (1119-03 ② · 기획서 3-3 · rules-v1 초안 2절).

순수 함수 · 바깥 호출 없음 · 읽는 곳 없음(성적표 묶음 전까지 어디서도 부르지 않음).

막음 1 (미래 정보 금지): 판정과 제외는 **진입 전까지 접수된 내용만** 쓴다.
  - 같은 사람 반복 소량은 그 건의 접수일까지 접수된 건만 센다 (뒤에 올 건수를 보지 않는다).
  - 정정 · 철회 · 곧 매도는 판정에서 빼지 않고 tally_later_events 로 따로 센다.
모를 때(원문을 못 읽음 등)는 맞춰 넣지 않고 unknown 으로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, Sequence

from .ledger import kr_i2_establish_date

# ── 규칙 값 (rules-v1 초안 · 고정 전) ─────────────────────────────────────
REPEAT_MIN_COUNT = 3            # 같은 사람 같은 달 장내매수 접수가 이 건수 이상이면 …
REPEAT_SMALL_RATE_PCT = 0.1     # … 그 건의 지분 증감이 이 %p 미만일 때 「반복 소량」으로 뺀다
I2_WINDOW_DAYS = 30
SOLD_SOON_DAYS = 30             # 매수 접수 뒤 이 일수 안의 같은 사람 매도를 「곧 매도」로 센다

# 빼는 말 (취득 방법 · 보고 사유 글에 들어 있으면 뺀다)
EXCLUDE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "스톡옵션": ("주식매수선택권", "스톡옵션", "스톡 옵션"),
    "상속": ("상속",),
    "증여": ("증여", "수증"),
    "신탁": ("신탁",),
    "자사주 지급": ("자기주식", "자사주", "주식보상", "성과급", "상여"),
    "분할": ("분할", "병합"),
    "무상증자": ("무상증자", "무상신주", "주식배당", "무상 배정"),
}
OPEN_MARKET_BUY = "장내매수"


@dataclass(frozen=True)
class Verdict:
    """signal_type 이 있으면 성립. excluded 면 뺀 까닭. unknown 이면 모르는 까닭(판정 보류)."""

    signal_type: Optional[str] = None
    excluded: Optional[str] = None
    unknown: Optional[str] = None


@dataclass(frozen=True)
class InsiderTrade:
    rcept_no: str
    rcept_date: date
    person: str
    method: Optional[str]            # 원문에서 읽은 취득 방법 (못 읽었으면 None)
    qty: Optional[float]             # 증감 수 (+ 취득)
    change_rate: Optional[float]     # 지분 증감 비율 (%p)


def excluded_reason(text: Optional[str]) -> Optional[str]:
    for reason, words in EXCLUDE_KEYWORDS.items():
        if any(w in (text or "") for w in words):
            return reason
    return None


def _is_open_market_buy(t: InsiderTrade) -> bool:
    return bool(t.method) and OPEN_MARKET_BUY in t.method and (t.qty or 0) > 0


def classify_insider_trade(t: InsiderTrade, history: Sequence[InsiderTrade] = ()) -> Verdict:
    """임원 · 주요주주 1건 → KR-I1 성립 · 제외 · 모름.

    history = 같은 회사 같은 사람의 다른 접수 건. 이 건의 접수일 뒤 건은 무시한다 (막음 1).
    """
    if t.method is None:
        return Verdict(unknown="원문에서 취득 방법을 읽지 못함")
    why = excluded_reason(t.method)
    if why:
        return Verdict(excluded=why)
    if not _is_open_market_buy(t):
        return Verdict(excluded="장내매수 아님")
    if _repeat_small(t, history):
        return Verdict(excluded="같은 사람 같은 달 반복 소량")
    return Verdict(signal_type="KR-I1")


def _repeat_small(t: InsiderTrade, history: Sequence[InsiderTrade]) -> bool:
    if t.change_rate is None or abs(t.change_rate) >= REPEAT_SMALL_RATE_PCT:
        return False
    same_month = [
        h for h in history
        if h.person == t.person and h.rcept_no != t.rcept_no and h.rcept_date <= t.rcept_date
        and (h.rcept_date.year, h.rcept_date.month) == (t.rcept_date.year, t.rcept_date.month)
        and _is_open_market_buy(h) and excluded_reason(h.method) is None
    ]
    return len(same_month) + 1 >= REPEAT_MIN_COUNT


def kr_i2_date(trades: Sequence[InsiderTrade], as_of: date) -> Optional[date]:
    """as_of(진입 전날)까지 접수된 건만으로 KR-I2 성립 날짜 (서로 다른 2명 · 30일 안 · 둘째 사람 접수일)."""
    seen = [t for t in trades if t.rcept_date <= as_of]
    buys: list[tuple[str, date]] = []
    for t in seen:
        v = classify_insider_trade(t, [h for h in seen if h.rcept_date <= t.rcept_date])
        if v.signal_type == "KR-I1":
            buys.append((t.person, t.rcept_date))
    return kr_i2_establish_date(buys, I2_WINDOW_DAYS)


@dataclass(frozen=True)
class MajorFiling:
    rcept_no: str
    rcept_date: date
    person: str
    report_tp: str                   # 신규 · 변동 · 변경 (DART 보고 구분 글)
    report_resn: str                 # 보고 사유 글
    change_qty: Optional[float]
    purpose: Optional[str] = None    # management | simple | None(모름)


def classify_major_filing(f: MajorFiling) -> Verdict:
    """5% 공시 1건 → KR-M1(신규 · 경영 참가 목적) · KR-M2(보유 증가) · 제외 · 모름."""
    why = excluded_reason(f.report_resn)
    if why:
        return Verdict(excluded=why)
    if "신규" in f.report_tp:
        if f.purpose is None:
            return Verdict(unknown="보유 목적을 읽지 못함")
        if f.purpose == "management":
            return Verdict(signal_type="KR-M1")
        return Verdict(excluded="단순 투자 목적")
    if (f.change_qty or 0) > 0 and OPEN_MARKET_BUY in f.report_resn:
        return Verdict(signal_type="KR-M2")
    return Verdict(excluded="보유 증가 아님")


@dataclass(frozen=True)
class LaterItem:
    """진입 뒤에 접수된 같은 사람 · 같은 종목의 건 (정정 · 철회 · 매도 셈용)."""

    kind: str                        # amend | withdraw | sell | other
    rcept_date: date


def detect_report_kind(report_nm: Optional[str]) -> str:
    nm = report_nm or ""
    if "철회" in nm:
        return "withdraw"
    if "정정" in nm:
        return "amend"
    return "other"


def tally_later_events(entry_date: date, later: Sequence[LaterItem]) -> dict[str, int]:
    """진입 뒤 정정 · 철회 · 곧 매도 개수. 성립에서는 빼지 않고 성적표에 따로 보인다 (막음 1)."""
    out = {"amended": 0, "withdrawn": 0, "sold_soon": 0}
    for x in later:
        if x.rcept_date < entry_date:
            continue
        if x.kind == "amend":
            out["amended"] += 1
        elif x.kind == "withdraw":
            out["withdrawn"] += 1
        elif x.kind == "sell" and x.rcept_date - entry_date <= timedelta(days=SOLD_SOON_DAYS):
            out["sold_soon"] += 1
    return out
