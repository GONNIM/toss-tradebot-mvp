"""1116-01 · 스위치 파일 · 확인 코드 시험 (실제 텔레그램 · 토스 호출 0 · 시험용 가짜 비밀값만)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.execution.plan import switches as sw
from backend.execution.plan.models import PlanConfirmChallenge, PlanEvent, PlanSwitchAudit
from backend.services.db import get_session
from backend.tests.plan_fakes import plan_db  # noqa: F401

NOW = datetime(2026, 11, 20, 3, 0, 0)     # UTC naive (KST 12:00)
FAKE_HMAC_KEY = "test-only-hmac-key-not-a-secret"


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("PLAN_CONFIRM_HMAC_KEY", FAKE_HMAC_KEY)


class Outbox:
    """보낸 코드를 시험이 읽는다 (실제 발송 없음)."""

    def __init__(self, ok=True):
        self.ok, self.msgs = ok, []

    async def __call__(self, title, body):
        self.msgs.append((title, body))
        return self.ok

    @property
    def code(self):
        return re.search(r"확인 코드: (\d{6})", self.msgs[-1][1]).group(1)


# ── 스위치 파일 ─────────────────────────────────────────────────

def test_missing_and_broken_switch_file_means_off(tmp_path):
    p = tmp_path / "s.json"
    assert sw.read_switches(p)["live"] is False and sw.read_switches(p)["paper"] is False
    p.write_text("{not json")
    assert sw.read_switches(p)["live"] is False
    p.write_text('["live"]')
    assert sw.read_switches(p)["live"] is False
    p.write_text('{"live": "true", "paper": 1}')                      # bool 이 아니면 꺼짐
    assert sw.read_switches(p) == {**sw.read_switches(p), "live": False, "paper": False}
    p.write_text('{"live": true}')
    assert sw.read_switches(p)["live"] is True


async def test_set_switch_atomic_write_audit_and_permission(plan_db, tmp_path):
    p = tmp_path / "plan_switches.json"
    async with get_session() as s:
        old = await sw.set_switch(s, "paper", True, actor="대표(쿠키)", reason="모의 시작", path=p)
        assert old is False and sw.read_switches(p)["paper"] is True and sw.read_switches(p)["live"] is False
        assert (p.stat().st_mode & 0o777) == 0o600
        assert not list(tmp_path.glob(".plan_sw_*"))                    # 임시 파일 남지 않음
        assert await sw.set_switch(s, "paper", False, actor="대표(쿠키)", path=p) is True
        rows = list(await s.scalars(select(PlanSwitchAudit).order_by(PlanSwitchAudit.id)))
        assert [(r.switch, r.old, r.new, r.reason) for r in rows] == [("paper", False, True, "모의 시작"), ("paper", True, False, "")]
    with pytest.raises(ValueError):
        async with get_session() as s:
            await sw.set_switch(s, "bogus", True, actor="x", path=p)


def test_nothing_in_repo_writes_live_on_to_the_switch_file():
    """코드 · 스크립트 · 마이그레이션 · 시험은 스위치 파일에 켜짐을 쓰지 않는다 (쓰는 곳은 switches.py 한 곳)."""
    root = Path(__file__).resolve().parents[1]
    name = "plan_" + "switches"                                          # 이 파일 자신이 걸리지 않게 이름을 쪼갬
    real_path_tokens = ("backend/data/" + name, '"data" / "' + name, "_DEFAULT_" + "PATH")
    offenders = []
    for path in list(root.rglob("*.py")) + list((root.parent / "scripts").rglob("*.py") if (root.parent / "scripts").exists() else []):
        if "venv" in path.parts or path.name == "switches.py":
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        in_tests = "tests" in path.parts
        if not in_tests and name in src:
            offenders.append(f"{path.relative_to(root.parent)} (스위치 파일 이름 언급)")      # 쓰는 곳은 switches.py 한 곳
        if in_tests and path.name != "test_plan_switches.py" and any(t in src for t in real_path_tokens):
            offenders.append(f"{path.relative_to(root.parent)} (실제 스위치 파일 위치 언급)")
        if in_tests and path.name != "test_plan_switches.py" and "PLAN_SWITCH" + "_PATH" not in src and "set_" + "switch(" in src:
            offenders.append(f"{path.relative_to(root.parent)} (임시 위치 없이 스위치 설정)")
    assert not offenders, offenders
    assert "os.replace" in Path(sw.__file__).read_text()                   # 원자적 쓰기
    # 기본 위치는 추적 제외 폴더
    assert str(sw._DEFAULT_PATH).endswith("backend/data/plan_switches.json")


# ── 확인 코드 ───────────────────────────────────────────────────

async def test_correct_code_once_then_reuse_rejected_and_hash_only_stored(plan_db):
    out = Outbox()
    async with get_session() as s:
        cid = await sw.request_challenge(s, action="live_on", send=out, now=NOW)
        code = out.code
        row = await s.get(PlanConfirmChallenge, cid)
        assert code not in row.code_hmac and len(row.code_hmac) == 64         # 해시(HMAC)만
        assert out.msgs[0][0] == "확인 코드 발송"                                # 제목에는 코드 없음
        await sw.verify_challenge(s, challenge_id=cid, code=code, action="live_on", now=NOW)
        with pytest.raises(sw.ConfirmError) as e:
            await sw.verify_challenge(s, challenge_id=cid, code=code, action="live_on", now=NOW)
        assert e.value.reason == "invalid"                                       # 재사용 거부


async def test_constant_time_compare_is_used():
    assert "hmac.compare_digest" in Path(sw.__file__).read_text()


async def test_expired_code_is_rejected_and_not_counted_as_failure(plan_db):
    out = Outbox()
    async with get_session() as s:
        cid = await sw.request_challenge(s, action="live_on", send=out, now=NOW)
        with pytest.raises(sw.ConfirmError) as e:
            await sw.verify_challenge(s, challenge_id=cid, code=out.code, action="live_on", now=NOW + timedelta(minutes=5, seconds=1))
        assert e.value.reason == "expired"
        assert await sw.daily_fail_count(s, NOW) == 0


async def test_five_wrong_codes_invalidate_the_code_even_if_sixth_is_right(plan_db):
    out = Outbox()
    fails = []

    async def on_fail(n):
        fails.append(n)

    async with get_session() as s:
        cid = await sw.request_challenge(s, action="live_on", send=out, now=NOW)
        good = out.code
        bad = "000000" if good != "000000" else "111111"
        for i in range(5):
            with pytest.raises(sw.ConfirmError) as e:
                await sw.verify_challenge(s, challenge_id=cid, code=bad, action="live_on", on_fail=on_fail, now=NOW)
            assert e.value.reason == "wrong"
        assert fails == [1, 2, 3, 4, 5]                                          # 실패마다 ⑨ 알림 호출
        with pytest.raises(sw.ConfirmError) as e:
            await sw.verify_challenge(s, challenge_id=cid, code=good, action="live_on", now=NOW)
        assert e.value.reason == "invalid"


async def test_request_limit_three_per_15_minutes_per_action(plan_db):
    out = Outbox()
    async with get_session() as s:
        for _ in range(3):
            await sw.request_challenge(s, action="live_on", send=out, now=NOW)
        with pytest.raises(sw.ConfirmError) as e:
            await sw.request_challenge(s, action="live_on", send=out, now=NOW + timedelta(minutes=1))
        assert e.value.reason == "rate"
        await sw.request_challenge(s, action="approve", send=out, plan_id=1, revision=1, content_hash="h",
                                   now=NOW + timedelta(minutes=1))                # 동작 종류별로 센다
        await sw.request_challenge(s, action="live_on", send=out, now=NOW + timedelta(minutes=16))


async def test_new_code_invalidates_old_one_for_same_action_and_plan_only(plan_db):
    out = Outbox()
    async with get_session() as s:
        c1 = await sw.request_challenge(s, action="live_on", send=out, now=NOW)
        old = out.code
        a1 = await sw.request_challenge(s, action="approve", send=out, plan_id=1, revision=1, content_hash="h", now=NOW)
        a1_code = out.code
        await sw.request_challenge(s, action="live_on", send=out, now=NOW + timedelta(seconds=5))
        with pytest.raises(sw.ConfirmError) as e:
            await sw.verify_challenge(s, challenge_id=c1, code=old, action="live_on", now=NOW + timedelta(seconds=6))
        assert e.value.reason == "invalid"
        await sw.verify_challenge(s, challenge_id=a1, code=a1_code, action="approve", plan_id=1, revision=1,
                                  content_hash="h", now=NOW + timedelta(seconds=6))   # 다른 동작은 영향 없음


async def test_code_is_bound_to_action_plan_and_revision(plan_db):
    out = Outbox()
    async with get_session() as s:
        cid = await sw.request_challenge(s, action="approve", send=out, plan_id=7, revision=2, content_hash="abc", now=NOW)
        code = out.code
        for kw in ({"action": "live_on", "plan_id": None}, {"action": "adopt", "plan_id": 7},
                   {"action": "approve", "plan_id": 8}, {"action": "resume", "plan_id": 7}):
            with pytest.raises(sw.ConfirmError) as e:
                await sw.verify_challenge(s, challenge_id=cid, code=code, revision=2, content_hash="abc", now=NOW, **kw)
            assert e.value.reason == "mismatch"                                      # 거부만 · 실패로 세지 않음
        assert await sw.daily_fail_count(s, NOW) == 0
        with pytest.raises(sw.ConfirmError) as e:                                    # 값이 바뀜
            await sw.verify_challenge(s, challenge_id=cid, code=code, action="approve", plan_id=7, revision=3,
                                      content_hash="abc", now=NOW)
        assert e.value.reason == "changed"
        with pytest.raises(sw.ConfirmError):                                         # 바뀐 뒤에는 코드 자체가 무효
            await sw.verify_challenge(s, challenge_id=cid, code=code, action="approve", plan_id=7, revision=2,
                                      content_hash="abc", now=NOW)


async def test_daily_failure_lock_counts_all_actions_and_clears_next_kst_day(plan_db):
    out = Outbox()
    async with get_session() as s:
        # 실패 10번 쌓기: 한 코드로 5번씩 두 번 (실거래 켜기 + 승인 합산)
        c1 = await sw.request_challenge(s, action="live_on", send=out, now=NOW + timedelta(hours=1))
        for _ in range(5):
            with pytest.raises(sw.ConfirmError):
                await sw.verify_challenge(s, challenge_id=c1, code="999999" if out.code != "999999" else "888888",
                                          action="live_on", now=NOW + timedelta(hours=1))
        c2 = await sw.request_challenge(s, action="approve", send=out, plan_id=1, revision=1, content_hash="h",
                                        now=NOW + timedelta(hours=1))
        for _ in range(5):
            with pytest.raises(sw.ConfirmError):
                await sw.verify_challenge(s, challenge_id=c2, code="999999" if out.code != "999999" else "888888",
                                          action="approve", plan_id=1, revision=1, content_hash="h",
                                          now=NOW + timedelta(hours=1))
        assert await sw.daily_fail_count(s, NOW + timedelta(hours=2)) == 10
        for action in ("live_on", "approve", "resume", "adopt"):
            with pytest.raises(sw.ConfirmError) as e:
                await sw.request_challenge(s, action=action, send=out, plan_id=1, revision=1, content_hash="h",
                                           now=NOW + timedelta(hours=2))
            assert e.value.reason == "locked"
        # 다음 날(KST 자정 넘김)에는 풀린다 · NOW 는 KST 12:00 → 13시간 뒤가 다음 날 01:00
        await sw.request_challenge(s, action="live_on", send=out, now=NOW + timedelta(hours=13))


async def test_no_key_means_cannot_request_and_send_failure_invalidates(plan_db, monkeypatch):
    async with get_session() as s:
        out = Outbox(ok=False)
        with pytest.raises(sw.ConfirmError) as e:
            await sw.request_challenge(s, action="live_on", send=out, now=NOW)
        assert e.value.reason == "send_failed"                                       # 텔레그램 없음 → 켤 수 없음
        row = (await s.scalars(select(PlanConfirmChallenge))).first()
        assert row.invalid_at is not None
        monkeypatch.delenv("PLAN_CONFIRM_HMAC_KEY")
        from backend.services import config
        monkeypatch.setattr(config, "get", lambda n, d=None: None if n == "PLAN_CONFIRM_HMAC_KEY" else os.environ.get(n, d))
        with pytest.raises(sw.ConfirmError) as e:
            await sw.request_challenge(s, action="live_on", send=Outbox(), now=NOW)
        assert e.value.reason == "no_key"


@pytest.mark.real_notifier_send
async def test_code_is_not_in_notification_log_or_logs(plan_db, monkeypatch, caplog):
    """코드가 알림 기록 · 로그에 남지 않는다 · 하루 요약 모드여도 즉시 보낸다."""
    import logging

    from backend.services import notification_log as nl
    from backend.services import notifier as nmod

    sent, recorded = [], []

    class FakeResp:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            sent.append(json["text"])
            return FakeResp()

    async def fake_record(category, key, title, status, detail=None):
        recorded.append((category, key, title, status, detail))

    monkeypatch.setattr(nmod.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(nl, "record", fake_record)
    n = nmod.TelegramNotifier(nmod.TelegramConfig(bot_token="fake-token", chat_id="1"))
    caplog.set_level(logging.DEBUG)
    async with get_session() as s:
        cid = await sw.request_challenge(s, action="live_on", send=n.send_immediate, now=NOW)
    code = re.search(r"확인 코드: (\d{6})", sent[0]).group(1)
    blob = json.dumps(recorded, ensure_ascii=False) + caplog.text
    assert code not in blob and recorded[0][2] == "확인 코드 발송" and recorded[0][3] == "sent"
    assert recorded[0][0] == "execution"                                          # ⑨ 실주문 범주
