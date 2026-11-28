"""1128-01 · 국내 종목 상세 가격 · 증권사 의견 칸 (관리자 전용 · 표시 전용).

사용자 결정 (2026-11-28): 네이버 일봉 · 네이버 증권사 의견은 로그인 화면에만 보인다 (㉢) · 비로그인 요청은 네이버를 부르지 않는다.
계획: docs/outputs/1128-종목상세-고도화/고도화-방안.md 2절 나 · Fable 조건부 GO (막음 ㄱ~ㅁ · 권고 ㅂ~ㅌ).

지키는 것
- 허용 코드만: krx_stock_meta 또는 DART 회사 목록 가운데 종목코드가 있는 행의 6자리 코드. 그 밖은 바깥 호출 0 (막음 ㅁ).
- 표시만: 여기서 만든 값은 점수 · 순위 · 후보 선정 · 경보 · 알림에 쓰지 않는다. 증권사 의견은 원문 값만 보인다 (계산 · 해석 없음).
- 1102-08 교훈: 바깥 받기는 DB 세션을 열기 전에 끝낸다. 세션이 열려 있는 동안 네트워크 호출 0.
- 같은 종목 동시 요청은 종목별 잠금으로 한 번만 받는다. 10분 캐시. 하루 바깥 호출 상한 300번 (종목당 일봉 1 + 종합 1 = 2번 → 약 150종목).
- 교훈 #26: 날짜는 'YYYYMMDD' 와 'YYYY-MM-DD' 둘 다 읽고, 받은 줄 · 저장한 줄 · 버린 줄을 센다.
- 칸마다 따로 실패한다: 일봉이 실패해도 종합 칸이, 종합이 실패해도 그림 · 숫자 칸이 보인다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.services.models import DartCorpCodeMap, KrQuoteCallLog, KrQuoteDaily, KrxStockMeta

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

DAILY_CALL_CAP = 300          # 하루 바깥 호출 상한 (네이버 일봉 + 종합) · KST 날짜 기준
CALLS_PER_REFRESH = 2         # 한 종목을 새로 받을 때 쓰는 호출 수 (일봉 1 + 종합 1)
CACHE_SEC = 600.0             # 같은 종목 10분 캐시
FAIL_CACHE_SEC = 60.0         # 받기에 실패한 결과는 1분만 기억 (바로 다시 시도하되 연타는 막음)
HISTORY_YEARS = 6             # 처음 받을 기간 (일봉 1년 + 200일선 여유 · 주봉 5년 + 40주 여유)
AVG_VOLUME_DAYS = 20          # 평균 거래량 = 저장 일봉 최근 20거래일 (거래량이 있는 날만)

OPINION_HEAD = "전문가 의견 모음 · 추정 · 보장 아님"
GRADE_NOTE = "네이버 평균 의견 값 원문 (해석 안 함)"
USE_NOTE = "표시 전용 · 점수 · 순위 · 경보에 쓰지 않음"
SOURCE_NAVER = "네이버 증권"
SOURCE_NAVER_LIVE = "네이버 실시간"
SOURCE_CHART = "네이버 일봉 · 수정주가 여부 확인 전"
NO_OPINION = "증권사 의견 없음"
PLAN_HINT_NOTE = "계획으로 옮기기 미리 채우기용 · 표시 전용 · 이 값으로 계획을 만들거나 바꾸지 않음"

_CODE_RE = re.compile(r"^\d{6}$")
_MISSING = {"", "-", "N/A", "n/a", "NA"}

DailyFetcher = Callable[[str, date, date], Awaitable[Optional[list]]]
IntegFetcher = Callable[[str], Awaitable[Optional[dict]]]
LiveFetcher = Callable[[str], Awaitable[Any]]


def _session():
    """시험이 바꿔 끼울 수 있게 한 곳에서만 세션을 연다."""
    from backend.services.db import get_session

    return get_session()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _kst_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(KST).date()


# ─────────────────────────────────────────────────────────────────
# 값 읽기 (실제 응답 모양 · 2026-11-28 curl 로 확인 · tests/fixtures/naver_kr/)
# ─────────────────────────────────────────────────────────────────

def parse_date(v: Any) -> Optional[date]:
    """'20261127' (일봉 localDate) 와 '2026-11-26' (종합 consensusInfo.createDate) 둘 다 읽는다 (교훈 #26)."""
    if v is None:
        return None
    s = str(v).strip()
    try:
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d").date()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    return None


def parse_number(v: Any) -> Optional[float]:
    """숫자 · '171,300' · '45.84%' · '-1,995원' · '5.64배' 읽기 · '-' · 'N/A' · 빈 칸은 None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return None if f != f or f in (float("inf"), float("-inf")) else f
    s = str(v).strip()
    if s in _MISSING:
        return None
    s = re.sub(r"[,%원배주\s]", "", s)
    try:
        f = float(s)
    except ValueError:
        return None
    return None if f != f else f


def parse_won(v: Any) -> Optional[float]:
    """'1,049조 4,070억' · '169억' · '81.1억' → 원 (조 = 1e12 · 억 = 1e8 · 만 = 1e4). 숫자만 있으면 그대로."""
    if v is None:
        return None
    s = str(v).strip()
    if s in _MISSING:
        return None
    if not re.search(r"[조억만]", s):
        return parse_number(s)
    total, hit = 0.0, False
    for num, unit in re.findall(r"([\d,]+(?:\.\d+)?)\s*([조억만])", s):
        n = parse_number(num)
        if n is None:
            return None
        total += n * {"조": 1e12, "억": 1e8, "만": 1e4}[unit]
        hit = True
    return total if hit else None


def parse_daily(items: Any) -> tuple[list[dict], int, int]:
    """네이버 일봉 줄 → (저장할 줄, 받은 줄 수, 버린 줄 수). 날짜 없음 · 종가 없음/0 이하 줄은 버린다.

    줄 모양: {localDate:'20261127', closePrice:179500.0, openPrice, highPrice, lowPrice, accumulatedTradingVolume:14293472, foreignRetentionRate}
    """
    if not isinstance(items, list):
        return [], 0, 0
    out: dict[date, dict] = {}
    dropped = 0
    for it in items:
        if not isinstance(it, dict):
            dropped += 1
            continue
        d = parse_date(it.get("localDate"))
        c = parse_number(it.get("closePrice"))
        if d is None or c is None or c <= 0:
            dropped += 1
            continue
        out[d] = {"d": d, "o": parse_number(it.get("openPrice")), "h": parse_number(it.get("highPrice")),
                  "l": parse_number(it.get("lowPrice")), "c": c, "v": parse_number(it.get("accumulatedTradingVolume"))}
    return [out[d] for d in sorted(out)], len(items), dropped


def _info_map(raw: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in raw.get("totalInfos") or []:
        if isinstance(t, dict) and t.get("code"):
            out[str(t["code"])] = t.get("value")
    return out


def parse_integration(raw: Any) -> dict:
    """종합 API → {"basics": 숫자 칸 dict, "opinion": dict | None, "dropped": 읽지 못한 칸 수}.

    52주 범위는 「Adjusted」 칸이 있으면 그 값을 쓴다 (2026-11-28 335870 으로 확인: 일봉 그림의 최고 · 최저와 Adjusted 값이 같음).
    평균 의견 · 평균 목표가는 consensusInfo (없으면 opinion None).
    """
    if not isinstance(raw, dict):
        return {"basics": {}, "opinion": None, "dropped": 0}
    info = _info_map(raw)
    dropped = 0

    def pick(*codes: str, conv=parse_number) -> Optional[float]:
        nonlocal dropped
        for c in codes:
            if c in info:
                v = conv(info[c])
                if v is not None:
                    return v
        if any(c in info for c in codes):
            dropped += 1   # 칸은 있는데 값을 읽지 못함 ('-' · 'N/A' 포함)
        return None

    basics = {
        "market_cap": pick("marketValue", conv=parse_won),
        "low_52w": pick("lowPriceOf52WeeksAdjusted", "lowPriceOf52Weeks"),
        "high_52w": pick("highPriceOf52WeeksAdjusted", "highPriceOf52Weeks"),
        "foreign_rate": pick("foreignRate"),
    }
    opinion = None
    ci = raw.get("consensusInfo")
    if isinstance(ci, dict):
        mean_rating = parse_number(ci.get("recommMean"))
        mean_target = parse_number(ci.get("priceTargetMean"))
        created = parse_date(ci.get("createDate"))
        if mean_rating is not None or mean_target is not None:
            opinion = {"mean_rating": mean_rating, "mean_target": mean_target,
                       "created": created.isoformat() if created else None}
        else:
            dropped += 1
    return {"basics": basics, "opinion": opinion, "dropped": dropped}


# ─────────────────────────────────────────────────────────────────
# 허용 코드 (막음 ㅁ) · 하루 호출 장부
# ─────────────────────────────────────────────────────────────────

async def lookup_allowed(code: str) -> Optional[dict]:
    """6자리 코드가 저장된 표에 있으면 {"name", "market"} · 없으면 None. 바깥 호출 0.

    허용: krx_stock_meta 의 행 · DART 회사 목록 가운데 stock_code 가 있는 행 (비상장은 stock_code 가 비어 있어 빠짐).
    """
    if not isinstance(code, str) or not _CODE_RE.match(code):
        return None
    async with _session() as s:
        meta = (await s.execute(select(KrxStockMeta).where(KrxStockMeta.ticker == code))).scalar_one_or_none()
        if meta is not None:
            return {"name": meta.name, "market": meta.market}
        dart = (await s.execute(select(DartCorpCodeMap).where(DartCorpCodeMap.stock_code == code)
                                .limit(1))).scalar_one_or_none()
        if dart is not None:
            return {"name": dart.corp_name, "market": None}
    return None


_LEDGER_LOCK = asyncio.Lock()


async def reserve_calls(n: int, now: Optional[datetime] = None) -> bool:
    """오늘(KST) 호출 장부에 n번을 미리 적는다. 상한(300)을 넘으면 적지 않고 False."""
    day = _kst_today(now)
    async with _LEDGER_LOCK:
        async with _session() as s:
            row = (await s.execute(select(KrQuoteCallLog).where(KrQuoteCallLog.day == day))).scalar_one_or_none()
            used = row.calls if row else 0
            if used + n > DAILY_CALL_CAP:
                return False
            if row is None:
                s.add(KrQuoteCallLog(day=day, calls=n))
            else:
                row.calls = used + n
    return True


async def calls_today(now: Optional[datetime] = None) -> int:
    async with _session() as s:
        row = (await s.execute(select(KrQuoteCallLog).where(KrQuoteCallLog.day == _kst_today(now)))).scalar_one_or_none()
    return row.calls if row else 0


# ─────────────────────────────────────────────────────────────────
# 저장 · 읽기 (짧은 세션 · 네트워크 호출 없음)
# ─────────────────────────────────────────────────────────────────

async def store_daily(code: str, rows: list[dict]) -> int:
    """그 종목 일봉을 통째로 바꾼다 (수정주가 여부를 몰라 옛 값이 섞이지 않게). 저장한 줄 수."""
    if not rows:
        return 0
    now = _utcnow()
    async with _session() as s:
        await s.execute(delete(KrQuoteDaily).where(KrQuoteDaily.ticker == code))
        s.add_all([KrQuoteDaily(ticker=code, trade_date=r["d"], open=r["o"], high=r["h"], low=r["l"], close=r["c"],
                                volume=r["v"], fetched_at=now) for r in rows])
    return len(rows)


async def load_daily(code: str) -> list[dict]:
    async with _session() as s:
        rs = (await s.execute(select(KrQuoteDaily).where(KrQuoteDaily.ticker == code)
                              .order_by(KrQuoteDaily.trade_date))).scalars().all()
    return [{"d": r.trade_date, "o": r.open, "h": r.high, "l": r.low, "c": r.close, "v": r.volume} for r in rs]


# ─────────────────────────────────────────────────────────────────
# 받기 (잠금 · 캐시 · 상한 · 세션 밖)
# ─────────────────────────────────────────────────────────────────

_LOCKS: dict[str, asyncio.Lock] = {}
_CACHE: dict[str, tuple[float, dict]] = {}   # code → (만료 monotonic, {"integ": 파싱 결과 | None, "notes": [...]})


def _lock_for(code: str) -> asyncio.Lock:
    lk = _LOCKS.get(code)
    if lk is None:
        lk = _LOCKS[code] = asyncio.Lock()
    return lk


async def default_daily_fetch(code: str, start: date, end: date) -> Optional[list]:
    from backend.discovery.data_sources.naver_quote.client import fetch_daily_kr_raw

    return await fetch_daily_kr_raw(code, start, end)


async def default_integ_fetch(code: str) -> Optional[dict]:
    from backend.discovery.data_sources.naver_quote.client import fetch_integration_kr

    return await fetch_integration_kr(code)


async def default_live_fetch(code: str) -> Any:
    from backend.discovery.data_sources.naver_quote.client import fetch_one

    return await fetch_one(code)


async def _refresh(code: str, daily_fetch: DailyFetcher, integ_fetch: IntegFetcher, now: Optional[datetime]) -> dict:
    """한 종목을 새로 받는다 (잠금 안에서만 부름). 칸마다 따로 실패하고 결과 {"integ", "notes", "ok"} 를 돌려 준다."""
    notes: list[str] = []
    today = _kst_today(now)
    if not await reserve_calls(CALLS_PER_REFRESH, now):
        logger.warning("[kr_quotes] 하루 상한 %d 도달 · %s 는 저장된 값만", DAILY_CALL_CAP, code)
        return {"integ": None, "notes": ["하루 바깥 조회 한도에 닿아 저장된 값만 보여 드립니다"], "ok": False, "limited": True}
    start = today - timedelta(days=int(HISTORY_YEARS * 366))
    # 바깥 받기는 세션 밖 · 두 호출은 서로 독립
    daily_raw, integ_raw = await asyncio.gather(
        _safe(daily_fetch(code, start, today)), _safe(integ_fetch(code)))
    ok = True

    rows, received, dropped = parse_daily(daily_raw)
    saved = 0
    if daily_raw is None:
        ok = False
        notes.append("일봉을 받지 못했습니다")
    elif rows:
        saved = await store_daily(code, rows)
    else:
        ok = False
        notes.append("일봉이 비어 있습니다")
    logger.info("[kr_quotes] %s 일봉 받음 %d · 저장 %d · 버림 %d", code, received, saved, dropped)
    if received and not saved:
        logger.warning("[kr_quotes] %s 일봉 %d줄을 받았지만 하나도 저장하지 못함 (모양이 바뀌었을 수 있음)", code, received)

    integ = None
    if integ_raw is None:
        ok = False
        notes.append("종합 정보를 받지 못했습니다")
    else:
        integ = parse_integration(integ_raw)
        logger.info("[kr_quotes] %s 종합 받음 · 읽지 못한 칸 %d · 의견 %s", code, integ["dropped"],
                    "있음" if integ["opinion"] else "없음")
    return {"integ": integ, "notes": notes, "ok": ok, "limited": False}


async def _safe(aw: Awaitable) -> Any:
    try:
        return await aw
    except Exception as exc:  # noqa: BLE001 — 한 칸 실패가 다른 칸을 막지 않음
        logger.warning("[kr_quotes] 받기 실패 · %s", type(exc).__name__)
        return None


async def live_quote(code: str, fetch: Optional[LiveFetcher] = None) -> Optional[dict]:
    """네이버 현재가 (기존 polling 클라이언트의 60초 캐시 사용) · 실패면 None."""
    try:
        q = await (fetch or default_live_fetch)(code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[kr_quotes] 현재가 실패 · %s", type(exc).__name__)
        return None
    if q is None:
        return None
    return {"price": q.current_price, "change_pct": q.change_rate, "market_status": q.market_status,
            "traded_at": None, "source": SOURCE_NAVER_LIVE}


# ─────────────────────────────────────────────────────────────────
# 조회 (관리자 화면 요청)
# ─────────────────────────────────────────────────────────────────

def _avg_volume(rows: list[dict]) -> Optional[float]:
    vs = [r["v"] for r in rows if r["v"] and r["v"] > 0][-AVG_VOLUME_DAYS:]
    return round(sum(vs) / len(vs)) if vs else None


async def quote_view(code: str, info: Optional[dict] = None, daily_fetch: Optional[DailyFetcher] = None,
                     integ_fetch: Optional[IntegFetcher] = None, live_fetch: Optional[LiveFetcher] = None,
                     now: Optional[datetime] = None) -> dict:
    """GET /api/v1/stock/{code}/quote 본문 (biotech quote_view 와 같은 칸 이름). 허용 검사는 호출자가 이미 했다.

    문장은 고정 머리말만 · 판정 문장 없음 · 자체 계산은 평균 거래량(최근 20거래일 평균) 하나뿐이다.
    """
    from backend.services.holdings_swing import build_chart

    daily_fetch = daily_fetch or default_daily_fetch
    integ_fetch = integ_fetch or default_integ_fetch
    async with _lock_for(code):
        hit = _CACHE.get(code)
        if hit is not None and time.monotonic() < hit[0]:
            state = hit[1]
        else:
            state = await _refresh(code, daily_fetch, integ_fetch, now)
            if not state.get("limited"):   # 상한에 막힌 것은 기억하지 않는다 (다음 날 바로 풀림)
                _CACHE[code] = (time.monotonic() + (CACHE_SEC if state["ok"] else FAIL_CACHE_SEC), state)
    notes = list(state["notes"])
    integ = state["integ"]

    rows = await load_daily(code)      # 세션은 읽고 바로 닫힘 · 이후 바깥 호출은 live 하나뿐
    live = await live_quote(code, live_fetch)
    today = _kst_today(now)

    chart = None
    if rows:
        chart = build_chart("KR", ([r["d"] for r in rows], [r["c"] for r in rows], "naver"), today,
                            volumes=[r["v"] for r in rows], source_text=SOURCE_CHART)
    last = rows[-1] if rows else None
    b_int = (integ or {}).get("basics") or {}
    basics = None
    if last is not None or b_int:
        basics = {"price_close": last["c"] if last else None, "volume": last["v"] if last else None,
                  "avg_volume": _avg_volume(rows), "avg_volume_note": f"저장 일봉 최근 {AVG_VOLUME_DAYS}거래일 평균",
                  "market_cap": b_int.get("market_cap"), "low_52w": b_int.get("low_52w"),
                  "high_52w": b_int.get("high_52w"), "foreign_rate": b_int.get("foreign_rate"),
                  "source": SOURCE_NAVER}

    op = (integ or {}).get("opinion")
    if integ is None:
        opinion, opinion_status, opinion_note = None, "failed", "의견을 받지 못했습니다"
    elif op is None:
        opinion, opinion_status, opinion_note = None, "none", NO_OPINION
    else:
        opinion = {"head": OPINION_HEAD, "grade_note": GRADE_NOTE, "mean_rating": op["mean_rating"],
                   "mean_target": op["mean_target"], "created": op["created"], "source": SOURCE_NAVER,
                   "use_note": USE_NOTE}
        opinion_status, opinion_note = "ok", None

    wk = (chart or {}).get("week40") or {}
    wk_series = wk.get("series") or []
    plan_hints = {
        "last_close": last["c"] if last else None,
        "week40_line": wk_series[-1]["m"] if wk_series else None,
        "low_52w": b_int.get("low_52w"), "high_52w": b_int.get("high_52w"),
        "asof": last["d"].isoformat() if last else None,
        "note": PLAN_HINT_NOTE,
    }
    live_note = None if live else "실시간 실패 · 저장 종가를 보여 드립니다"
    return {
        "ticker": code,
        "name": (info or {}).get("name"),
        "market_label": (info or {}).get("market"),
        "asof": last["d"].isoformat() if last else None,
        "live": live,
        "live_note": live_note,
        "basics": basics,
        "chart": chart,
        "opinion": opinion,
        "opinion_status": opinion_status,
        "opinion_note": opinion_note,
        "plan_hints": plan_hints,
        "notes": notes,
        "use_note": USE_NOTE,
    }
