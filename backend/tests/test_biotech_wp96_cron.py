"""WP96 · crontab 줄 덧붙이기 · 기존 세 줄 그대로 · 두 번 실행해도 5줄 (중복 없음)."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXISTING = """# WP69-3g · biotech 서버 파이프
0 7 * * * /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh >> /root/toss-tradebot-mvp/var/biotech/logs/daily.log 2>&1
0 6 * * 1 /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh --aact-weekly-only >> /root/toss-tradebot-mvp/var/biotech/logs/aact-weekly.log 2>&1
0 8 15 * * /bin/bash -c "cd /root/toss-tradebot-mvp && backend/.venv/bin/python -m backend.scripts.biotech_h56_forward_eval --window 60d" >> /root/toss-tradebot-mvp/var/biotech/logs/forward-monthly.log 2>&1
"""


def _merge(cur: Path) -> str:
    return subprocess.run(["bash", str(ROOT / "deploy" / "merge_cron_lines.sh"), str(cur), str(ROOT / "deploy" / "biotech_cron_lines.txt")],
                          check=True, capture_output=True, text=True).stdout


def _entries(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_merge_twice_gives_five_entries_no_duplicates(tmp_path):
    cur = tmp_path / "cron"
    cur.write_text(EXISTING)
    first = _merge(cur)
    cur.write_text(first)
    second = _merge(cur)
    assert len(_entries(first)) == 6 and second == first          # WP99 · 06:30 레딧 묶음 줄 추가
    assert first.startswith(EXISTING)                         # 기존 줄 (주석 포함) 은 순서·내용 그대로
    assert sum("--radar-13d-weekly-only" in ln for ln in _entries(second)) == 1


def test_empty_crontab_gets_two_lines(tmp_path):
    cur = tmp_path / "cron"
    cur.write_text("")
    assert len(_entries(_merge(cur))) == 3


def test_deploy_workflow_calls_merge_and_keeps_existing_restart():
    wf = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "bash deploy/merge_cron_lines.sh /tmp/biotech_cron.cur deploy/biotech_cron_lines.txt" in wf
    assert "systemctl restart tradebot-api tradebot-cron" in wf


def test_missing_trailing_newline_does_not_join_lines(tmp_path):
    cur = tmp_path / "cron"
    cur.write_text(EXISTING.rstrip("\n"))
    assert len(_entries(_merge(cur))) == 6
