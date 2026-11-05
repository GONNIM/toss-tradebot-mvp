"""1105-06 · 백업 지연 알림 (services/backup_watch.py)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from backend.services import backup_watch as bw

KST = ZoneInfo("Asia/Seoul")


def _snap(base, when: datetime, ok: bool = True):
    d = base / when.astimezone(KST).strftime("%Y%m%d_%H%M%S")
    d.mkdir(parents=True)
    if ok:
        (d / ".ok").touch()
    latest = base / "LATEST"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    os.symlink(d.name, latest)
    return d


def test_fresh_backup_ok(tmp_path):
    now = datetime(2026, 11, 6, 0, 10, tzinfo=timezone.utc)      # 09:10 KST
    _snap(tmp_path, now - timedelta(hours=6))                      # 03:10 KST
    assert bw.backup_problem(tmp_path, now) is None


def test_stale_backup_alerts(tmp_path):
    now = datetime(2026, 11, 6, 0, 10, tzinfo=timezone.utc)
    _snap(tmp_path, now - timedelta(hours=37))
    msg = bw.backup_problem(tmp_path, now)
    assert msg and "37시간 전" in msg


def test_missing_latest_alerts(tmp_path):
    msg = bw.backup_problem(tmp_path, datetime.now(tz=timezone.utc))
    assert msg and "LATEST" in msg


def test_latest_without_ok_alerts(tmp_path):
    now = datetime.now(tz=timezone.utc)
    _snap(tmp_path, now - timedelta(hours=1), ok=False)
    assert "성공 표식" in bw.backup_problem(tmp_path, now)


def test_dangling_latest_alerts(tmp_path):
    os.symlink("20990101_000000", tmp_path / "LATEST")
    assert "LATEST" in bw.backup_problem(tmp_path, datetime.now(tz=timezone.utc))


async def test_job_sends_warning(tmp_path, monkeypatch):
    sent = []

    class _N:
        async def send_warning(self, title, body, category=None, dedupe_id=None):
            sent.append((title, category))
            return True

    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr("backend.services.notifier.TelegramNotifier", _N)
    out = await bw.check_backup_fresh()
    assert out["ok"] is False and sent and sent[0][1] == "system"
