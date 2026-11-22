"""1122-01 섹터 시총 갱신 · 출처 고르기 시험.

외부 호출(FDR)은 모두 가짜 표로 바꾼다. 종목 이름은 가짜다.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.discovery.data_sources.mapping import iter_all_tickers
from backend.discovery.sector_leaders import analysis as A
from backend.discovery.sector_leaders import mcap_source as M
from backend.discovery.sector_leaders import scheduler as S
from backend.services.db import get_session, init_db
from backend.services.models import KrxMarketSnapshot, KrxStockMeta

CODES = sorted({t.code for t in iter_all_tickers()})


def _listing(n_rows=2771, skip=(), overrides=None, base=1.0e12):
    """가짜 FDR 표. CODES 는 모두 넣고(skip 제외) 나머지 행은 채움용 가짜 코드."""
    overrides = overrides or {}
    rows = []
    for i, c in enumerate(CODES):
        if c in skip:
            continue
        r = {"Code": c, "Name": f"가짜{i}", "Market": "KOSPI",
             "Close": 1000.0 + i, "Marcap": base * (i + 1), "Stocks": 1.0e6}
        r.update(overrides.get(c, {}))
        rows.append(r)
    fill = max(0, n_rows - len(rows))
    for j in range(fill):
        rows.append({"Code": f"9{j:05d}", "Name": f"채움{j}", "Market": "KOSDAQ",
                     "Close": 1.0, "Marcap": 1.0e9, "Stocks": 1.0})
    return pd.DataFrame(rows)


def _fetcher(df):
    async def f():
        return df
    return f


@pytest_asyncio.fixture
async def db():
    await init_db()
    async with get_session() as s:
        await s.execute(delete(KrxStockMeta))
        await s.execute(delete(KrxMarketSnapshot))
    yield
    async with get_session() as s:
        await s.execute(delete(KrxStockMeta))
        await s.execute(delete(KrxMarketSnapshot))


async def _seed_meta(s, value=5.0e11, close=500.0, fetched=datetime(2026, 6, 1, 3, 0, 0), codes=None):
    for c in codes or CODES:
        s.add(KrxStockMeta(ticker=c, name="옛", market="KOSPI", market_cap_krw=value,
                           last_close=close, fetched_at=fetched))
    await s.flush()


async def _meta(s, code):
    return (await s.execute(select(KrxStockMeta).where(KrxStockMeta.ticker == code))).scalar_one()


# ── 값 지키기 (M1) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_values_are_written(db):
    async with get_session() as s:
        await _seed_meta(s)
        st = await M.refresh_sector_meta(s, CODES, fetcher=_fetcher(_listing()))
        await s.commit()
        assert st["skipped"] is False and st["found"] == len(CODES)
        m = await _meta(s, CODES[0])
        assert m.market_cap_krw == pytest.approx(1.0e12)
        assert m.last_close == pytest.approx(1000.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, float("nan"), -5.0, None, float("inf")])
async def test_bad_marcap_or_close_keeps_old_value(db, bad):
    c = CODES[3]
    async with get_session() as s:
        await _seed_meta(s)
        df = _listing(overrides={c: {"Marcap": bad, "Close": bad}})
        st = await M.refresh_sector_meta(s, CODES, fetcher=_fetcher(df))
        await s.commit()
        assert st["skipped"] is False and st["found"] == len(CODES) - 1
        m = await _meta(s, c)
        assert m.market_cap_krw == 5.0e11 and m.last_close == 500.0


@pytest.mark.asyncio
async def test_bad_close_alone_keeps_old_close_but_updates_marcap(db):
    c = CODES[4]
    async with get_session() as s:
        await _seed_meta(s)
        df = _listing(overrides={c: {"Close": float("nan")}})
        await M.refresh_sector_meta(s, CODES, fetcher=_fetcher(df))
        await s.commit()
        m = await _meta(s, c)
        assert m.market_cap_krw == pytest.approx(1.0e12 * (CODES.index(c) + 1))
        assert m.last_close == 500.0


@pytest.mark.asyncio
async def test_too_few_listing_rows_skips_everything(db):
    async with get_session() as s:
        await _seed_meta(s)
        df = _listing(n_rows=M.MIN_LISTING_ROWS - 1)
        # 행 수를 기준 미만으로 만들기 위해 채움 행이 없어야 한다
        df = df.head(M.MIN_LISTING_ROWS - 1)
        st = await M.refresh_sector_meta(s, CODES, fetcher=_fetcher(df))
        await s.commit()
        assert st["skipped"] is True
        assert (await _meta(s, CODES[0])).market_cap_krw == 5.0e11


@pytest.mark.asyncio
async def test_too_few_found_skips_everything(db):
    need = -(-len(CODES) * 8 // 10)  # ceil(0.8 * 51)
    skip = set(CODES[: len(CODES) - need + 1])  # 찾은 수 = need - 1
    async with get_session() as s:
        await _seed_meta(s)
        st = await M.refresh_sector_meta(s, CODES, fetcher=_fetcher(_listing(skip=skip)))
        await s.commit()
        assert st["skipped"] is True and st["found"] == need - 1
        assert (await _meta(s, CODES[-1])).market_cap_krw == 5.0e11


@pytest.mark.asyncio
async def test_exactly_at_threshold_runs(db):
    need = -(-len(CODES) * 8 // 10)
    skip = set(CODES[: len(CODES) - need])  # 찾은 수 = need
    async with get_session() as s:
        await _seed_meta(s)
        st = await M.refresh_sector_meta(s, CODES, fetcher=_fetcher(_listing(skip=skip)))
        await s.commit()
        assert st["skipped"] is False and st["found"] == need
        # 목록에 없던 종목은 옛 값 그대로
        assert (await _meta(s, CODES[0])).market_cap_krw == 5.0e11


# ── 출처 고르기 (M3) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_newer_snapshot_wins_and_same_source_for_all(db):
    async with get_session() as s:
        await _seed_meta(s, value=5.0e11, fetched=datetime(2026, 6, 1, 3, 0, 0))
        for c in CODES[1:]:  # CODES[0] 은 스냅샷에 없음
            s.add(KrxMarketSnapshot(ticker=c, snapshot_date="2026-11-22", market_cap=7.0e11, close_price=70.0))
            s.add(KrxMarketSnapshot(ticker=c, snapshot_date="2026-10-01", market_cap=1.0e11, close_price=10.0))
        await s.flush()
        ch = await M.load_mcap_choice(s, CODES)
    assert ch.primary == "snapshot"
    assert all(ch.values[c] == 7.0e11 for c in CODES[1:])  # 가장 새로운 날짜 행
    assert ch.sources[CODES[1]] == ("snapshot", "2026-11-22")
    # 스냅샷에 없는 종목만 메타로 채움
    assert ch.sources[CODES[0]] == ("meta", "2026-06-01") and ch.values[CODES[0]] == 5.0e11
    assert sum(1 for v in ch.sources.values() if v[0] == "meta") == 1


@pytest.mark.asyncio
async def test_newer_meta_wins_over_older_snapshot(db):
    async with get_session() as s:
        await _seed_meta(s, value=5.0e11, fetched=datetime(2026, 11, 22, 3, 0, 0))
        for c in CODES:
            s.add(KrxMarketSnapshot(ticker=c, snapshot_date="2026-11-01", market_cap=7.0e11, close_price=70.0))
        await s.flush()
        ch = await M.load_mcap_choice(s, CODES)
    assert ch.primary == "meta"
    assert all(v == 5.0e11 for v in ch.values.values())


@pytest.mark.asyncio
async def test_same_date_prefers_meta(db):
    async with get_session() as s:
        await _seed_meta(s, value=5.0e11, fetched=datetime(2026, 11, 22, 3, 0, 0))
        for c in CODES:
            s.add(KrxMarketSnapshot(ticker=c, snapshot_date="2026-11-22", market_cap=7.0e11, close_price=70.0))
        await s.flush()
        ch = await M.load_mcap_choice(s, CODES)
    assert ch.primary == "meta"


@pytest.mark.asyncio
async def test_choice_logs_ticker_source_date(db, caplog):
    import logging
    caplog.set_level(logging.INFO, logger=M.logger.name)
    async with get_session() as s:
        await _seed_meta(s, fetched=datetime(2026, 6, 1, 3, 0, 0), codes=CODES[:1])
        s.add(KrxMarketSnapshot(ticker=CODES[1], snapshot_date="2026-11-22", market_cap=7.0e11, close_price=1.0))
        await s.flush()
        await M.load_mcap_choice(s, CODES[:2])
    text = caplog.text
    assert f"{CODES[1]}': 'snapshot@2026-11-22'" in text and f"{CODES[0]}': 'meta@2026-06-01'" in text


@pytest.mark.asyncio
async def test_compute_uses_chosen_source_for_score(db, monkeypatch):
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    yoy = {t.item: {m: float(i) for i, m in enumerate(months)} for t in iter_all_tickers()}
    ret = {c: {m: float((i * 7) % 5) for i, m in enumerate(months)} for c in CODES}

    async def fy(_s):
        return yoy

    async def fr(_s):
        return ret

    monkeypatch.setattr(A, "_load_item_yoy", fy)
    monkeypatch.setattr(A, "_load_ticker_monthly_return", fr)
    async with get_session() as s:
        await _seed_meta(s, value=5.0e11, fetched=datetime(2026, 6, 1, 3, 0, 0))
        for c in CODES:
            s.add(KrxMarketSnapshot(ticker=c, snapshot_date="2026-11-22", market_cap=2.0e13, close_price=1.0))
        await s.flush()
        res = await A.compute_sector_leaders(s)
    assert res and all(r.market_cap_krw == 2.0e13 for r in res)


# ── top10 대체 가격 ────────────────────────────────────────────


def test_pick_last_close_snapshot_newer_gives_date():
    meta = KrxStockMeta(ticker="000000", name="x", last_close=100.0, fetched_at=datetime(2026, 6, 1))
    snap = KrxMarketSnapshot(ticker="000000", snapshot_date="2026-11-22", close_price=120.0)
    assert M.pick_last_close(meta, snap) == (120.0, "2026-11-22")


def test_pick_last_close_meta_newer_or_equal_keeps_old_behavior():
    meta = KrxStockMeta(ticker="000000", name="x", last_close=100.0, fetched_at=datetime(2026, 11, 22))
    snap = KrxMarketSnapshot(ticker="000000", snapshot_date="2026-11-22", close_price=120.0)
    assert M.pick_last_close(meta, snap) == (100.0, None)


def test_pick_last_close_meta_missing_uses_snapshot_and_none_when_both_bad():
    snap = KrxMarketSnapshot(ticker="000000", snapshot_date="2026-11-22", close_price=120.0)
    assert M.pick_last_close(None, snap) == (120.0, "2026-11-22")
    bad = KrxStockMeta(ticker="000000", name="x", last_close=float("nan"))
    assert M.pick_last_close(bad, None) == (None, None)


# ── 잡 연결 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_three_jobs_refresh_before_recompute_and_survive_failure(monkeypatch):
    order: list[str] = []

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def ok(*_a, **_kw):
        order.append("other")
        return {}

    async def boom_refresh(*_a, **_kw):
        order.append("meta")
        raise RuntimeError("FDR 실패")

    async def recompute(*_a, **_kw):
        order.append("recompute")
        return {}

    monkeypatch.setattr(S, "get_session", fake_session)
    monkeypatch.setattr(S, "motir_catchup", ok)
    monkeypatch.setattr(S, "monthly_ingest_job", ok)
    monkeypatch.setattr(S, "refresh_kdi_cache", ok)
    monkeypatch.setattr(S, "_customs_fetch_recent", ok)
    monkeypatch.setattr(S, "_krx_candles_refresh", ok)
    monkeypatch.setattr(S, "_krx_meta_refresh", boom_refresh)
    monkeypatch.setattr(S, "_recompute_sector_leaders", recompute)
    for job in (S.monthly_full_refresh_job, S.customs_interim_10day_job, S.customs_interim_20day_job):
        order.clear()
        st = await job()
        assert order.index("meta") < order.index("recompute"), job.__name__
        assert "error" in st["krx_meta"] and st["recompute"] == {}
        assert order[-1] == "recompute"


@pytest.mark.asyncio
async def test_meta_refresh_step_commits_before_fetch_and_rolls_back_on_failure(monkeypatch):
    calls: list[str] = []

    class FakeSession:
        async def commit(self):
            calls.append("commit")

        async def rollback(self):
            calls.append("rollback")

    async def fake_refresh(_s, codes):
        calls.append("fetch")
        raise RuntimeError("실패")

    monkeypatch.setattr(S, "refresh_sector_meta", fake_refresh)
    with pytest.raises(RuntimeError):
        await S._krx_meta_refresh(FakeSession())
    assert calls == ["commit", "fetch", "rollback"]


# ── 1122-04 · 받기 시간 제한 · 오래된 메타 종목만 스냅샷으로 ─────────────


@pytest.mark.asyncio
async def test_fetch_timeout_skips_and_recompute_still_runs(db, monkeypatch):
    """받기가 제한 시간을 넘으면 건너뜀 · 아무것도 안 쓰고 · 재계산 단계는 그대로 돈다."""
    import asyncio

    monkeypatch.setattr(M, "FETCH_TIMEOUT_SEC", 0.05)

    async def hang():
        await asyncio.sleep(5)

    monkeypatch.setattr(M, "fetch_sector_listing", hang)
    recomputed = []

    async def fake_recompute(session):
        recomputed.append(1)
        return {"ok": True}

    monkeypatch.setattr(S, "_recompute_sector_leaders", fake_recompute)
    async with get_session() as s:
        await _seed_meta(s)
        st = await S._krx_meta_refresh(s)  # 예외 없이 건너뜀으로 돌아와야 한다
        assert st["skipped"] is True and st["reason"].startswith("timeout")
        assert (await _meta(s, CODES[0])).market_cap_krw == 5.0e11
        out = await S._recompute_sector_leaders(s)
    assert out == {"ok": True} and recomputed == [1]


@pytest.mark.asyncio
async def test_stale_meta_ticker_only_filled_from_newer_snapshot(db):
    """주 출처=메타 · 한 종목만 메타 날짜가 옛것 → 그 종목만 스냅샷 값."""
    stale = CODES[2]
    async with get_session() as s:
        await _seed_meta(s, fetched=datetime(2026, 11, 22, 3, 0, 0))
        (await _meta(s, stale)).fetched_at = datetime(2026, 6, 1, 3, 0, 0)
        s.add(KrxMarketSnapshot(ticker=stale, snapshot_date="2026-11-10", market_cap=7.0e11, close_price=70.0))
        await s.flush()
        ch = await M.load_mcap_choice(s, CODES)
    assert ch.primary == "meta"
    assert ch.sources[stale] == ("snapshot", "2026-11-10")
    assert ch.values[stale] == pytest.approx(7.0e11)
    others = [c for c in CODES if c != stale]
    assert all(ch.sources[c] == ("meta", "2026-11-22") for c in others)
    assert all(ch.values[c] == pytest.approx(5.0e11) for c in others)


@pytest.mark.asyncio
async def test_same_date_keeps_meta(db):
    """메타 날짜와 스냅샷 날짜가 같으면 그대로 메타."""
    c = CODES[2]
    async with get_session() as s:
        await _seed_meta(s, fetched=datetime(2026, 11, 22, 3, 0, 0))
        s.add(KrxMarketSnapshot(ticker=c, snapshot_date="2026-11-22", market_cap=7.0e11, close_price=70.0))
        await s.flush()
        ch = await M.load_mcap_choice(s, CODES)
    assert ch.sources[c] == ("meta", "2026-11-22")
    assert ch.values[c] == pytest.approx(5.0e11)
