"""Serenity · 바이오 알림 문구 (1023-05 Task 9)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import alert_text as at
from backend.services import notifier as nmod
from backend.tests.alert_rules import violations

KST = timezone(timedelta(hours=9))


class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        return self

    async def _add(self, title, body, **kw):
        self.calls.append((title, body))
        return True

    send_info = send_warning = send_critical = _add


@pytest.mark.asyncio
async def test_serenity_success_wording(monkeypatch):
    from backend.discovery.serenity import scheduler as ss

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    await ss._notify_job_result("crawler", {"inserted": 12, "skipped": 4310, "invalid": 0, "total_archive": 4322, "submodule_sha": "9f3c"})
    title, body = rec.calls[0]
    assert title == "📥 Serenity 작업 · 글 수집 끝"
    assert "새로 저장 12 · 건너뜀 4,310" in body
    assert "submodule_sha" not in body and "9f3c" not in body
    assert violations(title, body) == []


@pytest.mark.asyncio
async def test_serenity_failure_next_run(monkeypatch):
    from backend.discovery.serenity import scheduler as ss

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    await ss._notify_job_result("extractor", error="ReadTimeout <x>")
    title, body = rec.calls[0]
    assert title == "⚠️ Serenity 작업 · 신호 추출 실패"
    assert "다음 실행: " in body and "07:00" in body
    assert "&lt;x&gt;" in body
    assert violations(title, body) == []


def test_next_run_weekday():
    # 10/23 (금) → 다음 월요일 06:00 = 10/26
    assert at.next_run(6, 0, now=datetime(2026, 10, 23, 12, 0, tzinfo=KST), weekday=0) == "10/26 06:00"
    # 월요일 05:00 → 같은 날
    assert at.next_run(6, 0, now=datetime(2026, 10, 26, 5, 0, tzinfo=KST), weekday=0) == "10/26 06:00"


def test_biotech_daily_failure_wording():
    from backend.scripts import biotech_notify as bn

    title, body = bn.build_message("critical", "매일 작업 실패 · {step}", "원인: {step} 단계가 오류로 멈춤 (exit 1)",
                                   step="confirm", next_spec="07:00", now=datetime(2026, 10, 23, 7, 5, tzinfo=KST))
    assert title == "🚨 바이오 · 매일 작업 실패 · 확인"
    assert "원인: 확인 단계가 오류로 멈춤 (exit 1)" in body
    assert "다음 실행: 10/24 07:00" in body
    assert "서버" not in body and "로그" not in body
    assert violations(title, body) == []


def test_biotech_notify_weekday_spec():
    from backend.scripts import biotech_notify as bn

    _, body = bn.build_message("warning", "임상시험 주간 자료 실패", "x", next_spec="mon 06:00",
                               now=datetime(2026, 10, 23, 7, 5, tzinfo=KST))
    assert "다음 실행: 10/26 06:00" in body


def test_biotech_aact_failure_wording(monkeypatch):
    from backend.scripts import biotech_h69_aact_weekly as aact

    rec = _Rec()
    monkeypatch.setattr(nmod, "TelegramNotifier", rec)
    aact._notify_failure_sync("download", "3회 재시도 실패 · 2026-10-26")
    title, body = rec.calls[0]
    assert title.startswith("🚨 바이오 · 임상시험 주간 자료 실패")
    assert "다음 실행:" in body and "서버" not in body and "스크립트" not in body
    assert violations(title, body) == []


def test_biotech_radar_inputs_keep_file_names(monkeypatch):
    from backend.scripts import biotech_h46v3_radar as radar

    monkeypatch.setattr(radar._P, "find", lambda *a, **k: None)
    monkeypatch.setattr(radar._P, "find_glob", lambda *a, **k: None)
    sent = []
    missing = radar.check_inputs("abc1234", notify=lambda t, b: sent.append((t, b)))
    title, body = sent[0]
    assert title.startswith("⚠️ 바이오 · 레이더 입력")
    assert all(n in body for n in missing)   # WP94 대조용 원래 이름 유지
    assert violations(title, body) == []
