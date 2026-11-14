"""1114-03 · 밈 알림 성적판 — 알림 뒤 결과를 토스 일봉으로 매일 쌓고 요약한다.

계획: docs/plans/meme-stock-discovery/08-alert-outcomes-plan-1114-03.md (검토 반영 · 사용자 결정 11/14)

원칙
- 단위 = (종목, 기준일) 의 첫 알림 하나. 기준일 = 알림이 쓴 종가 봉의 날짜.
- 진입 = 「첫 알림 시각 뒤에 처음 열리는 봉」의 시가. N일 수익률 = 진입 봉을 1번째로 세어 N번째 봉 종가 / 진입 시가 − 1.
- 정규장 마감(KR 15:30 KST · US 16:00 ET) 뒤의 봉만 쓴다 · 마감 전 봉은 쓰지 않는다.
- 수익률 칸은 비용 전 원값. 왕복 비용 0.25% 는 요약할 때 뺀다.
- 코스닥 비교는 행마다 같은 진입일 시가 · 같은 끝 날짜 종가로 짝지어 잰다 (국내 행만).
- 가격은 토스 일봉만 쓴다. 없으면 계산 불가 (다른 소스로 채우지 않음).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.services.broker_links import is_kr_code
from backend.services.outcomes import Bar, bar_on_or_before, parse_bars

logger = logging.getLogger(__name__)

# ── 상수 (사용자 결정 11/14 「계획대로」) ───────────────────────────────
START_DATE = date(2026, 7, 3)        # 이 날 이후 알림만 대상
COST = 0.0025                        # 왕복 비용 0.25% · 요약할 때 뺌
MIN_N = 30                           # 30건 미만 칸은 숫자를 숨김 (서버가 null)
UP_SHARE_MIN = 0.5                   # 순 5일 오른 비율 기준
MISSING_MAX = 0.10                   # 계산 불가·끊김 비율이 넘으면 판정 보류
HORIZONS = (1, 3, 5, 10)
MAX_BARS = 10                        # 진입 봉부터 10봉까지 채움
MAX_FAILS = 3                        # 토스에서 못 받기를 3회 겹치면 계산 불가
KRX_JUMP = 0.305                     # 이웃 봉 종가 변동이 ±30.5% 넘으면 계산 불가 (분할·상장 의심)
KRX_LIMIT = 0.30
KR_ALERT_CUTOFF = time(16, 10)       # 국내 알림 시각 기준: 16:10 전이면 전날 종가 기준으로 추정
MAX_SYMBOLS_PER_RUN = 900            # 한 번에 부를 종목 수 상한 (첫 실행 약 780 · 나머지는 다음 날)
INDEX_SYMBOL = "KOSDAQ"
VERDICT_HORIZON = 5

STATUSES = ("ok", "pending", "not_buyable", "no_trade", "broken", "unavailable")
FINAL = {"ok", "not_buyable", "no_trade", "broken", "unavailable"}
HAS_RET = {"ok", "pending", "broken"}   # 값이 남는 상태 (끊김은 값 남기고 끝)

_KST = ZoneInfo("Asia/Seoul")
_ET = ZoneInfo("America/New_York")
_TZ = {"KR": _KST, "US": _ET}
_OPEN = {"KR": time(9, 0), "US": time(9, 30)}
_CLOSE = {"KR": time(15, 30), "US": time(16, 0)}


# ── 시각 · 봉 도우미 ────────────────────────────────────────────────

def market_of(ticker: str, payload_market: Optional[str] = None) -> str:
    if payload_market:
        return "KR" if payload_market.upper() in ("KRX", "KR") else "US"
    return "KR" if is_kr_code(ticker.upper()) else "US"


def open_dt(market: str, d: date) -> datetime:
    return datetime.combine(d, _OPEN[market], tzinfo=_TZ[market])


def close_dt(market: str, d: date) -> datetime:
    return datetime.combine(d, _CLOSE[market], tzinfo=_TZ[market])


def closed_bars(bars: list[Bar], market: str, now_utc: datetime) -> list[Bar]:
    """정규장 마감이 지난 봉만."""
    return [b for b in bars if now_utc >= close_dt(market, b.d)]


def _prev_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def estimate_signal_date(market: str, triggered_at: datetime) -> date:
    """알림 시각(시간대 없음 · KST)으로 기준일을 추정한다 (payload·스냅샷이 없을 때만 · 휴장은 토스 봉으로 보정).

    국내: 16:10 전이면 전날. 미국: 현지(ET) 16:00 마감 전이면 전날.
    """
    kst = triggered_at.replace(tzinfo=_KST)
    if market == "KR":
        d = kst.date()
        if kst.time() < KR_ALERT_CUTOFF:
            d -= timedelta(days=1)
        return _prev_weekday(d)
    et = kst.astimezone(_ET)
    d = et.date()
    if et.time() < _CLOSE["US"]:
        d -= timedelta(days=1)
    return _prev_weekday(d)


def corrected_signal_date(bars: list[Bar], d: date) -> date:
    """추정한 기준일이 휴장일이면 (그 뒤 봉이 이미 있는데 그날 봉은 없으면) 직전 거래일로 보정."""
    if any(b.d == d for b in bars):
        return d
    if any(b.d > d for b in bars):
        prior = [b for b in bars if b.d < d]
        if prior:
            return prior[-1].d
    return d


# ── 국내 호가 · 상한가 ─────────────────────────────────────────────

def krx_tick(price: float) -> int:
    """2023 호가 단위 규칙 (주식)."""
    for limit, tick in ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100), (500_000, 500)):
        if price < limit:
            return tick
    return 1_000


def krx_upper_limit(prev_close: float) -> float:
    """상한가 = 전일 종가 × 1.30 을 호가 단위로 내림."""
    raw = prev_close * (1 + KRX_LIMIT)
    tick = krx_tick(raw)
    return math.floor(raw / tick + 1e-9) * tick


# ── 계산 (순수 함수) ────────────────────────────────────────────────

def _blank() -> dict[str, Any]:
    d: dict[str, Any] = {
        "prev_close": None, "signal_close": None, "signal_day_ret": None,
        "entry_date": None, "entry_open": None,
        "max_up": None, "max_down": None, "bars_after": 0,
    }
    for h in HORIZONS:
        d[f"ret_{h}d"] = None
        d[f"idx_ret_{h}d"] = None
    return d


def _result(status: str, note: Optional[str], base: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    out["status"] = status
    out["status_note"] = note
    return out


def compute_outcome(
    *,
    market: str,
    signal_date: date,
    first_alert_at: datetime,
    bars: list[Bar],
    index_bars: Optional[list[Bar]],
    ref_latest: Optional[date],
    now_utc: datetime,
) -> dict[str, Any]:
    """한 행의 결과를 계산한다. bars 는 날짜 오름차순 전체 (마감 전 봉 포함 가능).

    first_alert_at: 시간대 없는 서버 현지(KST) 시각.
    index_bars: 국내 행의 코스닥 일봉 (없으면 None → 지수 칸 비움).
    ref_latest: 끊김 판단용 기준 최신 거래일.
    """
    out = _blank()
    if not bars:
        return _result("unavailable", "토스 일봉 없음", out)
    if bars[0].d > signal_date:
        return _result("unavailable", "기준일 봉이 받은 일봉 범위 밖", out)

    closed = closed_bars(bars, market, now_utc)
    if any(b.d == signal_date for b in bars) and not any(b.d == signal_date for b in closed):
        return _result("pending", "기준일 봉이 아직 마감 전", out)
    sig = bar_on_or_before(closed, signal_date)
    if sig is None:
        return _result("unavailable", "기준일 봉 없음", out)
    if sig.d != signal_date and not any(b.d > signal_date for b in bars):
        return _result("pending", "기준일 봉이 아직 안 들어옴", out)

    idx_sig = [b for b in closed if b.d < sig.d]
    prev = idx_sig[-1] if idx_sig else None
    out["signal_close"] = sig.close
    if prev is not None:
        out["prev_close"] = prev.close
        out["signal_day_ret"] = sig.close / prev.close - 1 if prev.close else None

    alert_at = first_alert_at.replace(tzinfo=_KST)
    entry = next((b for b in closed if b.d > sig.d and open_dt(market, b.d) > alert_at), None)
    if entry is None:
        return _result("pending", "알림 뒤 처음 열리는 봉이 아직 없음", out)
    e_i = closed.index(entry)
    window = closed[e_i:e_i + MAX_BARS]
    out["entry_date"] = entry.d

    # 이웃 봉 종가 변동 (국내 · 분할·상장 의심)
    if market == "KR":
        span = [b for b in closed if sig.d <= b.d <= window[-1].d]
        for a, b in zip(span, span[1:]):
            if a.close and abs(b.close / a.close - 1) > KRX_JUMP:
                return _result("unavailable", "이웃 봉 종가 변동이 ±30.5% 넘음 (분할·상장 의심)", out)

    if not entry.open:
        return _result("unavailable", "진입 봉 시가 없음", out)
    out["entry_open"] = entry.open
    if entry.volume is not None and entry.volume == 0:
        return _result("no_trade", "진입 봉 거래 없음", out)
    if market == "KR":
        before_entry = closed[e_i - 1].close if e_i > 0 else None
        if before_entry and entry.open >= krx_upper_limit(before_entry):
            return _result("not_buyable", "시가가 상한가라 살 수 없음", out)

    out["bars_after"] = len(window)
    for h in HORIZONS:
        if len(window) >= h:
            out[f"ret_{h}d"] = window[h - 1].close / entry.open - 1
    out["max_up"] = max(b.high for b in window) / entry.open - 1
    out["max_down"] = min(b.low for b in window) / entry.open - 1

    if market == "KR" and index_bars:
        idx_by_d = {b.d: b for b in index_bars}
        ie = idx_by_d.get(entry.d)
        if ie is not None and ie.open:
            for h in HORIZONS:
                if len(window) >= h:
                    ib = idx_by_d.get(window[h - 1].d)
                    if ib is not None:
                        out[f"idx_ret_{h}d"] = ib.close / ie.open - 1

    if len(window) >= MAX_BARS:
        return _result("ok", None, out)
    if ref_latest is not None and closed[-1].d < ref_latest:
        return _result("broken", "봉이 끊김 (다른 종목보다 최신일이 앞섬)", out)
    return _result("pending", None, out)


# ── 요약 (순수 함수) ────────────────────────────────────────────────

V_COUNT = "판정 보류 · 건수 부족"
V_MISSING = "판정 보류 · 빠진 행 많음"
V_HIGHER = "지난 값에서 코스닥보다 높았음"
V_NONE = "없음 · 코스닥보다 낫다는 근거 없음"


def _g(r: Any, name: str) -> Any:
    return r.get(name) if isinstance(r, dict) else getattr(r, name, None)


def _net(r: Any, h: int) -> Optional[float]:
    v = _g(r, f"ret_{h}d")
    return None if v is None or _g(r, "status") not in HAS_RET else v - COST


def _cell(label: str, rows: list[Any], h: int) -> dict[str, Any]:
    vals = [(_net(r, h), _g(r, "max_down")) for r in rows]
    vals = [(v, md) for v, md in vals if v is not None]
    n = len(vals)
    if n < MIN_N:   # 30건 미만 칸은 숫자를 서버가 지운다
        return {"label": label, "n": n, "median": None, "up_share": None, "median_max_down": None}
    mds = [md for _, md in vals if md is not None]
    return {
        "label": label, "n": n,
        "median": median(v for v, _ in vals),
        "up_share": sum(1 for v, _ in vals if v > 0) / n,
        "median_max_down": median(mds) if mds else None,
    }


def _bucket_type(r: Any) -> str:
    t = _g(r, "alert_type")
    return {"ERUPTING": "상승 강도 알림", "BLAZING": "급등 전 단계 알림"}.get(t, "그 밖")


def _bucket_score(r: Any) -> str:
    s = _g(r, "score")
    if s is None:
        return "점수 없음"
    return "1.0 미만" if s < 1.0 else "1.0~1.2" if s < 1.2 else "1.2~1.5" if s < 1.5 else "1.5 이상"


def _bucket_day(r: Any) -> str:
    v = _g(r, "signal_day_ret")
    if v is None:
        return "등락 모름"
    p = v * 100
    return "10% 미만" if p < 10 else "10~20%" if p < 20 else "20~29%" if p < 29 else "29% 이상"


def _bucket_era(r: Any) -> str:
    # 1114-02 배포 뒤에 저장된 알림만 발송 결과(send_result)가 payload 에 있다
    return "11/14 알림 고침 뒤" if _g(r, "send_result") is not None else "11/14 알림 고침 전"


def _bucket_market(r: Any) -> str:
    return "국내" if _g(r, "market") == "KR" else "미국"


def _bucket_send(r: Any) -> str:
    s = _g(r, "send_result")
    return "보냄" if s == "sent" else "안 보냄(건너뜀·대기)" if s in ("skipped", "queued") else "기록 없음(옛 알림)"


_BREAKDOWNS = (
    ("type", "알림 종류", _bucket_type, ("상승 강도 알림", "급등 전 단계 알림", "그 밖")),
    ("score", "급등 전 단계 점수", _bucket_score, ("1.0 미만", "1.0~1.2", "1.2~1.5", "1.5 이상", "점수 없음")),
    ("day", "알림 기준일의 하루 등락", _bucket_day, ("10% 미만", "10~20%", "20~29%", "29% 이상", "등락 모름")),
    ("era", "11/14 알림 고침 전과 뒤", _bucket_era, ("11/14 알림 고침 전", "11/14 알림 고침 뒤")),
    ("market", "시장", _bucket_market, ("국내", "미국")),
    ("send", "텔레그램 발송 여부", _bucket_send, ("보냄", "안 보냄(건너뜀·대기)", "기록 없음(옛 알림)")),
)


def verdict_of(rows: list[Any]) -> dict[str, Any]:
    """국내 · 순 5일 · 행마다 짝지은 코스닥 값 비교. 규칙은 계획서 「계산 규칙 · API」 + 검토 반영."""
    h = VERDICT_HORIZON
    kr = [r for r in rows if _g(r, "market") == "KR"]
    den = [r for r in kr if _g(r, "status") != "pending" or _g(r, f"ret_{h}d") is not None]
    missing = sum(1 for r in den if _g(r, "status") in ("unavailable", "broken"))
    share = missing / len(den) if den else None
    paired = [r for r in kr if _net(r, h) is not None and _g(r, f"idx_ret_{h}d") is not None]
    n = len(paired)
    info: dict[str, Any] = {
        "horizon": h, "n_paired": n, "missing": missing, "denominator": len(den), "missing_share": share,
        "net_median": None, "kosdaq_median": None, "up_share": None,
        "min_n": MIN_N, "missing_max": MISSING_MAX, "up_share_min": UP_SHARE_MIN,
    }
    if n < MIN_N:
        return {**info, "code": "hold_count", "label": V_COUNT}
    nets = [_net(r, h) for r in paired]
    idxs = [_g(r, f"idx_ret_{h}d") for r in paired]
    info["net_median"] = median(nets)
    info["kosdaq_median"] = median(idxs)
    info["up_share"] = sum(1 for v in nets if v > 0) / n
    if share is not None and share > MISSING_MAX:
        return {**info, "code": "hold_missing", "label": V_MISSING}
    if info["net_median"] > info["kosdaq_median"] and info["up_share"] > UP_SHARE_MIN:
        return {**info, "code": "higher", "label": V_HIGHER}
    return {**info, "code": "none", "label": V_NONE}


def summarize_outcomes(rows: list[Any], horizon: int = 5, now: Optional[datetime] = None) -> dict[str, Any]:
    """성적판 요약. 30건 미만 칸의 숫자는 null · 모든 값은 지난 값 (추정 · 보장 아님)."""
    h = horizon
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        s = _g(r, "status")
        if s in counts:
            counts[s] += 1
    with_ret = [r for r in rows if _net(r, h) is not None]
    dates = [_g(r, "signal_date") for r in rows if _g(r, "signal_date") is not None]
    paired = [r for r in with_ret if _g(r, "market") == "KR" and _g(r, f"idx_ret_{h}d") is not None]

    overall = _cell("전체", rows, h)
    n_paired = len(paired)
    overall["n_paired"] = n_paired
    if n_paired >= MIN_N:
        diffs = [_net(r, h) - _g(r, f"idx_ret_{h}d") for r in paired]
        overall["diff_vs_kosdaq"] = median(diffs)
        kos = {"median": median(_g(r, f"idx_ret_{h}d") for r in paired), "n": n_paired}
    else:
        overall["diff_vs_kosdaq"] = None
        kos = {"median": None, "n": n_paired}

    breakdowns = []
    for key, title, fn, order in _BREAKDOWNS:
        cells = [_cell(lab, [r for r in rows if fn(r) == lab], h) for lab in order]
        breakdowns.append({"key": key, "title": title, "cells": cells})

    return {
        "as_of": (now or datetime.now(timezone.utc)).isoformat(),
        "horizon": h,
        "cost": COST,
        "period": {
            "start": min(dates).isoformat() if dates else None,
            "end": max(dates).isoformat() if dates else None,
            "distinct_dates": len({_g(r, "signal_date") for r in with_ret}),
            "alerts": len(rows),
        },
        "kosdaq": kos,
        "verdict": verdict_of(rows),
        "status_counts": counts,
        "overall": overall,
        "breakdowns": breakdowns,
        "notes": [
            "설명용 값입니다. 지난 값 · 추정 · 보장 아님.",
            "수익률은 알림 뒤 처음 열린 봉의 시가에서 잰 값이고 왕복 비용 0.25% 를 뺀 값입니다.",
            "코스닥 비교는 국내 알림만, 같은 진입일 시가 · 같은 끝 날짜 종가로 짝지어 쟀습니다. 미국은 비교 지수가 없습니다.",
            f"{MIN_N}건 미만 칸은 숫자를 숨깁니다.",
        ],
    }


def recent_rows(rows: list[Any]) -> list[dict[str, Any]]:
    def f(r: Any, name: str):
        v = _g(r, name)
        return v.isoformat() if isinstance(v, (date, datetime)) else v

    out = []
    for r in rows:
        item = {
            "signal_date": f(r, "signal_date"), "ticker": _g(r, "ticker"), "market": _g(r, "market"),
            "alert_type": _g(r, "alert_type"), "score": _g(r, "score"),
            "signal_day_ret": _g(r, "signal_day_ret"), "entry_date": f(r, "entry_date"),
            "entry_open": _g(r, "entry_open"), "send_result": _g(r, "send_result"),
            "max_up": _g(r, "max_up"), "max_down": _g(r, "max_down"),
            "status": _g(r, "status"), "status_note": _g(r, "status_note"),
            "bars_after": _g(r, "bars_after"),
        }
        for h in HORIZONS:
            item[f"ret_{h}d"] = _net(r, h)   # 비용 뺀 값
        out.append(item)
    return out


# ── DB 실행 ─────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_table() -> None:
    """이 표만 만든다 (멱등)."""
    from backend.services.db import engine
    from backend.services.models import MemeAlertOutcome

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: MemeAlertOutcome.__table__.create(c, checkfirst=True))


async def _load_groups(session, since: datetime) -> dict[tuple[str, date], dict[str, Any]]:
    """알림 이력을 (종목, 기준일) 로 묶는다 · 기준일: payload.bar_date → 직전 스냅샷 → 알림 시각."""
    from backend.discovery.meme_watch.alert import _snapshot_base_date
    from backend.services.models import MemeAlertHistory, MemeVolumeSnapshot

    alerts = (await session.execute(
        select(MemeAlertHistory).where(MemeAlertHistory.triggered_at >= since).order_by(MemeAlertHistory.triggered_at, MemeAlertHistory.id)
    )).scalars().all()
    groups: dict[tuple[str, date], dict[str, Any]] = {}
    for a in alerts:
        try:
            pl = json.loads(a.payload or "{}")
        except (ValueError, TypeError):
            pl = {}
        if not isinstance(pl, dict):
            pl = {}
        market = market_of(a.ticker, pl.get("market"))
        sd: Optional[date] = None
        if pl.get("bar_date"):
            try:
                sd = date.fromisoformat(pl["bar_date"])
            except ValueError:
                sd = None
        if sd is None:
            snap = (await session.execute(
                select(MemeVolumeSnapshot.snapshot_at, MemeVolumeSnapshot.bar_date)
                .where(MemeVolumeSnapshot.ticker == a.ticker, MemeVolumeSnapshot.snapshot_at <= a.triggered_at)
                .order_by(MemeVolumeSnapshot.snapshot_at.desc()).limit(1)
            )).first()
            if snap is not None:
                sd = snap[1] or _snapshot_base_date(snap[0], "KRX" if market == "KR" else "US")
        if sd is None:
            sd = estimate_signal_date(market, a.triggered_at)
        if sd < START_DATE:
            continue
        g = groups.setdefault((a.ticker, sd), {"alerts": []})
        g["alerts"].append((a, pl, market))
    return groups


async def run_meme_outcomes(
    client=None, now: Optional[datetime] = None, max_symbols: int = MAX_SYMBOLS_PER_RUN,
) -> dict[str, Any]:
    """알림 이력 → 성적 장부. 끝난 행은 다시 부르지 않고 · 미완 행만 이어 채운다 · 요약 (건수만) 을 돌려준다.

    now: 시험용 현재 시각 (시간대 있는 UTC). 첫 실행은 7/03 부터 모두 채운다 (한 번에 max_symbols 종목까지).
    """
    from backend.services.db import get_session
    from backend.services.models import MemeAlertOutcome

    if client is None:
        from backend.execution.brokers.toss_client import get_toss_client

        client = get_toss_client()
    now = now or _utcnow()
    await ensure_table()
    summary: dict[str, Any] = {"new": 0, "fetched": 0, "failed": 0, "deferred": 0, "index": "skip"}
    all_failed = False

    async with get_session() as session:
        groups = await _load_groups(session, datetime.combine(START_DATE, time()))
        existing = (await session.execute(select(MemeAlertOutcome))).scalars().all()
        by_key = {(r.ticker, r.signal_date): r for r in existing}
        known_first_ids = {r.first_alert_id for r in existing if r.first_alert_id is not None}

        for (ticker, sd), g in groups.items():
            first, pl, market = g["alerts"][0]
            row = by_key.get((ticker, sd))
            if row is not None:
                if row.status not in FINAL:
                    row.alerts_same_day = len(g["alerts"])
                continue
            if first.id in known_first_ids:   # 휴장 보정으로 기준일이 바뀐 행
                continue
            row = MemeAlertOutcome(
                user_id=first.user_id or "owner", ticker=ticker, market=market, signal_date=sd,
                first_alert_id=first.id, first_alert_at=first.triggered_at, alert_type=first.alert_type,
                alerts_same_day=len(g["alerts"]), score=pl.get("score"), intensity=pl.get("intensity"),
                send_result=pl.get("send_result"), status="pending", fail_count=0, bars_after=0,
            )
            session.add(row)
            by_key[(ticker, sd)] = row
            summary["new"] += 1

        pending = [r for r in by_key.values() if r.status == "pending"]
        symbols = sorted({r.ticker for r in pending})
        if len(symbols) > max_symbols:
            summary["deferred"] = len(symbols) - max_symbols
            symbols = symbols[:max_symbols]
        sym_set = set(symbols)
        pending = [r for r in pending if r.ticker in sym_set]

        # 국내 비교 지수 (한 번) · 실패하면 지수 칸만 비움
        index_bars: Optional[list[Bar]] = None
        if any(r.market == "KR" for r in pending):
            try:
                index_bars = parse_bars(await asyncio.to_thread(client.indicator_candles, INDEX_SYMBOL, 200)) or None
            except Exception as exc:  # noqa: BLE001
                logger.warning("[meme_outcomes] 코스닥 일봉 실패 · %s", type(exc).__name__)
                index_bars = None
            summary["index"] = "ok" if index_bars else "failed"

        bars_by: dict[str, list[Bar]] = {}
        failed: set[str] = set()
        for sym in symbols:
            try:
                bars = parse_bars(await asyncio.to_thread(client.candles, sym, 200))
            except Exception as exc:  # noqa: BLE001 — 토스에 없는 종목 등
                logger.warning("[meme_outcomes] 일봉 없음 %s · %s", sym, type(exc).__name__)
                bars = []
            if bars:
                bars_by[sym] = bars
            else:
                failed.add(sym)
        summary["fetched"] = len(bars_by)
        summary["failed"] = len(failed)
        if symbols and len(failed) == len(symbols):
            all_failed = True

        kr_index_closed = closed_bars(index_bars, "KR", now) if index_bars else []
        ref_kr = kr_index_closed[-1].d if kr_index_closed else None
        us_syms = {r.ticker for r in pending if r.market == "US"}
        us_lasts = [cb[-1].d for sym, b in bars_by.items()
                    if sym in us_syms and (cb := closed_bars(b, "US", now))]
        ref_us = max(us_lasts) if us_lasts else None
        naive_now = now.astimezone(timezone.utc).replace(tzinfo=None)

        for r in pending:
            if r.ticker in failed:
                r.fail_count = (r.fail_count or 0) + 1
                if r.fail_count >= MAX_FAILS:
                    r.status, r.status_note = "unavailable", "토스 일봉을 3회 받지 못함"
                else:
                    r.status_note = f"토스 일봉 못 받음 ({r.fail_count}회)"
                continue
            bars = bars_by[r.ticker]
            new_sd = corrected_signal_date(bars, r.signal_date)
            if new_sd != r.signal_date:
                if (r.ticker, new_sd) in by_key:
                    r.status, r.status_note = "unavailable", "기준일이 휴장일로 추정되나 앞 행과 겹침"
                    continue
                by_key.pop((r.ticker, r.signal_date), None)
                r.signal_date = new_sd
                by_key[(r.ticker, new_sd)] = r
            res = compute_outcome(
                market=r.market, signal_date=r.signal_date, first_alert_at=r.first_alert_at,
                bars=bars, index_bars=index_bars if r.market == "KR" else None,
                ref_latest=ref_kr if r.market == "KR" else ref_us, now_utc=now,
            )
            if res["status"] == "ok" and r.market == "KR" and index_bars is None:
                res["status"], res["status_note"] = "pending", "코스닥 값을 못 받아 다음 실행에서 다시 채움"
            for k, v in res.items():
                setattr(r, k, v)
            r.fail_count = 0
            r.computed_at = naive_now

        summary["by_status"] = {s: sum(1 for r in by_key.values() if r.status == s) for s in STATUSES}

    if all_failed:
        raise RuntimeError(f"토스 일봉 조회가 {len(symbols)}종목 모두 실패")
    logger.info("[meme_outcomes] %s", summary)
    return summary
