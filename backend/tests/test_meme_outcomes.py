"""1114-03 · 밈 알림 성적판 — 계산 · 요약 · 장부 · 경로 시험 (가짜 종목만 씀)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.services import meme_outcomes as mo
from backend.services.outcomes import Bar, parse_bars

KR = "900001"   # 가짜 국내 코드
US = "ZZTA"     # 가짜 미국 티커
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)   # 모든 시험 봉이 마감된 뒤


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def mk(start: date, closes: list[float], *, opens=None, volume=1000.0, highs=None, lows=None) -> list[Bar]:
    ds = weekdays(start, len(closes))
    opens = opens or closes
    return [Bar(d, c, (lows[i] if lows else min(c, opens[i])), (highs[i] if highs else max(c, opens[i])),
                opens[i], volume) for i, (d, c) in enumerate(zip(ds, closes))]


D0 = date(2026, 9, 7)  # 월


def kr_bars(n=15, base=1000.0, step=10.0):
    closes = [base + step * i for i in range(n)]
    return mk(D0, closes, opens=[c - 2 for c in closes])


def run(bars, *, market="KR", sig=D0 + timedelta(days=3), alert=None, idx=None, ref=None, now=NOW):
    return mo.compute_outcome(
        market=market, signal_date=sig, first_alert_at=alert or datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=5),
        bars=bars, index_bars=idx, ref_latest=ref, now_utc=now)


# ── 기준일 · 진입 · 마감 ───────────────────────────────────────────

def test_estimate_signal_date_kr_and_us():
    assert mo.estimate_signal_date("KR", datetime(2026, 9, 10, 16, 20)) == date(2026, 9, 10)
    assert mo.estimate_signal_date("KR", datetime(2026, 9, 10, 16, 5)) == date(2026, 9, 9)      # 16:10 전 → 전날
    assert mo.estimate_signal_date("KR", datetime(2026, 9, 12, 10, 0)) == date(2026, 9, 11)     # 토요일 → 금
    # 미국: 여름(EDT, UTC-4) · KST 05:30 = ET 16:30 → 그날 / KST 04:30 = ET 15:30 → 전날
    assert mo.estimate_signal_date("US", datetime(2026, 9, 11, 5, 30)) == date(2026, 9, 10)
    assert mo.estimate_signal_date("US", datetime(2026, 9, 11, 4, 30)) == date(2026, 9, 10 - 1)
    # 겨울(EST, UTC-5) · KST 06:30 = ET 16:30 → 그날 / KST 05:30 = ET 15:30 → 전날
    assert mo.estimate_signal_date("US", datetime(2026, 12, 3, 6, 30)) == date(2026, 12, 2)
    assert mo.estimate_signal_date("US", datetime(2026, 12, 3, 5, 30)) == date(2026, 12, 1)


def test_entry_is_first_bar_open_after_alert_time():
    bars = kr_bars()
    sig = bars[3].d   # 기준일 = 목
    # 마감 뒤 알림 → 다음 봉 시가
    r = run(bars, sig=sig, alert=datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=30))
    assert r["entry_date"] == bars[4].d and r["entry_open"] == bars[4].open
    # 장중 알림(기준일은 전날로 잡힘): 이미 지난 그날 시가를 쓰지 않고 다음 봉 시가를 쓴다
    r2 = run(bars, sig=bars[3].d, alert=datetime.combine(bars[4].d, datetime.min.time()).replace(hour=10, minute=0))
    assert r2["entry_date"] == bars[5].d and r2["entry_open"] == bars[5].open
    # 개장 전 알림이면 그날 시가
    r3 = run(bars, sig=bars[3].d, alert=datetime.combine(bars[4].d, datetime.min.time()).replace(hour=8, minute=0))
    assert r3["entry_date"] == bars[4].d


def test_returns_costless_raw_and_window():
    bars = kr_bars(15)
    sig = bars[3].d
    r = run(bars, sig=sig)
    e = bars[4]
    assert r["status"] == "ok" and r["bars_after"] == 10
    assert r["ret_1d"] == pytest.approx(e.close / e.open - 1)
    assert r["ret_3d"] == pytest.approx(bars[6].close / e.open - 1)
    assert r["ret_5d"] == pytest.approx(bars[8].close / e.open - 1)
    assert r["ret_10d"] == pytest.approx(bars[13].close / e.open - 1)
    assert r["signal_close"] == bars[3].close and r["prev_close"] == bars[2].close
    assert r["signal_day_ret"] == pytest.approx(bars[3].close / bars[2].close - 1)
    assert r["max_up"] == pytest.approx(max(b.high for b in bars[4:14]) / e.open - 1)
    assert r["max_down"] == pytest.approx(min(b.low for b in bars[4:14]) / e.open - 1)


def test_pending_until_ten_bars_and_partial_values_kept():
    bars = kr_bars(8)
    r = run(bars, sig=bars[3].d)
    assert r["status"] == "pending" and r["bars_after"] == 4
    assert r["ret_3d"] is not None and r["ret_5d"] is None and r["ret_10d"] is None


def test_only_closed_bars_count_us_et_close():
    # 미국 봉: 현지 16:00 ET 마감 뒤에만. 마지막 봉(09-15)은 ET 15:00 에는 마감 전
    bars = mk(D0, [10, 11, 12, 13, 14, 15, 16], opens=[9.9, 10.9, 11.9, 12.9, 13.9, 14.9, 15.9])
    sig = bars[2].d
    alert = datetime(2026, 9, 10, 8, 0)
    last = bars[-1].d
    et_1500 = datetime.combine(last, datetime.min.time()).replace(hour=15, tzinfo=timezone(timedelta(hours=-4))).astimezone(timezone.utc)
    et_1601 = et_1500 + timedelta(hours=1, minutes=1)
    before = run(bars, market="US", sig=sig, alert=alert, now=et_1500)
    after = run(bars, market="US", sig=sig, alert=alert, now=et_1601)
    assert before["bars_after"] == len(bars) - 3 - 1     # 마감 전 마지막 봉은 쓰지 않음
    assert after["bars_after"] == len(bars) - 3


def test_signal_bar_before_close_is_pending():
    bars = kr_bars(6)
    sig = bars[-1].d
    kst_1500 = datetime.combine(sig, datetime.min.time()).replace(hour=15, tzinfo=timezone(timedelta(hours=9))).astimezone(timezone.utc)
    r = run(bars, sig=sig, now=kst_1500)
    assert r["status"] == "pending" and "마감 전" in r["status_note"]


def test_no_entry_bar_yet_is_pending():
    bars = kr_bars(5)
    r = run(bars, sig=bars[-1].d)
    assert r["status"] == "pending" and r["entry_date"] is None and r["signal_close"] == bars[-1].close


# ── 상태 ───────────────────────────────────────────────────────────

def test_not_buyable_when_open_at_upper_limit():
    base = mk(D0, [10000, 10000, 10000, 10000])        # 기준 봉 종가 10,000 → 상한가 13,000
    nxt = Bar(base[-1].d + timedelta(days=1), 13000, 13000, 13000, 13000, 500.0)
    bars = base + [nxt] + mk(nxt.d + timedelta(days=1), [13000] * 11)
    r = run(bars, sig=base[-1].d)
    assert r["status"] == "not_buyable"
    assert r["ret_1d"] is None and r["ret_5d"] is None


def test_krx_upper_limit_and_tick():
    assert mo.krx_upper_limit(10000) == 13000
    assert mo.krx_upper_limit(12345) == 16040          # 16,048.5 → 10원 단위 내림
    assert mo.krx_upper_limit(100000) == 130000
    assert mo.krx_upper_limit(1000) == 1300
    assert mo.krx_tick(1999) == 1 and mo.krx_tick(4999) == 5 and mo.krx_tick(600000) == 1000


def test_no_trade_when_volume_zero():
    base = mk(D0, [1000, 1000, 1000, 1000])
    zero = Bar(base[-1].d + timedelta(days=1), 1000, 1000, 1000, 1000, 0.0)
    r = run(base + [zero], sig=base[-1].d)
    assert r["status"] == "no_trade" and r["ret_1d"] is None


def test_broken_keeps_values_and_ends():
    bars = kr_bars(8)
    r = run(bars, sig=bars[3].d, ref=bars[-1].d + timedelta(days=3))
    assert r["status"] == "broken" and r["ret_3d"] is not None
    r2 = run(bars, sig=bars[3].d, ref=bars[-1].d)    # 최신일과 같으면 끊김 아님
    assert r2["status"] == "pending"


def test_unavailable_cases():
    bars = kr_bars(15)
    # 기준일 봉이 받은 일봉보다 앞섬 (200봉 밖)
    assert run(bars, sig=bars[0].d - timedelta(days=30))["status"] == "unavailable"
    # 이웃 봉 ±30.5% 넘음
    jump = kr_bars(15)
    jump[6] = Bar(jump[6].d, jump[5].close * 1.4, jump[6].low, jump[6].close * 1.4, jump[6].open, 1000.0)
    assert run(jump, sig=jump[3].d)["status"] == "unavailable"
    # 같은 변동은 미국에서는 검사하지 않음 (국내 규칙)
    assert run(jump, market="US", sig=jump[3].d, alert=datetime(2026, 9, 11, 9, 0))["status"] != "unavailable"
    assert run([], sig=D0)["status"] == "unavailable"


def test_holiday_signal_date_corrected():
    bars = kr_bars(8)
    holiday = bars[3].d + timedelta(days=1)      # 금(거래일)을 휴장으로 가정하려면 봉에서 하나 뺀다
    bars2 = [b for b in bars if b.d != holiday]
    assert mo.corrected_signal_date(bars2, holiday) == bars2[3].d
    assert mo.corrected_signal_date(bars, bars[3].d) == bars[3].d
    assert mo.corrected_signal_date(bars2, bars2[-1].d + timedelta(days=1)) == bars2[-1].d + timedelta(days=1)  # 뒤 봉 없음 → 그대로


def test_index_return_paired_per_row():
    bars = kr_bars(15)
    sig = bars[3].d
    idx = mk(D0, [100 + 2 * i for i in range(15)], opens=[100 + 2 * i - 1 for i in range(15)])
    r = run(bars, sig=sig, idx=idx)
    ie = idx[4]
    assert r["idx_ret_1d"] == pytest.approx(idx[4].close / ie.open - 1)
    assert r["idx_ret_5d"] == pytest.approx(idx[8].close / ie.open - 1)
    assert r["idx_ret_10d"] == pytest.approx(idx[13].close / ie.open - 1)
    # 지수에 그 날짜가 없으면 그 칸만 비움
    idx2 = [b for b in idx if b.d != bars[8].d]
    r2 = run(bars, sig=sig, idx=idx2)
    assert r2["idx_ret_5d"] is None and r2["idx_ret_3d"] is not None
    # 미국은 지수를 비움
    r3 = run(bars, market="US", sig=sig, alert=datetime(2026, 9, 11, 9, 0), idx=idx)
    assert r3["idx_ret_5d"] is None


def test_parse_bars_handles_list_and_dict_and_open_volume():
    c = {"timestamp": "2026-09-10T00:00:00+09:00", "openPrice": "10", "closePrice": "11", "highPrice": "12",
         "lowPrice": "9", "volume": "0"}
    for resp in ({"candles": [c]}, [c]):
        b = parse_bars(resp)[0]
        assert (b.open, b.close, b.volume) == (10.0, 11.0, 0.0)
    assert parse_bars(None) == [] and parse_bars("x") == []
    # 기존 호출 방식 (Bar 4칸) 호환
    assert Bar(date(2026, 1, 1), 1, 1, 1).open is None


# ── 요약 ───────────────────────────────────────────────────────────

def row(i=0, *, market="KR", ret5=0.10, idx5=0.01, status="ok", sd=None, **kw):
    base = dict(
        market=market, status=status, signal_date=sd or date(2026, 9, 1) + timedelta(days=i % 20),
        ticker=f"T{i}", alert_type="BLAZING", score=1.1, signal_day_ret=0.05, send_result=None,
        max_down=-0.05, max_up=0.2, alerts_same_day=1,
        ret_1d=ret5 / 2, ret_3d=ret5, ret_5d=ret5, ret_10d=ret5, idx_ret_1d=idx5, idx_ret_3d=idx5,
        idx_ret_5d=idx5, idx_ret_10d=idx5)
    base.update(kw)
    return SimpleNamespace(**base)


def test_verdict_count_hold_under_30():
    rows = [row(i) for i in range(29)]
    v = mo.verdict_of(rows)
    assert v["label"] == "판정 보류 · 건수 부족" and v["n_paired"] == 29
    assert mo.verdict_of([])["label"] == "판정 보류 · 건수 부족"


def test_verdict_higher_and_none():
    rows = [row(i) for i in range(30)]           # 순 5일 = 0.10-0.0025 > 코스닥 0.01 · 모두 양수
    assert mo.verdict_of(rows)["label"] == "지난 값에서 코스닥보다 높았음"
    low = [row(i, ret5=0.005) for i in range(30)]  # 순 0.0025 < 코스닥 0.01
    assert mo.verdict_of(low)["label"] == "없음 · 코스닥보다 낫다는 근거 없음"
    # 중앙값은 높아도 오른 비율이 50% 이하면 「높았음」 아님
    mixed = [row(i, ret5=0.30) for i in range(14)] + [row(100 + i, ret5=-0.02) for i in range(16)]
    assert mo.verdict_of(mixed)["label"] != "지난 값에서 코스닥보다 높았음"


def test_verdict_hold_when_missing_over_10pct():
    ok = [row(i) for i in range(30)]
    bad = [row(100 + i, status="unavailable", ret_5d=None, ret_1d=None, ret_3d=None, ret_10d=None,
               idx_ret_5d=None) for i in range(4)]   # 4/34 = 11.8%
    v = mo.verdict_of(ok + bad)
    assert v["label"] == "판정 보류 · 빠진 행 많음" and v["missing"] == 4
    few = [row(100 + i, status="unavailable", ret_5d=None, idx_ret_5d=None) for i in range(3)]  # 3/33 = 9.1%
    assert mo.verdict_of(ok + few)["label"] == "지난 값에서 코스닥보다 높았음"
    # 끊김도 빠진 행
    brk = [row(100 + i, status="broken") for i in range(4)]
    assert mo.verdict_of(ok + brk)["label"] == "판정 보류 · 빠진 행 많음"
    # 아직 안 끝난 행(값 없음)은 분모에서 뺀다
    pend = [row(200 + i, status="pending", ret_5d=None, idx_ret_5d=None) for i in range(10)]
    assert mo.verdict_of(ok + few + pend)["label"] == "지난 값에서 코스닥보다 높았음"


def test_summary_hides_cells_under_30_and_counts():
    rows = [row(i) for i in range(30)] + [row(100 + i, alert_type="ERUPTING") for i in range(5)] \
        + [row(200, status="not_buyable", ret_1d=None, ret_3d=None, ret_5d=None, ret_10d=None, idx_ret_5d=None)]
    s = mo.summarize_outcomes(rows, 5)
    cells = {c["label"]: c for bd in s["breakdowns"] for c in bd["cells"] if bd["key"] == "type"}
    assert cells["상승 강도 알림"]["n"] == 5 and cells["상승 강도 알림"]["median"] is None
    assert cells["급등 전 단계 알림"]["median"] == pytest.approx(0.10 - mo.COST)
    assert s["overall"]["n"] == 35 and s["status_counts"]["not_buyable"] == 1
    assert s["period"]["distinct_dates"] >= 1 and s["period"]["alerts"] == 36
    assert s["cost"] == 0.0025
    assert s["overall"]["diff_vs_kosdaq"] == pytest.approx(0.10 - mo.COST - 0.01)
    # 30건 안 되면 코스닥 비교 숫자도 null
    small = mo.summarize_outcomes([row(i) for i in range(10)], 5)
    assert small["overall"]["median"] is None and small["overall"]["diff_vs_kosdaq"] is None
    assert small["kosdaq"]["median"] is None and small["verdict"]["label"] == "판정 보류 · 건수 부족"
    # 쓰이는 낱말 점검 (신호 낱말 · 명령문 없음)
    text = json.dumps(s, ensure_ascii=False)
    for bad in ("골든", "데드", "크로스", "교차", "정배열", "역배열", "사십시오", "매수하십시오"):
        assert bad not in text


def test_summary_era_and_send_split():
    rows = [row(i, send_result="sent") for i in range(30)] + [row(50 + i, send_result="skipped") for i in range(30)] \
        + [row(100 + i) for i in range(5)]
    s = mo.summarize_outcomes(rows, 5)
    era = {c["label"]: c for bd in s["breakdowns"] if bd["key"] == "era" for c in bd["cells"]}
    send = {c["label"]: c for bd in s["breakdowns"] if bd["key"] == "send" for c in bd["cells"]}
    assert era["1114-02 배포 후"]["n"] == 60 and era["1114-02 배포 전"]["n"] == 5
    assert send["보냄"]["n"] == 30 and send["안 보냄(건너뜀·대기)"]["n"] == 30
    assert send["기록 없음(옛 알림)"]["median"] is None


def test_recent_rows_apply_cost():
    out = mo.recent_rows([row(1, ret5=0.10)])
    assert out[0]["ret_5d"] == pytest.approx(0.10 - mo.COST)
    assert out[0]["signal_date"] == date(2026, 9, 2).isoformat()


# ── 속도 제한 그룹 · 잡 등록 ─────────────────────────────────────────

def test_resolve_group_routes_indicator_candles_to_chart():
    from backend.execution.brokers.rate_limiter import resolve_group

    assert resolve_group("/api/v1/market-indicators/KOSDAQ/candles") == "MARKET_INDICATOR_CHART"
    assert resolve_group("/api/v1/market-indicators/KOSPI/candles") == "MARKET_INDICATOR_CHART"
    assert resolve_group("/api/v1/market-indicators/KOSDAQ/price") == "MARKET_INDICATOR"
    assert resolve_group("/api/v1/candles") == "MARKET_DATA_CHART"


def test_job_registered_17_35_mon_sat_with_grace():
    from apscheduler.triggers.cron import CronTrigger

    from backend.scheduler.cron import build_scheduler
    from backend.services.job_watch import GRACE_DEFAULT

    job = build_scheduler().get_job("meme_outcomes_daily")
    assert job is not None and job.coalesce is True and job.misfire_grace_time == GRACE_DEFAULT
    f = {x.name: str(x) for x in job.trigger.fields}
    assert isinstance(job.trigger, CronTrigger)
    assert (f["hour"], f["minute"], f["day_of_week"]) == ("17", "35", "mon-sat")


def test_toss_client_indicator_candles_path_and_validation(monkeypatch):
    from backend.execution.brokers import toss_client as tc

    class Dummy(tc.TossClient):
        def __init__(self):
            pass

        def get(self, path, *, params=None, use_account_header=True):
            self.seen = (path, params, use_account_header)
            return {"candles": []}

    d = Dummy()
    d.indicator_candles("KOSDAQ", 500)
    assert d.seen == ("/api/v1/market-indicators/KOSDAQ/candles", {"interval": "1d", "count": 200}, False)
    with pytest.raises(ValueError):
        d.indicator_candles("../x")


# ── 장부 (DB) ──────────────────────────────────────────────────────

class FakeToss:
    def __init__(self, by: dict, index=None, fail_index=False, fail_all=False):
        self.by, self.index, self.fail_index, self.fail_all = by, index, fail_index, fail_all
        self.calls: list[str] = []
        self.index_calls = 0

    @staticmethod
    def _resp(bars):
        return {"candles": [{"timestamp": f"{b.d}T00:00:00+09:00", "openPrice": str(b.open), "closePrice": str(b.close),
                             "highPrice": str(b.high), "lowPrice": str(b.low), "volume": str(b.volume)}
                            for b in reversed(bars)]}

    def candles(self, symbol, count=200):
        self.calls.append(symbol)
        if self.fail_all or symbol not in self.by:
            raise RuntimeError("없음")
        return self._resp(self.by[symbol])

    def indicator_candles(self, symbol, count=200):
        self.index_calls += 1
        if self.fail_index or self.index is None:
            raise RuntimeError("지수 실패")
        return self._resp(self.index)


@pytest_asyncio.fixture
async def clean():
    from backend.services.db import get_session, init_db
    from backend.services.models import MemeAlertHistory, MemeAlertOutcome, MemeVolumeSnapshot

    await init_db()
    async with get_session() as s:
        for m in (MemeAlertOutcome, MemeAlertHistory, MemeVolumeSnapshot):
            await s.execute(delete(m))
    yield


async def add_alert(ticker, at, *, bar_date=None, market="KRX", send_result="sent", score=1.2):
    from backend.services.db import get_session
    from backend.services.models import MemeAlertHistory

    async with get_session() as s:
        s.add(MemeAlertHistory(ticker=ticker, alert_type="BLAZING", triggered_at=at, payload=json.dumps(
            {"score": score, "intensity": 3.0, "market": market, "bar_date": bar_date, "send_result": send_result})))


async def outcomes():
    from backend.services.db import get_session
    from backend.services.models import MemeAlertOutcome

    async with get_session() as s:
        return (await s.execute(select(MemeAlertOutcome).order_by(MemeAlertOutcome.id))).scalars().all()


@pytest.mark.asyncio
async def test_backfill_idempotent_and_groups_same_day(clean):
    bars = kr_bars(15)
    sig = bars[3].d
    idx = mk(D0, [100 + i for i in range(15)], opens=[99 + i for i in range(15)])
    t1 = datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=20)
    await add_alert(KR, t1, bar_date=sig.isoformat())
    await add_alert(KR, t1 + timedelta(hours=1), bar_date=sig.isoformat())          # 같은 날 두 번째 알림 → 한 행
    await add_alert(KR, datetime(2026, 6, 1, 16, 20), bar_date="2026-06-01")        # 7/03 이전 → 제외
    client = FakeToss({KR: bars}, index=idx)
    out = await mo.run_meme_outcomes(client=client, now=NOW)
    rows = await outcomes()
    assert len(rows) == 1 and out["new"] == 1
    r = rows[0]
    assert r.status == "ok" and r.alerts_same_day == 2 and r.send_result == "sent" and r.score == 1.2
    assert r.first_alert_at == t1 and r.entry_date == bars[4].d and r.idx_ret_5d is not None
    assert client.calls == [KR] and client.index_calls == 1
    # 다시 돌려도 끝난 행은 다시 부르지 않고 새 행도 만들지 않는다
    client2 = FakeToss({KR: bars}, index=idx)
    out2 = await mo.run_meme_outcomes(client=client2, now=NOW)
    assert client2.calls == [] and client2.index_calls == 0 and len(await outcomes()) == 1 and out2["new"] == 0


@pytest.mark.asyncio
async def test_pending_row_continues_next_run(clean):
    bars = kr_bars(15)
    sig = bars[3].d
    await add_alert(KR, datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=20), bar_date=sig.isoformat())
    idx = mk(D0, [100 + i for i in range(15)], opens=[99 + i for i in range(15)])
    await mo.run_meme_outcomes(client=FakeToss({KR: bars[:8]}, index=idx[:8]), now=NOW)
    r = (await outcomes())[0]
    assert r.status == "pending" and r.bars_after == 4 and r.ret_10d is None
    # 지수·종목 모두 같은 최신일이므로 끊김 아님 → 다음 실행에서 이어 채움
    await mo.run_meme_outcomes(client=FakeToss({KR: bars}, index=idx), now=NOW)
    r = (await outcomes())[0]
    assert r.status == "ok" and r.ret_10d is not None and len(await outcomes()) == 1


@pytest.mark.asyncio
async def test_old_row_without_bar_date_uses_snapshot_then_time(clean):
    from backend.services.db import get_session
    from backend.services.models import MemeVolumeSnapshot

    bars = kr_bars(15)
    sig = bars[3].d
    snap_at = datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=0)
    async with get_session() as s:
        s.add(MemeVolumeSnapshot(ticker=KR, snapshot_at=snap_at, volume=1, volume_z_20d=0, return_1d_pct=0,
                                 close=1, bar_date=sig))
    await add_alert(KR, snap_at + timedelta(minutes=30), bar_date=None, send_result=None)   # 옛 행 → 스냅샷 기준일
    # 스냅샷이 없는 다른 종목 옛 행 → 알림 시각 추정 (16:10 전 → 전날)
    await add_alert("900002", datetime.combine(bars[5].d, datetime.min.time()).replace(hour=16, minute=30),
                    bar_date=None, send_result=None)
    await mo.run_meme_outcomes(client=FakeToss({KR: bars, "900002": bars}, index=mk(D0, [100.0] * 15)), now=NOW)
    rows = {r.ticker: r for r in await outcomes()}
    assert rows[KR].signal_date == sig and rows[KR].send_result is None
    assert rows["900002"].signal_date == bars[5].d


@pytest.mark.asyncio
async def test_us_row_has_no_index_and_us_base(clean):
    bars = mk(D0, [10 + i for i in range(15)], opens=[9.5 + i for i in range(15)])
    sig = bars[3].d
    await add_alert(US, datetime(2026, 9, 11, 5, 30), bar_date=sig.isoformat(), market="US")
    await mo.run_meme_outcomes(client=FakeToss({US: bars}), now=NOW)
    r = (await outcomes())[0]
    assert r.market == "US" and r.status == "ok" and r.idx_ret_5d is None and r.entry_date == bars[4].d


@pytest.mark.asyncio
async def test_all_fail_raises_and_counts_then_unavailable(clean):
    bars = kr_bars(15)
    sig = bars[3].d
    await add_alert(KR, datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=20), bar_date=sig.isoformat())
    for expected in (1, 2, 3):
        with pytest.raises(RuntimeError):
            await mo.run_meme_outcomes(client=FakeToss({}, fail_all=True, index=mk(D0, [100.0] * 15)), now=NOW)
        r = (await outcomes())[0]
        assert r.fail_count == expected
    assert r.status == "unavailable"
    # 계산 불가는 끝난 행 → 다시 부르지 않는다
    c = FakeToss({KR: bars}, index=mk(D0, [100.0] * 15))
    await mo.run_meme_outcomes(client=c, now=NOW)
    assert c.calls == []


@pytest.mark.asyncio
async def test_index_failure_only_gives_pending_not_error(clean):
    bars = kr_bars(15)
    sig = bars[3].d
    await add_alert(KR, datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=20), bar_date=sig.isoformat())
    out = await mo.run_meme_outcomes(client=FakeToss({KR: bars}, fail_index=True), now=NOW)   # 오류 없이 성공
    r = (await outcomes())[0]
    assert out["index"] == "failed" and r.status == "pending" and r.idx_ret_5d is None and r.ret_5d is not None
    idx = mk(D0, [100 + i for i in range(15)], opens=[99 + i for i in range(15)])
    await mo.run_meme_outcomes(client=FakeToss({KR: bars}, index=idx), now=NOW)
    r = (await outcomes())[0]
    assert r.status == "ok" and r.idx_ret_5d is not None


@pytest.mark.asyncio
async def test_max_symbols_cap_defers(clean):
    bars = kr_bars(15)
    sig = bars[3].d
    at = datetime.combine(sig, datetime.min.time()).replace(hour=16, minute=20)
    for t in ("900001", "900002", "900003"):
        await add_alert(t, at, bar_date=sig.isoformat())
    by = {t: bars for t in ("900001", "900002", "900003")}
    idx = mk(D0, [100.0] * 15)
    out = await mo.run_meme_outcomes(client=FakeToss(by, index=idx), now=NOW, max_symbols=2)
    assert out["deferred"] == 1 and sum(1 for r in await outcomes() if r.status == "ok") == 2
    await mo.run_meme_outcomes(client=FakeToss(by, index=idx), now=NOW, max_symbols=2)
    assert all(r.status == "ok" for r in await outcomes())


# ── API (로그인 필요) ───────────────────────────────────────────────

TOKEN = "test-sniper-token-meme-outcomes"
H = {"X-API-Token": TOKEN}


@pytest_asyncio.fixture
async def client(monkeypatch, clean):
    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/meme-watch/outcomes/summary", "/api/v1/meme-watch/outcomes/recent"])
async def test_outcome_endpoints_require_login(client, path):
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers={"X-API-Token": "wrong"})).status_code == 401


@pytest.mark.asyncio
async def test_outcome_endpoints_with_token(client):
    from backend.services.db import get_session
    from backend.services.models import MemeAlertOutcome

    async with get_session() as s:
        for i in range(3):
            s.add(MemeAlertOutcome(ticker=f"T{i}", market="KR", signal_date=date(2026, 9, 1) + timedelta(days=i),
                                   alert_type="BLAZING", score=1.1, status="ok", ret_5d=0.1, idx_ret_5d=0.01,
                                   ret_1d=0.1, ret_3d=0.1, ret_10d=0.1, max_down=-0.02, bars_after=10,
                                   first_alert_at=datetime(2026, 9, 1, 16, 20)))
    r = await client.get("/api/v1/meme-watch/outcomes/summary?horizon=5", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["label"] == "판정 보류 · 건수 부족" and body["overall"]["n"] == 3
    assert body["overall"]["median"] is None          # 30건 미만 → 서버가 null
    assert body["status_counts"]["ok"] == 3 and body["cost"] == 0.0025
    assert (await client.get("/api/v1/meme-watch/outcomes/summary?horizon=7", headers=H)).status_code == 422
    rr = await client.get("/api/v1/meme-watch/outcomes/recent?limit=2", headers=H)
    items = rr.json()["items"]
    assert rr.status_code == 200 and len(items) == 2 and items[0]["signal_date"] == "2026-09-03"
    assert items[0]["ret_5d"] == pytest.approx(0.1 - 0.0025)
    assert (await client.get("/api/v1/meme-watch/outcomes/recent?limit=0", headers=H)).status_code == 422
