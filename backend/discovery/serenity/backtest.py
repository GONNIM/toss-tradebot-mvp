"""Serenity signal → 실 주가 대조 백테스트 · Phase L14 v6 (2026-08-04).

Fable 5 6차 GO 반영:
    - RETURN_WINDOWS = (1, 3, 5, 10, 30, 60, 180) · +1d/+3d 급등 검증 추가
    - entry 기준가 = 다음 거래일 시가 (look-ahead 방지 · v6 §2.7)
    - return_* 컬럼은 raw 저장 (다음 시가 기준 무조정 · v6 D1 이중 차감 제거)
      · entry_with_slippage_price 는 참고 컬럼 · 계산 진입점 아님
    - gap_next_open_pct = (다음 시가 - signal 종가) / signal 종가 × 100
    - delisting_flag heuristic · signal_date+30d 이후 history 종료 감지
    - benchmark_iwm/spy_return_* 병렬 계산 · 초과수익 (표시/판정 계층에서 조정)

파이프라인:
    미처리 signals → yfinance history(signal_date, +200d) →
    entry (다음 거래일 시가) → return_*d (raw) → benchmark forward return 조회 →
    delisting 판정 → SerenityBacktest upsert

주기: 매일 KST 01:00 (v6 §2.2 · scheduler.py).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import not_, select
from sqlalchemy.exc import IntegrityError

from backend.discovery.serenity.benchmark import benchmark_forward_return
from backend.discovery.serenity.constants import SLIPPAGE_PCT
from backend.services.db import get_session
from backend.services.models import SerenityBacktest, SerenitySignal
from backend.services.ticker_map import to_yfinance_symbol

logger = logging.getLogger(__name__)

RETURN_WINDOWS = (1, 3, 5, 10, 30, 60, 180)
BENCHMARK_WINDOWS = (1, 3, 5, 10, 30)
_HISTORY_WINDOW_DAYS = 200
_DELISTING_LOOKBACK_DAYS = 30  # signal_date+30d 이후 history 종료 시 상폐 의심


def _round_pct(base: float, target: float) -> float:
    if base <= 0:
        return 0.0
    return round((target - base) / base * 100, 2)


def _detect_delisting(hist, signal_date) -> bool:
    """상폐 heuristic · signal_date+30d 이후 마지막 close 존재 여부.

    True = signal_date+30d 이후 history 없음 = 상폐/티커 소멸 의심.

    v6 hotfix (2026-08-04): cutoff (signal_date+30d) 가 아직 도래하지 않은 최근 signal 은
    판정 불가 → False. 또한 hist 마지막 date 가 today 근접 (3일 이내) 이면 상장 유지 판정.
    이전 로직은 최근 signal 을 무조건 상폐로 오판했음 (delisting=456/456 사고).
    """
    if hist is None or getattr(hist, "empty", True):
        return True
    try:
        last_date = hist.index[-1].date()
        today = datetime.utcnow().date()
        cutoff = signal_date + timedelta(days=_DELISTING_LOOKBACK_DAYS)
        # cutoff 미도래 · 판정 불가
        if cutoff > today:
            return False
        # hist last 가 today 근접 (yfinance 최신 거래일 반영 지연 감안 3일)
        if (today - last_date).days <= 3:
            return False
        return last_date < cutoff
    except (AttributeError, IndexError):
        return False


def backtest_signal(signal: dict[str, Any], *, ticker_client=None) -> Optional[dict]:
    """개별 signal 백테스트 · yfinance sync 호출.

    signal dict 필요 필드: id · ticker · extracted_at (datetime)
    ticker_client · 테스트 mock 주입 지점.

    반환: SerenityBacktest 생성용 dict.
      · 성공 · return_*/entry/gap/benchmark 채움
      · empty history · None 반환 (실패 카운트)
      · 상폐 감지 · delisting_flag=True + 채울 수 있는 필드만 채움

    v6 D1 원칙: return_* = raw · 다음 시가 기준 무조정. slippage/cost 조정은 판정/표시 계층.
    """
    ticker_raw = signal["ticker"]
    yahoo_symbol = to_yfinance_symbol(ticker_raw)
    signal_at = signal["extracted_at"]
    signal_date = (
        signal_at.date() if isinstance(signal_at, datetime) else datetime.fromisoformat(str(signal_at)).date()
    )
    end_date = signal_date + timedelta(days=_HISTORY_WINDOW_DAYS)

    try:
        if ticker_client is None:
            import yfinance as yf
            stock = yf.Ticker(yahoo_symbol)
        else:
            stock = ticker_client(yahoo_symbol)
        hist = stock.history(start=signal_date.isoformat(), end=end_date.isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning("[serenity] yfinance history 실패 · %s (%s) · %s",
                       ticker_raw, yahoo_symbol, exc)
        return None

    if hist is None or getattr(hist, "empty", True) or len(hist) < 1:
        return None

    try:
        signal_price = float(hist.iloc[0]["Close"])
    except (KeyError, IndexError, ValueError):
        return None
    if signal_price <= 0:
        return None

    delisting = _detect_delisting(hist, signal_date)

    payload: dict[str, Any] = {
        "signal_id": signal["id"],
        "ticker": ticker_raw,
        "signal_date": signal_date.isoformat(),
        "price_at_signal": round(signal_price, 4),
        "entry_next_open_price": None,
        "entry_with_slippage_price": None,
        "gap_next_open_pct": None,
        "delisting_flag": delisting,
    }
    for w in RETURN_WINDOWS:
        payload[f"return_{w}d"] = None

    # entry = 다음 거래일 시가 (index 1) · look-ahead 방지
    if len(hist) >= 2:
        try:
            next_open = float(hist.iloc[1]["Open"])
            if next_open > 0:
                payload["entry_next_open_price"] = round(next_open, 4)
                # 참고 컬럼 · 계산 진입점 아님 (v6 D1)
                payload["entry_with_slippage_price"] = round(next_open * (1 + SLIPPAGE_PCT / 100), 4)
                payload["gap_next_open_pct"] = _round_pct(signal_price, next_open)

                # Forward return · 다음 시가 기준 raw (무조정)
                for days in RETURN_WINDOWS:
                    # index 1 = 다음 거래일 · +days 후 = index 1+days
                    idx = 1 + days
                    if len(hist) > idx:
                        try:
                            future_close = float(hist.iloc[idx]["Close"])
                            payload[f"return_{days}d"] = _round_pct(next_open, future_close)
                        except (KeyError, IndexError, ValueError):
                            continue
        except (KeyError, IndexError, ValueError):
            pass

    return payload


async def _attach_benchmark_returns(payload: dict) -> None:
    """payload 에 benchmark_iwm/spy_return_* 병렬 조회 · in-place mutate."""
    signal_date = payload["signal_date"]
    for symbol_key, symbol in (("iwm", "IWM"), ("spy", "SPY")):
        for days in BENCHMARK_WINDOWS:
            key = f"benchmark_{symbol_key}_return_{days}d"
            try:
                payload[key] = await benchmark_forward_return(symbol, signal_date, days)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[serenity] benchmark fetch 실패 · %s %s %dd · %s",
                             symbol, signal_date, days, exc)
                payload[key] = None


async def load_pending_signals(limit: int = 100) -> list[dict]:
    """SerenityBacktest 미존재 signal 최근순 조회."""
    async with get_session() as session:
        exists_sub = (
            select(SerenityBacktest.signal_id)
            .where(SerenityBacktest.signal_id == SerenitySignal.id)
            .exists()
        )
        stmt = (
            select(SerenitySignal)
            .where(not_(exists_sub))
            .order_by(SerenitySignal.extracted_at.desc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {"id": r.id, "ticker": r.ticker, "extracted_at": r.extracted_at}
        for r in rows
    ]


async def _persist_backtest(payload: dict) -> bool:
    """단일 백테스트 upsert. race 시 update 로 재시도."""
    async with get_session() as session:
        row = SerenityBacktest(
            id=str(uuid.uuid4()),
            signal_id=payload["signal_id"],
            ticker=payload["ticker"],
            signal_date=payload["signal_date"],
            price_at_signal=payload.get("price_at_signal"),
            entry_next_open_price=payload.get("entry_next_open_price"),
            entry_with_slippage_price=payload.get("entry_with_slippage_price"),
            gap_next_open_pct=payload.get("gap_next_open_pct"),
            delisting_flag=payload.get("delisting_flag", False),
            **{f"return_{w}d": payload.get(f"return_{w}d") for w in RETURN_WINDOWS},
            **{f"benchmark_iwm_return_{w}d": payload.get(f"benchmark_iwm_return_{w}d") for w in BENCHMARK_WINDOWS},
            **{f"benchmark_spy_return_{w}d": payload.get(f"benchmark_spy_return_{w}d") for w in BENCHMARK_WINDOWS},
        )
        session.add(row)
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()

    # 이미 있는 signal_id · update
    async with get_session() as s2:
        target = (await s2.execute(
            select(SerenityBacktest).where(SerenityBacktest.signal_id == payload["signal_id"])
        )).scalar_one()
        target.ticker = payload["ticker"]
        target.signal_date = payload["signal_date"]
        target.price_at_signal = payload.get("price_at_signal")
        target.entry_next_open_price = payload.get("entry_next_open_price")
        target.entry_with_slippage_price = payload.get("entry_with_slippage_price")
        target.gap_next_open_pct = payload.get("gap_next_open_pct")
        target.delisting_flag = payload.get("delisting_flag", False)
        for w in RETURN_WINDOWS:
            setattr(target, f"return_{w}d", payload.get(f"return_{w}d"))
        for w in BENCHMARK_WINDOWS:
            setattr(target, f"benchmark_iwm_return_{w}d", payload.get(f"benchmark_iwm_return_{w}d"))
            setattr(target, f"benchmark_spy_return_{w}d", payload.get(f"benchmark_spy_return_{w}d"))
        target.computed_at = datetime.utcnow()
        await s2.commit()
    return True


async def refresh_backtests(
    batch_size: int = 500,
    *,
    concurrency: int = 4,
    ticker_client=None,
    retries: int = 2,
) -> dict:
    """미처리 signals 배치 백테스트 · v6 D1 raw 원칙.

    반환: {"pending": N, "computed": M, "failed": K, "delisting": D}
    """
    pending = await load_pending_signals(limit=batch_size)
    if not pending:
        return {"pending": 0, "computed": 0, "failed": 0, "delisting": 0}

    sem = asyncio.Semaphore(concurrency)
    stats = {"pending": len(pending), "computed": 0, "failed": 0, "delisting": 0}

    async def _one(sig: dict) -> None:
        async with sem:
            payload = None
            for attempt in range(retries + 1):
                payload = await asyncio.to_thread(
                    backtest_signal, sig, ticker_client=ticker_client,
                )
                if payload is not None:
                    break
                if attempt < retries:
                    await asyncio.sleep(1 + attempt)  # 1s, 2s backoff

            if payload is None:
                stats["failed"] += 1
                return

            await _attach_benchmark_returns(payload)

            if payload.get("delisting_flag"):
                stats["delisting"] += 1
            if await _persist_backtest(payload):
                stats["computed"] += 1

    await asyncio.gather(*[_one(s) for s in pending])
    logger.info("[serenity] backtest refresh · %s", stats)
    return stats
