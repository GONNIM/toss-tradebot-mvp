"""자동 초안 · 계획서 10절 (v4 7절 · 남은 문제 7 고침).

- 실행 조건: 최신 레이더 파일 이름(`radar_v1_3_YYYYMMDD.csv`)의 날짜가 오늘(KST)일 때. 파일 수정 시각 · radar.json 의
  `generated` 는 쓰지 않는다.
- 첫 시도는 07:15, 이어서 10분 간격 최대 6번(07:15 · 07:25 · 07:35 · 07:45 · 07:55 · 08:05). 그때까지 없으면
  그날 초안 없음 + 시스템 경고 1건.
- 대상: 레이더 후보 또는 대표가 지정한 종목 중 진입 창이 7일 안에 열리거나 이미 열린 것.
  제외: 상장폐지 · 인수 완료 · 합병 진행 · 거래 정지 · 같은 종목 열린 계획.
  경고 줄: 계속기업 의문 · 최저가 미달 · 최근 30일 증자. 판정 자료가 없으면 「자료 없음 → 경고 줄」(추측하지 않음).
- 촉매 날짜 우선순위: 대표 입력 > 회사 8-K · 보도자료(신뢰도 표시) > 임상시험 등록부(「추정」). 범위만 있으면 중간점
  (1분기 2/15 · 상반기 4/1 · 하반기 10/1 · 4분기 11/15). 진입 창 = 촉매 −30일 ~ +14일, 확정 발표는 5거래일 전 마감.
- 값은 6절 규칙 · 값마다 근거 한 줄. 대표는 초안에서 예산 · 매수가 · TP1 · 손절 폭만 바꾸고 「사용자 수정」으로 표시.
- 초안은 매일 다시 계산(사용자 수정 값 유지) · 진입 창이 닫히면 만료. 승인된 계획은 다시 계산하지 않는다.
- 알림: 「바이오」 범주 1건 요약 (종목 이름 · 진입 창 날짜 · 경고만 · 금액 없음).

[자료 연결] 촉매 날짜 · 제외 판정 · 경고 판정 · 기준가의 출처는 `CandidateLoader` 로 받는다. 이 저장소에는 상장폐지 ·
증자 · 계속기업 판정을 한 번에 주는 출처가 없어 기본 로더는 모두 「자료 없음」을 돌려준다(경고 줄로 남고 추측하지 않음).
후보 종목은 레이더 파일의 ticker 열과 대표 지정 목록에서 읽는다.
"""
from __future__ import annotations

import csv
import inspect
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import sessions as sess
from .pricing import D, buy_order, buy_watch, qty_for_budget, sell_watch

_KST = timezone(timedelta(hours=9))
RADAR_RE = re.compile(r"^radar_v1_3_(\d{8})\.csv$")
ATTEMPT_TIMES = ((7, 15), (7, 25), (7, 35), (7, 45), (7, 55), (8, 5))
MAX_ATTEMPTS = len(ATTEMPT_TIMES)


def radar_dirs() -> list:
    """레이더 파일을 찾는 폴더 목록. 기존 바이오 규칙(BIOTECH_RUNTIME_DIR > docs > backend/data)을 화면과 똑같이 쓴다.
    PLAN_RADAR_DIR 은 시험용 덮어쓰기(설정하면 그 폴더 하나만)."""
    import os

    raw = os.environ.get("PLAN_RADAR_DIR")
    if raw:
        return [Path(raw)]
    try:
        from backend.api.routes import biotech as bt

        return list(bt._search_dirs("candidates"))
    except Exception:  # noqa: BLE001
        return []


def radar_dir() -> list:
    """옛 이름 · radar_dirs 와 같다."""
    return radar_dirs()


def _dirs(directory) -> list:
    if directory is None:
        return []
    return [directory] if isinstance(directory, Path) else list(directory)


def latest_radar_date(directory) -> Optional[date]:
    """파일 이름의 날짜만 본다 (폴더 하나 또는 목록)."""
    best: Optional[date] = None
    for d in _dirs(directory):
        if not d.is_dir():
            continue
        for f in d.iterdir():
            m = RADAR_RE.match(f.name)
            if m:
                try:
                    day = datetime.strptime(m.group(1), "%Y%m%d").date()
                except ValueError:
                    continue
                best = day if best is None or day > best else best
    return best


def today_kst(now_utc: Optional[datetime] = None) -> date:
    n = now_utc or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(_KST).date()


def radar_ready(directory, today: date) -> bool:
    """어제 날짜 · 파일 없음이면 False (초안을 만들지 않는다)."""
    return latest_radar_date(directory) == today


def attempt_number(now_kst: datetime) -> Optional[int]:
    """지금 시각이 몇 번째 시도 시각인가(1~6). 시각이 아니면 None."""
    for i, (h, m) in enumerate(ATTEMPT_TIMES, start=1):
        if (now_kst.hour, now_kst.minute) == (h, m):
            return i
    return None


def radar_symbols(directory, today: date) -> list[str]:
    """오늘 날짜 레이더 파일의 ticker 열 (없으면 빈 목록) · 폴더가 여럿이면 먼저 찾은 파일."""
    for d in _dirs(directory):
        f = d / f"radar_v1_3_{today:%Y%m%d}.csv"
        if not f.exists():
            continue
        try:
            with f.open(encoding="utf-8", newline="") as fh:
                return [r["ticker"].strip().upper() for r in csv.DictReader(fh) if (r.get("ticker") or "").strip()]
        except (OSError, KeyError, UnicodeDecodeError):
            return []
    return []


# ─── 촉매 날짜 · 진입 창 ─────────────────────────────────────────

_RANGE_MID = {"Q1": (2, 15), "H1": (4, 1), "H2": (10, 1), "Q4": (11, 15)}   # 1분기 · 상반기 · 하반기 · 4분기 중간점
_SOURCE_RANK = {"user": 0, "company": 1, "registry": 2}
_SOURCE_LABEL = {"user": "대표 입력", "company": "회사 8-K · 보도자료", "registry": "임상시험 등록부(추정)"}


@dataclass(frozen=True)
class CatalystInput:
    source: str                         # user | company | registry
    day: Optional[date] = None          # 확정 날짜
    range_label: Optional[str] = None   # Q1 | H1 | H2 | Q4 (범위만 있을 때)
    year: Optional[int] = None
    confidence: str = ""                # 회사 자료의 신뢰도 표시


@dataclass(frozen=True)
class Catalyst:
    day: date
    source: str
    confirmed: bool                     # 날짜가 확정(범위 중간점 · 등록부 추정이 아님)
    basis: str                          # 근거 한 줄


def resolve_catalyst(inputs: list[CatalystInput]) -> Optional[Catalyst]:
    """우선순위 대표 > 회사 > 등록부. 같은 출처 안에서는 확정 날짜가 범위보다 앞. 범위만 있으면 중간점."""
    def key(c: CatalystInput):
        return (_SOURCE_RANK.get(c.source, 9), 0 if c.day else 1)

    for c in sorted(inputs, key=key):
        if c.day is not None:
            conf = f" · 신뢰도 {c.confidence}" if c.confidence else ""
            est = c.source == "registry"
            return Catalyst(c.day, c.source, confirmed=not est,
                            basis=f"촉매 날짜 = {_SOURCE_LABEL[c.source]}{conf} {c.day.isoformat()}")
        if c.range_label in _RANGE_MID and c.year:
            m, d = _RANGE_MID[c.range_label]
            return Catalyst(date(c.year, m, d), c.source, confirmed=False,
                            basis=f"촉매 날짜 = {_SOURCE_LABEL[c.source]}의 범위({c.range_label}) 중간점 {c.year}-{m:02d}-{d:02d}")
    return None


@dataclass(frozen=True)
class EntryWindow:
    opens: date
    ends: date
    close_on: date            # 마감일 (확정 발표는 5거래일 전 · 추정은 창 끝)


def _sub_trading_days(d: date, n: int, holidays: frozenset) -> date:
    k = 0
    while k < n:
        d -= timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            k += 1
    return d


def entry_window(cat: Catalyst, holidays: frozenset = frozenset()) -> EntryWindow:
    opens, ends = cat.day - timedelta(days=30), cat.day + timedelta(days=14)
    close = _sub_trading_days(cat.day, 5, holidays) if cat.confirmed else ends
    return EntryWindow(opens, ends, close)


def window_relevant(w: EntryWindow, today: date) -> bool:
    """진입 창이 7일 안에 열리거나 이미 열렸고 아직 닫히지 않았다."""
    return w.opens <= today + timedelta(days=7) and today <= w.ends


# ─── 제외 · 경고 ────────────────────────────────────────────────

EXCLUDE_FLAGS = (("delisted", "상장폐지"), ("acquired", "인수 완료"), ("merger_pending", "합병 진행"), ("halted", "거래 정지"))
WARN_FLAGS = (("going_concern", "계속기업 의문"), ("below_min_price", "최저가 미달"), ("offering_30d", "최근 30일 증자"))


def judge_flags(flags: dict) -> tuple[list[str], list[str]]:
    """(제외 사유, 경고 줄). 제외 항목은 True 일 때만 제외 · 값이 없으면(자료 없음) 제외하지 않고 경고 줄."""
    excl, warn = [], []
    for k, label in EXCLUDE_FLAGS:
        v = flags.get(k)
        if v is True:
            excl.append(label)
        elif v is None:
            warn.append(f"자료 없음 · {label} 여부 확인 못 함")
    for k, label in WARN_FLAGS:
        v = flags.get(k)
        if v is True:
            warn.append(label)
        elif v is None:
            warn.append(f"자료 없음 · {label} 여부 확인 못 함")
    return excl, warn


# ─── 초안 값 · 근거 한 줄 ─────────────────────────────────────────

def build_draft_params(*, ref_price, budget_usd, announce_at: datetime, entry_close_at: datetime,
                       entry_window_end: datetime, wide: bool = False, tp1_pct=None) -> dict:
    """후보 값 → 초안 값 (6절 규칙 · D7 사다리 기본 −3·−5·−7%). 넓은 폭은 「제안」으로만 쓴다(기본 아님)."""
    watch = buy_watch(ref_price)
    order = buy_order(ref_price)
    out = {
        "budget_usd": float(budget_usd),
        "buy_watch": float(watch),
        "buy_order": float(order),
        "qty": qty_for_budget(budget_usd, order),
        "ladder_pcts": [float(x) for x in (sess.WIDE_LADDER_PCTS if wide else sess.DEFAULT_LADDER_PCTS)],
        "announce_at": announce_at.isoformat(),
        "entry_close_at": entry_close_at.isoformat(),
        "entry_window_end": entry_window_end.isoformat(),
    }
    if tp1_pct is not None:
        tp = sell_watch(D(order) * (1 + D(tp1_pct)))
        out["tp1_watch"], out["tp1_order"] = float(tp), float(tp)
    return out


def rationale_lines(*, ref_price, budget_usd, tp1_pct, params: dict) -> dict:
    r = {
        "buy_watch": f"매수 감시가 = 기준가 {ref_price} 를 가격 단위로 내림 (6절)",
        "buy_order": "매수 주문가 = 감시가와 같음 (내림 · 6절)",
        "qty": "수량 = 예산 ÷ (매수가 × 1.001) 을 6 의 배수로 내림 (6절)" if budget_usd
        else "예산 미정 · 대표 입력 필요 (수량 0)",
        "ladder_pcts": "손절 사다리 = 평균가 −3 · −5 · −7% (기본 폭 · D7)",
    }
    if "tp1_watch" in params:
        r["tp1_watch"] = f"TP1 = 매수가 × (1 + {tp1_pct}) 올림"
    return r


CandidateLoader = Callable[[str], dict]


def no_data_loader(symbol: str) -> dict:
    """기본 로더 · 이 저장소에 판정 출처가 없어 모두 「자료 없음」."""
    return {"catalysts": [], "flags": {}, "ref_price": None, "budget_usd": None, "tp1_pct": None}


@dataclass
class DraftDecision:
    symbol: str
    action: str                                   # create | update | exclude | skip
    reasons: list = field(default_factory=list)   # 제외 사유 (exclude)
    warnings: list = field(default_factory=list)  # 경고 줄
    window: Optional[EntryWindow] = None
    params: Optional[dict] = None


def decide(symbol: str, data: dict, today: date, *, open_plan: bool = False,
           holidays: frozenset = frozenset()) -> DraftDecision:
    """한 종목의 초안 판단 (순수 함수). 제외 > 촉매 없음 > 창 밖 > 초안 값 순."""
    if open_plan:
        return DraftDecision(symbol, "exclude", reasons=["같은 종목 열린 계획"])
    excl, warn = judge_flags(data.get("flags") or {})
    if excl:
        return DraftDecision(symbol, "exclude", reasons=excl, warnings=warn)
    cat = resolve_catalyst(data.get("catalysts") or [])
    if cat is None:
        return DraftDecision(symbol, "skip", warnings=warn + ["자료 없음 · 촉매 날짜 확인 못 함 · 초안을 만들지 않음"])
    w = entry_window(cat, holidays)
    if not window_relevant(w, today):
        return DraftDecision(symbol, "skip", window=w, warnings=warn)
    ref, budget = data.get("ref_price"), data.get("budget_usd")
    if ref is None:
        return DraftDecision(symbol, "skip", window=w, warnings=warn + ["자료 없음 · 기준가 확인 못 함 · 초안을 만들지 않음"])
    if not cat.confirmed:
        warn = warn + [f"촉매 날짜는 추정입니다 ({_SOURCE_LABEL[cat.source]})"]
    at = lambda d: datetime(d.year, d.month, d.day, 21, 0)    # noqa: E731 · 미국 정규장 끝 무렵(UTC 21시 · 근사)
    params = build_draft_params(ref_price=ref, budget_usd=budget or 0, announce_at=at(cat.day),
                                entry_close_at=at(w.close_on), entry_window_end=at(w.ends), tp1_pct=data.get("tp1_pct"))
    params["rationale"] = {
        "catalyst": cat.basis,
        "window": f"진입 창 = 촉매 −30일 ~ +14일 ({w.opens} ~ {w.ends}) · "
                  + ("확정 발표라 5거래일 전 마감" if cat.confirmed else "추정 날짜라 창 끝에 마감"),
        **rationale_lines(ref_price=ref, budget_usd=budget, tp1_pct=data.get("tp1_pct"), params=params),
    }
    params["warnings"] = warn
    return DraftDecision(symbol, "create", warnings=warn, window=w, params=params)


def build_summary(decisions: list, expired: list) -> Optional[tuple[str, str]]:
    """「바이오」 범주 1건 요약 (제목 · 본문) · 바뀐 것이 없으면 None. 금액은 적지 않는다."""
    made = [d for d in decisions if d.action in ("create", "update")]
    excl = [d for d in decisions if d.action == "exclude"]
    if not made and not excl and not expired:
        return None
    lines = []
    for d in made:
        w = d.window
        lines.append(f"{d.symbol} · 진입 창 {w.opens} ~ {w.ends}" + (f" · 경고 {len(d.warnings)}건" if d.warnings else ""))
    if excl:
        lines.append("제외: " + ", ".join(f"{d.symbol}({'/'.join(d.reasons)})" for d in excl))
    if expired:
        lines.append("만료: " + ", ".join(expired))
    return f"자동 초안 {len(made)}건", "\n".join(lines) + "\n승인은 대표가 계획 화면에서 합니다."


async def run_draft_cycle(s, eng, *, today: date, symbols: list, loader: CandidateLoader = no_data_loader,
                          mode: str = "live", holidays: frozenset = frozenset()):
    """매일 다시 계산: 새 초안 만들기 · 기존 초안 다시 계산(사용자 수정 값 유지) · 창이 닫힌 초안 만료.
    승인된 계획(DRAFT 가 아닌 것)은 건드리지 않는다. 반환: (판단 목록, 만료된 종목)."""
    from sqlalchemy import select

    from . import sizing, state
    from .engine import params_of, parse_dt, set_params
    from .models import Plan

    decisions: list[DraftDecision] = []
    expired: list[str] = []
    existing = {p.symbol: p for p in await s.scalars(select(Plan).where(Plan.source == "draft", Plan.state == state.DRAFT))}
    for sym, plan in list(existing.items()):                        # 만료: 창이 닫힌 초안
        end = params_of(plan).get("entry_window_end")
        if end and parse_dt(end).date() < today:
            await state.transition(s, plan, state.CANCELLED, reason="진입 창 닫힘 · 초안 만료")
            expired.append(sym)
            existing.pop(sym)
    for sym in sorted(set(symbols) | set(existing)):
        plan = existing.get(sym)
        data = loader(sym)
        if inspect.isawaitable(data):
            data = await data
        d = decide(sym, data, today, open_plan=await sizing.open_plan_exists(s, sym), holidays=holidays)
        if d.action == "create" and plan is not None:
            cur = params_of(plan)
            keep = set(cur.get("user_edited") or [])
            new = {k: v for k, v in d.params.items() if k not in keep}
            if "budget_usd" in keep and "qty" not in keep:           # 대표가 예산을 바꿨으면 그 예산으로 수량 다시 계산
                new["qty"] = qty_for_budget(cur["budget_usd"], new.get("buy_order", cur.get("buy_order", 0)))
            await eng.update_draft(s, plan, new, by_user=False)
            pp = params_of(plan)
            pp["warnings"], pp["rationale"] = d.params["warnings"], d.params["rationale"]
            set_params(plan, pp)
            d.action = "update"
        elif d.action == "create":
            await eng.create_draft(s, symbol=sym, mode=mode, params=d.params, source="draft")
        elif plan is not None and d.action == "exclude":      # 자료가 잠깐 비었다고(skip) 대표가 고친 초안을 지우지 않는다
            await state.transition(s, plan, state.CANCELLED,
                                   reason="초안 대상에서 빠짐: " + "/".join(d.reasons or d.warnings)[:150])
            expired.append(sym)
        decisions.append(d)
    return decisions, expired
