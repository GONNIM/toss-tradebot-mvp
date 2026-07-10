"""Params override 3층 계층 스위트."""
from __future__ import annotations

from backend.execution.params import (
    ExecutionParams,
    ExecutionParamsStore,
    RiskBudget,
    ThresholdSet,
)


def test_env_fallback_when_no_file(tmp_paths):
    store = ExecutionParamsStore(path=tmp_paths["params"])
    p = store.get()
    # env 기본값 (05 / -03 / 08 / 02)
    assert p.global_.take_profit_pct == 0.05
    assert p.global_.stop_loss_pct == -0.03
    assert p.global_.trailing_arm_pct == 0.08
    assert p.global_.trailing_giveback_pct == 0.02


def test_ticker_override_wins_over_signal_wins_over_global(tmp_paths):
    store = ExecutionParamsStore(path=tmp_paths["params"])
    params = ExecutionParams(
        global_=ThresholdSet(take_profit_pct=0.05, stop_loss_pct=-0.03),
        risk_budget=RiskBudget(),
        tickers={"TICKER-A": ThresholdSet(take_profit_pct=0.10)},
        signals={"meme_stock": ThresholdSet(stop_loss_pct=-0.05)},
    )
    store.save(params)

    # 종목별 > 시그널별 > global
    r = store.resolve(ticker="TICKER-A", signal_source="meme_stock")
    assert r.take_profit_pct == 0.10       # 종목별 최우선
    assert r.stop_loss_pct == -0.05        # 시그널별 (종목별 미지정)


def test_hot_reload_on_file_mtime_change(tmp_paths):
    store = ExecutionParamsStore(path=tmp_paths["params"])
    p1 = store.get()
    assert p1.global_.take_profit_pct == 0.05

    # 파일 직접 변경 후 재조회 → 자동 재로드
    import json
    import time
    time.sleep(0.01)   # mtime 해상도 확보
    tmp_paths["params"].write_text(
        json.dumps({"global": {"take_profit_pct": 0.20}}),
        encoding="utf-8",
    )
    p2 = store.get()
    assert p2.global_.take_profit_pct == 0.20
