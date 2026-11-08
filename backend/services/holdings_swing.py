"""1108-02 · 보유 종목 사실 (스윙 2단계) — 사실만 낸다 (규칙 이름 · 명령문 · 규칙 계산값 없음).

계획: docs/plans/holdings-swing/2026-11-08-plan.md 5절 (사용자 ㉠② ㉡① · 검토 1108-02-07 조건부 GO 조건 1~6).
- 읽기(build_cards)는 DB 만 읽는다 — 화면 요청 때 토스·외부 호출 없음.
- 국내 공식 종가(fill_official_closes)와 대형·대표 기준 값(refresh_references)은 보유 기록 잡(국내 15:50 · 미국 07:10)
  이 끝난 뒤 별도 단계로 이어 받는다 (cron.run_swing_followup). 실패해도 보유 기록은 이미 저장돼 있다.
- 새 정해진 시각 잡 없음 → 교훈 #3 의 네 가지: 늦게 시작 = 기존 잡 설정을 따름 · 같은 시각 = 새 시각 없음 ·
  서버 재시작 = 다음 실행 때 빠진 날 채움(마지막 저장일 다음 날 ~ 오늘) · 실패 = 하루 1회 시스템 경고 + 화면 보류.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend.services.models import (
    HoldingHorizon,
    HoldingSnapshot,
    KrOfficialClose,
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

# 비용 추정 (조건 5 · 계획 4절): 국내 매도 거래세+농특세 0.20% + 수수료 0.015% · 미국 매도 0.1% + 환전 0.1%
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


async def set_horizon(session, market: str, ticker: str, value: str) -> Optional[str]:
    """long / short 저장 · unset 이면 행 삭제(미지정). 저장 뒤 값을 돌려준다."""
    row = (await session.execute(select(HoldingHorizon).where(
        HoldingHorizon.market == market, HoldingHorizon.ticker == ticker))).scalar_one_or_none()
    if value == "unset":
        if row is not None:
            await session.delete(row)
        return None
    if value not in HORIZONS:
        raise ValueError("보유 성격은 long, short, unset 만 가능")
    if row is None:
        session.add(HoldingHorizon(market=market, ticker=ticker, horizon=value, updated_at=_utcnow()))
    else:
        row.horizon = value
        row.updated_at = _utcnow()
    return value


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


async def build_cards(session, today: date) -> list[dict]:
    """보유 종목마다 「보유 종목 사실」 카드. 보유 성격이 없으면 보류."""
    from backend.services import real_holdings
    from backend.services.real_holdings import HoldingRow

    cards: list[dict] = []
    horizons = {(h.market, h.ticker): h.horizon for h in (await session.execute(select(HoldingHorizon))).scalars().all()}
    refs: dict[tuple[str, str], dict[str, SwingReference]] = {}
    for r in (await session.execute(select(SwingReference))).scalars().all():
        refs.setdefault((r.market, r.ticker), {})[r.item] = r

    for market in ("KR", "US"):
        for h in await _held(session, market):
            sym = h.symbol
            horizon = horizons.get((market, sym))
            card = {"market": market, "symbol": sym, "horizon": horizon, "status": "hold", "hold_reason": None,
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
    return cards
