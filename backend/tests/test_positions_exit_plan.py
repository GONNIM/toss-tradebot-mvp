"""1027-01 · /positions 청산 계획 「있음」 = 손절가나 목표가가 있을 때 (/account 와 같은 뜻)."""
from datetime import datetime
from types import SimpleNamespace

from backend.api.routes.positions import _build_exit_plan


def _judgment(inv=None, tgt=None, thesis="실적 개선 기대", horizon=30):
    return SimpleNamespace(
        id=7, invalidation_price=inv, target_price=tgt, horizon_days=horizon,
        ts=datetime(2026, 10, 1), thesis_md=thesis,
    )


def test_no_judgment_is_no_plan():
    plan = _build_exit_plan(None, 100.0)
    assert plan.has_plan is False
    assert plan.judgment_id is None


def test_judgment_without_prices_is_no_plan_but_keeps_content():
    plan = _build_exit_plan(_judgment(), 100.0)
    assert plan.has_plan is False
    assert plan.judgment_id == 7
    assert plan.thesis_full == "실적 개선 기대"
    assert plan.deadline == datetime(2026, 10, 31)
    assert plan.trigger_hit is False


def test_stop_only_is_plan():
    assert _build_exit_plan(_judgment(inv=90.0), 100.0).has_plan is True


def test_target_only_is_plan_and_trigger():
    plan = _build_exit_plan(_judgment(tgt=95.0), 100.0)
    assert plan.has_plan is True
    assert plan.trigger_reason == "target_reached"
