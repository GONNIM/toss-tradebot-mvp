"""Backtest 엔진 — v2 트랙 C Phase 3.

과거 SignalHit 히스토리를 순회 · 각 시그널 시점에 진입 → TP/SL/expire 도달까지 replay.
가격 이력: yfinance 재활용 (기존 discovery 인프라).

리포트 지표:
- 총 트레이드 · 승률 · 평균 수익률 · 평균 손실률
- 총 수익률 · MDD (Max Drawdown) · Sharpe (일간 수익률 기준)
- 시그널 소스별 세부 통계
- 종목별 세부 통계
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from backend.execution.params import get_params_store
from backend.services.db import get_session
from backend.services.models import SignalHit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    days: int = 30                   # 백테스트 기간 (일)
    sources: tuple[str, ...] = ("meme_stock", "vip", "activist")
    tickers: tuple[str, ...] = ()    # 빈 튜플 = 전체
    holding_days: int = 5            # TP/SL 미도달 시 강제 청산 (일)
    take_profit_pct: Optional[float] = None    # None = params store 값 사용
    stop_loss_pct: Optional[float] = None
    fee_rate: float = 0.00015        # KRX 기본 · US 는 fee_rate_us
    fee_rate_us: float = 0.0025


@dataclass
class Trade:
    ticker: str
    source: str
    signal_id: str
    entry_at: datetime
    entry_price: float
    exit_at: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    reason: str = "unresolved"        # tp | sl | expire | no_data


@dataclass
class SourceStats:
    source: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_return_pct: float = 0.0
    avg_return_pct: float = 0.0
    win_rate: float = 0.0


@dataclass
class BacktestReport:
    config: BacktestConfig
    generated_at: datetime
    trades: list[Trade]
    total_trades: int
    win_rate: float
    avg_return_pct: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    by_source: dict[str, SourceStats] = field(default_factory=dict)
    by_ticker: dict[str, SourceStats] = field(default_factory=dict)   # source 필드는 ticker 이름 재활용


# ─── 가격 조회 헬퍼 (실제로는 yfinance 등 사용 · Phase 1 단순 구현) ───
async def _fetch_ohlc(ticker: str, since: datetime, until: datetime) -> list[tuple[datetime, float, float, float, float]]:
    """(datetime, open, high, low, close) tuples · 일봉."""
    # Phase 3 초기 · yfinance 재사용 (동기 API를 blocking으로)
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 미설치 · 백테스트 skip")
        return []
    try:
        # KR 6자리 숫자면 .KS 추가
        symbol = f"{ticker}.KS" if ticker.isdigit() and len(ticker) == 6 else ticker
        end = until + timedelta(days=1)
        df = yf.download(
            symbol,
            start=since.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            return []
        rows: list[tuple[datetime, float, float, float, float]] = []
        for idx, row in df.iterrows():
            # multi-column 이면 첫 column 만
            def _val(name):
                v = row.get(name)
                if hasattr(v, "iloc"):
                    v = v.iloc[0]
                return float(v)
            rows.append((idx.to_pydatetime(), _val("Open"), _val("High"), _val("Low"), _val("Close")))
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("yfinance %s 실패 · %s", ticker, exc)
        return []


# ─── 시뮬레이션 ───
def _resolve_thresholds_for(ticker: str, source: str, cfg: BacktestConfig) -> tuple[float, float]:
    if cfg.take_profit_pct is not None and cfg.stop_loss_pct is not None:
        return cfg.take_profit_pct, cfg.stop_loss_pct
    params = get_params_store().resolve(ticker=ticker, signal_source=source)
    tp = cfg.take_profit_pct if cfg.take_profit_pct is not None else (
        params.take_profit_pct if params.take_profit_pct is not None else 0.05
    )
    sl = cfg.stop_loss_pct if cfg.stop_loss_pct is not None else (
        params.stop_loss_pct if params.stop_loss_pct is not None else -0.03
    )
    return tp, sl


async def _simulate_trade(hit: SignalHit, cfg: BacktestConfig) -> Trade:
    tp, sl = _resolve_thresholds_for(hit.ticker, hit.source, cfg)
    entry_at = hit.hit_at.astimezone(timezone.utc) if hit.hit_at.tzinfo else hit.hit_at.replace(tzinfo=timezone.utc)
    exit_by = entry_at + timedelta(days=cfg.holding_days)
    ohlc = await _fetch_ohlc(hit.ticker, entry_at, exit_by + timedelta(days=1))
    if not ohlc:
        return Trade(
            ticker=hit.ticker,
            source=hit.source,
            signal_id=hit.signal_id,
            entry_at=entry_at,
            entry_price=0.0,
            reason="no_data",
        )

    # 진입: 히트 다음 영업일 open (또는 첫 available)
    entry_bar = None
    for bar in ohlc:
        if bar[0].date() >= entry_at.date():
            entry_bar = bar
            break
    if entry_bar is None:
        return Trade(
            ticker=hit.ticker,
            source=hit.source,
            signal_id=hit.signal_id,
            entry_at=entry_at,
            entry_price=0.0,
            reason="no_data",
        )
    entry_price = entry_bar[1]  # open

    tp_price = entry_price * (1 + tp)
    sl_price = entry_price * (1 + sl)

    for bar_time, o, h, low, close in ohlc:
        if bar_time.date() <= entry_bar[0].date():
            continue
        # SL 우선 판정 (보수적)
        if low <= sl_price:
            exit_price = sl_price
            pnl = exit_price / entry_price - 1.0
            return Trade(
                ticker=hit.ticker, source=hit.source, signal_id=hit.signal_id,
                entry_at=entry_at, entry_price=entry_price,
                exit_at=bar_time, exit_price=exit_price, pnl_pct=pnl, reason="sl",
            )
        if h >= tp_price:
            exit_price = tp_price
            pnl = exit_price / entry_price - 1.0
            return Trade(
                ticker=hit.ticker, source=hit.source, signal_id=hit.signal_id,
                entry_at=entry_at, entry_price=entry_price,
                exit_at=bar_time, exit_price=exit_price, pnl_pct=pnl, reason="tp",
            )
        if bar_time >= exit_by:
            exit_price = close
            pnl = exit_price / entry_price - 1.0
            return Trade(
                ticker=hit.ticker, source=hit.source, signal_id=hit.signal_id,
                entry_at=entry_at, entry_price=entry_price,
                exit_at=bar_time, exit_price=exit_price, pnl_pct=pnl, reason="expire",
            )

    # 데이터 부족 · 마지막 종가 청산
    last = ohlc[-1]
    exit_price = last[4]
    pnl = exit_price / entry_price - 1.0
    return Trade(
        ticker=hit.ticker, source=hit.source, signal_id=hit.signal_id,
        entry_at=entry_at, entry_price=entry_price,
        exit_at=last[0], exit_price=exit_price, pnl_pct=pnl, reason="expire",
    )


# ─── 리포트 집계 ───
def _aggregate(trades: list[Trade]) -> tuple[float, float, float, float]:
    """(win_rate, avg_return, total_return, mdd) — 모두 fraction."""
    resolved = [t for t in trades if t.pnl_pct is not None]
    if not resolved:
        return (0.0, 0.0, 0.0, 0.0)
    wins = sum(1 for t in resolved if t.pnl_pct > 0)
    win_rate = wins / len(resolved)
    avg_return = statistics.fmean(t.pnl_pct for t in resolved)

    # 순차 복리 총수익 (동일 자본 재투자 가정)
    cum = 1.0
    peak = 1.0
    mdd = 0.0
    for t in sorted(resolved, key=lambda x: x.exit_at or x.entry_at):
        cum *= 1.0 + t.pnl_pct
        peak = max(peak, cum)
        dd = cum / peak - 1.0
        mdd = min(mdd, dd)
    return win_rate, avg_return, cum - 1.0, mdd


def _sharpe(trades: list[Trade]) -> float:
    """일간 수익률 근사 · rf=0 · N=len."""
    r = [t.pnl_pct for t in trades if t.pnl_pct is not None]
    if len(r) < 2:
        return 0.0
    mean = statistics.fmean(r)
    stdev = statistics.pstdev(r)
    if stdev == 0:
        return 0.0
    # 연율화 (거래일 252)
    return mean / stdev * math.sqrt(252)


def _by_key(trades: list[Trade], key: str) -> dict[str, SourceStats]:
    grouped: dict[str, list[Trade]] = {}
    for t in trades:
        k = getattr(t, key)
        grouped.setdefault(k, []).append(t)
    stats: dict[str, SourceStats] = {}
    for k, items in grouped.items():
        resolved = [t for t in items if t.pnl_pct is not None]
        wins = sum(1 for t in resolved if t.pnl_pct > 0)
        losses = sum(1 for t in resolved if t.pnl_pct <= 0)
        total = sum(t.pnl_pct for t in resolved)
        avg = statistics.fmean(t.pnl_pct for t in resolved) if resolved else 0.0
        rate = wins / len(resolved) if resolved else 0.0
        stats[k] = SourceStats(
            source=k, trades=len(resolved), wins=wins, losses=losses,
            total_return_pct=total, avg_return_pct=avg, win_rate=rate,
        )
    return stats


# ─── Public ───
async def run_backtest(cfg: BacktestConfig) -> BacktestReport:
    now = datetime.now(tz=timezone.utc)
    since = now - timedelta(days=cfg.days)

    async with get_session() as session:
        stmt = (
            select(SignalHit)
            .where(SignalHit.hit_at >= since)
            .where(SignalHit.action == "buy")
            .where(SignalHit.source.in_(list(cfg.sources)))
            .order_by(SignalHit.hit_at.asc())
        )
        if cfg.tickers:
            stmt = stmt.where(SignalHit.ticker.in_(list(cfg.tickers)))
        hits = (await session.execute(stmt)).scalars().all()

    trades: list[Trade] = []
    for hit in hits:
        trade = await _simulate_trade(hit, cfg)
        trades.append(trade)

    win_rate, avg_return, total_return, mdd = _aggregate(trades)
    sharpe = _sharpe(trades)

    return BacktestReport(
        config=cfg,
        generated_at=now,
        trades=trades,
        total_trades=len(trades),
        win_rate=win_rate,
        avg_return_pct=avg_return,
        total_return_pct=total_return,
        max_drawdown_pct=mdd,
        sharpe=sharpe,
        by_source=_by_key(trades, "source"),
        by_ticker=_by_key(trades, "ticker"),
    )
