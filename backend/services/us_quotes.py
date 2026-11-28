"""1128-01 ㉣ · 미국 비후보 종목 상세 가격 · 전문가 의견 칸 (관리자 전용 · 표시 전용 · 야후).

사용자 결정 (2026-11-28): 「㉣ 적용」 — 바이오 후보가 아닌 미국 종목의 상세 화면에도 가격 칸을 보인다.
Fable 조건부 GO (docs/plans/biotech/fable-bundles/2026-11-28-1128-01-us-scope.md · 막음 ㄱ~ㄹ · 권고 ㅁ~ㅊ).

지키는 것
- 허용 기호만 (ㄴ): 아래 ALLOWED_SOURCES 에 적은 저장 표에 이미 있는 미국 기호 모양만. 그 밖은 바깥 호출 0.
- 야후는 이 관리자 요청이 올 때만 부른다 (ㄹ ⑤: 공개 GET /stock/{ticker} 는 이 모듈의 받기 함수를 부르지 않는다).
  받기는 DB 세션 밖에서 (1102-08) · 기호별 잠금 + 전체 잠금 하나 + 받기 사이 1초 이상 · 짧은 제한 시간(20초).
- 같은 기호는 미국 동부 거래일 하루에 한 번만 · 하루 50종목 상한은 us_quote_day 의 그날 행 수로 센다 (메모리 숫자 아님 · 실패 행도 셈).
- 다른 야후 잡 시간대(KST 06:00~06:45 · 화~토 07:00~09:30)에는 새로 받지 않고 저장 값만. 야후가 429 를 주면 그날 화면 쪽 받기를 멈춘다.
- 종가 · 거래량 · 날짜는 일봉에서 「끝난 마지막 거래일」 값 (ㄷ) · 장중 값(currentPrice)을 종가로 쓰지 않는다.
- AI 요약 없음 · 네이버 실시간 없음 (바이오 후보는 바이오 길 /biotech/quote 를 그대로 쓴다 · 권고 ㅁ).
- 표시만: 점수 · 순위 · 후보 선정 · 경보 · 알림에 쓰지 않는다. 자체 계산은 하지 않는다 (평균 거래량도 야후 값 그대로).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from backend.services.models import UsQuoteClose, UsQuoteDay

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")

DAILY_TICKER_CAP = 50        # 하루(미국 동부 거래일) 새로 받는 종목 상한 · us_quote_day 그날 행 수로 셈
FETCH_TIMEOUT = 20.0         # 화면 요청용 짧은 제한 (권고 ㅈ) · 6년치 첫 받기가 넘기면 실패 행으로 남김
MIN_GAP_SEC = 1.0            # 야후 받기 사이 최소 간격 (전체 공통)
KEEP_DAYS = 30               # 보존 · 이 날짜 수가 지난 조회 행 · 그 종목에 행이 안 남은 일봉을 지움
CLOSE_CUTOFF = (16, 30)      # 미국 동부 16:30 이후에야 그날 봉을 끝난 봉으로 본다 (정규장 마감 16:00 + 여유)
AVG_NOTE = "야후가 준 평균 거래량 값 그대로"

# 다른 야후 잡이 도는 시간 (KST · 막음 ㄹ ③) · (요일 집합 | None=매일, 시작 분, 끝 분)
_BLOCK_WINDOWS: list[tuple[Optional[set[int]], int, int]] = [
    (None, 6 * 60, 6 * 60 + 45),                 # 06:00~06:45 universe 갱신 · Crazy
    ({1, 2, 3, 4, 5}, 7 * 60, 9 * 60 + 30),      # 화~토 07:00~09:30 미국 보유 기록 07:10 · 바이오 수집 08:45
]

OPINION_HEAD = "전문가 의견 모음 · 추정 · 보장 아님"
GRADE_NOTE = "증권사 표기 원문 (번역 · 해석 안 함)"
USE_NOTE = "표시 전용 · 점수 · 순위 · 경보에 쓰지 않음"
SOURCE_YAHOO = "야후 (yfinance)"
LIVE_NOTE = "실시간 가격은 바이오 후보만 보여 드립니다 · 아래는 저장한 종가입니다"

# 허용 목록 (막음 ㄴ) · 코드에 표 이름을 고정해 적는다 · (표 클래스 이름, 기호 열, 시장 열 | None, 시장 값)
ALLOWED_SOURCES = (
    ("TickerUniverse", "symbol", None, None),
    ("MemeUniverse", "ticker", "market", "US"),
    ("DiscoverySerenityScore", "ticker", None, None),
    ("HoldingSnapshot", "symbol", "market", "US"),
    ("UserJudgment", "ticker", None, None),        # 손으로 적는 값 · 대문자로 맞춰 비교 · 미국 기호 모양만 (US_SHAPE)
    ("CrazyPick", "ticker", None, None),
    ("MoonshotPick", "ticker", None, None),
)
US_SHAPE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")   # 글자로 시작 · 국내 6자리 코드(숫자로 시작)는 이 모양이 아님

Fetcher = Callable[[str], Awaitable[dict]]


def _session():
    """시험이 바꿔 끼울 수 있게 한 곳에서만 세션을 연다."""
    from backend.services.db import get_session

    return get_session()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def normalize(ticker: str) -> Optional[str]:
    """미국 기호 모양이면 대문자로, 아니면 None (국내 코드 포함)."""
    from backend.services.broker_links import is_kr_code

    t = (ticker or "").strip().upper()
    return t if US_SHAPE.match(t) and not is_kr_code(t) else None


def trading_day(now: Optional[datetime] = None) -> date:
    """「하루」의 기준 = 미국 동부 거래일 키 (토 · 일은 직전 금요일 · 공휴일은 따로 보지 않음)."""
    d = _now(now).astimezone(ET).date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def last_complete_date(now: Optional[datetime] = None) -> date:
    """일봉에서 쓸 수 있는 가장 늦은 날짜. 동부 16:30 전이면 오늘 봉은 덜 끝난 봉이라 어제까지."""
    et = _now(now).astimezone(ET)
    d = et.date()
    if not (et.weekday() < 5 and (et.hour, et.minute) >= CLOSE_CUTOFF):
        d -= timedelta(days=1)
    while d.weekday() >= 5:      # 주말은 거래일이 아니므로 직전 금요일로
        d -= timedelta(days=1)
    return d


def in_block_window(now: Optional[datetime] = None) -> bool:
    """다른 야후 잡 시간대인가 (KST)."""
    k = _now(now).astimezone(KST)
    m = k.hour * 60 + k.minute
    return any((days is None or k.weekday() in days) and lo <= m < hi for days, lo, hi in _BLOCK_WINDOWS)


# ─────────────────────────────────────────────────────────────────
# 허용 목록 (저장 표만 읽음 · 바깥 호출 0)
# ─────────────────────────────────────────────────────────────────

PRIVATE_SOURCES = ("HoldingSnapshot", "UserJudgment")   # 내 보유 · 판단 기록 표 · 비로그인 응답에는 쓰지 않는다 (Fable 병합 막음 ㄱ)


async def lookup_allowed(ticker: str, public: bool = False) -> Optional[str]:
    """허용 표에 있는 미국 기호면 대문자 기호 · 아니면 None.

    public=True (비로그인 개요 응답)면 보유 · 판단 기록 표는 보지 않는다 — 플래그로 보유 · 기록 여부가 새지 않게.
    """
    from backend.services import models as M

    t = normalize(ticker)
    if t is None:
        return None
    async with _session() as s:
        for cls_name, sym_col, mkt_col, mkt_val in ALLOWED_SOURCES:
            if public and cls_name in PRIVATE_SOURCES:
                continue
            cls = getattr(M, cls_name)
            q = select(getattr(cls, sym_col)).where(func.upper(getattr(cls, sym_col)) == t)
            if mkt_col:
                q = q.where(getattr(cls, mkt_col) == mkt_val)
            if (await s.execute(q.limit(1))).first() is not None:
                return t
    return None


# ─────────────────────────────────────────────────────────────────
# 받기 (잠금 · 간격 · 429)
# ─────────────────────────────────────────────────────────────────

_TICKER_LOCKS: dict[str, asyncio.Lock] = {}
_GLOBAL_LOCK = asyncio.Lock()
_LAST_CALL = [0.0]     # 마지막 야후 받기가 끝난 monotonic 시각


def _ticker_lock(t: str) -> asyncio.Lock:
    lk = _TICKER_LOCKS.get(t)
    if lk is None:
        lk = _TICKER_LOCKS[t] = asyncio.Lock()
    return lk


async def default_fetch(ticker: str) -> dict:
    """야후 한 종목 (회사 정보 · 의견 분포 · 등급 변경 · 6년 일봉). 바이오 수집과 같은 받기 함수를 쓴다."""
    from backend.services import biotech_quotes as bq

    return await bq.default_fetch(ticker, bq.FIRST_PERIOD)


def is_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return "ratelimit" in name or "429" in msg or "too many requests" in msg


def _trim_closes(raw: dict, cutoff: date) -> tuple[list[tuple[date, float]], dict]:
    """끝난 거래일(cutoff 까지)만 남긴다 (막음 ㄷ)."""
    closes = sorted({d: c for d, c in (raw.get("closes") or []) if c and c > 0 and d <= cutoff}.items())
    vols = {d: v for d, v in (raw.get("volumes") or {}).items() if d <= cutoff}
    return closes, vols


def _fields(raw: dict, closes: list[tuple[date, float]], vols: dict) -> dict:
    """저장할 칸 · 종가 · 거래량 · 날짜는 일봉에서 (야후 currentPrice · regularMarketVolume 은 쓰지 않음)."""
    from backend.services import biotech_quotes as bq

    f = bq.quote_fields(raw)
    last_d, last_c = closes[-1]
    return {
        "price_date": last_d, "price_close": last_c, "volume": vols.get(last_d),
        "avg_volume": f["avg_volume"], "market_cap": f["market_cap"], "low_52w": f["low_52w"], "high_52w": f["high_52w"],
        "total_cash": f["total_cash"], "short_pct_float": f["short_pct_float"], "short_asof": f["short_asof"],
        "exchange": f["exchange"], "analyst_json": f["analyst_json"],
    }


async def _read_state(t: str, day: date) -> dict:
    """짧게 읽기만 (세션은 바로 닫힘)."""
    async with _session() as s:
        today_row = (await s.execute(select(UsQuoteDay).where(UsQuoteDay.ticker == t, UsQuoteDay.fetch_day == day))).scalar_one_or_none()
        used = int((await s.execute(select(func.count()).select_from(UsQuoteDay).where(UsQuoteDay.fetch_day == day))).scalar_one())
        limited = (await s.execute(select(UsQuoteDay.ticker).where(UsQuoteDay.fetch_day == day, UsQuoteDay.status == "rate_limited")
                                   .limit(1))).first() is not None
        last_ok = (await s.execute(select(UsQuoteDay).where(UsQuoteDay.ticker == t, UsQuoteDay.status == "ok")
                                   .order_by(UsQuoteDay.fetch_day.desc()).limit(1))).scalar_one_or_none()
        longs = (await s.execute(select(UsQuoteClose.trade_date, UsQuoteClose.close, UsQuoteClose.volume)
                                 .where(UsQuoteClose.ticker == t).order_by(UsQuoteClose.trade_date))).all()
    return {"today": today_row, "used": used, "limited": limited, "last_ok": last_ok, "longs": longs}


async def _reserve(t: str, day: date) -> bool:
    """그날 행을 pending 으로 먼저 적는다 (상한 · 같은 날 두 번째 받기를 DB 로 막음). 이미 있으면 False."""
    async with _session() as s:
        if (await s.execute(select(UsQuoteDay.ticker).where(UsQuoteDay.ticker == t, UsQuoteDay.fetch_day == day))).first():
            return False
        used = int((await s.execute(select(func.count()).select_from(UsQuoteDay).where(UsQuoteDay.fetch_day == day))).scalar_one())
        if used >= DAILY_TICKER_CAP:
            return False
        s.add(UsQuoteDay(ticker=t, fetch_day=day, status="pending", fetched_at=_utcnow()))
    return True


async def _finish(t: str, day: date, status: str, error: Optional[str] = None, fields: Optional[dict] = None,
                  closes: Optional[list[tuple[date, float]]] = None, vols: Optional[dict] = None) -> None:
    """받은 뒤 짧은 세션 · 네트워크 호출 없음. 정리(보존 기간)도 여기서."""
    async with _session() as s:
        row = (await s.execute(select(UsQuoteDay).where(UsQuoteDay.ticker == t, UsQuoteDay.fetch_day == day))).scalar_one()
        row.status = status
        row.error = error
        row.fetched_at = _utcnow()
        for k, v in (fields or {}).items():
            setattr(row, k, v)
        if closes:
            await s.execute(delete(UsQuoteClose).where(UsQuoteClose.ticker == t))
            s.add_all([UsQuoteClose(ticker=t, trade_date=d, close=c, volume=(vols or {}).get(d)) for d, c in closes])
        await s.execute(delete(UsQuoteDay).where(UsQuoteDay.fetch_day < day - timedelta(days=KEEP_DAYS)))
        alive = select(UsQuoteDay.ticker).distinct()
        await s.execute(delete(UsQuoteClose).where(UsQuoteClose.ticker.not_in(alive)))


async def _fetch_one(t: str, day: date, fetch: Fetcher, now: Optional[datetime]) -> Optional[str]:
    """한 종목 받기 (기호별 잠금 안 · 여기서 전체 잠금). 돌려주는 값 = 화면에 붙일 안내 문장 (없으면 None)."""
    async with _GLOBAL_LOCK:
        if not await _reserve(t, day):       # 다른 요청이 먼저 받았거나 상한
            return None
        wait = MIN_GAP_SEC - (time.monotonic() - _LAST_CALL[0])
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            raw = await asyncio.wait_for(fetch(t), FETCH_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — 실패도 그날 행으로 남긴다 (다시 부르지 않음 · 상한에 셈)
            _LAST_CALL[0] = time.monotonic()
            kind = type(exc).__name__[:60]
            limited = is_rate_limit(exc)
            logger.warning("[us_quotes] 받기 실패 · %s · %s%s", t, kind, " · 429 · 오늘 화면 쪽 받기 중지" if limited else "")
            await _finish(t, day, "rate_limited" if limited else "failed", error=kind)
            return "지금 가격을 받지 못했습니다 · 내일 다시 시도합니다"
        _LAST_CALL[0] = time.monotonic()
    # 여기부터 전체 잠금 밖 · 계산은 메모리에서만
    closes, vols = _trim_closes(raw, last_complete_date(now))
    if not closes:
        logger.warning("[us_quotes] 일봉이 비어 있음 · %s", t)
        await _finish(t, day, "failed", error="empty_history")
        return "지금 가격을 받지 못했습니다 · 내일 다시 시도합니다"
    await _finish(t, day, "ok", fields=_fields(raw, closes, vols), closes=closes, vols=vols)
    logger.info("[us_quotes] 저장 · %s · 일봉 %d줄 · 종가 날짜 %s", t, len(closes), closes[-1][0])
    return None


# ─────────────────────────────────────────────────────────────────
# 조회 (관리자 화면 요청)
# ─────────────────────────────────────────────────────────────────

async def quote_view(ticker: str, fetch: Optional[Fetcher] = None, now: Optional[datetime] = None) -> dict:
    """GET /api/v1/stock/{ticker}/quote (미국 비후보) 본문. 허용 · 후보 검사는 호출자가 이미 했다.

    biotech quote_view 와 같은 칸 이름 · live 는 빈값 · summary · sec8k 는 빈값 (권고 ㅂ · ㅅ).
    """
    from backend.services.holdings_swing import build_chart

    fetch = fetch or default_fetch
    day = trading_day(now)
    notes: list[str] = []
    async with _ticker_lock(ticker):
        st = await _read_state(ticker, day)
        if st["today"] is None:
            if in_block_window(now):
                notes.append("지금은 다른 시세 수집 시간이어서 새로 받지 않고 저장된 값만 보여 드립니다")
            elif st["limited"]:
                notes.append("야후가 호출을 제한해 오늘은 새로 받지 않습니다 · 저장된 값만 보여 드립니다")
            elif st["used"] >= DAILY_TICKER_CAP:
                notes.append(f"오늘 조회 상한({DAILY_TICKER_CAP}종목)을 넘었습니다 · 내일 다시 보입니다")
            else:
                msg = await _fetch_one(ticker, day, fetch, now)
                if msg:
                    notes.append(msg)
                st = await _read_state(ticker, day)
        elif st["today"].status in ("failed", "rate_limited"):
            notes.append("오늘은 가격을 받지 못했습니다 · 내일 다시 시도합니다")
        elif st["today"].status == "pending":
            notes.append("가격을 받는 중입니다 · 잠시 뒤 다시 열어 주십시오")
    row = st["last_ok"]
    longs = st["longs"]
    et_today = _now(now).astimezone(ET).date()
    chart = (build_chart("US", ([d for d, _, _ in longs], [c for _, c, _ in longs], "yahoo"), et_today,
                         volumes=[v for _, _, v in longs]) if longs else None)
    analyst = json.loads(row.analyst_json) if row and row.analyst_json else {}
    dist = analyst.get("dist") or {}
    dsum = sum(v for v in dist.values() if isinstance(v, int)) if dist else None
    n_op = analyst.get("n_opinions")
    has_opinion = bool(n_op) or bool(dsum)
    asof = row.fetch_day.isoformat() if row else None
    return {
        "ticker": ticker,
        "kind": "us_stored",
        "asof": asof,                                           # 조회일 (미국 동부 거래일 키)
        "close_date": row.price_date.isoformat() if row and row.price_date else None,   # 종가의 날짜 (끝난 마지막 거래일)
        "live": None,
        "live_note": LIVE_NOTE,
        "basics": None if row is None else {
            "price_close": row.price_close, "volume": row.volume, "avg_volume": row.avg_volume,
            "market_cap": row.market_cap, "low_52w": row.low_52w, "high_52w": row.high_52w,
            "total_cash": row.total_cash, "short_pct_float": row.short_pct_float,
            "short_asof": row.short_asof.isoformat() if row.short_asof else None,
            "source": SOURCE_YAHOO,
        },
        "chart": chart,
        "opinion": None if not has_opinion else {
            "head": OPINION_HEAD, "grade_note": GRADE_NOTE, "n_opinions": n_op, "dist": dist, "dist_sum": dsum,
            "count_mismatch": bool(n_op is not None and dsum is not None and n_op != dsum),
            "targets": analyst.get("targets") or {}, "changes": analyst.get("changes") or [], "source": SOURCE_YAHOO,
            "asof": asof, "use_note": USE_NOTE,
        },
        "summary": None,
        "sec8k": None,
        "notes": notes,
        "empty_note": "이 종목의 가격 자료를 아직 받지 못했습니다.",
        "use_note": USE_NOTE,
    }
