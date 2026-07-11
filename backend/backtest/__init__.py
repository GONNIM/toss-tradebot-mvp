"""Backtest — v2 트랙 C Phase 3.

과거 시그널 히스토리를 Paper Adapter 로 replay · 승률·평균수익·MDD·샤프 리포트.

스펙: docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §6-3
"""
from .engine import BacktestConfig, BacktestReport, run_backtest

__all__ = ["BacktestConfig", "BacktestReport", "run_backtest"]
