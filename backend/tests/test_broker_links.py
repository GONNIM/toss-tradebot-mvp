"""1025-06 · 토스증권 주소 규칙 (국내 A코드 · 미국은 확인된 코드만 주문 화면)."""
from __future__ import annotations

import pytest

from backend.services import broker_links as bl
from backend.services.models import TossStockCode


def test_code_from_list_date():
    assert bl.toss_code_from_list_date("1981-05-27") == "US19810527001"
    assert bl.toss_code_from_list_date(None) is None
    assert bl.toss_code_from_list_date("1981/05/27") is None
    assert bl.toss_code_from_list_date("") is None


def test_kr_link():
    assert bl.is_kr_code("005930") and bl.is_kr_code("0101N0")
    assert not bl.is_kr_code("AAPL") and not bl.is_kr_code("ABCDEF")
    link = bl.broker_link("005930", None)
    assert link == {"symbol": "005930", "kind": "order", "url": "https://www.tossinvest.com/stocks/A005930/order", "verified": True}
    assert bl.broker_link("0101N0", None)["url"] == "https://www.tossinvest.com/stocks/A0101N0/order"


def test_us_unverified_is_search():
    row = TossStockCode(symbol="WEN", toss_code="US19810527001", source="api", verified=False)
    link = bl.broker_link("WEN", row)
    assert link["kind"] == "search" and link["url"] == "https://www.tossinvest.com/" and link["verified"] is False
    assert bl.broker_link("MRNA", None)["kind"] == "search"


def test_us_verified_is_order():
    row = TossStockCode(symbol="WEN", toss_code="US19810527001", source="manual", verified=True)
    assert bl.broker_link("WEN", row) == {"symbol": "WEN", "kind": "order", "url": "https://www.tossinvest.com/stocks/US19810527001/order", "verified": True}
    no_code = TossStockCode(symbol="X", toss_code=None, source="api", verified=True)
    assert bl.broker_link("X", no_code)["kind"] == "search"


def test_lowercase_and_junk():
    assert bl.normalize_symbol(" aapl ") == "AAPL"
    assert bl.normalize_symbol("brk.b") == "BRK.B"
    for bad in ("A;B", "", "A" * 13, "가나"):
        with pytest.raises(ValueError):
            bl.normalize_symbol(bad)


# ─── Task 6 · 하루 1회 배치 ───
from datetime import datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402


class _FakeToss:
    def __init__(self, data: dict[str, str | None]):
        self.data = data
        self.calls: list[list[str]] = []

    def stocks(self, symbols):
        self.calls.append(list(symbols))
        return [{"symbol": s, "listDate": self.data[s]} for s in symbols if s in self.data]


async def _rows():
    from backend.services.db import get_session

    async with get_session() as s:
        return {r.symbol: r for r in (await s.execute(select(TossStockCode))).scalars().all()}


@pytest.fixture
async def empty_table():
    from backend.services.db import get_session, init_db

    await init_db()
    async with get_session() as s:
        await s.execute(delete(TossStockCode))
    yield


@pytest.mark.asyncio
async def test_refresh_creates_rows(empty_table):
    fake = _FakeToss({"WEN": "1981-05-27"})
    out = await bl.refresh_toss_stock_codes(client=fake, symbols=["WEN", "005930"])
    rows = await _rows()
    assert rows["WEN"].toss_code == "US19810527001" and rows["WEN"].list_date == "1981-05-27"
    assert rows["WEN"].source == "api" and rows["WEN"].verified is False
    assert "005930" not in rows  # 국내는 표가 필요 없음
    assert out == {"asked": 1, "found": 1, "missing": 0, "skipped_manual": 0}


@pytest.mark.asyncio
async def test_refresh_keeps_manual(empty_table):
    from backend.services.db import get_session

    async with get_session() as s:
        s.add(TossStockCode(symbol="WEN", toss_code="US19810527002", source="manual", verified=True))
    fake = _FakeToss({"WEN": "1981-05-27"})
    out = await bl.refresh_toss_stock_codes(client=fake, symbols=["WEN"])
    row = (await _rows())["WEN"]
    assert row.toss_code == "US19810527002" and row.verified is True and row.source == "manual"
    assert fake.calls == [] and out["skipped_manual"] == 1


@pytest.mark.asyncio
async def test_refresh_missing_saved_null_and_not_reasked(empty_table):
    fake = _FakeToss({})
    out = await bl.refresh_toss_stock_codes(client=fake, symbols=["ZZZZ"])
    assert (await _rows())["ZZZZ"].toss_code is None and out["missing"] == 1
    again = await bl.refresh_toss_stock_codes(client=fake, symbols=["ZZZZ"])
    assert len(fake.calls) == 1 and again["asked"] == 0  # 7일 안에는 다시 묻지 않음


@pytest.mark.asyncio
async def test_refresh_reasks_after_7_days(empty_table):
    from backend.services.db import get_session

    async with get_session() as s:
        s.add(TossStockCode(symbol="OLD", toss_code=None, source="api", verified=False,
                            updated_at=datetime.utcnow() - timedelta(days=8)))
    fake = _FakeToss({"OLD": "2001-02-03"})
    await bl.refresh_toss_stock_codes(client=fake, symbols=["OLD"])
    assert (await _rows())["OLD"].toss_code == "US20010203001"


@pytest.mark.asyncio
async def test_refresh_batches_200(empty_table):
    syms = [f"T{i:03d}" for i in range(450)]
    fake = _FakeToss({s: "2020-01-01" for s in syms})
    out = await bl.refresh_toss_stock_codes(client=fake, symbols=syms)
    assert [len(c) for c in fake.calls] == [200, 200, 50] and out["found"] == 450


def test_radar_symbols_reads_ticker_column(tmp_path, monkeypatch):
    csv = tmp_path / "radar_v1_3_20261025.csv"
    csv.write_text("ticker,name\nLRMR,Larimar\n005930,삼성\nlrmr,dup\n,빈칸\n", encoding="utf-8")
    from backend.api.routes import biotech

    monkeypatch.setattr(biotech, "_latest_radar_csv", lambda: csv)
    assert bl.radar_symbols() == ["LRMR"]


def test_cron_registers_daily_0740():
    import inspect

    from backend.scheduler import cron

    src = inspect.getsource(cron.build_scheduler)
    assert 'CronTrigger(hour=7, minute=40)' in src and 'id="toss_stock_codes_daily"' in src
    assert inspect.iscoroutinefunction(cron.job_toss_stock_codes)


# ─── 최종 검토 (PR 2a) ───
@pytest.mark.asyncio
async def test_refresh_does_not_overwrite_manual_set_during_call(empty_table):
    """토스 응답을 기다리는 사이 관리자가 확인함으로 바꾼 값은 배치가 덮지 않는다."""
    from backend.services.db import get_session

    import asyncio

    loop = asyncio.get_running_loop()

    async def _admin_put():
        async with get_session() as sess:
            sess.add(TossStockCode(symbol="WEN", toss_code="US19810527009", source="manual", verified=True))

    class _SlowToss(_FakeToss):
        def stocks(self, symbols):  # 배치는 이 함수를 다른 스레드에서 부른다 · 그사이 관리자 PUT 이 들어옴
            asyncio.run_coroutine_threadsafe(_admin_put(), loop).result(timeout=5)
            return super().stocks(symbols)

    out = await bl.refresh_toss_stock_codes(client=_SlowToss({"WEN": "1981-05-27"}), symbols=["WEN"])
    row = (await _rows())["WEN"]
    assert row.source == "manual" and row.verified is True and row.toss_code == "US19810527009"
    assert out["found"] == 0


@pytest.mark.asyncio
async def test_refresh_bad_ticker_in_chunk_falls_back_one_by_one(empty_table):
    from backend.execution.exceptions import OrderRejected

    class _Strict(_FakeToss):
        def stocks(self, symbols):
            self.calls.append(list(symbols))
            if "BAD" in symbols:
                raise OrderRejected("stock-not-found", "없는 종목")
            return [{"symbol": s, "listDate": self.data[s]} for s in symbols if s in self.data]

    fake = _Strict({"WEN": "1981-05-27", "AAPL": "1980-12-12"})
    out = await bl.refresh_toss_stock_codes(client=fake, symbols=["WEN", "BAD", "AAPL"])
    rows = await _rows()
    assert rows["WEN"].toss_code == "US19810527001" and rows["AAPL"].toss_code == "US19801212001"
    assert rows["BAD"].toss_code is None and out == {"asked": 3, "found": 2, "missing": 1, "skipped_manual": 0}


@pytest.mark.asyncio
async def test_refresh_dict_response_is_ignored(empty_table):
    class _Dict(_FakeToss):
        def stocks(self, symbols):
            return {"unexpected": True}

    out = await bl.refresh_toss_stock_codes(client=_Dict({}), symbols=["WEN"])
    assert out["missing"] == 1
