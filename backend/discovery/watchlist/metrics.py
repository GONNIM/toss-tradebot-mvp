"""Watchlist 트레이드 메트릭 · Sprint 2 Week 4 T69.

Sprint 2 DoD 기준 (docs/plans/sniper/02-strategic-pivot-as-is-to-be.md §4):
  · 승률 ≥ 45%
  · R:R 2:1 이상
  · MDD -15% 이내 (자본 대비)
  · Watchlist 실제 급등 (D-day +5%) 비율 ≥ 30%
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional


@dataclass(frozen=True)
class Trade:
    """단일 매매 · entry + exit 완결.

    pnl_pct 는 (exit - entry) / entry (수수료 미반영 · v1).
    """
    ticker: str
    entry_price: float
    exit_price: float
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    reason: Optional[str] = None

    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.exit_price - self.entry_price) / self.entry_price

    @property
    def is_win(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class TradeMetrics:
    """매매 요약 메트릭."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_pnl_pct: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    max_win_pct: float = 0.0
    max_loss_pct: float = 0.0
    mdd_pct: float = 0.0                # equity curve 최대 낙폭 (% · 자본 대비)
    r_r_ratio: float = 0.0              # abs(avg_win) / abs(avg_loss)
    reason_breakdown: dict[str, int] = field(default_factory=dict)


def compute_metrics(trades: Iterable[Trade]) -> TradeMetrics:
    """Trade 리스트 → TradeMetrics.

    equity curve 는 각 trade pnl_pct 를 누적 (compound) · MDD 는 peak-to-trough %.
    """
    lst = [t for t in trades]
    if not lst:
        return TradeMetrics()

    pnls = [t.pnl_pct for t in lst]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    avg_pnl = statistics.mean(pnls) if pnls else 0.0
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    max_win = max(pnls, default=0.0)
    max_loss = min(pnls, default=0.0)

    # equity curve · compound · 시작 1.0
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for p in pnls:
        equity *= (1.0 + p)
        peak = max(peak, equity)
        drawdown = (equity - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, drawdown)

    # R:R
    rr = (avg_win / abs(avg_loss)) if avg_loss < 0 else float("inf") if avg_win > 0 else 0.0
    if rr == float("inf"):
        rr = 999.0

    reason_breakdown: dict[str, int] = {}
    for t in lst:
        key = t.reason or "unknown"
        reason_breakdown[key] = reason_breakdown.get(key, 0) + 1

    return TradeMetrics(
        total_trades=len(lst),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(lst), 4),
        avg_pnl_pct=round(avg_pnl, 4),
        avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4),
        max_win_pct=round(max_win, 4),
        max_loss_pct=round(max_loss, 4),
        mdd_pct=round(mdd, 4),
        r_r_ratio=round(rr, 3),
        reason_breakdown=reason_breakdown,
    )


# ─── Sprint 2 DoD 판정 ─────────────────────────
@dataclass
class DoDCheck:
    """개별 DoD 기준 pass/fail."""
    name: str
    target: str
    actual: str
    passed: bool


@dataclass
class DoDReport:
    """Sprint 2 DoD 전체 요약."""
    metrics: dict[str, Any]
    checks: list[DoDCheck]
    total_pass: bool


def evaluate_dod(metrics: TradeMetrics) -> DoDReport:
    """Sprint 2 DoD 기준 자동 판정."""
    checks: list[DoDCheck] = []

    # 승률 ≥ 45%
    checks.append(DoDCheck(
        name="win_rate", target=">= 45%",
        actual=f"{metrics.win_rate * 100:.1f}%",
        passed=metrics.win_rate >= 0.45 and metrics.total_trades >= 5,
    ))

    # R:R 2:1 이상
    checks.append(DoDCheck(
        name="r_r_ratio", target=">= 2.0",
        actual=f"{metrics.r_r_ratio:.2f}",
        passed=metrics.r_r_ratio >= 2.0 and metrics.total_trades >= 5,
    ))

    # MDD -15% 이내
    checks.append(DoDCheck(
        name="mdd", target="<= -15% (즉, mdd_pct >= -0.15)",
        actual=f"{metrics.mdd_pct * 100:.1f}%",
        passed=metrics.mdd_pct >= -0.15,
    ))

    # 최소 5거래일 시뮬 (총 매매 5건 이상)
    checks.append(DoDCheck(
        name="min_trades", target=">= 5 trades",
        actual=str(metrics.total_trades),
        passed=metrics.total_trades >= 5,
    ))

    total_pass = all(c.passed for c in checks)
    return DoDReport(
        metrics=asdict(metrics),
        checks=checks,
        total_pass=total_pass,
    )
