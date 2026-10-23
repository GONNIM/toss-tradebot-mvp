"""VIP · 행동주의 알림 문구 (1023-05 Task 5)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.discovery.activist import notifier as an
from backend.discovery.activist.state import ActivistEvent
from backend.discovery.activist.wolf_pack import WolfPackEntry, WolfPackGroup
from backend.discovery.vip import notifier as vn
from backend.discovery.vip.activist_tracker import Filing
from backend.discovery.vip.position import Event
from backend.tests.alert_rules import violations


class _N:
    def __init__(self):
        self.calls: list = []

    async def send_info(self, title, body, category=None, dedupe_id=None):
        self.calls.append({"title": title, "body": body, "category": category, "dedupe_id": dedupe_id})
        return True


def _cfg(**kw):
    base = dict(tag="WEN", company_name="Wendy's", avg_price=10.0, qty=300, stop_pct=-0.05, tp1_pct=0.07, tp2_pct=0.15,
                activist_name="Trian", activist_cik="1345471")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_vip_tp1():
    n = _N()
    await vn.send_position_event(n, Event(name="TP1", pnl=0.142, current_price=11.42), _cfg())
    c = n.calls[0]
    assert c["title"] == "🎯 VIP 감시 · Wendy's 설정한 1차 기준 도달"
    assert "설정 기준 +7.0% · 지금 +14.2%" in c["body"]
    assert "산 값 $10.00 → 지금 $11.42 (+14.2%)" in c["body"]
    assert "300주 · 평가 손익 +$426.00" in c["body"]
    assert c["dedupe_id"] == "WEN:TP1"
    assert violations(c["title"], c["body"]) == []


@pytest.mark.asyncio
async def test_vip_stop():
    n = _N()
    await vn.send_position_event(n, Event(name="STOP_APPROACH", pnl=-0.2777, current_price=6.32), _cfg(avg_price=8.75, qty=90))
    c = n.calls[0]
    assert c["title"] == "🛑 VIP 감시 · Wendy's 손절선 아래 (-27.8%)"
    assert "손절 기준 -5.0% · 지금 -27.8%" in c["body"]
    assert "-$218.70" in c["body"]
    assert violations(c["title"], c["body"]) == []


@pytest.mark.asyncio
async def test_vip_filing():
    n = _N()
    f = Filing(accession="0001345471-26-000012", form="SC 13D/A", filing_date="2026-10-22", primary_doc="d.htm", primary_desc="Amendment No. 3")
    await vn.send_activist_filing(n, f, _cfg())
    c = n.calls[0]
    assert c["title"] == "🕵 VIP 감시 · Wendy's 행동주의 공시"
    assert "Trian 의 보유 변경 보고 (13D/A) · 10/22" in c["body"]
    assert "https://www.sec.gov/Archives/edgar/data/1345471/000134547126000012/" in c["body"]
    assert violations(c["title"], c["body"]) == []


def _evt(**kw):
    base = dict(id="x", country="US", filer_key="elliott", filer_name="Elliott Investment Management L.P.",
                form="SC 13D", accession="0001011438-26-000400", filing_date="2026-10-22",
                target_desc="SOUTHWEST AIRLINES CO", target_ticker="LUV", target_cik="92380",
                score=92, intensity_label="CRITICAL")
    base.update(kw)
    return ActivistEvent(**base)


@pytest.mark.asyncio
async def test_activist_13d_new_vs_amend():
    n = _N()
    await an.send_event(n, _evt())
    await an.send_event(n, _evt(form="SC 13D/A", intensity_label="STRONG", score=70))
    new, amend = n.calls
    assert new["title"] == "🌋 행동주의 · 강한 신호 · Elliott Inve… → LUV 92점"
    assert "경영 참여 목적 5% 이상 보유 신규 보고 (13D)" in new["body"]
    assert "https://www.sec.gov/Archives/edgar/data/92380/000101143826000400/" in new["body"]
    assert "보유 변경 보고 (13D/A)" in amend["body"]
    for c in n.calls:
        assert violations(c["title"], c["body"]) == []


@pytest.mark.asyncio
async def test_activist_long_filer_title_len():
    n = _N()
    await an.send_event(n, _evt(filer_name="A" * 60, target_ticker=None, target_desc="B" * 60))
    assert len(n.calls[0]["title"]) <= 40


@pytest.mark.asyncio
async def test_activist_kr_dart_link():
    n = _N()
    await an.send_event(n, _evt(country="KR", form="대량보유 (MANAGEMENT)", accession="20261012000123",
                                target_desc="백금T&A", target_ticker="046310", target_cik=None))
    c = n.calls[0]
    assert "백금T&amp;A(046310)" in c["body"]
    assert "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261012000123" in c["body"]
    assert violations(c["title"], c["body"]) == []


@pytest.mark.asyncio
async def test_wolfpack_wording():
    entries = [
        WolfPackEntry("elliott", "Elliott", 1, "SC 13D", "2026-10-01", 1.0, "a1", "CRITICAL"),
        WolfPackEntry("starboard", "Starboard", 1, "SC 13D", "2026-10-22", 1.0 + 21 * 86400, "a2", "CRITICAL"),
        WolfPackEntry("third", "Third Point", 2, "SC 13D", "2026-10-15", 2.0, "a3", "STRONG"),
    ]
    g = WolfPackGroup(target_ticker="LUV", target_desc="SOUTHWEST AIRLINES CO", target_cik="92380", country="US", entries=entries)
    n = _N()
    await an.send_wolf_pack(n, g, is_new=False, new_filer_name="Starboard")
    c = n.calls[0]
    assert c["title"].startswith("🐺 행동주의 · ")
    assert "여러 운용사" in c["title"]
    assert "30일 안에 3곳 (상위 운용사 2곳)" in c["body"]
    assert "확률" not in c["body"]
    assert violations(c["title"], c["body"]) == []


@pytest.mark.asyncio
async def test_vip_long_company_keeps_event():
    n = _N()
    await vn.send_position_event(n, Event(name="STOP_APPROACH", pnl=-0.2777, current_price=6.32),
                                 _cfg(company_name="Procter & Gamble Company Worldwide"))
    t = n.calls[0]["title"]
    assert t.endswith("손절선 아래 (-27.8%)")
    assert "&amp;" in t and "&amp;amp;" not in t


@pytest.mark.asyncio
async def test_activist_title_differs_by_filer():
    n = _N()
    await an.send_event(n, _evt())
    await an.send_event(n, _evt(filer_name="Starboard Value LP", filer_key="starboard"))
    assert n.calls[0]["title"] != n.calls[1]["title"]
    assert n.calls[0]["title"].endswith("LUV 92점")


@pytest.mark.asyncio
async def test_wolfpack_title_has_score():
    entries = [WolfPackEntry("a", "A", 1, "SC 13D", "2026-10-01", 1.0, "a1", "CRITICAL"),
               WolfPackEntry("b", "B", 1, "SC 13D", "2026-10-02", 2.0, "a2", "CRITICAL")]
    g = WolfPackGroup(target_ticker="LUV", target_desc="X", target_cik=None, country="US", entries=entries)
    n = _N()
    await an.send_wolf_pack(n, g, is_new=False)
    assert f"{g.intensity_score}점" in n.calls[0]["title"]
