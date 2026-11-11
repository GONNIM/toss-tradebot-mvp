"""1030-03 · 정해진 시각 잡의 늦음 허용 · 건너뜀 감시 · 시각 겹침 (교훈 #3).

10/31~11/06 국회 잡이 매일 1.8~5초 늦어 7일 모두 돌지 않았다.
- 원인 1: misfire_grace_time 을 적지 않아 APScheduler 기본 1초.
- 원인 2: 같은 06:00 에 serenity crawler 의 동기 호출이 이벤트 루프를 막음.
- 원인 3: 건너뛰어도 WARNING 한 줄뿐이라 아무도 몰랐음.
아래 시험이 세 가지를 각각 막는다.
"""
from __future__ import annotations

import ast
import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.services import job_watch
from backend.services.job_watch import GRACE_BEFORE_OPEN, GRACE_DEFAULT, GRACE_MIN

BACKEND = Path(__file__).resolve().parents[1]


# ── 1. 정적 검사: 모든 cron 잡에 늦음 허용이 있다 (앞으로 생길 잡 포함) ─────────────

def _cron_add_job_calls():
    for path in BACKEND.rglob("*.py"):
        if "venv" in path.parts or "tests" in path.parts:
            continue
        src = path.read_text()
        if "add_job" not in src:
            continue
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_job":
                seg = ast.get_source_segment(src, node) or ""
                if '"cron"' in seg or "CronTrigger" in seg:
                    yield path, node


def test_every_cron_job_has_misfire_grace():
    allowed_names = {"GRACE_DEFAULT", "GRACE_BEFORE_OPEN", "grace"}
    bad = []
    count = 0
    for path, node in _cron_add_job_calls():
        count += 1
        kw = {k.arg: k.value for k in node.keywords}
        v = kw.get("misfire_grace_time")
        ok = (
            (isinstance(v, ast.Constant) and isinstance(v.value, int) and v.value >= GRACE_MIN)
            or (isinstance(v, ast.Name) and v.id in allowed_names)
        )
        if not ok:
            bad.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert count >= 40, f"cron add_job 을 {count}개만 찾음 · 검사 방법이 깨졌을 수 있음"
    assert not bad, f"misfire_grace_time 없음/너무 짧음 (≥{GRACE_MIN}초 · job_watch 상수 사용): {bad}"


# ── 2. 등록된 잡의 실제 값 ────────────────────────────────────────────────

def _api_scheduler() -> AsyncIOScheduler:
    from backend.discovery.meme_watch.scheduler import register_meme_jobs
    from backend.discovery.sector_leaders.scheduler import register_monthly_jobs
    from backend.discovery.serenity.scheduler import register_serenity_jobs
    from backend.discovery.watchlist.scheduler import register_watchlist_jobs
    from backend.powderkeg.scheduler import register_powderkeg_jobs
    from backend.principles.scheduler import register_principles_jobs

    s = AsyncIOScheduler(timezone="Asia/Seoul")
    register_monthly_jobs(s)
    register_meme_jobs(s)
    register_watchlist_jobs(s)
    register_powderkeg_jobs(s)
    register_serenity_jobs(s)
    register_principles_jobs(s)
    return s


@pytest.mark.parametrize("job_id,grace", [
    ("watchlist_assembly", GRACE_DEFAULT),
    ("watchlist_finalize", GRACE_BEFORE_OPEN),
    ("watchlist_dart_events_am", GRACE_BEFORE_OPEN),
    ("watchlist_dart_events_pm", GRACE_DEFAULT),
    ("watchlist_rank_daily", GRACE_DEFAULT),
    ("watchlist_rank_rt", GRACE_BEFORE_OPEN),
    ("powderkeg_holding_expiry", GRACE_DEFAULT),
])
def test_registered_grace_values(job_id, grace):
    job = _api_scheduler().get_job(job_id)
    assert job is not None
    assert job.misfire_grace_time == grace
    assert job.coalesce is True


def test_before_open_jobs_finish_before_market_open():
    """늦음 허용을 더해도 08:20 공시 · 08:30 목록이 09:00 개장 실행 전."""
    assert 8 * 60 + 30 + GRACE_BEFORE_OPEN // 60 < 9 * 60
    assert 8 * 60 + 20 + GRACE_BEFORE_OPEN // 60 <= 8 * 60 + 30


def test_cron_service_jobs_have_grace_and_watch():
    from backend.scheduler.cron import build_scheduler

    s = build_scheduler()
    cron_jobs = [j for j in s.get_jobs() if isinstance(j.trigger, CronTrigger)]
    assert len(cron_jobs) >= 10
    for j in cron_jobs:
        assert j.misfire_grace_time == GRACE_DEFAULT, j.id
        assert j.coalesce is True, j.id


# ── 3. 시각 겹침: 같은 프로세스의 정해진 시각 잡은 5분 이상 띄운다 ───────────────

def _expand(expr: str):
    if expr.isdigit():
        return [int(expr)]
    if "-" in expr and all(p.isdigit() for p in expr.split("-")):
        a, b = map(int, expr.split("-"))
        return list(range(a, b + 1))
    return None  # */5 같은 반복 · hour="*" 매시 잡은 겹침 검사에서 뺀다 (예: 매시 :15 트렌드 ↔ 08:15 비용 점검 · grace 로 보호)


def _fixed_times(jobs):
    out = []
    for j in jobs:
        if not isinstance(j.trigger, CronTrigger):
            continue
        f = {x.name: str(x) for x in j.trigger.fields}
        hours, minutes = _expand(f["hour"]), _expand(f["minute"])
        if hours is None or minutes is None or len(minutes) != 1:
            continue
        for h in hours:
            out.append((h * 60 + minutes[0], j.id, f.get("day", "*"), f.get("day_of_week", "*")))
    return out


def _main_py_fixed_times():
    """main.py 안에서 바로 등록하는 cron 잡 (backup_watch · universe · blue_chip)."""
    src = (BACKEND / "api" / "main.py").read_text()
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_job":
            kw = {k.arg: k.value for k in node.keywords}
            if not any(isinstance(a, ast.Constant) and a.value == "cron" for a in node.args):
                continue
            h, m, i = kw["hour"].value, kw["minute"].value, kw["id"].value
            out.append((h * 60 + m, i, "*", "*"))
    assert len(out) >= 3
    return out


_WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _weekdays(expr):
    if expr == "*":
        return set(_WD)
    out = set()
    for part in expr.split(","):
        if "-" in part:
            a, b = part.split("-")
            out |= set(_WD[_WD.index(a):_WD.index(b) + 1])
        else:
            out.add(part)
    return out


def _same_days(d1, w1, d2, w2):
    if d1 != "*" and d2 != "*" and d1 != d2:
        return False   # 다른 날짜의 월간 잡 (11일 · 21일)
    return bool(_weekdays(w1) & _weekdays(w2))


def _too_close(times, gap=5):
    times = sorted(times)
    bad = []
    for i, (t1, id1, d1, w1) in enumerate(times):
        for t2, id2, d2, w2 in times[i + 1:]:
            if t2 - t1 >= gap:
                break
            if id1 != id2 and _same_days(d1, w1, d2, w2):
                bad.append(f"{t1 // 60:02d}:{t1 % 60:02d} {id1} ↔ {t2 // 60:02d}:{t2 % 60:02d} {id2}")
    return bad


def test_api_process_fixed_time_jobs_are_5min_apart():
    times = _fixed_times(_api_scheduler().get_jobs()) + _main_py_fixed_times()
    assert len(times) >= 20
    bad = _too_close(times)
    assert not bad, f"같은 프로세스 정해진 시각 잡이 5분 안에 겹침: {bad}"


def test_cron_process_fixed_time_jobs_are_5min_apart():
    from backend.scheduler.cron import build_scheduler

    bad = _too_close(_fixed_times(build_scheduler().get_jobs()))
    assert not bad, f"cron 서비스 정해진 시각 잡이 5분 안에 겹침: {bad}"


def test_biotech_quotes_job_registered_0845_tue_sat():
    """1111-01 · cron 서비스 08:45 화~토 · 늦음 허용 30분 · 같은 프로세스 잡과 5분 간격은 위 시험이 함께 본다."""
    from backend.scheduler.cron import build_scheduler

    job = build_scheduler().get_job("biotech_quotes")
    assert job is not None and job.misfire_grace_time == GRACE_DEFAULT and job.coalesce is True
    f = {x.name: str(x) for x in job.trigger.fields}
    assert (f["hour"], f["minute"], f["day_of_week"]) == ("8", "45", "tue-sat")


def test_assembly_moved_off_0600():
    job = _api_scheduler().get_job("watchlist_assembly")
    f = {x.name: str(x) for x in job.trigger.fields}
    assert (f["hour"], f["minute"]) == ("6", "10")


# ── 4. 실제 동작: 루프가 2초 막혀도 늦음 허용이 있으면 돈다 · 없으면 건너뛰고 알린다 ──────

async def _run_with_blocked_loop(grace):
    ran, sent = [], []
    job_watch._sent_keys.clear()
    s = AsyncIOScheduler(timezone="Asia/Seoul")
    job_watch.attach_missed_alert(s, process="test", send=lambda t, b, k: sent.append((t, b, k)))
    # 초 단위 cron 이라 마이크로초를 버려도 1초 이상 미래가 되게 2초 뒤
    at = (datetime.now(s.timezone) + timedelta(seconds=2)).replace(microsecond=0)
    kw = {} if grace is None else {"misfire_grace_time": grace}
    s.add_job(lambda: ran.append(1), CronTrigger(hour=at.hour, minute=at.minute, second=at.second,
                                                 timezone="Asia/Seoul"),
              id="blocked_job", name="막힘 시험 잡", **kw)
    s.start()
    await asyncio.sleep(0)
    time.sleep(4.5)          # serenity 동기 호출처럼 이벤트 루프를 막는다 (예정 시각보다 2.5초 이상 넘김)
    await asyncio.sleep(0.5)
    s.shutdown(wait=False)
    return ran, sent


@pytest.mark.asyncio
async def test_blocked_loop_without_grace_skips_and_alerts():
    """기본 1초 → 건너뜀 (11/06 서버와 같은 일) · 감시가 알림 1건을 보낸다."""
    ran, sent = await _run_with_blocked_loop(None)
    assert ran == []
    assert len(sent) == 1
    title, body, key = sent[0]
    assert "건너뜀" in title and "막힘 시험 잡" in body
    assert key.startswith("job_missed:test:blocked_job:")


@pytest.mark.asyncio
async def test_blocked_loop_with_grace_still_runs():
    ran, sent = await _run_with_blocked_loop(GRACE_MIN)
    assert ran == [1]
    assert sent == []


def test_interval_job_miss_is_not_alerted():
    """interval 잡은 다음 회차가 곧 돌므로 알리지 않는다 (11/03~06 하루 수백 건 · 알림 폭주 방지)."""
    sent = []
    s = AsyncIOScheduler(timezone="Asia/Seoul")
    job_watch.attach_missed_alert(s, process="test", send=lambda t, b, k: sent.append(k))
    s.add_job(lambda: None, "interval", seconds=5, id="tick")
    listener = s._listeners[-1][0]

    class _Ev:
        job_id = "tick"
        scheduled_run_time = datetime.now()

    listener(_Ev())
    assert sent == []


def test_same_miss_alerted_once():
    sent = []
    job_watch._sent_keys.clear()
    s = AsyncIOScheduler(timezone="Asia/Seoul")
    job_watch.attach_missed_alert(s, process="test", send=lambda t, b, k: sent.append(k))
    s.add_job(lambda: None, "cron", hour=6, minute=10, id="daily", name="하루 잡")
    listener = s._listeners[-1][0]

    class _Ev:
        job_id = "daily"
        scheduled_run_time = datetime(2026, 11, 6, 6, 10)

    async def _go():
        listener(_Ev())
        listener(_Ev())
        await asyncio.sleep(0)

    asyncio.run(_go())
    assert len(sent) == 1
