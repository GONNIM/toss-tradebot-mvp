"""섹터 · Crazy · Moonshot · 시스템 경고 문구 (1023-05 Task 6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.services import notifier as nmod
from backend.tests.alert_rules import violations

KST = timezone(timedelta(hours=9))


def _item(rank=1, **kw):
    base = dict(rank=rank, name="원익IPS", ticker="240810", attractiveness=0.612, item="반도체 제조장비",
                price_source="live", current_price=102700.0, entry_price=79714.0,
                entry_status="🟡 22.4% 조정 대기", point_price=118400.0, point_pct=15.3, horizon_months=6)
    base.update(kw)
    return SimpleNamespace(**base)


def test_sector_wording():
    title, body = nmod.format_sector_leaders_alert([_item(1), _item(2, name="B&C"), _item(3)], "0.5", expanded=True)
    assert title == "📊 섹터 리더 · 오늘 상위 3종목"
    assert "1. 원익IPS 102,700원 · 지정가 참고 79,714원 · 통계 추정 6개월 뒤 118,400원 (+15.3%)" in body
    assert "B&amp;C" in body
    assert "참고선까지 22.4% 아래" in body
    assert "보장 아님" in body
    assert violations(title, body) == []


def test_sector_none_fields():
    title, body = nmod.format_sector_leaders_alert(
        [_item(current_price=None, entry_price=None, point_price=None, point_pct=None, entry_status="🔴 과열 관망 (52W 91%)")], "0.6")
    assert "None" not in body
    assert "지정가 참고 —" in body
    assert "과열" in body
    assert violations(title, body) == []


def test_sector_empty():
    title, body = nmod.format_sector_leaders_alert([], "empty")
    assert title == "📊 섹터 리더 · 오늘 기준을 넘은 종목 없음"
    assert violations(title, body) == []


def test_sector_entry_status_prefix_kept():
    it = _item(entry_status="🟢 지금 매수 가능 (ATR 완충 흡수)")
    _, body = nmod.format_sector_leaders_alert([it], "0.6")
    assert "현재가가 지정가 참고선 근처" in body
    assert it.entry_status.startswith("🟢")   # 화면이 쓰는 값은 그대로


def _pick(rank, **kw):
    base = dict(rank=rank, ticker=f"T{rank}", current_price=38.12, market_cap_usd=8.4e9, total_score=78.5,
                thesis="Quantum computing leader with new DARPA contract and more words here")
    base.update(kw)
    return SimpleNamespace(**base)


def test_crazy_top5():
    title, body = nmod.format_crazy_alert([_pick(i) for i in range(1, 11)])
    assert title.startswith("🎯 Crazy 종목 · ") and title.endswith("상위 5")
    assert "1. T1 $38.12 · 79점 · Quantum computing leader with" in body
    assert "6. T6" not in body
    assert "나머지 5종목과 분석 전문은 화면에서" in body
    assert violations(title, body) == []


def test_moonshot_wording():
    picks = [_pick(i, current_price=2.14, risk_level="HIGH", manipulation_risk=3, buy_price_market=2.14,
                   buy_price_limit_3pct=2.0758, buy_price_limit_7pct=1.9902, risk_warning="저가주 변동성 높음",
                   thesis="Cannabis M&A catalyst") for i in range(1, 4)]
    title, body = nmod.format_moonshot_alert(picks)
    assert title.startswith("🚀 Moonshot 종목 · ") and title.endswith("상위 3")
    assert "조작 위험 3/5 (높음)" in body
    assert "지정가 참고: 지금 $2.14 · 3% 아래 $2.08 · 7% 아래 $1.99" in body
    assert "M&amp;A" in body
    assert violations(title, body) == []


class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self):
        return self

    async def send_warning(self, title, body, **kw):
        self.calls.append((title, body))
        return True


@pytest.mark.asyncio
async def test_job_failure_next_run(monkeypatch):
    from backend.scheduler import cron

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    monkeypatch.setattr(cron, "_now_utc", lambda: datetime(2026, 10, 23, 7, 0, tzinfo=KST))
    await cron._alert_job_failure("Crazy Picks", httpx.ReadTimeout("t"), 6, 30)
    title, body = rec.calls[0]
    assert title == "⚠️ 시스템 경고 · Crazy 종목 실패"
    assert "원인: 외부 응답 시간 초과 (ReadTimeout)" in body
    assert "다음 실행: 10/24 06:30" in body
    assert violations(title, body) == []


@pytest.mark.asyncio
async def test_sector_0905_failure_next_is_1705(monkeypatch):
    from backend.scheduler import cron

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    monkeypatch.setattr(cron, "_now_utc", lambda: datetime(2026, 10, 23, 9, 6, tzinfo=KST))

    async def boom(slot):
        raise RuntimeError("x")

    monkeypatch.setattr(cron, "run_sector_leaders_alert_job", boom)
    await cron.job_sector_leaders_alert_0905()
    title, body = rec.calls[0]
    assert title == "⚠️ 시스템 경고 · 섹터 리더 09:05 실패"
    assert "다음 실행: 10/23 17:05" in body


@pytest.mark.asyncio
async def test_job_failure_without_time_omits_line(monkeypatch):
    from backend.scheduler import cron

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    await cron._alert_job_failure("Crazy Picks", ValueError("x"))
    assert "다음 실행" not in rec.calls[0][1]


@pytest.mark.asyncio
async def test_job_failure_dedupe_key_unchanged(monkeypatch):
    from backend.scheduler import cron

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    monkeypatch.setattr(cron, "_failure_alerted", {})
    await cron._alert_job_failure("Crazy Picks", ValueError("x"), 6, 30)
    assert "Crazy Picks" in cron._failure_alerted


@pytest.mark.asyncio
async def test_watch_batch_wording(monkeypatch, tmp_path):
    from backend.services import notifier_profile as npf

    monkeypatch.setattr(npf, "_queue", npf.WatchQueue(tmp_path / "watch.json"))

    sent = []

    async def _send(title, body):
        sent.append((title, body))
        return True

    q = npf.get_watch_queue()
    for src in ("meme_stock", "meme_stock", "activist"):
        q.enqueue(SimpleNamespace(source=src, level="INFO", tags=()), "t", "b")
    await npf.flush_watch_batch(_send)
    title, body = sent[0]
    assert title == "📊 시스템 경고 · 30분 모음 3건"
    assert "밈 2" in body and "행동주의 1" in body
    assert violations(title, body) == []
