"""1119-02 · 한국 ETF 이름 목록 (krx_etf_name) — 채우기 · 이름 조회 두 갈래 · 시작 채움 가드.

시험 자료의 코드 · 이름은 모두 가짜다 (실제 종목 · ETF 이름을 쓰지 않는다).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from backend.services import etf_names as en
from backend.services import stock_names as sn


def _rows(n: int, prefix: str = "EN") -> list[tuple[str, str]]:
    return [(f"{i:06d}", f"{prefix}{i}") for i in range(1, n + 1)]


@pytest_asyncio.fixture
async def db():
    from backend.services.db import get_session, init_db
    from backend.services.models import KrxEtfName, KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList

    await init_db()                       # create_all 이 새 표를 만든다
    async with get_session() as session:
        for model in (KrxEtfName, KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList):
            await session.execute(delete(model))
    sn.clear_memo()
    yield
    async with get_session() as session:        # 다른 시험 파일(같은 메모리 DB)에 ETF 행이 남지 않게
        await session.execute(delete(KrxEtfName))
    sn.clear_memo()


async def _count(model) -> int:
    from backend.services.db import get_session

    async with get_session() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar() or 0


async def _add(*rows):
    from backend.services.db import get_session

    async with get_session() as session:
        for r in rows:
            session.add(r)


# ── 표 · 칸 ────────────────────────────────────────────────────────────────
def test_table_has_only_ticker_name_fetched_at():
    from backend.services.models import KrxEtfName

    assert [c.name for c in KrxEtfName.__table__.columns] == ["ticker", "name", "fetched_at"]
    assert KrxEtfName.__table__.c.ticker.primary_key


# ── 이름 조회 두 갈래: 맨 뒤 · 주식 이름이 먼저 ─────────────────────────────
@pytest.mark.asyncio
async def test_single_lookup_reads_etf_table_last_and_stock_name_wins(db):
    from backend.services.models import KrxEtfName, KrxStockMeta

    await _add(KrxEtfName(ticker="000101", name="ETF가짜이름"), KrxEtfName(ticker="000102", name="ETF겹침"),
               KrxStockMeta(ticker="000102", name="주식메타이름"))
    assert await sn.lookup_kr_name("000101") == "ETF가짜이름"
    assert await sn.lookup_kr_name("000102") == "주식메타이름"          # 주식 이름이 먼저
    assert await sn.lookup_kr_name("000103") is None


@pytest.mark.asyncio
async def test_batch_lookup_reads_etf_table_last_and_stock_name_wins(db):
    from backend.services.models import KrxEtfName, KrxStockMeta, LiveTapeUniverse

    await _add(KrxEtfName(ticker="000101", name="ETF가짜이름"), KrxEtfName(ticker="000102", name="ETF겹침"),
               LiveTapeUniverse(ticker="000102", name="유니버스이름"), KrxStockMeta(ticker="000104", name="주식메타이름"),
               KrxEtfName(ticker="000104", name="ETF겹침2"))
    got = await sn.lookup_kr_names(["000101", "000102", "000103", "000104"])
    assert got == {"000101": "ETF가짜이름", "000102": "유니버스이름", "000104": "주식메타이름"}


def test_lookup_tables_count_is_five_and_header_order_line_updated():
    assert sn.KR_TABLES == 5
    src = open(sn.__file__, encoding="utf-8").read()
    assert '_lookup_many("KR", codes, _kr_table, KR_TABLES)' in src
    assert "KRX 메타 (채우는 잡이 없어) → ETF 이름 목록" in src      # 머리말 순서 줄


@pytest.mark.asyncio
async def test_name_lookup_path_never_calls_outside(db, monkeypatch):
    """이름 조회 경로(비로그인 요청 포함)는 표만 읽는다 — FDR 호출 함수를 부르면 실패."""
    def boom(*a, **k):
        raise AssertionError("이름 조회가 바깥 호출 함수를 불렀다")

    monkeypatch.setattr(en, "fetch_etf_listing", boom)
    monkeypatch.setattr(en, "refresh_etf_names", boom)
    assert await sn.lookup_kr_names(["000101"]) == {}
    assert await sn.lookup_kr_name("000101") is None
    src = open(sn.__file__, encoding="utf-8").read()
    assert "FinanceDataReader" not in src.split('"""', 2)[2] and "etf_names" not in src.split('"""', 2)[2]   # 코드 본문이 채우기 모듈을 부르지 않음


# ── 채우기: upsert 만 · 지우지 않음 · 500 미만이면 표 그대로 ─────────────────
@pytest.mark.asyncio
async def test_refresh_upserts_and_never_deletes(db):
    from backend.services.models import KrxEtfName

    stats = await en.refresh_etf_names(lambda: _rows(600))
    assert stats == {"fetched": 600, "inserted": 600, "updated": 0, "unchanged": 0}
    # 일부 이름이 바뀌고 일부 코드가 목록에서 빠진 새 목록
    new = _rows(550, prefix="EN")
    new[0] = ("000001", "바뀐이름")
    stats = await en.refresh_etf_names(lambda: new)
    assert stats["updated"] == 1 and stats["unchanged"] == 549 and stats["inserted"] == 0
    assert await _count(KrxEtfName) == 600                    # 빠진 50개도 남는다
    from backend.services.db import get_session

    async with get_session() as session:
        assert (await session.execute(select(KrxEtfName.name).where(KrxEtfName.ticker == "000001"))).scalar() == "바뀐이름"
        assert (await session.execute(select(KrxEtfName.name).where(KrxEtfName.ticker == "000600"))).scalar() == "EN600"


@pytest.mark.asyncio
async def test_refresh_too_few_rows_leaves_table_untouched(db):
    from backend.services.models import KrxEtfName

    await en.refresh_etf_names(lambda: _rows(600))
    with pytest.raises(en.EtfListingTooSmall):
        await en.refresh_etf_names(lambda: _rows(499, prefix="NEW"))
    assert await _count(KrxEtfName) == 600
    from backend.services.db import get_session

    async with get_session() as session:
        assert (await session.execute(select(KrxEtfName.name).where(KrxEtfName.ticker == "000001"))).scalar() == "EN1"   # 이름도 그대로


@pytest.mark.asyncio
async def test_refresh_fetch_error_leaves_table_untouched(db):
    from backend.services.models import KrxEtfName

    def boom():
        raise ConnectionError("fake network error")

    with pytest.raises(ConnectionError):
        await en.refresh_etf_names(boom)
    assert await _count(KrxEtfName) == 0


@pytest.mark.asyncio
async def test_refresh_does_not_touch_krx_stock_meta(db):
    from backend.services.models import KrxStockMeta

    await _add(KrxStockMeta(ticker="000777", name="주식메타이름"))
    await en.refresh_etf_names(lambda: _rows(600))
    assert await _count(KrxStockMeta) == 1
    assert "KrxStockMeta" not in open(en.__file__, encoding="utf-8").read().split('"""', 2)[2]     # 코드 본문에서 안 씀


def test_clean_rows_filters_bad_rows():
    got = en.clean_rows([("000001", " 이름A "), ("000001", "중복"), ("", "빈코드"), ("000002", ""), ("000003", "000003"),
                         ("TOOLONGCODE", "긴코드"), (None, "x"), ("00000Z", "영숫자코드")])
    assert got == [("000001", "이름A"), ("00000Z", "영숫자코드")]


# ── 시작 채움: 빈 표일 때만 · 시험 · API 전용 모드에서는 안 돎 · 실패해도 계속 ─────
@pytest.mark.asyncio
async def test_startup_fill_is_blocked_under_tests_and_makes_no_outside_call(db, monkeypatch):
    called = []
    monkeypatch.setattr(en, "fetch_etf_listing", lambda: called.append(1) or _rows(600))
    assert en.startup_fill_allowed() is False                  # pytest 안에서는 막힘
    assert await en.fill_on_start() is None
    assert called == []


def test_startup_fill_is_blocked_by_api_only_env(monkeypatch):
    import sys

    monkeypatch.setenv("BIOTECH_API_ONLY", "1")
    assert en.startup_fill_allowed() is False
    monkeypatch.delenv("BIOTECH_API_ONLY")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)       # pytest 감지를 잠시 끄고 허용 경로를 본다
    assert en.startup_fill_allowed() is True


@pytest.mark.asyncio
async def test_startup_fill_runs_only_when_table_empty(db, monkeypatch):
    monkeypatch.setattr(en, "startup_fill_allowed", lambda: True)
    calls = []

    def fetch():
        calls.append(1)
        return _rows(600)

    assert (await en.fill_on_start(fetch))["inserted"] == 600
    assert await en.fill_on_start(fetch) is None               # 이제 비어 있지 않음 → 바깥 호출 없음
    assert calls == [1]


@pytest.mark.asyncio
async def test_startup_fill_failure_is_logged_alerted_and_not_raised(db, monkeypatch, caplog):
    monkeypatch.setattr(en, "startup_fill_allowed", lambda: True)
    alerts = []

    def boom():
        raise TimeoutError("fake timeout")

    async def alert(exc):
        alerts.append(type(exc).__name__)

    assert await en.fill_on_start(boom, alert=alert) is None    # 예외를 밖으로 내지 않는다
    assert alerts == ["TimeoutError"]
    assert any("시작 채움 실패" in r.message for r in caplog.records)
    from backend.services.models import KrxEtfName

    assert await _count(KrxEtfName) == 0


@pytest.mark.asyncio
async def test_fetch_runs_off_the_event_loop(db):
    """FDR 호출은 asyncio.to_thread (이벤트 루프를 막지 않음) — 부른 스레드가 메인 스레드가 아니다."""
    import threading

    seen = []

    def fetch():
        seen.append(threading.current_thread() is threading.main_thread())
        return _rows(600)

    await en.refresh_etf_names(fetch)
    assert seen == [False]


# ── cron 서비스: 주간 잡 · 시작 채움 ────────────────────────────────────────
def test_weekly_job_registered_sunday_1230_with_grace():
    from backend.scheduler.cron import build_scheduler
    from backend.services.job_watch import GRACE_DEFAULT

    job = build_scheduler().get_job("etf_names_weekly")
    assert job is not None and job.misfire_grace_time == GRACE_DEFAULT and job.coalesce is True
    f = {x.name: str(x) for x in job.trigger.fields}
    assert (f["day_of_week"], f["hour"], f["minute"]) == ("sun", "12", "30")


@pytest.mark.asyncio
async def test_weekly_job_failure_sends_system_alert(monkeypatch):
    from backend.scheduler import cron

    sent = []

    async def fake_alert(name, exc, *a):
        sent.append((name, type(exc).__name__))

    async def boom(*a, **k):
        raise en.EtfListingTooSmall("ETF 목록 유효 행 3개")

    monkeypatch.setattr(cron, "_alert_job_failure", fake_alert)
    monkeypatch.setattr(en, "refresh_etf_names", boom)
    await cron.job_etf_names()                                 # 예외를 밖으로 내지 않는다
    assert sent == [("ETF 이름 목록", "EtfListingTooSmall")]


def test_startup_fill_only_in_cron_process_and_not_awaited():
    src = open(__import__("backend.scheduler.cron", fromlist=["x"]).__file__, encoding="utf-8").read()
    daemon = src[src.index("async def main_daemon"):src.index("async def main_once")]
    assert "asyncio.create_task(job_etf_names_startup())" in daemon      # 뒤로 보냄 · 기다리지 않음
    assert "await job_etf_names_startup" not in daemon
    api_main = open(__import__("backend.api.main", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert "etf_names" not in api_main                                   # API 프로세스에서는 안 돎
