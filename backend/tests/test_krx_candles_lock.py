"""1102-08 · KRX 일봉 적재가 SQLite 쓰기 잠금을 오래 잡지 않는지 (월간 재계산 잠금 고침).

외부 요청 없음 — pykrx 받기(fetch_daily_candles)는 가짜로 바꾼다. 파일 SQLite 는 임시 폴더에 만든다.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert  # noqa: F401  (아래 기준 구현에서 쓰지 않음 · 새 코드와 구분용 아님)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.discovery.data_sources.krx_price import loader
from backend.services.models import KrxDailyCandle

END = date(2026, 10, 30)


def _df(n: int = 3, base: float = 100.0, ret=0.5) -> pd.DataFrame:
    idx = pd.date_range("2026-10-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "시가": [base + i for i in range(n)],
            "고가": [base + i + 2 for i in range(n)],
            "저가": [base + i - 2 for i in range(n)],
            "종가": [base + i + 1 for i in range(n)],
            "거래량": [1000.0 + i for i in range(n)],
            "등락률": [ret] * n,
        },
        index=idx,
    )


async def _ingest_reference(session, tickers, fetch, end_date):
    """옛 구현(origin/main 5259ed5)과 같은 동작의 기준 — 행마다 SELECT · 끝까지 flush 만."""
    stats = {"tickers": 0, "rows_inserted": 0, "rows_updated": 0, "failures": 0}
    for ticker in sorted(set(tickers)):
        stats["tickers"] += 1
        try:
            df = await fetch(ticker)
        except Exception:
            stats["failures"] += 1
            continue
        if df.empty:
            continue
        for d, row in df.iterrows():
            ds = d.strftime("%Y-%m-%d")
            existing = (
                await session.execute(
                    select(KrxDailyCandle).where(
                        KrxDailyCandle.ticker == ticker, KrxDailyCandle.date == ds
                    )
                )
            ).scalar_one_or_none()
            vals = dict(
                open=float(row["시가"]), high=float(row["고가"]), low=float(row["저가"]),
                close=float(row["종가"]), volume=float(row["거래량"]),
                return_pct=float(row.get("등락률") or 0.0),
            )
            if existing is None:
                session.add(KrxDailyCandle(ticker=ticker, date=ds, **vals))
                stats["rows_inserted"] += 1
            else:
                for k, v in vals.items():
                    setattr(existing, k, v)
                stats["rows_updated"] += 1
        await session.flush()
    await session.commit()
    return stats


@pytest.fixture
async def file_db(tmp_path):
    path = tmp_path / "krx.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 30})
    async with engine.begin() as conn:
        await conn.run_sync(KrxDailyCandle.__table__.create)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield path, Session
    await engine.dispose()


async def _dump(Session) -> list[tuple]:
    async with Session() as s:
        rows = (await s.execute(select(KrxDailyCandle).order_by(KrxDailyCandle.ticker, KrxDailyCandle.date))).scalars().all()
        return [
            (r.ticker, r.date, r.open, r.high, r.low, r.close, r.volume, r.return_pct) for r in rows
        ]


def _patch_fetch(monkeypatch, frames: dict, hook=None):
    async def fake(ticker, start, end):
        if hook:
            hook(ticker)
        v = frames[ticker]
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(loader, "fetch_daily_candles", fake)

    async def ref_fetch(ticker):
        return await fake(ticker, None, None)

    return ref_fetch


# ① 옛 코드와 새 코드의 결과 동일 ─────────────────────────────────


async def test_same_result_as_old_logic(tmp_path, monkeypatch):
    results = []
    for name in ("old", "new"):
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / (name + '.db')}")
        async with engine.begin() as conn:
            await conn.run_sync(KrxDailyCandle.__table__.create)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        # 기존 행: 값이 다른 것 · 값이 같은 것(같아도 updated) 둘 다 미리 넣는다
        async with Session() as s:
            s.add_all([
                KrxDailyCandle(ticker="AAA", date="2026-10-01", open=1, high=1, low=1, close=1, volume=1, return_pct=9.0),
                KrxDailyCandle(ticker="AAA", date="2026-10-02", open=101.0, high=103.0, low=99.0, close=102.0, volume=1001.0, return_pct=0.5),
            ])
            await s.commit()
        # 등락률 0 · NaN 은 `or 0.0` 로 0.0 (NaN 은 truthy 라 그대로 NaN 이 아님 → 숫자만 비교하려 0 과 값 있음만 씀)
        frames = {
            "AAA": _df(3, 100.0, 0.5),
            "BBB": _df(2, 50.0, 0.0),
            "CCC": pd.DataFrame(),
            "DDD": RuntimeError("boom"),
        }
        ref_fetch = _patch_fetch(monkeypatch, frames)
        async with Session() as s:
            if name == "old":
                st = await _ingest_reference(s, list(frames), ref_fetch, END)
            else:
                st = await loader.ingest_24m_candles(s, list(frames), END)
        results.append((st, await _dump(Session)))
        await engine.dispose()
    (st_old, rows_old), (st_new, rows_new) = results
    assert st_old == st_new == {"tickers": 4, "rows_inserted": 3, "rows_updated": 2, "failures": 1}
    assert rows_old == rows_new
    assert len(rows_new) == 5
    assert [r[7] for r in rows_new if r[0] == "BBB"] == [0.0, 0.0]  # or 0.0


# ② 파일 SQLite 두 연결 잠금 ───────────────────────────────────


def _probe_write(path) -> str | None:
    """다른 연결이 쓰기를 시도한다. 0.2초 안에 못 잡으면 오류 문구를 돌려준다."""
    con = sqlite3.connect(path, timeout=0.2, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        return None
    except sqlite3.OperationalError as e:
        return str(e)
    finally:
        con.close()


async def test_other_connection_can_write_while_fetching(file_db, monkeypatch):
    path, Session = file_db
    probes: dict[str, str | None] = {}
    frames = {t: _df(20) for t in ("AAA", "BBB", "CCC")}
    _patch_fetch(monkeypatch, frames, hook=lambda t: probes.__setitem__(t, _probe_write(path)))
    async with Session() as s:
        await loader.ingest_24m_candles(s, list(frames), END)
    print("probe results:", probes)
    assert probes == {"AAA": None, "BBB": None, "CCC": None}, probes


# ③ 한 종목 쓰기 실패가 번지지 않음 ───────────────────────────────


async def test_write_failure_isolated_per_ticker(file_db, monkeypatch):
    path, Session = file_db
    bad = _df(3)
    bad["종가"] = [float("nan")] * 3  # 아래에서 쓰기 단계 예외를 만든다
    frames = {"AAA": _df(3), "BBB": bad, "CCC": _df(3, 70.0)}
    _patch_fetch(monkeypatch, frames)

    real = loader._upsert_rows

    async def flaky(session, ticker, rows):
        if ticker == "BBB":
            raise sqlite3.OperationalError("database is locked")
        return await real(session, ticker, rows)

    monkeypatch.setattr(loader, "_upsert_rows", flaky)
    async with Session() as s:
        st = await loader.ingest_24m_candles(s, list(frames), END)
    assert st["failures"] == 1 and st["tickers"] == 3
    assert st["rows_inserted"] == 6
    rows = await _dump(Session)
    assert {r[0] for r in rows} == {"AAA", "CCC"} and len(rows) == 6


# ④ 받기 호출 때 세션이 깨끗함 ─────────────────────────────────


async def test_session_clean_when_fetch_called(file_db, monkeypatch):
    path, Session = file_db
    seen: list[tuple] = []
    async with Session() as s:
        def hook(t):
            seen.append((t, bool(s.dirty), bool(s.new), s.in_transaction()))

        _patch_fetch(monkeypatch, {t: _df(5) for t in ("AAA", "BBB", "CCC")}, hook=hook)
        await loader.ingest_24m_candles(s, ["AAA", "BBB", "CCC"], END)
    assert [x[0] for x in seen] == ["AAA", "BBB", "CCC"]
    assert all(x[1:] == (False, False, False) for x in seen), seen


# ⑤ 51종목 × 500행 최장 잠금 시간 ────────────────────────────────


async def test_longest_lock_51x500(file_db, monkeypatch):
    path, Session = file_db
    tickers = [f"{i:06d}" for i in range(51)]
    frames = {t: _df(500, 100.0 + i) for i, t in enumerate(tickers)}
    _patch_fetch(monkeypatch, frames)

    # 쓰기 잠금이 잡힌 구간: 다른 연결에서 짧게 BEGIN IMMEDIATE 를 반복 시도해 막힌 가장 긴 연속 시간을 잰다.
    stop = asyncio.Event()
    longest = {"s": 0.0}

    def watcher():
        blocked_since = None
        while not stop_flag["v"]:
            err = _probe_write_fast(path)
            now = time.perf_counter()
            if err and blocked_since is None:
                blocked_since = now
            elif not err and blocked_since is not None:
                longest["s"] = max(longest["s"], now - blocked_since)
                blocked_since = None
        if blocked_since is not None:
            longest["s"] = max(longest["s"], time.perf_counter() - blocked_since)

    stop_flag = {"v": False}
    task = asyncio.create_task(asyncio.to_thread(watcher))
    t0 = time.perf_counter()
    async with Session() as s:
        st = await loader.ingest_24m_candles(s, tickers, END)
    total = time.perf_counter() - t0
    stop_flag["v"] = True
    await task
    print(f"51x500: total={total:.2f}s longest_lock={longest['s']:.3f}s stats={st}")
    assert st["rows_inserted"] == 51 * 500
    assert longest["s"] < 1.0  # 한 종목(500행) commit 구간은 1초 안


def _probe_write_fast(path) -> str | None:
    con = sqlite3.connect(path, timeout=0.0, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        return None
    except sqlite3.OperationalError as e:
        return str(e)
    finally:
        con.close()
        time.sleep(0.002)
