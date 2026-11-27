"""1119-03 ② · 국내 공시 수집 · 유형 판정 · 과거 채우기 시험.

자료는 모두 지어낸 값 (회사 · 사람 이름 · 접수번호 · 숫자). 바깥 네트워크 없음 (httpx.MockTransport).
응답 칸 이름은 client.py 의 majorstock 응답 읽기와 OpenDART DS004 명세(elestock)를 따른다.
"""
from __future__ import annotations

import io
import os
import zipfile
from datetime import date, datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from backend.discovery.big_hands import dart_collect as dc
from backend.discovery.big_hands import kr_types as kt
from backend.discovery.big_hands.collect_models import (
    DartCollectCursor, DartDocCache, DartInsiderRow, DartMajorstockRow, PriceDaily,
)
from backend.discovery.big_hands.dart_parse import (
    document_zip_to_text, parse_elestock_item, parse_holding_purpose, parse_insider_trade_lines,
    parse_majorstock_item,
)
from backend.discovery.big_hands.scheduler import JOB_ID, register_big_hands_jobs
from backend.scripts import big_hands_backfill as bf
from backend.services.db import get_session, init_db

CORP = "00000001"
CORP2 = "00000002"


@pytest_asyncio.fixture(autouse=True)
async def _clean():
    await init_db()
    async with get_session() as s:
        for m in (DartInsiderRow, DartMajorstockRow, DartDocCache, DartCollectCursor, PriceDaily):
            await s.execute(delete(m))
    yield


# ── 가짜 DART ───────────────────────────────────────────────────────────

def _ele(rcept_no, rcept_dt, who, change, hold="1000", rate="0.5", irds_rate="0.1"):
    return {"rcept_no": rcept_no, "rcept_dt": rcept_dt, "corp_code": CORP, "stock_code": "000001",
            "repror": who, "isu_exctv_ofcps": "대표이사", "isu_main_shrholdr": "-",
            "sp_stock_lmp_cnt": hold, "sp_stock_lmp_irds_cnt": change, "sp_stock_lmp_rate": rate,
            "sp_stock_lmp_irds_rate": irds_rate}


def _maj(rcept_no, rcept_dt, tp, resn, irds="5000", who="가짜펀드"):
    return {"rcept_no": rcept_no, "rcept_dt": rcept_dt, "corp_code": CORP, "stock_code": "000001",
            "report_tp": tp, "repror": who, "stkqy": "100000", "stkqy_irds": irds, "stkrt": "5.2",
            "stkrt_irds": "0.3", "report_resn": resn}


def _zip(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.xml", f"<DOCUMENT><BODY>{body}</BODY></DOCUMENT>")
    return buf.getvalue()


class FakeDart:
    """호출을 세고 이름별 응답을 준다."""

    def __init__(self, ele=None, maj=None, docs=None, status=None):
        self.ele, self.maj, self.docs = ele or {}, maj or {}, docs or {}
        self.status = status or {}
        self.seen: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        name = req.url.path.rsplit("/", 1)[-1]
        self.seen.append(name)
        q = dict(req.url.params)
        if name in self.status:
            return httpx.Response(200, json={"status": self.status[name], "message": ""})
        if name == "elestock.json":
            rows = self.ele.get(q["corp_code"])
            return httpx.Response(200, json={"status": "000", "list": rows} if rows else {"status": "013"})
        if name == "majorstock.json":
            rows = self.maj.get(q["corp_code"])
            return httpx.Response(200, json={"status": "000", "list": rows} if rows else {"status": "013"})
        if name == "document.xml":
            body = self.docs.get(q["rcept_no"])
            if body is None:
                return httpx.Response(200, json={"status": "014"})
            return httpx.Response(200, content=_zip(body))
        return httpx.Response(404)

    def collector(self, **kw):
        kw.setdefault("gap_sec", 0)
        return dc.DartCollector(key="dummy-key-for-test", http=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)), **kw)


BUY_DOC = "소유상황 변동 2026-03-10 장내매수(+) 20,000 12,800 합계"


# ── 읽기 ────────────────────────────────────────────────────────────────

def test_parse_elestock_and_majorstock_items():
    i = parse_elestock_item(_ele("20260310000001", "20260310", "가짜임원", "20,000"))
    assert (i.rcept_no, i.change_qty, i.hold_rate, i.change_rate) == ("20260310000001", 20000.0, 0.5, 0.1)
    assert i.rcept_date == date(2026, 3, 10)
    assert parse_elestock_item({"rcept_no": "", "rcept_dt": "20260310"}) is None
    m = parse_majorstock_item(_maj("20260311000002", "20260311", "신규보고", "신규보고"))
    assert (m.report_tp, m.change_qty) == ("신규보고", 5000.0)


def test_dashed_receipt_date_is_read_for_elestock_and_majorstock():
    """DART 안내서: elestock 접수일은 YYYY-MM-DD. 8자리만 읽어 11/27 첫 수집이 0건이었다."""
    i = parse_elestock_item(_ele("20261127000001", "2026-11-27", "가짜임원", "100"))
    assert i is not None and i.rcept_date == date(2026, 11, 27)
    m = parse_majorstock_item(_maj("20261127000002", "2026-11-27", "신규보고", "신규보고"))
    assert m is not None and m.rcept_date == date(2026, 11, 27)
    assert parse_elestock_item(_ele("20261127000003", "2026-13-01", "가짜임원", "1")) is None
    assert parse_elestock_item(_ele("20261127000004", "2026/11/27", "가짜임원", "1")) is None


def test_row_key_is_stable_and_differs_by_reporter():
    a = parse_elestock_item(_ele("1", "20260310", "갑", "10"))
    b = parse_elestock_item(_ele("1", "20260310", "을", "10"))
    assert a.key == parse_elestock_item(_ele("1", "20260310", "갑", "10")).key
    assert a.key != b.key


def test_document_zip_and_trade_line_parse():
    text = document_zip_to_text(_zip(f"<TD>{BUY_DOC}</TD>"))
    lines = parse_insider_trade_lines(text)
    assert len(lines) == 1
    assert (lines[0].trade_date, lines[0].method, lines[0].qty, lines[0].unit_price) == (
        date(2026, 3, 10), "장내매수(+)", 20000.0, 12800.0)
    assert document_zip_to_text(b'{"status":"014"}') is None
    assert parse_insider_trade_lines("관련 없는 글") == []


def test_holding_purpose():
    assert parse_holding_purpose("보유목적 : 경영권 영향") == "management"
    assert parse_holding_purpose("1. 보유 목적 단순투자") == "simple"
    assert parse_holding_purpose("목적 글 없음", "주식등의대량보유상황보고서(일반)") == "management"
    assert parse_holding_purpose("목적 글 없음", "주식등의대량보유상황보고서(약식)") == "simple"
    assert parse_holding_purpose("목적 글 없음") is None


# ── 유형 판정 ───────────────────────────────────────────────────────────

def _t(no, d, who="갑", method="장내매수(+)", qty=1000.0, rate=0.5):
    return kt.InsiderTrade(no, d, who, method, qty, rate)


def test_kr_i1_open_market_buy():
    v = kt.classify_insider_trade(_t("1", date(2026, 3, 10)))
    assert v.signal_type == "KR-I1" and v.excluded is None


@pytest.mark.parametrize("method,reason", [
    ("주식매수선택권행사", "스톡옵션"), ("상속", "상속"), ("증여(+)", "증여"), ("신탁계약", "신탁"),
    ("자기주식 지급", "자사주 지급"), ("액면분할", "분할"), ("무상증자", "무상증자"),
])
def test_exclusions(method, reason):
    v = kt.classify_insider_trade(_t("1", date(2026, 3, 10), method=method))
    assert v.signal_type is None and v.excluded == reason


def test_not_open_market_and_unknown():
    assert kt.classify_insider_trade(_t("1", date(2026, 3, 10), method="유상증자")).excluded == "장내매수 아님"
    assert kt.classify_insider_trade(_t("1", date(2026, 3, 10), qty=-5.0, method="장내매도(-)")).excluded == "장내매수 아님"
    assert kt.classify_insider_trade(_t("1", date(2026, 3, 10), method=None)).unknown


def test_repeat_small_uses_only_filings_up_to_entry():
    """막음 1: 셋째 소량 건은 빠지지만, 앞 두 건은 뒤에 올 건수 때문에 빠지지 않는다."""
    ts = [_t(str(i), date(2026, 3, 2 + i), rate=0.02) for i in range(1, 5)]
    verdicts = [kt.classify_insider_trade(t, ts) for t in ts]
    assert [v.signal_type for v in verdicts[:2]] == ["KR-I1", "KR-I1"]       # 첫째 · 둘째는 그대로 성립
    assert verdicts[2].excluded == "같은 사람 같은 달 반복 소량"
    assert verdicts[3].excluded == "같은 사람 같은 달 반복 소량"
    big = _t("9", date(2026, 3, 20), rate=0.5)                                # 소량이 아니면 빼지 않음
    assert kt.classify_insider_trade(big, ts + [big]).signal_type == "KR-I1"
    other_month = _t("8", date(2026, 4, 2), rate=0.02)
    assert kt.classify_insider_trade(other_month, ts + [other_month]).signal_type == "KR-I1"


def test_kr_i2_two_people_within_30_days_and_no_future():
    a = _t("1", date(2026, 3, 10), who="갑")
    b = _t("2", date(2026, 4, 1), who="을")
    same = _t("3", date(2026, 4, 5), who="갑")
    assert kt.kr_i2_date([a, b], as_of=date(2026, 4, 30)) == date(2026, 4, 1)
    assert kt.kr_i2_date([a, b], as_of=date(2026, 3, 31)) is None            # 둘째 접수 전에는 성립 아님
    assert kt.kr_i2_date([a, same], as_of=date(2026, 4, 30)) is None         # 같은 사람 둘은 1명
    far = _t("4", date(2026, 5, 20), who="을")
    assert kt.kr_i2_date([a, far], as_of=date(2026, 6, 30)) is None          # 30일 밖


def test_kr_m1_and_m2():
    f = lambda **k: kt.MajorFiling(**{"rcept_no": "1", "rcept_date": date(2026, 3, 10), "person": "가짜펀드",
                                      "report_tp": "신규보고", "report_resn": "신규보고", "change_qty": 5000.0, **k})
    assert kt.classify_major_filing(f(purpose="management")).signal_type == "KR-M1"
    assert kt.classify_major_filing(f(purpose="simple")).excluded == "단순 투자 목적"
    assert kt.classify_major_filing(f(purpose=None)).unknown
    assert kt.classify_major_filing(f(purpose="management", report_resn="상속")).excluded == "상속"
    inc = f(report_tp="변동보고", report_resn="장내매수(+)")
    assert kt.classify_major_filing(inc).signal_type == "KR-M2"
    assert kt.classify_major_filing(f(report_tp="변동보고", report_resn="장내매도(-)", change_qty=-5.0)).excluded
    assert kt.classify_major_filing(f(report_tp="변동보고", report_resn="무상증자", change_qty=100.0)).excluded == "무상증자"


def test_later_events_are_counted_not_removed():
    entry = date(2026, 3, 11)
    later = [kt.LaterItem("amend", date(2026, 3, 15)), kt.LaterItem("withdraw", date(2026, 3, 20)),
             kt.LaterItem("sell", date(2026, 3, 25)), kt.LaterItem("sell", date(2026, 6, 1)),
             kt.LaterItem("amend", date(2026, 3, 1))]          # 진입 전 건은 세지 않음
    assert kt.tally_later_events(entry, later) == {"amended": 1, "withdrawn": 1, "sold_soon": 1}
    assert kt.detect_report_kind("[기재정정]임원ㆍ주요주주특정증권등소유상황보고서") == "amend"
    assert kt.detect_report_kind("[철회]보고서") == "withdraw"
    assert kt.detect_report_kind("임원ㆍ주요주주특정증권등소유상황보고서") == "other"


# ── 수집 · 저장 · 중복 · 원문 캐시 ──────────────────────────────────────

async def _count(model):
    async with get_session() as s:
        return (await s.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.asyncio
async def test_collect_corp_saves_rows_fetches_docs_only_for_increases_and_is_idempotent():
    fake = FakeDart(
        ele={CORP: [_ele("A1", "20260310", "갑", "20,000"), _ele("A2", "20260311", "을", "-500"),
                    _ele("A0", "20151231", "병", "100")]},
        maj={CORP: [_maj("M1", "20260312", "신규보고", "신규보고"), _maj("M2", "20260313", "변동보고", "장내매수(+)")]},
        docs={"A1": BUY_DOC, "M1": "보유목적 경영권 영향"},
    )
    col = fake.collector()
    s = await dc.collect_corp(col, CORP, since=date(2016, 1, 1))
    assert (s.insider_new, s.major_new, s.docs_fetched) == (2, 2, 2)        # 2015 줄은 저장 안 함 · 증가 1건 + 신규 1건만 원문
    assert fake.seen.count("document.xml") == 2
    async with get_session() as ses:
        rows = {r.rcept_no: r for r in (await ses.execute(select(DartInsiderRow))).scalars()}
        assert rows["A1"].method == "장내매수(+)" and rows["A1"].unit_price == 12800.0
        assert rows["A1"].trade_date == date(2026, 3, 10) and rows["A1"].processed_at is not None
        assert rows["A2"].doc_status == "none" and rows["A2"].processed_at is not None   # 감소 건은 원문 없이 처리됨
        majors = {r.rcept_no: r for r in (await ses.execute(select(DartMajorstockRow))).scalars()}
        assert majors["M1"].purpose == "management" and majors["M2"].doc_status == "none"
        assert (await ses.execute(select(func.count()).select_from(DartCollectCursor))).scalar_one() == 2

    calls_before = len(fake.seen)
    s2 = await dc.collect_corp(fake.collector(), CORP, since=date(2016, 1, 1))     # 다시 돌려도 중복 없음
    assert (s2.insider_new, s2.major_new, s2.docs_fetched) == (0, 0, 0)
    assert len(fake.seen) - calls_before == 2                                      # 목록 두 번만 부름 · 원문은 안 받음
    assert await _count(DartInsiderRow) == 2 and await _count(DartMajorstockRow) == 2


@pytest.mark.asyncio
async def test_doc_cache_by_receipt_number_is_reused():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100"), _ele("A1", "20260310", "을", "200")]},
                    docs={"A1": BUY_DOC})
    s = await dc.collect_corp(fake.collector(), CORP, kinds=("elestock",), since=date(2016, 1, 1))
    assert s.insider_new == 2 and s.docs_fetched == 1 and s.doc_cache_hits == 1
    assert fake.seen.count("document.xml") == 1
    assert await _count(DartDocCache) == 1


@pytest.mark.asyncio
async def test_unparsed_and_missing_docs_are_marked_not_guessed():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100"), _ele("A2", "20260311", "을", "100")]},
                    docs={"A1": "읽을 수 없는 모양의 글"})            # A2 는 원문 없음(014)
    await dc.collect_corp(fake.collector(), CORP, kinds=("elestock",), since=date(2016, 1, 1))
    async with get_session() as ses:
        rows = {r.rcept_no: r for r in (await ses.execute(select(DartInsiderRow))).scalars()}
    assert rows["A1"].doc_status == "unparsed" and rows["A1"].method is None
    assert rows["A2"].doc_status == "missing" and rows["A2"].method is None


@pytest.mark.asyncio
async def test_failed_call_does_not_mark_cursor_and_020_stops():
    class Boom(FakeDart):
        def handler(self, req):
            self.seen.append("x")
            return httpx.Response(500)
    f = Boom()
    s = await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    assert s.failed_corps == 1 and await _count(DartCollectCursor) == 0
    lim = FakeDart(status={"elestock.json": "020"})
    with pytest.raises(dc.RateLimited):
        await dc.collect_corp(lim.collector(), CORP, kinds=("elestock",))


@pytest.mark.asyncio
async def test_call_limit_and_gap():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100")]}, docs={"A1": BUY_DOC})
    sleeps = []

    async def fake_sleep(sec):
        sleeps.append(sec)
    col = fake.collector(max_calls=1, gap_sec=1.0, sleep=fake_sleep)
    with pytest.raises(dc.CallLimit):
        await dc.collect_corp(col, CORP, kinds=("elestock",))                     # elestock 1회 뒤 원문 부를 때 상한
    assert col.calls == 1
    col2 = fake.collector(max_calls=5, gap_sec=1.0, sleep=fake_sleep)
    await dc.collect_corp(col2, CORP, kinds=("elestock",))
    assert sleeps and all(x >= 1.0 for x in sleeps)                              # 호출 사이 1초 이상


@pytest.mark.asyncio
async def test_cursor_stays_open_when_doc_budget_runs_out_then_resumes():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100"), _ele("A2", "20260311", "을", "100")]},
                    docs={"A1": BUY_DOC, "A2": BUY_DOC})
    await dc.collect_corp(fake.collector(), CORP, kinds=("elestock",), doc_budget=[1])
    async with get_session() as ses:
        cur = await ses.get(DartCollectCursor, (CORP, "elestock"))
        assert cur is not None and cur.processed_at is None                      # 남은 줄이 있어 아직 끝 아님
    await dc.collect_corp(fake.collector(), CORP, kinds=("elestock",))
    async with get_session() as ses:
        assert (await ses.get(DartCollectCursor, (CORP, "elestock"))).processed_at is not None
        left = (await ses.execute(select(func.count()).select_from(DartInsiderRow).where(DartInsiderRow.processed_at.is_(None)))).scalar_one()
    assert left == 0


# ── 매일 수집 · 스위치 · 잡 ─────────────────────────────────────────────

class _Disc:
    def __init__(self, corp, no, nm="임원ㆍ주요주주특정증권등소유상황보고서"):
        self.corp_code, self.rcept_no, self.report_nm = corp, no, nm


@pytest.mark.asyncio
async def test_collect_daily_uses_lists_and_does_not_touch_cursor():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100"), _ele("OLD", "20200101", "병", "100")]},
                    maj={CORP2: [dict(_maj("M1", "20260310", "변동보고", "장내매수(+)"), corp_code=CORP2)]},
                    docs={"A1": BUY_DOC})

    async def lister(bgn, end, detail):
        return [_Disc(CORP, "A1")] if detail == "D002" else [_Disc(CORP2, "M1", "[기재정정]주식등의대량보유상황보고서(약식)")]

    out = await dc.collect_daily(date(2026, 3, 10), collector=fake.collector(), lister=lister)
    assert out["corps_found"] == 2 and out["insider_new"] == 1 and out["major_new"] == 1 and out["stopped"] is None
    assert await _count(DartCollectCursor) == 0                                   # 과거 채우기가 건너뛰지 않게
    async with get_session() as ses:
        r = (await ses.execute(select(DartInsiderRow))).scalar_one()
        m = (await ses.execute(select(DartMajorstockRow))).scalar_one()
    assert r.report_nm == "임원ㆍ주요주주특정증권등소유상황보고서" and m.report_nm.startswith("[기재정정]")


@pytest.mark.asyncio
async def test_collect_daily_saves_dashed_dates_and_counts_dropped_rows():
    """11/27 운영 첫 수집 재현: elestock 접수일이 YYYY-MM-DD 이면 예전 코드는 0건 저장."""
    fake = FakeDart(ele={CORP: [_ele("A1", "2026-03-10", "갑", "-100"), _ele("A9", "", "을", "100")]})

    async def lister(bgn, end, detail):
        return [_Disc(CORP, "A1")] if detail == "D002" else []

    out = await dc.collect_daily(date(2026, 3, 10), collector=fake.collector(), lister=lister)
    assert out["insider_new"] == 1 and out["dropped_rows"] == 1
    assert await _count(DartInsiderRow) == 1


@pytest.mark.asyncio
async def test_collect_daily_without_key_skips(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert await dc.collect_daily() == {"skipped": "no_key"}


def test_collect_switch_default_off(monkeypatch):
    monkeypatch.delenv(dc.ENABLE_ENV, raising=False)
    assert dc.collect_enabled() is False
    monkeypatch.setenv(dc.ENABLE_ENV, "1")
    assert dc.collect_enabled() is True


def test_register_job_off_by_default_and_values_when_on(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from backend.services.job_watch import GRACE_DEFAULT

    monkeypatch.delenv(dc.ENABLE_ENV, raising=False)
    s = AsyncIOScheduler(timezone="Asia/Seoul")
    assert register_big_hands_jobs(s) is False and s.get_job(JOB_ID) is None
    monkeypatch.setenv(dc.ENABLE_ENV, "true")
    assert register_big_hands_jobs(s) is True
    j = s.get_job(JOB_ID)
    f = {x.name: str(x) for x in j.trigger.fields}
    assert (f["hour"], f["minute"], f["day_of_week"]) == ("19", "10", "mon-fri")
    assert j.misfire_grace_time == GRACE_DEFAULT and j.coalesce is True and j.max_instances == 1


# ── 과거 채우기 스크립트 ────────────────────────────────────────────────

def test_read_corp_file(tmp_path):
    p = tmp_path / "corps.txt"
    p.write_text("# 주석\n00000001\n\n00000002 # 뒤 주석\nabc\n123\n00000001\n", encoding="utf-8")
    assert bf.read_corp_file(p) == ["00000001", "00000002"]


@pytest.mark.asyncio
async def test_backfill_dry_run_makes_no_calls_and_no_writes():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100")]})
    code = await bf.run([CORP, CORP2], since_year=2016, limit=5, max_calls=10, batch_size=1, dry_run=True,
                        collector=fake.collector())
    assert code == bf.EXIT_OK and fake.seen == []
    assert await _count(DartInsiderRow) == 0 and await _count(DartCollectCursor) == 0


@pytest.mark.asyncio
async def test_backfill_limit_resume_and_rerun_no_duplicates():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100")], CORP2: [dict(_ele("B1", "20260311", "을", "100"), corp_code=CORP2)]},
                    docs={"A1": BUY_DOC, "B1": BUY_DOC})
    sl = []

    async def nosleep(x):
        sl.append(x)
    kw = dict(since_year=2016, max_calls=50, batch_size=1, dry_run=False, sleep=nosleep)
    assert await bf.run([CORP, CORP2], limit=1, collector=fake.collector(), **kw) == bf.EXIT_OK
    assert await _count(DartInsiderRow) == 1                                     # 상한 1회사만
    assert await bf.run([CORP, CORP2], limit=1, collector=fake.collector(), **kw) == bf.EXIT_OK
    assert await _count(DartInsiderRow) == 2                                     # 끝낸 회사는 건너뛰고 다음 회사
    before = len(fake.seen)
    assert await bf.run([CORP, CORP2], limit=5, collector=fake.collector(), **kw) == bf.EXIT_OK
    assert len(fake.seen) == before and await _count(DartInsiderRow) == 2        # 다시 돌려도 호출 0 · 중복 0


@pytest.mark.asyncio
async def test_backfill_call_limit_exits_with_code_5():
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100")]}, docs={"A1": BUY_DOC})
    code = await bf.run([CORP], since_year=2016, limit=5, max_calls=1, batch_size=1, dry_run=False,
                        collector=fake.collector(max_calls=1))
    assert code == bf.EXIT_LIMIT


def test_backfill_refuses_forbidden_time(monkeypatch, tmp_path):
    from backend.scripts import big_hands_probe as probe

    p = tmp_path / "c.txt"
    p.write_text("00000001\n")
    monkeypatch.setattr(probe, "in_forbidden_window", lambda *a, **k: True)
    assert bf.main(["--corp-file", str(p)]) == bf.EXIT_BAD_TIME


def test_new_tables_exist_and_price_table_is_empty_until_next_batch():
    names = {t.name for t in (DartInsiderRow.__table__, DartMajorstockRow.__table__, DartDocCache.__table__,
                              DartCollectCursor.__table__, PriceDaily.__table__)}
    assert names == {"dart_insider_row", "dart_majorstock_row", "dart_doc_cache", "dart_collect_cursor",
                     "big_hands_price_daily"}


# ── 1119-03 ② 둘째 묶음 · 막음 A · B · 권고 ㄱ ㄹ ㅁ ─────────────────────────

class _DocStatus(FakeDart):
    """document.xml 만 지정한 응답(HTTP 코드 · 본문)으로 바꾼다."""

    def __init__(self, doc_resp, **kw):
        super().__init__(**kw)
        self.doc_resp = doc_resp

    def handler(self, req):
        if req.url.path.endswith("document.xml"):
            self.seen.append("document.xml")
            return self.doc_resp
        return super().handler(req)


@pytest.mark.asyncio
async def test_document_020_stops_without_cache_or_processed_mark():
    f = _DocStatus(httpx.Response(200, json={"status": "020", "message": "limit"}),
                   ele={CORP: [_ele("A1", "20260310", "갑", "100")]})
    with pytest.raises(dc.RateLimited):
        await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    assert await _count(DartDocCache) == 0 and await _count(DartCollectCursor) == 0
    async with get_session() as ses:
        row = (await ses.execute(select(DartInsiderRow))).scalar_one()
    assert row.processed_at is None and row.doc_status is None


@pytest.mark.asyncio
@pytest.mark.parametrize("resp", [
    httpx.Response(200, json={"status": "800", "message": "점검"}), httpx.Response(404, json={"status": "014"}),
    httpx.Response(200, content=b"not json"), httpx.Response(200, json={"status": "010"})])
async def test_document_other_errors_are_not_cached_and_get_refetched(resp):
    f = _DocStatus(resp, ele={CORP: [_ele("A1", "20260310", "갑", "100")]})
    await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    assert await _count(DartDocCache) == 0
    async with get_session() as ses:
        row = (await ses.execute(select(DartInsiderRow))).scalar_one()
    assert row.processed_at is None                                    # 다음에 다시 받는다
    g = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100")]}, docs={"A1": BUY_DOC})
    await dc.collect_corp(g.collector(), CORP, kinds=("elestock",))   # 다시 돌리면 다시 받는다
    assert g.seen.count("document.xml") == 1
    async with get_session() as ses:
        row = (await ses.execute(select(DartInsiderRow))).scalar_one()
    assert row.doc_status == "parsed"


@pytest.mark.asyncio
async def test_document_file_missing_status_is_cached_as_missing():
    for st in ("013", "014"):
        f = _DocStatus(httpx.Response(200, json={"status": st}), ele={CORP: [_ele("A" + st, "20260310", "갑", "100")]})
        await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    async with get_session() as ses:
        got = {r.status for r in (await ses.execute(select(DartDocCache))).scalars()}
    assert got == {"missing"} and await _count(DartDocCache) == 2


def test_httpx_loggers_are_warning_in_api_main():
    import logging

    import backend.api.main  # noqa: F401  · 불러올 때 로그 수준을 올린다

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


@pytest.mark.asyncio
async def test_backfill_stops_cleanly_when_window_closes_mid_run(monkeypatch):
    fake = FakeDart(ele={CORP: [_ele("A1", "20260310", "갑", "100")], CORP2: [dict(_ele("B1", "20260311", "을", "100"), corp_code=CORP2)]},
                    docs={"A1": BUY_DOC, "B1": BUY_DOC})
    calls = iter([False, True])                                        # 첫 회사는 통과 · 둘째 회사 앞에서 걸림
    monkeypatch.setattr(bf, "_in_window", lambda: next(calls))
    code = await bf.run([CORP, CORP2], since_year=2016, limit=5, max_calls=50, batch_size=1, dry_run=False,
                        collector=fake.collector(), check_window=True)
    assert code == bf.EXIT_BAD_TIME
    async with get_session() as ses:
        done = {c.corp_code for c in (await ses.execute(select(DartCollectCursor))).scalars() if c.processed_at}
    assert done == {CORP}                                             # 둘째 회사는 손대지 않음 · 처리 표시 일관


@pytest.mark.asyncio
async def test_daily_list_calls_count_against_limit_and_failure_is_reported():
    fake = FakeDart()
    col = fake.collector(max_calls=1)
    out = await dc.collect_daily(date(2026, 3, 10), collector=col)    # 목록 호출도 상한 1 에 걸린다
    assert out["stopped"] == "call_limit" and out["dart_calls"] == 1

    class ListBoom(FakeDart):
        def handler(self, req):
            if req.url.path.endswith("list.json"):
                return httpx.Response(500)
            return super().handler(req)
    g = ListBoom()
    out = await dc.collect_daily(date(2026, 3, 10), collector=g.collector())
    assert out["list_failed"] == ["D002", "D001"] and out["corps_found"] == 0

    class ListEmpty(FakeDart):
        def handler(self, req):
            if req.url.path.endswith("list.json"):
                return httpx.Response(200, json={"status": "013"})
            return super().handler(req)
    out = await dc.collect_daily(date(2026, 3, 10), collector=ListEmpty().collector())
    assert out["list_failed"] == [] and out["corps_found"] == 0       # 「공시 없음」은 실패가 아님


@pytest.mark.asyncio
async def test_daily_list_reads_pages_and_skips_unlisted():
    class Paged(FakeDart):
        def handler(self, req):
            if req.url.path.endswith("list.json"):
                pg = int(req.url.params["page_no"])
                it = {"corp_code": CORP, "stock_code": "000001", "rcept_no": f"P{pg}", "report_nm": "x"}
                un = {"corp_code": CORP2, "stock_code": " ", "rcept_no": "U", "report_nm": "x"}
                return httpx.Response(200, json={"status": "000", "total_page": 2, "list": [it, un]})
            return super().handler(req)
    got = await Paged().collector().list_disclosures(date(2026, 3, 1), date(2026, 3, 10), "D002")
    assert [d.rcept_no for d in got] == ["P1", "P2"]


@pytest.mark.asyncio
async def test_identical_lines_in_one_filing_are_both_saved():
    same = _ele("A1", "20260310", "갑", "100")
    fake = FakeDart(ele={CORP: [same, dict(same), dict(same, sp_stock_lmp_cnt="2000")]}, docs={"A1": BUY_DOC})
    await dc.collect_corp(fake.collector(), CORP, kinds=("elestock",))
    assert await _count(DartInsiderRow) == 3
    await dc.collect_corp(fake.collector(), CORP, kinds=("elestock",))   # 다시 돌려도 늘지 않음
    assert await _count(DartInsiderRow) == 3
    a = parse_elestock_item(same)
    assert a.key == parse_elestock_item(dict(same)).key                   # 첫 줄 열쇠는 순번 도입 전과 같다


# ── 1119-03 ② 셋째 묶음 · 막음 A-2 (원문 오류는 XML 로 온다) ─────────────────

def _xml(status: str, message: str = "x") -> httpx.Response:
    body = f"<?xml version='1.0' encoding='UTF-8'?><result><status>{status}</status><message>{message}</message></result>"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "application/xml"})


@pytest.mark.asyncio
async def test_xml_document_020_stops_without_cache_or_processed_mark():
    f = _DocStatus(_xml("020"), ele={CORP: [_ele("A1", "20260310", "갑", "100"), _ele("A2", "20260311", "을", "100")]})
    with pytest.raises(dc.RateLimited):
        await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    assert f.seen.count("document.xml") == 1                          # 첫 호출에서 멈춤 · 남은 원문을 부르지 않음
    assert await _count(DartDocCache) == 0 and await _count(DartCollectCursor) == 0
    async with get_session() as ses:
        rows = (await ses.execute(select(DartInsiderRow))).scalars().all()
    assert all(r.processed_at is None for r in rows)


@pytest.mark.asyncio
async def test_xml_document_014_is_cached_as_missing_and_marks_processed():
    f = _DocStatus(_xml("014", "파일이 존재하지 않습니다."), ele={CORP: [_ele("A1", "20260310", "갑", "100")]})
    await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    async with get_session() as ses:
        got = {r.status for r in (await ses.execute(select(DartDocCache))).scalars()}
        row = (await ses.execute(select(DartInsiderRow))).scalar_one()
    assert got == {"missing"} and row.doc_status == "missing" and row.processed_at is not None


@pytest.mark.asyncio
async def test_xml_document_010_is_error_not_cached():
    f = _DocStatus(_xml("010"), ele={CORP: [_ele("A1", "20260310", "갑", "100")]})
    await dc.collect_corp(f.collector(), CORP, kinds=("elestock",))
    assert await _count(DartDocCache) == 0
    async with get_session() as ses:
        row = (await ses.execute(select(DartInsiderRow))).scalar_one()
    assert row.processed_at is None


def test_error_status_ignores_entities_and_truncates_big_body():
    evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><result><status>020</status></result>'
    assert dc._error_status(evil) is None                              # DOCTYPE 이 있는 XML 은 읽지 않는다
    assert dc._error_status(b"<result><status>014</status></result>" + b" " * 100000) == "014"
    assert dc._error_status(b"<result><message>x</message></result>") is None


def test_error_status_survives_multibyte_encoding_and_reads_after_bom():
    euckr = '<?xml version="1.0" encoding="EUC-KR"?><result><status>013</status><message>없음</message></result>'.encode("euc-kr")
    assert dc._error_status(euckr) is None                             # 예외로 수집 전체가 멈추지 않고 error 로 간다
    assert dc._error_status(b"\xef\xbb\xbf<result><status>014</status></result>") == "014"
    assert dc._error_status(b'\xef\xbb\xbf{"status": "020"}') == "020"


@pytest.mark.asyncio
async def test_backfill_moves_on_even_when_a_corp_has_missing_xml_document():
    fake = _DocStatus(_xml("014"),
                      ele={CORP: [_ele("A1", "20260310", "갑", "100")], CORP2: [dict(_ele("B1", "20260311", "을", "100"), corp_code=CORP2)]})

    async def nosleep(x):
        pass
    kw = dict(since_year=2016, max_calls=50, batch_size=1, dry_run=False, sleep=nosleep)
    assert await bf.run([CORP, CORP2], limit=1, collector=fake.collector(), **kw) == bf.EXIT_OK
    assert await bf.run([CORP, CORP2], limit=1, collector=fake.collector(), **kw) == bf.EXIT_OK
    assert fake.seen.count("document.xml") == 2                        # 회사마다 1번씩 · 같은 회사를 다시 부르지 않음
    async with get_session() as ses:
        corps = {r.corp_code for r in (await ses.execute(select(DartInsiderRow))).scalars()}
    assert corps == {CORP, CORP2}
