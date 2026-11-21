"""1120-01 단계 2 · 섹터 수출 자료 빠진 달 따라잡기 · 표 모양 변화 · 계산 시각 (교훈 #22).

9/1 · 10/1 · 11/1 에 PDF 를 받지 못한 채 석 달이 지나도록 아무도 몰랐다.
외부 호출은 모두 가짜로 바꾼다 (KDI 사이트에 가지 않음).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from backend.discovery.data_sources.motir_export import parser as P
from backend.discovery.sector_leaders import scheduler as S

# ── 따라잡을 달 계산 ──────────────────────────────────────────


def test_months_to_catch_up_several_missing():
    got = S.months_to_catch_up({"2026-08"}, date(2026, 11, 1))
    # 최근 6개월 창(06~11) 중 비어 있는 달 전부
    assert got == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)]


def test_months_to_catch_up_middle_hole_only():
    present = {"2026-05", "2026-06", "2026-07", "2026-08", "2026-10"}
    # 8월 있음 · 9월 없음 · 10월 있음 → 이번 달이 10월이면 9월만
    assert S.months_to_catch_up(present, date(2026, 10, 1)) == [date(2026, 9, 1)]
    # 이번 달이 11월이고 아직 없으면 9월 + 11월
    assert S.months_to_catch_up(present, date(2026, 11, 1)) == [date(2026, 9, 1), date(2026, 11, 1)]


def test_months_to_catch_up_nothing_missing():
    full = {f"2026-{m:02d}" for m in range(6, 12)}
    assert S.months_to_catch_up(full, date(2026, 11, 1)) == []


def test_months_to_catch_up_no_history_only_current():
    assert S.months_to_catch_up(set(), date(2026, 11, 1)) == [date(2026, 11, 1)]
    assert S.months_to_catch_up(None, date(2026, 11, 1)) == [date(2026, 11, 1)]


def test_months_to_catch_up_window_is_six_months_across_year_end():
    got = S.months_to_catch_up({"2025-01"}, date(2026, 2, 1))
    assert got == [date(2025, 9, 1), date(2025, 10, 1), date(2025, 11, 1), date(2025, 12, 1),
                   date(2026, 1, 1), date(2026, 2, 1)]
    assert S.MOTIR_CATCHUP_MAX_MONTHS == 6


# ── motir_catchup 동작 (DB · KDI 가짜) ────────────────────────


class _Env:
    present: set = set()
    behavior: dict = {}
    calls: list = []


@pytest.fixture
def fake_env(monkeypatch):
    env = _Env()
    env.present = {"2026-06", "2026-07", "2026-08"}
    env.behavior = {}
    env.calls = []

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def fake_present(_session):
        return env.present

    async def fake_ingest(report_month=None, *, pdf_dir=None):
        key = S._month_key(report_month)
        env.calls.append(key)
        behavior = env.behavior.get(key, "ok")
        if behavior == "keyerror":
            raise KeyError(f"KDI num 미확인: {key}")
        if behavior == "boom":
            raise RuntimeError("PDF 읽기 실패")
        return {"item_inserted": 1}

    monkeypatch.setattr(S, "get_session", fake_session)
    monkeypatch.setattr(S, "_ingested_report_months", fake_present)
    monkeypatch.setattr(S, "monthly_ingest_job", fake_ingest)
    return env


@pytest.mark.asyncio
async def test_catchup_receives_all_missing_months_in_order(fake_env):
    st = await S.motir_catchup(current=date(2026, 11, 1))
    assert fake_env.calls == ["2026-09", "2026-10", "2026-11"]
    assert st["ok"] == 3 and st["failed"] == 0 and st["not_yet"] == 0
    assert st["months"]["2026-10"]["status"] == "ok"


@pytest.mark.asyncio
async def test_current_month_not_yet_is_warning_not_error(fake_env, caplog):
    fake_env.behavior = {"2026-11": "keyerror"}
    with caplog.at_level(logging.DEBUG, logger=S.logger.name):
        st = await S.motir_catchup(current=date(2026, 11, 1))
    assert st["months"]["2026-11"]["status"] == "not_yet"
    assert st["ok"] == 2 and st["not_yet"] == 1 and st["failed"] == 0
    recs = [r for r in caplog.records if "아직 KDI 에 없음" in r.getMessage()]
    assert recs and all(r.levelno == logging.WARNING for r in recs)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_past_month_missing_is_error_and_later_months_continue(fake_env, caplog):
    fake_env.behavior = {"2026-09": "keyerror", "2026-10": "boom"}
    with caplog.at_level(logging.DEBUG, logger=S.logger.name):
        st = await S.motir_catchup(current=date(2026, 11, 1))
    assert fake_env.calls == ["2026-09", "2026-10", "2026-11"]  # 중간 실패 뒤에도 계속
    assert st["months"]["2026-09"]["status"] == "failed"
    assert st["months"]["2026-10"]["status"] == "failed"
    assert st["months"]["2026-11"]["status"] == "ok"
    assert st["failed"] == 2
    assert [r for r in caplog.records if r.levelno >= logging.ERROR and "2026-09" in r.getMessage()]


@pytest.mark.asyncio
async def test_catchup_cap_limits_downloads(fake_env):
    fake_env.present = {"2025-01"}
    await S.motir_catchup(current=date(2026, 11, 1))
    assert len(fake_env.calls) == 6
    assert fake_env.calls[-1] == "2026-11"


@pytest.mark.asyncio
async def test_already_current_does_nothing(fake_env):
    fake_env.present = {f"2026-{m:02d}" for m in range(6, 12)}
    st = await S.motir_catchup(current=date(2026, 11, 1))
    assert fake_env.calls == [] and st["targets"] == []


@pytest.mark.asyncio
async def test_middle_hole_is_retried_even_if_later_month_present(fake_env):
    # 8월 있음 · 9월 없음 · 10월 있음 · 이번 달(11월) 없음 → 9월과 11월만 시도
    fake_env.present = {"2026-05", "2026-06", "2026-07", "2026-08", "2026-10"}
    await S.motir_catchup(current=date(2026, 11, 1))
    assert fake_env.calls == ["2026-09", "2026-11"]


@pytest.mark.asyncio
async def test_interim_jobs_run_catchup_first_and_continue_on_failure(monkeypatch):
    order: list[str] = []

    @asynccontextmanager
    async def fake_session():
        yield object()

    async def boom(**_kw):
        order.append("catchup")
        raise RuntimeError("KDI 연결 실패")

    async def ok(*_a, **_kw):
        order.append("step")
        return {}

    monkeypatch.setattr(S, "get_session", fake_session)
    monkeypatch.setattr(S, "motir_catchup", boom)
    monkeypatch.setattr(S, "_customs_fetch_recent", ok)
    monkeypatch.setattr(S, "_krx_candles_refresh", ok)
    monkeypatch.setattr(S, "_recompute_sector_leaders", ok)
    for job in (S.customs_interim_10day_job, S.customs_interim_20day_job):
        order.clear()
        st = await job()
        assert order == ["catchup", "step", "step", "step"]
        assert "error" in st["motir"]


# ── 표 모양: 별칭 · 보조 표 ───────────────────────────────────


def _row(name, base):
    cols = [str(base + i) for i in range(13)]
    return [name, "1,000"] + cols


def _block(name, base):
    return [_row(name, base), [None, "(1.0)"] + ["(1.0)"] * 13, [None, "1.0"] + ["1.0"] * 13]


def _table(names):
    rows = [["품목명"] + [None] * 14, [None, None] + ["m"] * 13]
    for n, b in names:
        rows += _block(n, b)
    return rows


def test_alias_maps_renamed_item_to_same_item():
    t = _table([("선박", 100), ("철\n강", 200)])  # 이름이 '철강' 으로 바뀜 (줄바꿈 포함)
    recs = P._parse_block(t, P.report_to_months(date(2026, 10, 1)), P.ITEM_ORDER_15, has_share=True)
    assert {r.item for r in recs} == {"선박", "철강제품"}


class _FakePage:
    def __init__(self, tables):
        self._t = tables

    def extract_tables(self):
        return self._t


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_items_moved_to_extension_table_are_read(monkeypatch, tmp_path):
    main_names = [(n, 100 + i) for i, n in enumerate(
        ["반도체", "자동차", "일반기계", "석유제품", "석유화학", "선박", "철강", "자동차부품",
         "무선통신기기", "디스플레이", "전기기기", "바이오헬스", "비철금속", "컴퓨터", "농수산식품"])]
    ext_names = [("화장품", 1), ("섬유", 2), ("생활용품", 3), ("가전", 4), ("이차전지", 5)]
    pdf = _FakePdf([_FakePage([_table(main_names)]), _FakePage([_table(ext_names)])])
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    monkeypatch.setattr(P.pdfplumber, "open", lambda _p: pdf)
    recs = P.parse_item_timeseries(f, date(2026, 10, 1), include_consumer_supplement=False)
    items = {r.item for r in recs}
    assert {"철강제품", "가전", "섬유", "이차전지"} <= items
    assert "비철금속" not in items and "전기기기" not in items  # 새 품목은 건너뜀 (규칙 불변)
    assert len(recs) == len(items) * 13  # 중복 없음


def test_truly_missing_item_is_left_out_and_reported(monkeypatch, tmp_path, caplog):
    # 47행(15품목)을 맞추려고 새 품목 하나를 가전 자리에 둔다 — 가전은 어느 표에도 없음
    main_names = [(n if n != "가전" else "전기기기", 100 + i) for i, n in enumerate(P.ITEM_ORDER_15)]
    pdf = _FakePdf([_FakePage([_table(main_names)])])
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF")
    monkeypatch.setattr(P.pdfplumber, "open", lambda _p: pdf)
    with caplog.at_level(logging.WARNING, logger=P.logger.name):
        recs = P.parse_item_timeseries(f, date(2026, 10, 1), include_consumer_supplement=False)
    assert "가전" not in {r.item for r in recs}
    assert P.missing_items(recs, include_consumer=False) == ["가전"]
    assert any("끝내 못 읽은 품목" in r.getMessage() and "가전" in r.getMessage() for r in caplog.records)


# ── 계산 시각: 요청 시각이 아니라 sector_leaders.computed_at 최대값 ──


@pytest.mark.asyncio
async def test_computed_at_is_calculation_time_not_request_time():
    from sqlalchemy import delete

    from backend.services.db import get_session, init_db
    from backend.services.models import MotirItemExport, SectorLeader

    await init_db()
    async with get_session() as s:
        await s.execute(delete(SectorLeader))
        await s.execute(delete(MotirItemExport))
        s.add(SectorLeader(item="선박", ticker="000001", name="가", rank=1, score=1.0,
                           confidence="weak", computed_at=datetime(2026, 11, 11, 3, 0, 0)))
        s.add(SectorLeader(item="선박", ticker="000002", name="나", rank=2, score=0.5,
                           confidence="weak", computed_at=datetime(2026, 11, 21, 3, 5, 9)))
        s.add(MotirItemExport(item="선박", month="2026-09", value_musd=1.0,
                              source_report_month="2026-10", source_pdf="x.pdf"))
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/sector-leaders/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["computed_at"] == "2026-11-21T03:05:09Z"
    assert body["latest_export_month"] == "2026-09"
    assert body["latest_report_month"] == "2026-10"
