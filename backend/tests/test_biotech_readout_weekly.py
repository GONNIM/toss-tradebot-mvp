"""1112-08 · 결과 발표 보충 서버 주간 작업 · 요청은 MockTransport (외부 요청 0) · 날짜는 모두 고정 (교훈 #5)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from backend.scripts import biotech_h48v3_candidates as cand
from backend.scripts import biotech_readout_increment as ri
from backend.scripts.biotech_sec_common import SecDailyLedger

ROOT = Path(__file__).resolve().parents[2]
DOCS_INC = ROOT / "docs" / "plans" / "biotech" / "data" / "h39_readouts_increment.json"
DOCS_INC_SHA = "88adee2ec3cfa9afd6e6ced9ecca2acf824181078466cf814a5fbf1d8dca5e75"
CRON_LINES = ROOT / "deploy" / "biotech_cron_lines.txt"
SERVER_SH = ROOT / "backend" / "scripts" / "biotech_h48v3_daily_server.sh"

# 화요일 22:00 KST = 13:00 UTC · 미국 동부 어제 = 2026-11-30
NOW = datetime(2026, 12, 1, 13, 0, tzinfo=timezone.utc)
BODY_HIT = "ACCEPTANCE-DATETIME>20261120070000\nThe trial met the primary endpoint with statistically significant topline results."
BODY_MISS = "ACCEPTANCE-DATETIME>20261121070000\nOther news."


def _efts(hits):
    return {"hits": {"total": {"value": len(hits)}, "hits": [{"_source": h} for h in hits]}}


def _base(n=2, ticker=True):
    ciks = [f"{i:010d}" for i in range(1, n + 1)]
    ev = [{"cik": ciks[0], "ticker": "AAA" if ticker else "", "accession": "0000000001-26-000001"}]
    return {"processed_ciks": ciks, "events": ev}


class Env:
    """한 번의 22:00 실행 환경 (RUNTIME 폴더 · docs 본 · 가짜 SEC)."""

    def __init__(self, tmp_path: Path, docs_until="2026-11-12"):
        self.rt = tmp_path / "rt"
        self.rt.mkdir(exist_ok=True)
        self.path = self.rt / "h39_readouts_increment.json"
        self.docs = tmp_path / "docs_inc.json"
        self.docs.write_text(json.dumps({"since": "2026-09-02", "until": docs_until, "complete": True,
                                         "events": [{"cik": "0000000009", "accession": "docs-1"}]}))
        self.alerts: list = []
        self.seen: list = []

    def run(self, now=NOW, routes=None, base=None, cap=300, today_fn=None, clear_halt=False, sec_tickers=None, on_request=None):
        routes = routes if routes is not None else {"ciks=": (200, _efts([]))}

        def handler(req: httpx.Request):
            self.seen.append(str(req.url))
            if on_request:
                on_request(req)
            for k, (status, payload) in routes.items():
                if k in str(req.url):
                    return httpx.Response(status, json=payload) if isinstance(payload, dict) else httpx.Response(status, text=payload)
            return httpx.Response(404, text="")

        day = now.astimezone(ri.KST).strftime("%Y%m%d")
        ledger = SecDailyLedger(self.rt / f"sec_usage_{day}.json", day)
        if ledger.path.exists():
            ledger = SecDailyLedger.load(day=day, base=self.rt)
        with httpx.Client(transport=httpx.MockTransport(handler)) as c:
            code = ri.weekly_run(now, self.path, self.docs, base or _base(), ledger,
                                 lambda: ri.make_getter(c, ledger, cap, sleep=lambda s: None, today_fn=today_fn),
                                 lambda cause, lines: self.alerts.append((cause, lines)),
                                 sec_tickers=sec_tickers, cap=cap, clear_halt=clear_halt)
        return code

    def state(self) -> dict:
        return json.loads(self.path.read_text())

    def put(self, d: dict):
        self.path.write_text(json.dumps(d))

    def causes(self):
        return [c for c, _ in self.alerts]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# ─ 기간 순수 함수 ───────────────────────────────────────────────────────────────

def test_plan_period_cases():
    y = date(2026, 11, 30)
    assert ri.plan_period("2026-09-02", "2026-11-12", True, y) == {"action": "new", "since": "2026-11-09", "until": "2026-11-30"}   # 첫 실행 · 11/12 기준
    assert ri.plan_period("2026-11-09", "2026-11-23", True, y)["action"] == "new"             # 정확히 7일 전
    assert ri.plan_period("2026-11-09", "2026-11-24", True, y)["action"] == "idle"            # 6일 전
    assert ri.plan_period("2026-11-09", "2026-11-20", False, y) == {"action": "resume", "since": "2026-11-09", "until": "2026-11-20"}   # 덜 끝남은 같은 기간
    assert ri.plan_period("2026-11-09", "2026-11-10", False, y)["action"] == "resume"          # 얼마나 오래돼도 덜 끝났으면 이어 받기


def test_et_yesterday_uses_us_eastern():
    assert ri.et_yesterday(NOW) == date(2026, 11, 30)
    assert ri.et_yesterday(datetime(2026, 12, 1, 3, 0, tzinfo=timezone.utc)) == date(2026, 11, 29)   # 미국 동부는 아직 11/30 밤


def test_first_server_run_opens_period_from_docs_until(env):
    code = env.run()
    d = env.state()
    assert code == 0 and (d["since"], d["until"]) == ("2026-11-09", "2026-11-30")
    assert d["complete"] is True and d["opened_at"] == "2026-12-01"
    assert d["events"] == []                                     # docs 본 사건은 RUNTIME 본에 복사하지 않음


def test_idle_when_period_done_and_fresh(env):
    env.run()
    env.seen.clear()
    later = NOW + timedelta(days=3)
    assert env.run(now=later) == 0
    assert env.seen == []                                        # 요청 0


# ─ 막음 ① complete ──────────────────────────────────────────────────────────────

def test_complete_false_on_period_rollover_and_before_first_request(env):
    env.run()                                                    # 11/09~11/30 끝남 (True)
    assert env.state()["complete"] is True
    observed = []
    later = NOW + timedelta(days=8)                              # 12/09 22:00 KST → 새 기간 12/06 (11/30−3 = 11/27)~12/08
    env.run(now=later, on_request=lambda r: observed.append(json.loads(env.path.read_text())["complete"]))
    assert observed and observed[0] is False                     # 첫 요청 때 파일에는 False 로 적혀 있음
    d = env.state()
    assert (d["since"], d["until"]) == ("2026-11-27", "2026-12-08") and d["complete"] is True


def test_incomplete_stays_false_and_resumes_same_period(env):
    env.run(routes={"ciks=0000000001": (500, "e"), "ciks=0000000002": (200, _efts([]))})
    d = env.state()
    assert d["complete"] is False and d["processed_ciks"] == ["0000000002"]
    key = "2026-11-09~2026-11-30"
    env.seen.clear()
    assert env.run(now=NOW + timedelta(days=1)) == 0
    assert len(env.seen) == 1 and "0000000001" in env.seen[0]    # 처리한 회사는 건너뛰고 못 한 회사만
    d = env.state()
    assert d["complete"] is True and (d["since"], d["until"]) == ("2026-11-09", "2026-11-30") and key in d["period_stats"]


# ─ 막음 ② last_run_at ───────────────────────────────────────────────────────────

def test_last_run_at_written_even_when_nothing_to_do(env):
    env.run()
    env.run(now=NOW + timedelta(days=2))
    assert env.state()["last_run_at"].startswith("2026-12-03T22:00")
    env.run(now=NOW + timedelta(days=3))
    assert env.state()["last_run_at"].startswith("2026-12-04T22:00")


# ─ 막음 ③ 이미 본 접수번호 ──────────────────────────────────────────────────────

def test_no_keyword_bodies_saved_and_not_refetched_next_period(env):
    routes = {"ciks=0000000001": (200, _efts([{"adsh": "0000000001-26-000010", "items": "8.01", "file_date": "2026-11-20"}])),
              "ciks=0000000002": (200, _efts([])),
              "000000000126000010": (200, BODY_MISS)}
    env.run(routes=routes)
    d = env.state()
    assert d["no_kw_accessions"]["2026-11-09~2026-11-30"] == ["0000000001-26-000010"]
    env.seen.clear()
    env.run(now=NOW + timedelta(days=8), routes=routes)          # 겹친 기간 (11/27~) 에 같은 접수번호가 다시 나옴
    assert not any("000000000126000010" in u for u in env.seen if "efts" not in u)   # 본문을 다시 받지 않음


def test_no_keyword_list_keeps_only_last_two_periods(env):
    d = {"since": "2026-11-09", "until": "2026-11-30", "processed_ciks": [], "events": [], "complete": False,
         "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0}, "opened_at": "2026-12-01",
         "no_kw_accessions": {"2026-10-01~2026-10-10": ["old-1"], "2026-10-20~2026-11-05": ["old-2"]}}
    env.put(d)
    env.run()
    assert sorted(env.state()["no_kw_accessions"]) == ["2026-10-20~2026-11-05", "2026-11-09~2026-11-30"]


def test_known_accessions_cover_wp39_docs_and_runtime(env):
    d = {"since": "2026-11-09", "until": "2026-11-30", "processed_ciks": [], "complete": False, "opened_at": "2026-12-01",
         "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0},
         "events": [{"cik": "0000000001", "accession": "rt-1"}]}
    env.put(d)
    routes = {"ciks=0000000001": (200, _efts([
        {"adsh": "0000000001-26-000001", "items": "8.01"},         # WP39 명부
        {"adsh": "docs-1", "items": "8.01"},                       # docs 본
        {"adsh": "rt-1", "items": "8.01"},                         # RUNTIME 본
    ])), "ciks=0000000002": (200, _efts([]))}
    env.run(routes=routes)
    assert len(env.seen) == 2                                    # EFTS 두 번뿐 · 본문 0


# ─ 티커 · 기간별 통계 ───────────────────────────────────────────────────────────

def test_new_event_ticker_from_sec_list_and_wp39_wins(env):
    routes = {"ciks=0000000001": (200, _efts([{"adsh": "0000000001-26-000020", "items": "8.01", "file_date": "2026-11-20"}])),
              "ciks=0000000002": (200, _efts([{"adsh": "0000000002-26-000021", "items": "7.01", "file_date": "2026-11-21"}])),
              "000000000126000020": (200, BODY_HIT), "000000000226000021": (200, BODY_HIT)}
    env.run(routes=routes, sec_tickers={"0000000001": "ZZZ", "0000000002": "BBB"})
    tk = {e["cik"]: e["ticker"] for e in env.state()["events"]}
    assert tk == {"0000000001": "AAA", "0000000002": "BBB"}


def test_period_stats_kept_per_period(env):
    routes = {"ciks=": (200, _efts([]))}
    env.run(routes=routes)
    env.run(now=NOW + timedelta(days=8), routes=routes)
    ps = env.state()["period_stats"]
    assert set(ps) == {"2026-11-09~2026-11-30", "2026-11-27~2026-12-08"}
    assert ps["2026-11-09~2026-11-30"]["efts_calls"] == 2 and ps["2026-11-27~2026-12-08"]["efts_calls"] == 2


# ─ 장부 ─────────────────────────────────────────────────────────────────────────

def test_ledger_merged_with_other_job_writes(env):
    def other_job(req):                                          # 요청 사이에 다른 잡이 같은 장부 파일에 더함
        led = SecDailyLedger.load(day="20261201", base=env.rt)
        led.add("form4", 1)
        led.save()
    env.run(on_request=other_job)
    led = SecDailyLedger.load(day="20261201", base=env.rt)
    assert led.counts == {"form4": 2, "readout_increment": 2}     # 다른 잡이 더한 2건이 사라지지 않음


def test_cap_checked_before_send_with_plus_one(env):
    led = SecDailyLedger(env.rt / "sec_usage_20261201.json", "20261201")
    led.add("form4", 299)
    led.save()
    env.run()
    assert len(env.seen) == 1                                    # 299 + 1 = 300 까지는 보냄 · 다음은 301 > 300 이라 멈춤
    d = env.state()
    assert d["complete"] is False and d["processed_ciks"] == ["0000000001"]
    assert SecDailyLedger.load(day="20261201", base=env.rt).total() == 300


def test_cap_already_reached_sends_nothing(env):
    led = SecDailyLedger(env.rt / "sec_usage_20261201.json", "20261201")
    led.add("form4", 300)
    led.save()
    assert env.run() == ri.EXIT_CAP and env.seen == []
    assert env.state()["last_run_at"]                            # 요청이 없어도 실행 기록은 남김


def test_stops_when_kst_date_rolls_over(env):
    calls = []

    def today():                                                 # 두 번째 요청 직전에 자정을 넘김
        calls.append(1)
        return "20261201" if len(calls) == 1 else "20261202"

    code = env.run(today_fn=today)
    assert code == ri.EXIT_CAP and len(env.seen) == 1
    assert env.state()["complete"] is False


# ─ 차단 · 알림 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [403, 429])
def test_block_alerts_once_and_two_days_in_a_row_halts(env, status):
    routes = {"ciks=": (status, "blocked")}
    assert env.run(routes=routes) == ri.EXIT_BLOCKED
    assert env.causes() == [f"http_{status}"]
    assert env.run(routes=routes) == ri.EXIT_BLOCKED             # 같은 날 다시 → 같은 원인 알림은 또 가지 않음
    assert env.causes() == [f"http_{status}"]
    code = env.run(now=NOW + timedelta(days=1), routes=routes)   # 이튿날 또 → 자동 멈춤
    assert code == ri.EXIT_BLOCKED and env.state()["halted"] == "2026-12-02"
    assert env.causes() == [f"http_{status}", f"http_{status}", "halted"]
    env.seen.clear()
    assert env.run(now=NOW + timedelta(days=2), routes=routes) == ri.EXIT_HALTED
    assert env.seen == []                                        # 멈춘 뒤에는 요청 0
    assert env.state()["last_run_at"].startswith("2026-12-03")   # 멈춘 날에도 실행 기록은 남김
    assert env.run(now=NOW + timedelta(days=3), routes={"ciks=": (200, _efts([]))}, clear_halt=True) == 0   # 사람이 다시 켬
    assert "halted" not in env.state() and env.seen


def test_block_on_non_consecutive_days_does_not_halt(env):
    routes = {"ciks=": (403, "blocked")}
    env.run(routes=routes)
    env.run(now=NOW + timedelta(days=2), routes=routes)
    assert "halted" not in env.state()


@pytest.mark.parametrize("status", [410, 401])
def test_410_401_alert_immediately(env, status):
    env.run(routes={"ciks=0000000001": (status, "x"), "ciks=0000000002": (200, _efts([]))})
    assert env.causes() == [f"http_{status}"]
    assert env.state()["complete"] is False                      # 그 회사는 처리 목록에 안 넣음


def test_server_errors_two_days_in_a_row_alert(env):
    routes = {"ciks=0000000001": (500, "e"), "ciks=0000000002": (200, _efts([]))}
    env.run(routes=routes)
    assert env.causes() == []
    env.run(now=NOW + timedelta(days=1), routes=routes)
    assert env.causes() == ["errors_2d"]


def test_alert_once_per_day_per_cause_and_no_trade_wording(env):
    d: dict = {}
    sent = []
    today = date(2026, 12, 1)
    assert ri.send_alert_once(d, "http_403", today, lambda c, l: sent.append(l), "HTTP 403")
    assert not ri.send_alert_once(d, "http_403", today, lambda c, l: sent.append(l))
    assert ri.send_alert_once(d, "http_403", today + timedelta(days=1), lambda c, l: sent.append(l))
    assert len(sent) == 2
    for cause in ri.CAUSE_TEXT:
        text = " ".join(ri.CAUSE_TEXT[cause].split())
        assert not re.search(r"매수|매도|사십시오|파십시오|추천|권유|목표가", text)


def test_period_open_over_7_days_alerts_with_progress_and_reason(env):
    d = {"since": "2026-11-09", "until": "2026-11-30", "processed_ciks": [], "events": [], "complete": False,
         "opened_at": "2026-11-23", "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0}}
    env.put(d)
    env.run(routes={"ciks=0000000001": (500, "e"), "ciks=0000000002": (200, _efts([]))})
    assert "stale_open" in env.causes()
    lines = dict(env.alerts)["stale_open"]
    assert any("처리 1/2" in x for x in lines)


def test_persistent_failure_company_dropped_after_7_days(env):
    d = {"since": "2026-11-09", "until": "2026-11-30", "processed_ciks": ["0000000002"], "events": [], "complete": False,
         "opened_at": "2026-11-23", "fail_counts": {"0000000001": 3},
         "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0}}
    env.put(d)
    env.run(routes={"ciks=0000000001": (500, "e")})
    s = env.state()
    assert s["complete"] is True and s["closed_incomplete"] is True and s["abandoned_ciks"] == ["0000000001"]
    assert any("1곳" in x for x in dict(env.alerts)["stale_open"])


def test_broken_runtime_file_not_overwritten(env):
    env.path.write_text("{broken")
    assert env.run() == ri.EXIT_BROKEN
    assert env.path.read_text() == "{broken" and env.seen == []
    assert env.causes() == ["file_broken"]


# ─ 오래됨 점검 ──────────────────────────────────────────────────────────────────

def test_check_stale_alerts_when_until_old_or_run_stopped(env):
    env.run()                                                    # until 11/30 · 마지막 실행 12/01
    notify = lambda c, l: env.alerts.append((c, l))
    env.alerts.clear()
    ri.check_stale(NOW + timedelta(days=2), env.path, env.docs, notify)
    assert env.causes() == []                                    # 12/03 · 3일 이내 · until 3일
    ri.check_stale(NOW + timedelta(days=5), env.path, env.docs, notify)   # 12/06 · 마지막 실행 5일 전 · until 6일
    assert env.causes() == ["stale_run"]
    ri.check_stale(NOW + timedelta(days=5), env.path, env.docs, notify)
    assert env.causes() == ["stale_run"]                         # 같은 날 같은 원인은 한 번
    ri.check_stale(NOW + timedelta(days=11), env.path, env.docs, notify)  # 12/12 · until 12일
    assert "stale_until" in env.causes()


def test_check_stale_without_runtime_file_starts_the_clock(env):
    notify = lambda c, l: env.alerts.append((c, l))
    ri.check_stale(NOW, env.path, env.docs, notify)              # 파일 없음 · docs 본 until 11/12 → 이미 9일 넘음
    assert "stale_until" in env.causes()
    assert env.state()["first_seen_at"].startswith("2026-12-01")
    env.alerts.clear()
    ri.check_stale(NOW + timedelta(days=4), env.path, env.docs, notify)
    assert "stale_run" in env.causes()                           # 22:00 줄이 한 번도 안 돌아도 3일 넘으면 알림


def test_check_stale_makes_no_requests(env, monkeypatch):
    monkeypatch.setattr(ri, "build_client", lambda **k: (_ for _ in ()).throw(AssertionError("요청 금지")))
    ri.check_stale(NOW, env.path, env.docs, lambda c, l: None)


# ─ 잠금 · 서버 전용 · 파일 불변 ─────────────────────────────────────────────────

def test_lock_blocks_second_runner(tmp_path):
    with ri.WeeklyLock(tmp_path / ".lock") as a:
        assert a.acquired
        with ri.WeeklyLock(tmp_path / ".lock") as b:
            assert not b.acquired
    with ri.WeeklyLock(tmp_path / ".lock") as c:
        assert c.acquired                                        # 풀린 뒤에는 다시 잡힘


def test_weekly_main_refuses_without_runtime_dir(monkeypatch):
    monkeypatch.setattr(ri._P, "RUNTIME_DIR", None)
    class A: check_stale = False; weekly = True; clear_halt = False; cap = 300
    assert ri.weekly_main(A()) == ri.EXIT_HALTED                 # 로컬에서 docs 본을 덮어쓰지 않음


def test_docs_increment_file_unchanged():
    assert hashlib.sha256(DOCS_INC.read_bytes()).hexdigest() == DOCS_INC_SHA


# ─ 후보 단계 합쳐 읽기 ──────────────────────────────────────────────────────────

def _cand_dirs(tmp_path, monkeypatch):
    docs, rt = tmp_path / "docs", tmp_path / "rt"
    docs.mkdir()
    rt.mkdir()
    monkeypatch.setattr(cand, "FALLBACK_DIR", docs)
    monkeypatch.setattr(cand, "RUNTIME_DIR", rt)
    monkeypatch.setattr(cand, "DATA_DIR", tmp_path / "nodata")
    (docs / "h39_readouts_checkpoint.json").write_text(json.dumps({"events": [
        {"cik": "0000000001", "accession": "wp39-1", "d_day": "2099-01-01"}]}))
    return docs, rt


def _ev(cik, acc, d="2099-01-01", **kw):
    return {"cik": cik, "accession": acc, "d_day": d, **kw}


def test_candidates_merge_both_files_docs_wins_and_logs_counts(tmp_path, monkeypatch, caplog):
    docs, rt = _cand_dirs(tmp_path, monkeypatch)
    (docs / "h39_readouts_increment.json").write_text(json.dumps({"events": [
        _ev("0000000002", "d-1", direction="positive"), _ev("0000000003", "same", direction="positive")]}))
    (rt / "h39_readouts_increment.json").write_text(json.dumps({"events": [
        _ev("0000000003", "same", direction="negative"),                       # docs 본과 같은 접수번호 → docs 본 우선
        _ev("0000000004", "r-1"), _ev("0000000001", "wp39-1")]}))              # WP39 와 같은 접수번호 → 한 번만
    with caplog.at_level(logging.INFO, logger="biotech_h48v3_candidates"):
        out = cand.source_a_readout("sha")
    by = {o["cik"]: o for o in out}
    assert sorted(by) == ["0000000001", "0000000002", "0000000003", "0000000004"]
    assert by["0000000003"]["direction"] == "positive"
    assert any("docs 본 더한 사건 2" in r.message and "RUNTIME 본 더한 사건 1" in r.message and "합 3" in r.message for r in caplog.records)


@pytest.mark.parametrize("broken", ["docs", "RUNTIME"])
def test_candidates_continue_when_one_file_broken(tmp_path, monkeypatch, broken):
    docs, rt = _cand_dirs(tmp_path, monkeypatch)
    (docs / "h39_readouts_increment.json").write_text(json.dumps({"events": [_ev("0000000002", "d-1")]}))
    (rt / "h39_readouts_increment.json").write_text(json.dumps({"events": [_ev("0000000003", "r-1")]}))
    (docs if broken == "docs" else rt).joinpath("h39_readouts_increment.json").write_text("{broken")
    out = {o["cik"] for o in cand.source_a_readout("sha")}
    assert out == ({"0000000001", "0000000003"} if broken == "docs" else {"0000000001", "0000000002"})


def test_candidates_continue_when_a_file_missing(tmp_path, monkeypatch):
    docs, rt = _cand_dirs(tmp_path, monkeypatch)
    (rt / "h39_readouts_increment.json").write_text(json.dumps({"events": [_ev("0000000003", "r-1")]}))   # docs 본 없음
    assert {o["cik"] for o in cand.source_a_readout("sha")} == {"0000000001", "0000000003"}
    (rt / "h39_readouts_increment.json").unlink()                                                          # 둘 다 없음 · WP39 만
    assert {o["cik"] for o in cand.source_a_readout("sha")} == {"0000000001"}


# ─ cron 줄 · 서버 셸 ────────────────────────────────────────────────────────────

def _cron_minutes(text: str):
    out = []
    for ln in text.splitlines():
        if ln.strip() and not ln.lstrip().startswith("#"):
            m, h = ln.split()[:2]
            out.append((int(h) * 60 + int(m), ln))
    return out


def test_cron_22_line_present_and_apart_from_other_lines():
    lines = _cron_minutes(CRON_LINES.read_text())
    mine = [m for m, ln in lines if "--readout-weekly-only" in ln]
    assert mine == [22 * 60]
    others = [m for m, ln in lines if "--readout-weekly-only" not in ln]
    # 구역 밖 사용자 줄 (07:00 일일 · 월 06:00 AACT · 15일 08:00 forward) 도 함께 본다
    others += [7 * 60, 6 * 60, 8 * 60]
    assert all(abs(m - 22 * 60) >= 60 for m in others)           # 다른 봇 줄과 한 시간 이상 간격
    assert len([1 for _, ln in lines if "readout-weekly.log" in ln]) == 1


def test_server_script_has_weekly_mode_and_stale_check():
    sh = SERVER_SH.read_text()
    assert '"--readout-weekly-only"' in sh and "biotech_readout_increment --weekly" in sh
    assert "biotech_readout_increment --check-stale" in sh
    # 07:00 파이프의 점검은 첫 단계(후보) 앞 · 실패해도 파이프 계속
    assert sh.index("--check-stale") < sh.index('echo "[1/11] candidates"')
    assert re.search(r"--check-stale \|\| echo", sh)
