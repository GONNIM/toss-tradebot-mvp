"""섹터 판정 문구 · 종류 값 (1101-01) — 사고팔기를 권하는 낱말 없음 · red 두 뜻을 kind 로 가름."""
from __future__ import annotations

import pytest

from backend.discovery.sector_leaders import confluence as cmod
from backend.discovery.sector_leaders.forecast import HistoricalBand, HorizonForecast, compute_verdict

BANNED = ("매수", "매도", "추천", "진입")


def _h(pt, r2=0.3, warn=False):
    return HorizonForecast(
        horizon_months=6, n_samples=30, r_squared=r2, p_value_approx=0.01, hit_rate=0.6,
        alpha=0.0, beta=1.0, rmse=1.0, latest_input_yoy=10.0, point_estimate_pct=pt,
        ci_low_pct=pt - 5, ci_high_pct=pt + 5, sample_warning=warn,
    )


BAND = HistoricalBand(horizon_months=6, n_windows=24, p10_pct=-20.0, p50_pct=0.0, p90_pct=20.0)


@pytest.mark.parametrize("h,band,oos,kind,color", [
    (_h(10, warn=True), BAND, None, "warning", "red"),
    (_h(10), BAND, 0.3, "warning", "red"),
    (_h(30), BAND, 0.6, "neutral", "amber"),
    (_h(-30), BAND, 0.6, "neutral", "amber"),
    (_h(10), BAND, 0.6, "up", "green"),
    (_h(3, r2=0.1), BAND, 0.6, "up", "green"),
    (_h(-10), BAND, 0.6, "down", "red"),
    (_h(0), BAND, 0.6, "neutral", "amber"),
])
def test_verdict_kind_and_wording(h, band, oos, kind, color):
    v = compute_verdict(h, band, oos)
    assert (v.kind, v.color) == (kind, color)
    for w in BANNED:
        assert w not in v.label + v.context + v.action_hint


def _sig(c):
    return cmod.SignalContribution(
        name="x", label="x", raw_value=1.0, raw_label="x", normalized=c, weight=1.0,
        contribution=c, detail="x", direction="bullish" if c > 0 else "bearish" if c < 0 else "neutral",
    )


@pytest.mark.parametrize("score,label", [
    (0.8, "강한 상승 동의"), (0.5, "중간 상승 신호"), (0.0, "혼재 (단독 판단 금지)"),
    (-0.5, "중간 하락 신호"), (-0.8, "강한 하락 동의"),
])
def test_confluence_wording(monkeypatch, score, label):
    monkeypatch.setattr(cmod, "signal_export_yoy", lambda *a, **k: _sig(score))
    for name in ("signal_region_consistency", "signal_stock_momentum", "signal_revision_trend", "signal_customs_interim"):
        monkeypatch.setattr(cmod, name, lambda *a, **k: _sig(0.0))
    r = cmod.compute_confluence(0.0, {}, {}, [])
    assert r.grade_label == label
    for w in ("매수", "매도"):
        assert w not in r.grade_label + r.interpretation
    if score <= -0.7:
        assert "약세 동의" in r.interpretation
