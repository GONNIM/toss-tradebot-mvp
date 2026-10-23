"""화약고 알림 문구 · 종목명 (1023-05 Task 4)."""
from __future__ import annotations

import html

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.powderkeg import orders as orders_mod
from backend.powderkeg import scheduler as pk_sched
from backend.powderkeg import triggers as tr
from backend.services.db import get_session, init_db
from backend.services.models import KrxMarketSnapshot, PowderKegEvent, PowderKegList
from backend.tests.alert_rules import violations


@pytest_asyncio.fixture(autouse=True)
async def _clean():
    await init_db()
    async with get_session() as session:
        for m in (PowderKegEvent, PowderKegList, KrxMarketSnapshot):
            await session.execute(delete(m))
    yield


@pytest.fixture
def sent(monkeypatch):
    log: list = []

    async def _stub(title, body, urgent=False, category="unknown"):
        log.append({"title": title, "body": body, "urgent": urgent, "category": category})
        return True

    monkeypatch.setattr(tr, "_send_notification", _stub)
    return log


async def _event(ticker, etype, title="공시 제목", url="https://dart.fss.or.kr/x"):
    async with get_session() as session:
        e = PowderKegEvent(ticker=ticker, event_type=etype, source="dart", source_id=f"{etype}{ticker}", title=title, url=url)
        session.add(e)
        await session.flush()
        eid = e.id
    async with get_session() as session:
        return (await session.execute(select(PowderKegEvent).where(PowderKegEvent.id == eid))).scalar_one()


async def _list(ticker, name=None):
    async with get_session() as session:
        session.add(PowderKegList(run_id="20260813-000000", ticker=ticker, name=name, status="passed"))


async def _snapshot(ticker, name):
    async with get_session() as session:
        session.add(KrxMarketSnapshot(ticker=ticker, snapshot_date="2026-08-13", name=name))


@pytest.mark.asyncio
async def test_dnt_wording(sent):
    await _snapshot("012345", "가나다전자")
    await _list("012345")
    await tr.process_type_b(await _event("012345", "B1", "횡령·배임혐의발생"))
    m = sent[0]
    assert m["title"] == "🚨 화약고 거래 주의 · 가나다전자(012345)"
    assert "횡령·배임" in m["body"]
    assert "화약고 후보 목록에서 뺐습니다 (1건)." in m["body"]
    assert "공시 원문: https://dart.fss.or.kr/x" in m["body"]
    assert violations(m["title"], m["body"]) == []


@pytest.mark.asyncio
async def test_dnt_name_with_ampersand(sent):
    await _snapshot("064960", "S&T모티브")
    await tr.process_type_b(await _event("064960", "B3", "거래정지 <안내>"))
    t, b = sent[0]["title"], sent[0]["body"]
    assert "S&amp;T모티브(064960)" in t and "&amp;amp;" not in t
    assert "S&T모티브" in html.unescape(t)  # notifier 가 기록하는 plain_title
    assert "&lt;안내&gt;" in b


@pytest.mark.asyncio
async def test_dnt_name_looked_up_before_removal(sent):
    await _list("012345", name="목록에만있는이름")
    await tr.process_type_b(await _event("012345", "B1"))
    assert "목록에만있는이름(012345)" in sent[0]["title"]


@pytest.mark.asyncio
async def test_dnt_unknown_name(sent):
    await tr.process_type_b(await _event("999999", "B1"))
    assert "999999 (종목명 확인 안 됨)" in sent[0]["title"]


@pytest.mark.asyncio
async def test_candidate_negative_wording(sent, monkeypatch):
    async def _neg(_t):
        return "observed_negative"

    monkeypatch.setattr(tr, "_get_empirical_direction", _neg)
    await _snapshot("034567", "가나다")
    await tr.process_type_a(await _event("034567", "A3", "주식담보제공계약"))
    m = sent[0]
    assert m["title"].startswith("🔬 화약고 후보 · 담보 제공 · 가나다(034567)")
    assert "12개월 뒤 평균 -5% 아래 (통계 · 보장 아님)" in m["body"]
    assert "<" not in m["body"].replace("<b>", "")
    assert violations(m["title"], m["body"]) == []


@pytest.mark.asyncio
async def test_candidate_a4_has_label(sent, monkeypatch):
    async def _obs(_t):
        return "observing"

    monkeypatch.setattr(tr, "_get_empirical_direction", _obs)
    await tr.process_type_a(await _event("034567", "A4"))
    m = sent[0]
    assert m["category"] == "unknown"
    assert "화약고 후보 · 5% 보고" in m["title"]
    assert "과거 자료가 적어 방향을 판단하기 어렵습니다." in m["body"]
    assert violations(m["title"], m["body"]) == []


@pytest.mark.asyncio
async def test_ticket_and_reeval_wording(monkeypatch):
    calls: list = []

    class _N:
        async def send_info(self, title, body, category=None, dedupe_id=None):
            calls.append((title, body))

        async def send_warning(self, title, body, category=None, dedupe_id=None):
            calls.append((title, body))

    import backend.services.notifier as nmod

    monkeypatch.setattr(nmod, "TelegramNotifier", _N)
    await _snapshot("005930", "삼성전자")
    await orders_mod._notify_ticket_approved(42, "005930", "admin")
    t, b = calls[0]
    assert t == "✅ 화약고 티켓 승인 · 삼성전자(005930)"
    assert "승인 번호 42 · 승인한 사람 admin" in b
    assert violations(t, b) == []

    expired = [{"ticker": f"00000{i}", "age_days": 366 + i, "ticket_id": i} for i in range(7)]
    await pk_sched._notify_expiry(expired)
    t, b = calls[1]
    assert t == "⚠️ 화약고 12개월 재평가 · 7종목"
    assert b.count("일") >= 5 and "외 2종목" in b
    assert violations(t, b) == []
