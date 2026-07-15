"""P7-1g corp_code 매핑 테스트."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DART_API_KEY", "test_key_stub")

from backend.discovery.data_sources.dart.client import CorpCodeEntry
from backend.powderkeg.collectors import corp_codes as cc_mod
from backend.powderkeg.collectors.corp_codes import (
    refresh_corp_codes,
    resolve_corp_code,
    resolve_many,
)
from backend.services.db import get_session, init_db
from backend.services.models import DartCorpCodeMap


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    await init_db()
    async with get_session() as session:
        await session.execute(delete(DartCorpCodeMap))
    yield


@pytest.mark.asyncio
async def test_refresh_persists_all_entries(monkeypatch):
    async def _stub_fetch():
        return [
            CorpCodeEntry(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
            CorpCodeEntry(corp_code="00164779", corp_name="에스케이하이닉스", stock_code="000660", modify_date="20240101"),
            CorpCodeEntry(corp_code="00113517", corp_name="효성", stock_code="004800", modify_date="20240101"),
            CorpCodeEntry(corp_code="00113576", corp_name="영풍", stock_code="000670", modify_date="20240101"),
            # 비상장 · stock_code None
            CorpCodeEntry(corp_code="99999999", corp_name="비상장회사", stock_code=None, modify_date="20240101"),
        ]
    monkeypatch.setattr(cc_mod, "fetch_corp_codes", _stub_fetch)

    stats = await refresh_corp_codes()
    assert stats["total"] == 5
    assert stats["with_stock"] == 4
    assert stats["upserted"] == 5


@pytest.mark.asyncio
async def test_resolve_corp_code(monkeypatch):
    async def _stub_fetch():
        return [
            CorpCodeEntry(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
        ]
    monkeypatch.setattr(cc_mod, "fetch_corp_codes", _stub_fetch)
    await refresh_corp_codes()

    assert await resolve_corp_code("005930") == "00126380"
    assert await resolve_corp_code("999999") is None
    assert await resolve_corp_code("") is None


@pytest.mark.asyncio
async def test_resolve_many_batch(monkeypatch):
    async def _stub_fetch():
        return [
            CorpCodeEntry(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101"),
            CorpCodeEntry(corp_code="00164779", corp_name="SK하이닉스", stock_code="000660", modify_date="20240101"),
        ]
    monkeypatch.setattr(cc_mod, "fetch_corp_codes", _stub_fetch)
    await refresh_corp_codes()

    r = await resolve_many(["005930", "000660", "999999"])
    assert r == {"005930": "00126380", "000660": "00164779"}


@pytest.mark.asyncio
async def test_refresh_upsert_on_rerun(monkeypatch):
    """재실행 · 동일 corp_code 값 갱신 (corp_name 변경 반영)."""
    async def _stub_fetch_v1():
        return [CorpCodeEntry(corp_code="00126380", corp_name="구명칭", stock_code="005930", modify_date="20230101")]
    async def _stub_fetch_v2():
        return [CorpCodeEntry(corp_code="00126380", corp_name="삼성전자", stock_code="005930", modify_date="20240101")]

    monkeypatch.setattr(cc_mod, "fetch_corp_codes", _stub_fetch_v1)
    await refresh_corp_codes()
    monkeypatch.setattr(cc_mod, "fetch_corp_codes", _stub_fetch_v2)
    await refresh_corp_codes()

    async with get_session() as session:
        rows = (await session.execute(select(DartCorpCodeMap))).scalars().all()
    assert len(rows) == 1
    assert rows[0].corp_name == "삼성전자"    # 최신 반영


@pytest.mark.asyncio
async def test_resolve_empty_ticker():
    assert await resolve_corp_code("") is None
    assert await resolve_many([]) == {}
