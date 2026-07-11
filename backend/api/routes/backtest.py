"""Backtest API — v2 트랙 C Phase 3."""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Body

from backend.backtest import BacktestConfig, run_backtest

router = APIRouter()


@router.post("/run")
async def run(
    days: int = Body(30, embed=True),
    sources: Optional[list[str]] = Body(None, embed=True),
    tickers: Optional[list[str]] = Body(None, embed=True),
    holding_days: int = Body(5, embed=True),
    take_profit_pct: Optional[float] = Body(None, embed=True),
    stop_loss_pct: Optional[float] = Body(None, embed=True),
):
    cfg = BacktestConfig(
        days=days,
        sources=tuple(sources) if sources else ("meme_stock", "vip", "activist"),
        tickers=tuple(tickers) if tickers else (),
        holding_days=holding_days,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
    )
    report = await run_backtest(cfg)

    return {
        "config": asdict(cfg),
        "generated_at": report.generated_at.isoformat(),
        "summary": {
            "total_trades": report.total_trades,
            "win_rate": report.win_rate,
            "avg_return_pct": report.avg_return_pct,
            "total_return_pct": report.total_return_pct,
            "max_drawdown_pct": report.max_drawdown_pct,
            "sharpe": report.sharpe,
        },
        "by_source": {
            k: {
                "trades": v.trades,
                "wins": v.wins,
                "losses": v.losses,
                "win_rate": v.win_rate,
                "avg_return_pct": v.avg_return_pct,
                "total_return_pct": v.total_return_pct,
            }
            for k, v in report.by_source.items()
        },
        "by_ticker": {
            k: {
                "trades": v.trades,
                "wins": v.wins,
                "losses": v.losses,
                "win_rate": v.win_rate,
                "avg_return_pct": v.avg_return_pct,
                "total_return_pct": v.total_return_pct,
            }
            for k, v in report.by_ticker.items()
        },
        "trades": [
            {
                "ticker": t.ticker,
                "source": t.source,
                "signal_id": t.signal_id,
                "entry_at": t.entry_at.isoformat() if t.entry_at else None,
                "entry_price": t.entry_price,
                "exit_at": t.exit_at.isoformat() if t.exit_at else None,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
                "reason": t.reason,
            }
            for t in report.trades
        ],
    }
