"""WP96 → 1105-06 · crontab 봇 구역 (deploy/merge_cron_lines.sh).

구역 밖 줄 (사용자 줄 · 주석) 은 그대로 · 예전 덧붙이기로 들어간 같은 줄은 구역으로 옮김 · 두 번 실행해도 같음.
안전장치 (Fable 1105-04-01 막음 3): 봇 줄 없음 · 구역 표시 어긋남이면 exit 3 · 아무것도 출력하지 않음.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINES = ROOT / "deploy" / "biotech_cron_lines.txt"
EXISTING = """# WP69-3g · biotech 서버 파이프
0 7 * * * /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh >> /root/toss-tradebot-mvp/var/biotech/logs/daily.log 2>&1
0 6 * * 1 /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh --aact-weekly-only >> /root/toss-tradebot-mvp/var/biotech/logs/aact-weekly.log 2>&1
0 8 15 * * /bin/bash -c "cd /root/toss-tradebot-mvp && backend/.venv/bin/python -m backend.scripts.biotech_h56_forward_eval --window 60d" >> /root/toss-tradebot-mvp/var/biotech/logs/forward-monthly.log 2>&1
"""
BOT = [ln for ln in LINES.read_text().splitlines() if ln.strip()]


def _run(cur: Path, lines: Path = LINES) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(ROOT / "deploy" / "merge_cron_lines.sh"), str(cur), str(lines)],
                          capture_output=True, text=True)


def _merge(cur: Path) -> str:
    r = _run(cur)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _entries(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def test_merge_twice_same_result_user_lines_kept(tmp_path):
    cur = tmp_path / "cron"
    cur.write_text(EXISTING)
    first = _merge(cur)
    cur.write_text(first)
    second = _merge(cur)
    assert second == first                                          # 몇 번 실행해도 같음
    assert len(_entries(first)) == 3 + len(BOT) == 7                # 사용자 3 + 봇 4 (1103-03 백업 줄 포함)
    assert first.startswith(EXISTING)                               # 구역 밖 줄 (주석 포함) 은 순서·내용 그대로
    assert sum("--radar-13d-weekly-only" in ln for ln in _entries(second)) == 1


def test_old_appended_lines_move_into_block(tmp_path):
    """예전 방식 (구역 없이 덧붙임) 의 운영 crontab 8줄 → 사용자 4줄 (주석 포함) + 구역."""
    cur = tmp_path / "cron"
    cur.write_text(EXISTING + "\n".join(BOT) + "\n")
    out = _merge(cur)
    outside, block = out.split("# >>> toss-tradebot", 1)
    assert outside == EXISTING
    assert _entries(block.split("\n", 1)[1]) == BOT                # 표시 줄 다음부터


def test_block_replaced_wholesale(tmp_path):
    """구역 안 옛 줄 (바뀐 봇 줄) 은 지워지고 지금 봇 줄로 바뀜 · 구역 뒤 사용자 줄도 그대로."""
    cur = tmp_path / "cron"
    first = _merge(_write(tmp_path / "c0", EXISTING))
    old = first.replace(BOT[0], "0 6 * * 2 /bin/old-command") + "5 5 * * * user-after\n"
    cur.write_text(old)
    out = _merge(cur)
    assert "/bin/old-command" not in out
    assert "5 5 * * * user-after" in out
    assert len(_entries(out)) == 3 + len(BOT) + 1


def test_empty_crontab_gets_block_only(tmp_path):
    out = _merge(_write(tmp_path / "cron", ""))
    assert _entries(out) == BOT


def test_missing_trailing_newline_does_not_join_lines(tmp_path):
    out = _merge(_write(tmp_path / "cron", EXISTING.rstrip("\n")))
    assert len(_entries(out)) == 7


def test_empty_bot_lines_aborts_and_keeps_crontab(tmp_path):
    r = _run(_write(tmp_path / "cron", EXISTING), _write(tmp_path / "lines", "\n\n"))
    assert r.returncode == 3 and r.stdout == ""


def test_unclosed_block_aborts(tmp_path):
    r = _run(_write(tmp_path / "cron", EXISTING + "# >>> toss-tradebot x\n0 1 * * * old\n"))
    assert r.returncode == 3 and r.stdout == ""


def test_deploy_workflow_guards_and_backs_up():
    wf = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert "if bash deploy/merge_cron_lines.sh /tmp/biotech_cron.cur deploy/biotech_cron_lines.txt > /tmp/biotech_cron.new; then" in wf
    assert "cp /tmp/biotech_cron.cur var/crontab.before" in wf
    assert "systemctl restart tradebot-api tradebot-cron" in wf


def _write(p: Path, text: str) -> Path:
    p.write_text(text)
    return p
