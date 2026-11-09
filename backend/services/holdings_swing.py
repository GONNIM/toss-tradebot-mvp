"""1108-02 · 보유 종목 사실 (스윙 2단계) — 사실만 낸다 (규칙 이름 · 명령문 · 규칙 계산값 없음).

계획: docs/plans/holdings-swing/2026-11-08-plan.md 5절 (사용자 ㉠② ㉡① · 검토 1108-02-07 조건부 GO 조건 1~6).
- 읽기(build_cards)는 DB 만 읽는다 — 화면 요청 때 토스·외부 호출 없음.
- 국내 공식 종가(fill_official_closes)와 대형·대표 기준 값(refresh_references)은 보유 기록 잡(국내 15:50 · 미국 07:10)
  이 끝난 뒤 별도 단계로 이어 받는다 (cron.run_swing_followup). 실패해도 보유 기록은 이미 저장돼 있다.
- 새 정해진 시각 잡 없음 → 교훈 #3 의 네 가지: 늦게 시작 = 기존 잡 설정을 따름 · 같은 시각 = 새 시각 없음 ·
  서버 재시작 = 다음 실행 때 빠진 날 채움(마지막 저장일 다음 날 ~ 오늘) · 실패 = 하루 1회 시스템 경고 + 화면 보류.
"""
from __future__ import annotations

import asyncio
import logging
import math
import statistics
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from statistics import NormalDist

from sqlalchemy import delete, func, select

from backend.services.models import (
    HoldingHorizon,
    HoldingSnapshot,
    KrOfficialClose,
    SwingLongClose,
    SwingReference,
)

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
HORIZONS = ("long", "short")
FIRST_FILL_CALENDAR_DAYS = 240  # 처음 받을 때 약 160거래일
MIN_BARS = 20
MA_DAYS = (20, 60, 120)
SPLIT_SUSPECT = 0.30           # 하루 종가 변동 ±30% 초과 = 분할 의심 → 보류 (계획 5절)
SOURCE_GAP_PCT = 2.0           # 토스 종가와 공식 종가 차이 — 2% 는 근거 없는 값 (계획 5절 한계)
VOL_DAYS = 60
SHOW_AFTER_TURN_ROWS = 5       # 흑자 전환 뒤 보유 기록 행 5개까지 3층 (조건 5)
DISCLAIMER = "추정 · 보장 아님"

# 3단계 · 목표까지 거리 (계획 6절)
LONG_FETCH_TIMEOUT = 60        # 종목당 긴 일봉 받기 제한 (초) — 검토 조건 6
KR_LONG_START = date(2000, 1, 1)
US_LONG_PERIOD = "10y"
LONG_SOURCE = {"KR": "pykrx adjusted", "US": "yfinance close"}
MODEL_SIGMA_DAYS = 120         # 변동성 모형 σ 는 최근 120일 로그 수익
MIN_OWN_SAMPLE = 250           # 자기 이력 표본이 이보다 적으면 「표본 적음」
WINDOWS = (("3개월", 63), ("6개월", 126))
DRAWDOWN_THRESHOLD = 0.30
MEMO_MAX = 200
SHORT_LIMITS = [
    "기울기 0 가정: 오르내림이 중립이라고 놓고 계산한 값입니다.",
    "두꺼운 꼬리 무시: 드물게 크게 움직이는 날을 변동성 모형은 반영하지 않습니다.",
    "자기 이력의 생존·국면 편향: 지금까지 거래된 종목의 지난 기간만 반영하고 앞날의 국면은 다를 수 있습니다.",
    "남은 거래일은 평일 수이며 휴장일은 빼지 않았습니다.",
]
LONG_LIMITS = [
    "같은 종목 생존 자료: 지금까지 거래된 종목의 기록이라 거래가 끝난 사례는 들어 있지 않습니다.",
    "고점 대비 하락 사건은 이 종목의 과거 기록이며 앞날을 보장하지 않습니다.",
]

# 비용 추정 (조건 5 · 계획 4절): 국내 매도 거래세+농특세 0.20% + 수수료 0.015% · 미국 매도 0.1% + 환전 0.1%
# ─ 4단계 · 40주 평균선 (계획 7절 · 검토 1108-02-16) ─
WEEK_MA = 40
WEEK_SLOPE_BACK = 4            # 기울기 = 40주선이 4주 전보다 몇 % 달라졌나
WEEK_SERIES_KEEP = 260         # 그림은 최근 5년(끝난 주 260개)
WEEK_CHECK_YEARS = 10          # 검증 구간 — 자료가 짧으면 실제 기간
WEEK_CHECK_MIN_YEARS = 3.0     # 이보다 짧으면 검증 줄 없음
WEEK_CHECK_COST = 0.0025       # 바뀔 때마다 0.25%
WEEK_WHIPSAW_WEEKS = 4
WEEK40_SOURCE = {"KR": "KRX 일봉(pykrx · 수정주가) · 배당 미반영", "US": "Yahoo 종가(yfinance) · 배당 미반영"}

SELL_COST = {"KR": 0.0020 + 0.00015, "US": 0.001 + 0.001}
COST_NOTE = {
    "KR": "비용 추정: 매도 세금 0.20% + 수수료 0.015%",
    "US": "비용 추정: 매매 수수료 0.1% + 환전 0.1% (달러 기준)",
}

# 3층 카드 상수 (조건 6) — 출처: docs/plans/holdings-swing/backtest-2026-11-08.md 「비교 ② 본전 매도 vs D 로 보내기」 표.
# D = 고점 대비 하락 때 정리하는 방법 (이름은 화면에 쓰지 않음). 값은 보고서 표 그대로 (손으로 옮김).
THIRD_LAYER = {
    "KR": {"windows": 180, "mean": (2.5, 4.4), "median_diff": -0.77, "bottom5": (-3.3, -28.5)},
    "US": {"windows": 225, "mean": (1.8, 4.4), "median_diff": 1.38, "bottom5": (-2.2, -9.5)},
}
THIRD_LAYER_PERIOD = "2024-06~2026-10"
THIRD_LAYER_SOURCE = "출처: 보유 종목 과거 비교 보고서(2026-11-08) 비교 ②"

# 미국 대형·대표 ③ 흔들림 기준: S&P 100 99종목(GOOG 제외)의 최근 60일 일간 수익률 표준편차(%) 중앙값.
# 1단계 자료(yfinance Close, 마지막 날 2026-11-06)로 2026-11-08 에 계산한 값 — 매일 받지 않는다.
US_VOL_MEDIAN = 1.8805
US_VOL_AS_OF = date(2026, 11, 6)
US_VOL_SAMPLE = 99
# 미국 대형·대표 ① 고정 명단: 위키백과 영어판 S&P 100 문서 Components 표 (문서 기준일 2026-09-21 · 2026-11-08 받음 · 추정)
US_SP100 = frozenset("""AAPL ABBV ABT ACN ADBE AMAT AMD AMGN AMT AMZN ANET AVGO AXP BA BAC BKNG BLK BMY BNY C CAT CMCSA COF COP
COST CRM CSCO CVS CVX DE DELL DHR DIS DUK EMR FDX GD GE GEV GILD GM GOOG GOOGL GS HD IBM INTC INTU ISRG JNJ JPM KO LIN LLY
LMT LOW LRCX MA MCD MDLZ MDT META MMM MO MRK MS MSFT MU NEE NFLX NOW NVDA ORCL PANW PEP PFE PG PLTR PM QCOM RTX SBUX SCHW
SNDK SO T TMO TMUS TSLA TXN UBER UNH UNP UPS USB V VZ WFC WMT XOM""".split())
US_SIZE_USD = 100e9
KR_SIZE_RANK = 20


def _now_kst(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(KST)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─────────────────────────────────────────────────────────────────
# 보유 성격 (장기 / 단기 / 미지정)
# ─────────────────────────────────────────────────────────────────


_KEEP = object()  # PATCH 본문에 없던 칸 = 그대로


def clean_memo(value: Optional[str]) -> Optional[str]:
    """메모 정리: 앞뒤 공백 제거 · 개행(\\n)만 허용 · 그 밖 제어 문자 · 200자 초과는 ValueError. 빈 글은 None(지움)."""
    if value is None:
        return None
    text = value.replace("\r\n", "\n").strip()
    if any(unicodedata.category(ch) == "Cc" and ch != "\n" for ch in text):
        raise ValueError("메모에 쓸 수 없는 제어 문자가 있습니다")
    if len(text) > MEMO_MAX:
        raise ValueError(f"메모는 {MEMO_MAX}자까지입니다")
    return text or None


async def _basis_for(session, market: str, ticker: str, today: date) -> tuple[Optional[date], Optional[str]]:
    """기한 기본값의 기준일과 출처 (첫 저널 · 기록 시작) — 카드 사실 칸과 같은 계산."""
    from backend.services import real_holdings
    from backend.services.real_holdings import HoldingRow

    h = next((x for x in await _held(session, market) if x.symbol == ticker), None)
    if h is None:
        return None, None
    row = HoldingRow(h.symbol, h.name, market, h.currency or "", h.qty or 0, h.avg_price or 0, h.close,
                     h.market_value, h.purchase_amount or 0, None, None, "computed")
    f = await real_holdings.holding_facts(session, row, today)
    return f["basis_date"], f["basis_source"]


def default_deadline(basis: Optional[date]) -> Optional[date]:
    if basis is None:
        return None
    try:
        return basis.replace(year=basis.year + 1)
    except ValueError:  # 2/29
        return basis.replace(year=basis.year + 1, day=28)


async def save_horizon(session, market: str, ticker: str, value: str, *, deadline=_KEEP, memo=_KEEP,
                       today: Optional[date] = None) -> dict:
    """보유 성격 저장. unset 도 행을 지우지 않고 horizon="unset" 으로 남겨 기한·메모를 보존한다 (검토 조건 2).

    deadline: _KEEP 이면 그대로 · None 이면 기본값으로 되돌림 · 날짜가 기준일보다 앞이면 ValueError.
    memo: _KEEP 이면 그대로 · "" / None 이면 지움.
    """
    if value not in HORIZONS and value != "unset":
        raise ValueError("보유 성격은 long, short, unset 만 가능")
    if deadline is not _KEEP and deadline is not None:
        basis, _ = await _basis_for(session, market, ticker, today or _now_kst().date())
        if basis is not None and deadline < basis:
            raise ValueError("기한이 기준일보다 앞입니다")
    if memo is not _KEEP:
        memo = clean_memo(memo)
    row = (await session.execute(select(HoldingHorizon).where(
        HoldingHorizon.market == market, HoldingHorizon.ticker == ticker))).scalar_one_or_none()
    if row is None:
        row = HoldingHorizon(market=market, ticker=ticker, horizon=value, updated_at=_utcnow())
        session.add(row)
    else:
        row.horizon, row.updated_at = value, _utcnow()
    if deadline is not _KEEP:
        row.deadline = deadline
    if memo is not _KEEP:
        row.memo = memo
    return {"horizon": None if value == "unset" else value, "deadline": row.deadline, "memo": row.memo}


async def set_horizon(session, market: str, ticker: str, value: str) -> Optional[str]:
    """long / short 저장 · unset 이면 미지정(행은 보존). 저장 뒤 값(미지정은 None)을 돌려준다."""
    return (await save_horizon(session, market, ticker, value))["horizon"]


# ─────────────────────────────────────────────────────────────────
# 국내 공식 종가 이어 받기 (조건 1 · 2)
# ─────────────────────────────────────────────────────────────────

Fetcher = Callable[[str, date, date], Awaitable[object]]


async def _held(session, market: str) -> list[HoldingSnapshot]:
    """시장별 지금 들고 있는 종목의 최신 보유 기록 (수량 > 0)."""
    last = (await session.execute(
        select(HoldingSnapshot.symbol, func.max(HoldingSnapshot.trade_date))
        .where(HoldingSnapshot.market == market, HoldingSnapshot.kind == "holding")
        .group_by(HoldingSnapshot.symbol)
    )).all()
    out = []
    for sym, d in last:
        r = (await session.execute(select(HoldingSnapshot).where(
            HoldingSnapshot.symbol == sym, HoldingSnapshot.market == market,
            HoldingSnapshot.kind == "holding", HoldingSnapshot.trade_date == d))).scalar_one()
        if (r.qty or 0) > 0:
            out.append(r)
    return sorted(out, key=lambda r: r.symbol)


def _frame_rows(df, start: date, end: date) -> list[tuple[date, float]]:
    """pykrx 일봉 표 → (날짜, 종가). 날짜는 표의 날짜 그대로 쓴다 — 오늘 값으로 바꿔 적지 않는다."""
    rows: list[tuple[date, float]] = []
    if df is None or getattr(df, "empty", True):
        return rows
    for idx, r in df.iterrows():
        d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        try:
            close = float(r["종가"])
        except (KeyError, TypeError, ValueError):
            continue
        if close > 0 and start <= d <= end:
            rows.append((d, close))
    return rows


async def fill_official_closes(now: Optional[datetime] = None, fetch: Optional[Fetcher] = None) -> dict:
    """보유 중인 국내 종목의 KRX 공식 종가를 「마지막 저장일 다음 날 ~ 오늘」 받아 덮어쓴다.

    pykrx 호출은 loader.fetch_daily_candles(asyncio.to_thread) 재사용 — 백테스트와 같은 함수·수정주가.
    받은 표에 오늘 날짜 행이 없으면 오늘 행을 만들지 않는다 (어제 값을 오늘로 적지 않음).
    """
    from backend.discovery.data_sources.krx_price import loader
    from backend.services.db import get_session

    fetch = fetch or loader.fetch_daily_candles
    today = _now_kst(now).date()
    written, failures, tickers, last_date = 0, 0, 0, None
    async with get_session() as session:
        held = await _held(session, "KR")
        for h in held:
            tickers += 1
            last = (await session.execute(select(func.max(KrOfficialClose.trade_date)).where(
                KrOfficialClose.ticker == h.symbol))).scalar_one_or_none()
            start = last + timedelta(days=1) if last else today - timedelta(days=FIRST_FILL_CALENDAR_DAYS)
            if start > today:
                continue
            try:
                rows = _frame_rows(await fetch(h.symbol, start, today), start, today)
            except Exception as exc:  # noqa: BLE001 — 한 종목 실패가 다른 종목을 막지 않는다
                failures += 1
                logger.warning("[swing] 공식 종가 조회 실패 · %s", type(exc).__name__)
                continue
            for d, close in rows:
                row = (await session.execute(select(KrOfficialClose).where(
                    KrOfficialClose.ticker == h.symbol, KrOfficialClose.trade_date == d))).scalar_one_or_none()
                if row is None:
                    session.add(KrOfficialClose(ticker=h.symbol, trade_date=d, close=close, fetched_at=_utcnow()))
                else:
                    row.close, row.fetched_at = close, _utcnow()
                written += 1
                last_date = d if last_date is None or d > last_date else last_date
    logger.info("[swing] 공식 종가 %d행 · %s", written, last_date.isoformat() if last_date else "받은 날 없음")
    if tickers and failures == tickers:
        raise RuntimeError("공식 종가를 한 종목도 받지 못함")
    return {"tickers": tickers, "rows": written, "failures": failures, "last_date": last_date}


# ─────────────────────────────────────────────────────────────────
# 대형·대표 기준 값 저장 (하루 1회 · 같은 잡 끝)
# ─────────────────────────────────────────────────────────────────


async def _put_ref(session, market, ticker, item, value, as_of, note) -> None:
    row = (await session.execute(select(SwingReference).where(
        SwingReference.market == market, SwingReference.ticker == ticker,
        SwingReference.item == item))).scalar_one_or_none()
    if row is None:
        session.add(SwingReference(market=market, ticker=ticker, item=item, value=value, as_of=as_of,
                                   note=note, saved_at=_utcnow()))
    else:
        row.value, row.as_of, row.note, row.saved_at = value, as_of, note, _utcnow()


def _vol_pct(closes: list[float]) -> Optional[float]:
    """최근 60일 일간 수익률 표준편차(%) — 종가 61개 필요."""
    c = closes[-(VOL_DAYS + 1):]
    if len(c) < VOL_DAYS + 1:
        return None
    rets = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] > 0]
    return statistics.stdev(rets) * 100 if len(rets) >= 2 else None


async def _kr_ttm_owner_income(session, ticker: str) -> Optional[tuple[float, date]]:
    """principles_financial_cache(DART 누적) → 분기 단독 → 최근 4분기 합. 못 만들면 None (조건 2 · 「자료 없음」)."""
    from backend.principles.financials import cumulative_to_quarter, ttm_sum
    from backend.services.models import PrinciplesFinancialCache as C

    rows = (await session.execute(select(C).where(C.ticker == ticker).order_by(C.fiscal_year, C.fiscal_quarter))).scalars().all()
    by_year: dict[int, dict[int, Optional[float]]] = {}
    for r in rows:
        by_year.setdefault(r.fiscal_year, {})[r.fiscal_quarter] = r.net_income_owner_cum
    series: list[tuple[date, Optional[float]]] = []
    for y in sorted(by_year):
        q = cumulative_to_quarter(by_year[y])
        for k in (1, 2, 3, 4):
            if q[k] is not None or by_year[y].get(k) is not None:
                series.append((date(y, k * 3, 28), q[k]))
    total = ttm_sum([v for _, v in series])
    return (total, series[-1][0]) if total is not None else None


async def _default_listing():
    from backend.discovery.data_sources.krx_price import loader

    return await loader.fetch_all_meta()


async def _default_us_marcap(symbol: str) -> Optional[float]:
    import asyncio

    def _call() -> Optional[float]:
        import yfinance as yf

        v = yf.Ticker(symbol).fast_info["market_cap"]
        return float(v) if v else None

    return await asyncio.to_thread(_call)


async def _default_us_eps(symbol: str) -> list[dict]:
    from backend.discovery.data_sources.finnhub import FinnhubClient

    async with FinnhubClient() as c:
        return await c.get_eps_surprise_history(symbol, limit=4)


async def refresh_references(
    market: str, now: Optional[datetime] = None, *, listing=None, us_marcap=None, us_eps=None,
) -> dict:
    """들고 있는 종목의 대형·대표 기준 값을 하루 1회 저장한다. 한 항목이 실패해도 다른 항목은 저장한다."""
    from backend.services.db import get_session

    today = _now_kst(now).date()
    saved, failed = 0, 0
    async with get_session() as session:
        held = [h.symbol for h in await _held(session, market)]
        if market == "KR":
            try:
                df = await (listing or _default_listing)()
                kospi = df[df["Market"] == "KOSPI"].sort_values("Marcap", ascending=False)
                ranks = {str(c): i + 1 for i, c in enumerate(kospi["Code"].tolist())}
                market_of = dict(zip(df["Code"].astype(str), df["Market"]))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[swing] 국내 시가총액 조회 실패 · %s", type(exc).__name__)
                ranks, market_of, failed = {}, {}, failed + 1
            for sym in held:
                if sym in ranks:
                    await _put_ref(session, "KR", sym, "size", float(ranks[sym]), today, "KOSPI 시가총액 순위")
                    saved += 1
                elif sym in market_of:
                    await _put_ref(session, "KR", sym, "size", None, today, f"KOSPI 아님 ({market_of[sym]})")
                    saved += 1
                ni = await _kr_ttm_owner_income(session, sym)
                if ni is not None:
                    await _put_ref(session, "KR", sym, "earnings", ni[0], ni[1], "최근 4분기 지배주주순이익 합")
                    saved += 1
            # ③ 국내 기준 = krx_daily_candles 종목들의 60일 변동성 중앙값 (이미 DB 에 있는 값 · 날짜 함께)
            from backend.services.models import KrxDailyCandle as K

            mx = (await session.execute(select(func.max(K.date)))).scalar_one_or_none()
            if mx:
                since = (date.fromisoformat(mx) - timedelta(days=130)).isoformat()
                rows = (await session.execute(select(K.ticker, K.close).where(K.date >= since).order_by(K.ticker, K.date))).all()
                by_t: dict[str, list[float]] = {}
                for t, c in rows:
                    by_t.setdefault(t, []).append(c)
                vols = [v for v in (_vol_pct(c) for c in by_t.values()) if v is not None]
                if vols:
                    await _put_ref(session, "KR", "*", "vol_median", statistics.median(vols), date.fromisoformat(mx),
                                   f"krx_daily_candles {len(vols)}종목 중앙값")
                    saved += 1
        else:
            for sym in held:
                if sym.upper() not in US_SP100:
                    try:
                        mc = await (us_marcap or _default_us_marcap)(sym)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[swing] 미국 시가총액 조회 실패 · %s", type(exc).__name__)
                        mc, failed = None, failed + 1
                    if mc:
                        await _put_ref(session, "US", sym, "size", mc, today, "시가총액 (달러)")
                        saved += 1
                try:
                    eps = await (us_eps or _default_us_eps)(sym)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[swing] 미국 이익 조회 실패 · %s", type(exc).__name__)
                    eps, failed = [], failed + 1
                actual = [e.get("actual") for e in eps or []]
                if len(actual) >= 4 and all(a is not None for a in actual[:4]):
                    per = max(str(e.get("period") or "")[:10] for e in eps[:4])
                    await _put_ref(session, "US", sym, "earnings", float(sum(actual[:4])), date.fromisoformat(per) if per else today,
                                   "최근 4분기 주당순이익 합")
                    saved += 1
    logger.info("[swing] 기준 값 %s %d건 저장 · 실패 %d", market, saved, failed)
    if held and failed and saved == 0:
        raise RuntimeError("대형·대표 기준 값을 하나도 받지 못함")
    return {"market": market, "saved": saved, "failed": failed}


# ─────────────────────────────────────────────────────────────────
# 긴 일봉 받기 (3단계 · 하루 1회 · 같은 잡 끝) — 화면 요청 때는 swing_long_close 표만 읽는다
# ─────────────────────────────────────────────────────────────────

LongFetcher = Callable[[str, str], Awaitable[list]]


async def _default_long_fetch(market: str, ticker: str) -> list[tuple[date, float]]:
    """국내 = pykrx(loader.fetch_daily_candles 재사용 · 2000-01-01~) · 미국 = yfinance 10년 Close (auto_adjust=False)."""
    if market == "KR":
        from backend.discovery.data_sources.krx_price import loader

        end = _now_kst().date()
        return _frame_rows(await loader.fetch_daily_candles(ticker, KR_LONG_START, end), KR_LONG_START, end)

    def _call() -> list[tuple[date, float]]:
        import yfinance as yf

        df = yf.download(ticker.replace(".", "-"), period=US_LONG_PERIOD, auto_adjust=False, progress=False)
        close = df["Close"].squeeze().dropna()
        return [(idx.date(), float(v)) for idx, v in close.items() if float(v) > 0]

    return await asyncio.to_thread(_call)


async def fill_long_closes(market: str, now: Optional[datetime] = None, fetch: Optional[LongFetcher] = None) -> dict:
    """들고 있는 종목의 긴 일봉을 받아 swing_long_close 에 덮어쓴다 (종목마다: 받기 성공 뒤에만 그 종목 행을 교체).

    종목당 asyncio.wait_for(LONG_FETCH_TIMEOUT) — 초과·실패는 그 종목만 건너뛰고 기존 행은 그대로 둔다.
    한 종목도 받지 못하면 RuntimeError (cron 이 하루 1회 경고).
    """
    from backend.services.db import get_session

    fetch = fetch or _default_long_fetch
    written, failures, tickers = 0, 0, 0
    async with get_session() as session:
        held = await _held(session, market)
    for h in held:
        tickers += 1
        try:
            raw = await asyncio.wait_for(fetch(market, h.symbol), LONG_FETCH_TIMEOUT)
            rows = sorted({d: c for d, c in raw if c and c > 0}.items())
            if not rows:
                raise ValueError("받은 일봉이 없음")
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패(시간 초과 포함)가 다른 종목을 막지 않는다
            failures += 1
            logger.warning("[swing] 긴 일봉 받기 실패 · %s", type(exc).__name__)
            continue
        async with get_session() as session:
            await session.execute(delete(SwingLongClose).where(
                SwingLongClose.market == market, SwingLongClose.ticker == h.symbol))
            now_utc = _utcnow()
            session.add_all([SwingLongClose(market=market, ticker=h.symbol, trade_date=d, close=c,
                                            source=LONG_SOURCE[market], fetched_at=now_utc) for d, c in rows])
        written += len(rows)
    logger.info("[swing] 긴 일봉 %s %d행 · 실패 %d/%d", market, written, failures, tickers)
    if tickers and failures == tickers:
        raise RuntimeError("긴 일봉을 한 종목도 받지 못함")
    return {"market": market, "tickers": tickers, "rows": written, "failures": failures}


async def run_after_snapshot(market: str, now: Optional[datetime] = None) -> dict:
    """테스트용 한 줄 진입점 — 실제 cron 은 단계마다 따로 try 를 건다 (cron.run_swing_followup)."""
    out: dict = {}
    if market == "KR":
        out["official"] = await fill_official_closes(now)
    out["refs"] = await refresh_references(market, now)
    return out


# ─────────────────────────────────────────────────────────────────
# 사실 계산 (순수 함수)
# ─────────────────────────────────────────────────────────────────


def ma_distances(closes: list[float]) -> list[dict]:
    """종가와 20/60/120일 평균의 거리 % (위 +, 아래 −). 개수가 모자라면 그 평균만 「자료 부족」."""
    out = []
    for n in MA_DAYS:
        if len(closes) < n:
            out.append({"days": n, "avg": None, "distance_pct": None, "note": "자료 부족"})
            continue
        avg = sum(closes[-n:]) / n
        out.append({"days": n, "avg": round(avg, 4), "distance_pct": round((closes[-1] / avg - 1) * 100, 2), "note": None})
    return out


def split_suspect(closes: list[float]) -> bool:
    c = closes[-(max(MA_DAYS) + 1):]
    return any(c[i - 1] > 0 and abs(c[i] / c[i - 1] - 1) > SPLIT_SUSPECT for i in range(1, len(c)))


def net_pnl_pct(close: float, avg: float, market: str) -> float:
    """매도 비용을 뺀 평단 대비 손익 % (현지 통화 기준 — 미국은 달러)."""
    return (close * (1 - SELL_COST[market]) / avg - 1) * 100


def profit_turn(streak: list[HoldingSnapshot], market: str) -> Optional[dict]:
    """조건 5: 보유 기록(qty>0) 중 직전 행 비용 반영 손익 ≤ 0 이고 그날 행 > 0 인 날. 가장 최근 전환 · 여러 번이면 그때마다 새로 셈."""
    pts = [(s.trade_date, net_pnl_pct(s.close, s.avg_price, market)) for s in streak
           if s.close and s.avg_price and s.avg_price > 0]
    turn = None
    for i in range(1, len(pts)):
        if pts[i - 1][1] <= 0 < pts[i][1]:
            turn = i
    if turn is None:
        return None
    rows_since = len(pts) - 1 - turn
    if rows_since > SHOW_AFTER_TURN_ROWS:
        return None
    return {"turn_date": pts[turn][0], "rows_since": rows_since, "net_pnl_pct": round(pts[-1][1], 2)}


# ─────────────────────────────────────────────────────────────────
# 목표까지 거리 (3단계 · 순수 함수)
# ─────────────────────────────────────────────────────────────────


def weekdays_between(start: date, end: date) -> int:
    """start 다음 날부터 end 까지 평일 수 (end <= start 이면 0). 휴장일은 빼지 않는다."""
    if end <= start:
        return 0
    days = (end - start).days
    full, rem = divmod(days, 7)
    n = full * 5
    d = start + timedelta(days=full * 7)
    for _ in range(rem):
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def need_rise(avg: float, close: float, market: str) -> float:
    """본전까지 필요 상승률 R = avg / (close × (1 − 비용)) − 1 (소수)."""
    return avg / (close * (1 - SELL_COST[market])) - 1


def reflect_hit_prob(r: float, sigma_daily: float, days: int) -> Optional[float]:
    """기울기 0 로그정규에서 기간 안 한 번이라도 +R 에 닿을 확률 (반사 원리) 2(1 − Φ(ln(1+R) / (σ√T)))."""
    if r <= 0 or sigma_daily <= 0 or days <= 0:
        return None
    return 2 * (1 - NormalDist().cdf(math.log(1 + r) / (sigma_daily * math.sqrt(days))))


def sigma_daily(closes: list[float], n: int = MODEL_SIGMA_DAYS) -> Optional[float]:
    """최근 n일 로그 수익 표준편차 (종가 n+1개 필요 · 모자라면 None)."""
    c = closes[-(n + 1):]
    if len(c) < n + 1:
        return None
    return statistics.stdev([math.log(c[i] / c[i - 1]) for i in range(1, len(c))])


def own_history_hit(closes: list[float], r: float, days: int) -> tuple[Optional[float], int]:
    """아무 날에 사서 days 거래일 안 최고 종가가 +R 이상인 날의 비율(0~1)과 표본 수."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(closes) - days - 1
    if n <= 0:
        return None, 0
    a = np.asarray(closes, dtype=float)
    peak = sliding_window_view(a[1:], days).max(axis=1)[:n]
    hits = peak >= a[:n] * (1 + r)
    return float(hits.mean()), int(n)


def drawdown_events(closes: list[float], threshold: float = DRAWDOWN_THRESHOLD) -> list[dict]:
    """고점 대비 −threshold 이하로 처음 내려간 사건. 앞 고점을 회복하면 끝난 사건(걸린 거래일 = 하락 시작 ~ 회복), 못 했으면 진행 중."""
    events, i, n = [], 0, len(closes)
    peak = []
    pk = 0.0
    for c in closes:
        pk = max(pk, c)
        peak.append(pk)
    while i < n:
        if closes[i] / peak[i] - 1 <= -threshold:
            pk, j, trough = peak[i], i, closes[i]
            while j < n and closes[j] < pk:
                trough = min(trough, closes[j])
                j += 1
            events.append({"start_idx": i, "depth": trough / pk - 1, "days": (j - i) if j < n else None})
            i = j
        else:
            i += 1
    return events


def _pct1(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x * 100, 1)


def short_goal(closes_long: list[float], dates_long: list[date], *, avg: float, close: float, market: str,
               days_left: Optional[int]) -> dict:
    """단기: 필요 상승률 · 기간 안 한 번이라도 닿을 가능성(자기 이력 / 변동성 모형 나란히)."""
    r = need_rise(avg, close, market)
    out: dict = {"need_pct": round(r * 100, 2) if r > 0 else None, "above_breakeven": r <= 0,
                 "sigma120_pct": None, "windows": []}
    sig = sigma_daily(closes_long) if closes_long else None
    out["sigma120_pct"] = None if sig is None else round(sig * 100, 2)
    if r <= 0:
        return out
    wins = list(WINDOWS)
    if days_left:
        wins.append(("기한까지", days_left))
    for label, days in wins:
        if closes_long:
            frac, n = own_history_hit(closes_long, r, days)
        else:
            frac, n = None, 0
        note = "자료 없음" if frac is None else ("표본 적음" if n < MIN_OWN_SAMPLE else None)
        own = {"pct": _pct1(frac), "n": n, "note": note}
        prob = reflect_hit_prob(r, sig, days) if sig else None
        model = {"pct": _pct1(prob), "note": None if prob is not None else "자료 없음"}
        diff = None if frac is None or prob is None else round(abs(frac - prob) * 100, 1)  # 반올림 전 값의 차이
        out["windows"].append({"label": label, "days": days, "own": own, "model": model, "diff_pp": diff})
    return out


def long_goal(closes_long: list[float], dates_long: list[date], *, avg: float, close: float) -> dict:
    """장기: 평단까지 여유 · 역대 최고 대비 · 고점 대비 −30% 넘는 하락 사건."""
    out: dict = {"cushion_pct": round((avg / close - 1) * 100, 2), "ath": None, "drawdowns": None}
    if not closes_long:
        return out
    k = max(range(len(closes_long)), key=lambda i: (closes_long[i], dates_long[i]))
    out["ath"] = {"close": closes_long[k], "date": dates_long[k],
                  "from_ath_pct": round((close / closes_long[k] - 1) * 100, 2)}
    ev = drawdown_events(closes_long)
    done = [e["days"] for e in ev if e["days"] is not None]
    ongoing = next((e for e in ev if e["days"] is None), None)
    out["drawdowns"] = {
        "threshold_pct": int(DRAWDOWN_THRESHOLD * 100), "ended": len(done), "recovered": len(done),
        "days_min": min(done) if done else None, "days_max": max(done) if done else None,
        "days_median": statistics.median(done) if done else None,
        "ongoing": None if ongoing is None else {"start": dates_long[ongoing["start_idx"]],
                                                 "depth_pct": round(ongoing["depth"] * 100, 1)},
    }
    return out


def third_layer_lines(market: str) -> dict:
    t = THIRD_LAYER[market]
    return {
        "title": f"과거 비교 ({THIRD_LAYER_PERIOD} 한 기간 · 판정 없음): 본전에 팔기 vs 계속 들고 가며 고점 대비 하락 때 정리",
        "mean": f"평균 {t['mean'][0]:.1f}% / {t['mean'][1]:.1f}%",
        "median_diff": f"중앙값 차이 {t['median_diff']:+.2f}%p",
        "bottom5": f"가장 나쁜 5% {t['bottom5'][0]:.1f}% / {t['bottom5'][1]:.1f}%",
        "sample": f"표본 {t['windows']}창",
        "caveat": f"대형주 표본 · 이 종목 자료 아님 · 두 방법 모두 통과한 규칙 아님 · {DISCLAIMER}",
        "source": THIRD_LAYER_SOURCE,
    }


# ─────────────────────────────────────────────────────────────────
# 카드 만들기 (DB 만 읽음)
# ─────────────────────────────────────────────────────────────────


def _mmdd(d: date) -> str:
    return f"{d.month}/{d.day}"


def _blue_items(market, symbol, ref: dict, closes: list[float]) -> list[dict]:
    items = []
    # ① 크기
    r = ref.get("size")
    if market == "KR":
        if r is None:
            it = {"state": "none", "text": "자료 없음"}
        elif r.value is None:
            it = {"state": "not_met", "text": f"{r.note} · KOSPI 상위 {KR_SIZE_RANK}위 밖", "as_of": r.as_of}
        else:
            it = {"state": "met" if r.value <= KR_SIZE_RANK else "not_met",
                  "text": f"KOSPI 시가총액 {int(r.value)}위 (기준 상위 {KR_SIZE_RANK}위)", "as_of": r.as_of}
    elif symbol.upper() in US_SP100:
        it = {"state": "met", "text": "S&P 100 명단에 있음 (2026-11-08 받음 · 추정)", "as_of": date(2026, 11, 8)}
    elif r is not None and r.value:
        it = {"state": "met" if r.value >= US_SIZE_USD else "not_met",
              "text": f"시가총액 약 {r.value / 1e9:,.0f}억 달러 (기준 1,000억 달러)", "as_of": r.as_of}
    else:
        it = {"state": "none", "text": "자료 없음"}
    items.append({"key": "size", "label": "크기", **it})
    # ② 이익
    r = ref.get("earnings")
    if r is None or r.value is None:
        it = {"state": "none", "text": "자료 없음"}
    else:
        unit = "원" if market == "KR" else "(주당)"
        it = {"state": "met" if r.value > 0 else "not_met",
              "text": f"최근 4분기 이익 합 {'흑자' if r.value > 0 else '적자'} {unit}", "as_of": r.as_of}
    items.append({"key": "earnings", "label": "이익", **it})
    # ③ 흔들림
    own = _vol_pct(closes)
    if market == "KR":
        mr = ref.get("vol_median")
        med, med_as_of = (mr.value, mr.as_of) if mr else (None, None)
    else:
        med, med_as_of = US_VOL_MEDIAN, US_VOL_AS_OF
    if own is None or med is None:
        it = {"state": "none", "text": "자료 없음"}
    else:
        it = {"state": "met" if own <= med else "not_met",
              "text": f"60일 일간 변동성 {own:.2f}% (기준 중앙값 {med:.2f}%)", "as_of": med_as_of}
    items.append({"key": "vol", "label": "흔들림", **it})
    return items


# ─────────────────────────────────────────────────────────────────
# 4단계 · 40주 평균선 — 긴 일봉(swing_long_close)만 읽어 화면 요청 때 계산한다 (외부 호출 없음)
# ─────────────────────────────────────────────────────────────────

def week_friday(d: date) -> date:
    """토~금 한 묶음의 이름 = 그 주 금요일 (pandas W-FRI 와 같음)."""
    return d + timedelta(days=(4 - d.weekday()) % 7)


def ended_weeks(dates: list[date], closes: list[float], local_today: date) -> list[dict]:
    """주 묶음 가운데 끝난 주만. 주 종가 = 묶음의 마지막 자료 날 종가.

    마지막 묶음은 「자료 마지막 날 >= 그 주 금요일」 또는 「현지 오늘 > 그 주 금요일 이고 자료 마지막 날 >= 그 주 월요일」
    일 때만 끝난 주로 본다 (앞 묶음은 뒤 묶음이 있으니 늘 끝남).
    """
    groups: list[dict] = []
    for i, d in enumerate(dates):
        f = week_friday(d)
        if groups and groups[-1]["w"] == f:
            groups[-1]["idx"], groups[-1]["last"] = i, d
        else:
            groups.append({"w": f, "idx": i, "last": d, "c": 0.0})
    for g in groups:
        g["c"] = closes[g["idx"]]
    if groups:
        g = groups[-1]
        f = g["w"]
        if not (g["last"] >= f or (local_today > f and g["last"] >= f - timedelta(days=4))):
            groups.pop()
    return groups


def week_means(weeks: list[dict]) -> list[Optional[float]]:
    """끝난 주 종가 40개 단순평균 (40개 미만이면 None)."""
    c = [w["c"] for w in weeks]
    out: list[Optional[float]] = [None] * len(c)
    if len(c) < WEEK_MA:
        return out
    run = sum(c[:WEEK_MA])
    out[WEEK_MA - 1] = run / WEEK_MA
    for i in range(WEEK_MA, len(c)):
        run += c[i] - c[i - WEEK_MA]
        out[i] = run / WEEK_MA
    return out


def week_sides(weeks: list[dict], means: list[Optional[float]]) -> list[Optional[str]]:
    """주 종가가 선 위(above) · 아래(below). 선이 없거나 같으면 None."""
    out: list[Optional[str]] = []
    for w, m in zip(weeks, means):
        out.append(None if m is None or w["c"] == m else ("above" if w["c"] > m else "below"))
    return out


def streak_count(sides: list[Optional[str]]) -> Optional[int]:
    """끝난 주 전체에서 지금과 같은 쪽이 이어진 주 수 (표시 구간으로 자르지 않음)."""
    if not sides or sides[-1] is None:
        return None
    n = 0
    for s in reversed(sides):
        if s != sides[-1]:
            break
        n += 1
    return n


def week_slope_pct(means: list[Optional[float]]) -> Optional[float]:
    """40주선 기울기 = m[마지막] / m[4주 전] - 1 (끝난 주 44개 미만이면 None)."""
    k = len(means) - 1 - WEEK_SLOPE_BACK
    if k < 0 or means[k] is None or means[-1] is None or means[k] <= 0:
        return None
    return round((means[-1] / means[k] - 1) * 100, 1)


def whipsaw_ratio(flip_weeks: list[int], n_weeks: int, in_window: Callable[[int], bool]) -> Optional[float]:
    """평가 구간 안 바뀜 가운데 4주 이내 다시 바뀐 비율. 뒤 4주를 아직 못 본 마지막 바뀜은 센 쪽에서 뺀다."""
    seen = hit = 0
    for j, k in enumerate(flip_weeks):
        if not in_window(k):
            continue
        nxt = flip_weeks[j + 1] if j + 1 < len(flip_weeks) else None
        if nxt is not None:
            seen += 1
            hit += 1 if nxt - k <= WEEK_WHIPSAW_WEEKS else 0
        elif n_weeks - 1 - k >= WEEK_WHIPSAW_WEEKS:
            seen += 1
    return None if seen == 0 else round(hit / seen * 100, 1)


def week40_check(dates: list[date], closes: list[float], weeks: list[dict], means: list[Optional[float]], *,
                 window_years: float = WEEK_CHECK_YEARS, min_years: float = WEEK_CHECK_MIN_YEARS,
                 cost: float = WEEK_CHECK_COST) -> Optional[dict]:
    """같은 자료로 「선 아래 주에 쉬었다면」과 「그대로」를 나란히 계산 (추정).

    판정 = 끝난 주 종가 > 40주선 · 체결 = 그 주 마지막 자료 날의 다음 거래일 종가 · 첫 판정 전은 쉼 ·
    비용 = 쉬었다 샀다 바뀔 때마다(구간 첫날 이미 들고 있으면 처음 1번 포함) · 그대로는 처음 1번 · 이자 0.
    40주선은 전체 자료로 만들고 평가 구간만 최근 window_years.
    """
    n = len(dates)
    if n < 2 or not any(m is not None for m in means):
        return None
    end = dates[-1]
    try:
        cut = end.replace(year=end.year - int(window_years))
    except ValueError:  # 2/29
        cut = end.replace(year=end.year - int(window_years), day=28)
    e = next((i for i, d in enumerate(dates) if d >= cut), 0)
    years = (end - dates[e]).days / 365.25
    if years < min_years or e >= n - 1:
        return None

    pos_at = [0] * n
    exec_at: dict[int, int] = {}
    for w, m in zip(weeks, means):
        if m is not None and w["idx"] + 1 < n:
            exec_at[w["idx"] + 1] = 1 if w["c"] > m else 0
    pos = 0
    for i in range(n):
        pos = exec_at.get(i, pos)
        pos_at[i] = pos

    rule = [1.0]
    eq, held = 1.0, pos_at[e]
    if held:
        eq *= 1 - cost
    rule.append(eq)
    for i in range(e + 1, n):
        if held:
            eq *= closes[i] / closes[i - 1]
        if pos_at[i] != held:
            eq *= 1 - cost
            held = pos_at[i]
        rule.append(eq)
    hold = [1.0] + [(1 - cost) * closes[i] / closes[e] for i in range(e, n)]

    def mdd(seq: list[float]) -> float:
        peak, worst = seq[0], 0.0
        for v in seq:
            peak = max(peak, v)
            worst = max(worst, 1 - v / peak)
        return worst

    def cagr(v: float) -> float:
        return v ** (1 / years) - 1

    sigs = [None if m is None else (w["c"] > m) for w, m in zip(weeks, means)]
    flips = [k for k in range(1, len(sigs)) if sigs[k] is not None and sigs[k - 1] is not None and sigs[k] != sigs[k - 1]]
    whip = whipsaw_ratio(flips, len(weeks), lambda k: weeks[k]["idx"] >= e)
    return {"from": dates[e], "to": end, "years": round(years, 1), "rule_cagr": _pct1(cagr(rule[-1])),
            "hold_cagr": _pct1(cagr(hold[-1])), "rule_mdd": _pct1(mdd(rule)), "hold_mdd": _pct1(mdd(hold)),
            "whipsaw_pct": whip, "cost_pct": round(cost * 100, 2)}


def build_week40(market: str, dates: list[date], closes: list[float], local_today: date) -> Optional[dict]:
    """카드 칸 week40. 긴 일봉이 없으면 None (화면은 「자료 없음」). 판정 문장은 만들지 않는다."""
    if not dates:
        return None
    weeks = ended_weeks(dates, closes, local_today)
    if not weeks:
        return None
    means = week_means(weeks)
    sides = week_sides(weeks, means)
    last_w, last_m = weeks[-1], means[-1]
    out: dict = {"as_of_week": last_w["w"], "data_last_date": dates[-1], "side": sides[-1], "distance_pct": None,
                 "streak_weeks": streak_count(sides), "slope4w_pct": week_slope_pct(means), "series": [],
                 "check": None, "note": None}
    if last_m is not None:
        out["distance_pct"] = round((last_w["c"] / last_m - 1) * 100, 1)
    else:
        out["note"] = "40주 자료 부족"
    start = max(0, len(weeks) - WEEK_SERIES_KEEP)
    out["series"] = [{"w": weeks[i]["w"], "c": round(weeks[i]["c"], 4),
                      "m": None if means[i] is None else round(means[i], 4)} for i in range(start, len(weeks))]
    if last_m is not None:
        chk = week40_check(dates, closes, weeks, means)
        if chk:
            chk["source"] = WEEK40_SOURCE[market]
        out["check"] = chk
    return out


def _build_goal(market, horizon, avg, last, hr, basis_date, basis_source, long_series, today) -> Optional[dict]:
    """카드 기준 종가(국내 공식 · 미국 토스)와 긴 일봉 표에서 계산한 「목표까지 거리」. 결론 문장은 없다."""
    close_date, close = last
    if avg <= 0 or close <= 0:
        return None
    dates, closes, src = long_series if long_series else ([], [], None)
    goal: dict = {"kind": horizon, "basis": {"close": close, "date": close_date, "source": "krx" if market == "KR" else "toss"},
                  "cost_pct": round(SELL_COST[market] * 100, 3), "disclaimer": DISCLAIMER,
                  "long_series": {"source": src, "from": dates[0], "to": dates[-1], "n": len(dates)} if dates else None}
    if horizon == "short":
        user_deadline = hr.deadline if hr is not None else None
        deadline = user_deadline or default_deadline(basis_date)
        past = deadline is not None and deadline < today
        days_left = None if deadline is None else (0 if past else weekdays_between(today, deadline))
        goal.update(short_goal(closes, dates, avg=avg, close=close, market=market, days_left=days_left))
        goal.update({"deadline": deadline, "deadline_source": "user" if user_deadline else "default",
                     "deadline_basis_date": basis_date if not user_deadline else None,
                     "deadline_basis_source": basis_source if not user_deadline else None,
                     "days_left": days_left, "past_deadline": past, "limits": list(SHORT_LIMITS)})
    else:
        goal.update(long_goal(closes, dates, avg=avg, close=close))
        goal["limits"] = list(LONG_LIMITS)
    return goal


async def build_cards(session, today: date, now: Optional[datetime] = None) -> list[dict]:
    """보유 종목마다 「보유 종목 사실」 카드. 보유 성격이 없으면 보류."""
    from backend.services import real_holdings
    from backend.services.real_holdings import HoldingRow

    from backend.services.real_holdings import _LOCAL_TZ

    now_utc = now or datetime.now(timezone.utc)
    cards: list[dict] = []
    hrows = {(h.market, h.ticker): h for h in (await session.execute(select(HoldingHorizon))).scalars().all()}
    longs: dict[tuple[str, str], tuple[list[date], list[float], str]] = {}
    for r in (await session.execute(select(SwingLongClose).order_by(
            SwingLongClose.market, SwingLongClose.ticker, SwingLongClose.trade_date))).scalars().all():
        e = longs.setdefault((r.market, r.ticker), ([], [], r.source))
        e[0].append(r.trade_date)
        e[1].append(r.close)
    refs: dict[tuple[str, str], dict[str, SwingReference]] = {}
    for r in (await session.execute(select(SwingReference))).scalars().all():
        refs.setdefault((r.market, r.ticker), {})[r.item] = r

    for market in ("KR", "US"):
        for h in await _held(session, market):
            sym = h.symbol
            hr = hrows.get((market, sym))
            horizon = hr.horizon if hr is not None and hr.horizon in HORIZONS else None  # unset 은 null 로 보냄
            card = {"market": market, "symbol": sym, "horizon": horizon, "status": "hold", "hold_reason": None,
                    "deadline": hr.deadline if hr else None, "memo": hr.memo if hr else None, "goal": None, "week40": None,
                    "as_of": None, "close_source": "krx" if market == "KR" else "toss", "ma": [], "peak": None,
                    "blue_chip": None, "source_gap": None, "real_avg": {"status": "hold", "text": "보류 · 판 값 기록 없음"},
                    "profit_turn": None, "disclaimer": DISCLAIMER}
            cards.append(card)
            if horizon is None:
                card["hold_reason"] = "보유 성격을 정하면 보여 드립니다"
                continue

            toss = [(s.trade_date, s.close) for s in (await session.execute(select(HoldingSnapshot).where(
                HoldingSnapshot.symbol == sym, HoldingSnapshot.market == market, HoldingSnapshot.kind == "candle",
                HoldingSnapshot.close.is_not(None)).order_by(HoldingSnapshot.trade_date))).scalars().all()]
            if market == "KR":
                series = [(r.trade_date, r.close) for r in (await session.execute(select(KrOfficialClose).where(
                    KrOfficialClose.ticker == sym).order_by(KrOfficialClose.trade_date))).scalars().all()]
                if not series or (toss and series[-1][0] < toss[-1][0]):
                    card["hold_reason"] = "공식 종가를 아직 받지 못했습니다 (토스 값으로 대신 계산하지 않습니다)"
                    continue
            else:
                series = toss
            closes = [c for _, c in series]
            if len(closes) < MIN_BARS:
                card["hold_reason"] = f"일봉 {len(closes)}개 · {MIN_BARS}개가 쌓이면 보여 드립니다"
                continue
            if split_suspect(closes):
                card["hold_reason"] = "하루 종가 변동이 ±30% 를 넘은 날이 있어 보류합니다 (분할 의심)"
                continue

            card["status"], card["as_of"] = "ok", series[-1][0]
            card["ma"] = ma_distances(closes)
            row = HoldingRow(sym, h.name, market, h.currency or "", h.qty or 0, h.avg_price or 0, h.close,
                             h.market_value, h.purchase_amount or 0, None, None, "computed")
            f = await real_holdings.holding_facts(session, row, today)
            basis_date, basis_source = f["basis_date"], f["basis_source"]
            card["peak"] = {k: f[k] for k in ("from_peak_pct", "peak_close", "peak_date", "peak_complete", "basis_date", "basis_source")}
            ref = dict(refs.get((market, "*"), {}))
            ref.update(refs.get((market, sym), {}))
            items = _blue_items(market, sym, ref, closes)
            card["blue_chip"] = {"met": sum(1 for i in items if i["state"] == "met"), "total": 3, "items": items}

            if market == "KR":
                tmap, dday = dict(toss), series[-1][0]
                if dday in tmap and series[-1][1] > 0:
                    gap = (tmap[dday] / series[-1][1] - 1) * 100
                    card["source_gap"] = {"date": dday, "toss_close": tmap[dday], "official_close": series[-1][1],
                                          "gap_pct": round(gap, 2), "flag": abs(gap) > SOURCE_GAP_PCT}

            if horizon == "short":
                snaps = (await session.execute(select(HoldingSnapshot).where(
                    HoldingSnapshot.symbol == sym, HoldingSnapshot.market == market, HoldingSnapshot.kind == "holding",
                ).order_by(HoldingSnapshot.trade_date))).scalars().all()
                streak: list[HoldingSnapshot] = []
                for s in snaps:
                    streak = [] if (s.qty or 0) <= 0 else streak + [s]
                t = profit_turn(streak, market)
                if t:
                    card["profit_turn"] = {**t, "cost_note": COST_NOTE[market], "layer": third_layer_lines(market)}

            card["goal"] = _build_goal(market, horizon, h.avg_price or 0, series[-1], hr, basis_date, basis_source,
                                       longs.get((market, sym)), today)
            lg = longs.get((market, sym))
            if lg:
                card["week40"] = build_week40(market, lg[0], lg[1], now_utc.astimezone(_LOCAL_TZ[market]).date())
    return cards
