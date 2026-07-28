"""P2-5 · activist-radar 이슈 A/B 수정 회귀 테스트.

- SC 13G XML URI-agnostic 파싱 (issuer_name 채워짐)
- empty-string substring 매칭 방지 (events_by_target · detect_wolf_pack)
- Wolf Pack target_ticker 축 통일 정합
"""
from __future__ import annotations

import time

import pytest

from backend.discovery.activist import scoring
from backend.discovery.activist.sec_filing_details import _parse
from backend.discovery.activist.state import ActivistEvent, ActivistState


# ─────────────────────────────────────────────────────────────
# 이슈 A · SC 13G XML URI-agnostic 파싱
# ─────────────────────────────────────────────────────────────

SC13G_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13g">
  <coverPageHeader>
    <issuerInfo>
      <issuerName>Ionic Digital Inc.</issuerName>
      <issuerCIK>0001582090</issuerCIK>
      <issuerCusips>
        <issuerCusipNumber>46226T101</issuerCusipNumber>
      </issuerCusips>
    </issuerInfo>
    <securitiesClassTitle>Common Stock, $0.0001 par value</securitiesClassTitle>
    <amendmentNo>3</amendmentNo>
    <dateOfEvent>12/31/2025</dateOfEvent>
  </coverPageHeader>
  <reportingPersons>
    <reportingPersonInfo>
      <percentOfClass>5.4</percentOfClass>
      <aggregateAmountOwned>1250000</aggregateAmountOwned>
    </reportingPersonInfo>
  </reportingPersons>
</edgarSubmission>
"""

SC13D_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/schedule13D">
  <coverPageHeader>
    <issuerInfo>
      <issuerName>NN, Inc.</issuerName>
      <issuerCIK>0000918541</issuerCIK>
      <issuerCusips>
        <issuerCusipNumber>629337106</issuerCusipNumber>
      </issuerCusips>
    </issuerInfo>
    <securitiesClassTitle>Common Stock</securitiesClassTitle>
    <dateOfEvent>05/12/2026</dateOfEvent>
  </coverPageHeader>
  <reportingPersons>
    <reportingPersonInfo>
      <percentOfClass>7.9</percentOfClass>
      <aggregateAmountOwned>4200000</aggregateAmountOwned>
    </reportingPersonInfo>
  </reportingPersons>
  <items1To7>
    <item4>
      <transactionPurpose>Engagement with the Company regarding capital allocation.</transactionPurpose>
    </item4>
  </items1To7>
</edgarSubmission>
"""


def test_parse_sc13g_uri_agnostic():
    """SC 13G (소문자 g URI) 파싱 · v1.53 fix 이전엔 모든 필드 빈 문자열이던 케이스."""
    d = _parse(SC13G_XML)
    assert d.issuer_name == "Ionic Digital Inc."
    assert d.issuer_cik == "0001582090"
    assert d.issuer_cusip == "46226T101"
    assert d.securities_class_title == "Common Stock, $0.0001 par value"
    assert d.amendment_no == 3
    assert d.date_of_event == "12/31/2025"
    assert d.percent_of_class == pytest.approx(5.4)
    assert d.aggregate_amount_owned == 1_250_000


def test_parse_sc13d_still_works():
    """SC 13D (대문자 D URI) · 기존 정상 · 회귀 없음."""
    d = _parse(SC13D_XML)
    assert d.issuer_name == "NN, Inc."
    assert d.issuer_cik == "0000918541"
    assert d.percent_of_class == pytest.approx(7.9)
    assert d.transaction_purpose.startswith("Engagement with the Company")


# ─────────────────────────────────────────────────────────────
# 이슈 B · empty-string 매칭 방지 · Wolf Pack target_ticker 축
# ─────────────────────────────────────────────────────────────


def _make_evt(id, filer_key, target_ticker=None, target_desc="",
              event_type="ACTIVIST", detected_at=None):
    return ActivistEvent(
        id=id, country="US", filer_key=filer_key, filer_name=filer_key,
        form="SC 13D", accession=f"acc-{id}", filing_date="2026-07-15",
        target_desc=target_desc, target_ticker=target_ticker, target_cik=None,
        score=50, intensity_label="STRONG", wolf_pack=[],
        detected_at=detected_at or time.time(),
        event_type=event_type,
    )


def test_events_by_target_empty_string_guard():
    """v1.53 · target_desc == '' → 무한 매칭 버그 방지 · 빈 리스트 반환."""
    state = ActivistState()
    state.events = [
        _make_evt("1", "cerberus", target_desc="Smith & Nephew"),
        _make_evt("2", "impactive", target_desc="Asbury Auto"),
    ]
    assert state.events_by_target("", time.time() - 86400) == []
    assert state.events_by_target("   ", time.time() - 86400) == []


def test_events_by_ticker_empty_and_type_filter():
    """v1.53 · events_by_ticker · empty ticker → []  · INSIDER 이벤트 제외."""
    state = ActivistState()
    state.events = [
        _make_evt("a", "cevian", target_ticker="SNN", event_type="ACTIVIST"),
        _make_evt("b", "impactive", target_ticker="SNN", event_type="ACTIVIST"),
        _make_evt("c", "form4_us:SNN", target_ticker="SNN", event_type="INSIDER"),
        _make_evt("d", "legion", target_ticker="NNBR", event_type="ACTIVIST"),
    ]
    since = time.time() - 30 * 86400
    assert state.events_by_ticker("", since) == []
    snn = state.events_by_ticker("SNN", since)
    assert len(snn) == 2
    assert {e.filer_key for e in snn} == {"cevian", "impactive"}
    nnbr = state.events_by_ticker("NNBR", since)
    assert len(nnbr) == 1


def test_detect_wolf_pack_by_ticker():
    """v1.53 · Wolf Pack · target_ticker 축 · empty ticker → []."""
    state = ActivistState()
    state.events = [
        _make_evt("a", "cevian", target_ticker="SNN"),
        _make_evt("b", "impactive", target_ticker="SNN"),
        _make_evt("c", "legion", target_ticker="NNBR"),
    ]
    assert scoring.detect_wolf_pack(state, "SNN", "impactive") == ["cevian"]
    assert scoring.detect_wolf_pack(state, "NNBR", "legion") == []
    assert scoring.detect_wolf_pack(state, "", "anyone") == []
    assert scoring.detect_wolf_pack(state, "ZZZZ", "anyone") == []


def test_wolf_pack_ignores_insider_events():
    """v1.53 · Wolf Pack 은 ACTIVIST 만 · INSIDER 제외."""
    state = ActivistState()
    state.events = [
        _make_evt("a", "cevian", target_ticker="SNN", event_type="ACTIVIST"),
        _make_evt("b", "form4:SNN", target_ticker="SNN", event_type="INSIDER"),
    ]
    assert scoring.detect_wolf_pack(state, "SNN", "form4:SNN") == ["cevian"]


# ─────────────────────────────────────────────────────────────
# P2-5b · KR 경로 empty-string 가드 (v1.55)
# ─────────────────────────────────────────────────────────────


def test_kr_corp_name_empty_string_guard_prior_forms():
    """v1.55 · KR corp_name == '' 시 · substring 매칭 폭발 방지.

    원 · radar.py:289 US 경로 P2-5 fix 대칭 누락 · KR filer의 모든 이벤트가 wrong hit.
    """
    state = ActivistState()
    state.events = [
        _make_evt("1", "kcgi", target_desc="한양증권", target_ticker="001750"),
        _make_evt("2", "kcgi", target_desc="SK네트웍스", target_ticker="001740"),
    ]
    # KR 경로 시뮬레이션 · corp_name 빈 문자열 케이스
    corp_name = ""  # or None
    kr_corp_name = (corp_name or "").strip()
    prior_forms = []
    if kr_corp_name:
        up = kr_corp_name.upper()
        prior_forms = [
            e.form for e in state.events
            if e.filer_key == "kcgi"
            and up in (e.target_desc or "").upper()
        ]
    # 가드 · 빈 corp_name → prior_forms 빈 리스트 (폭발 방지)
    assert prior_forms == []

    # 대조 · corp_name 정상 시 · 매칭 정상 작동
    corp_name2 = "한양증권"
    kr_corp2 = (corp_name2 or "").strip()
    up2 = kr_corp2.upper()
    prior2 = [
        e.form for e in state.events
        if e.filer_key == "kcgi"
        and up2 in (e.target_desc or "").upper()
    ]
    assert len(prior2) == 1  # 한양증권만 매칭


# ─────────────────────────────────────────────────────────────
# P2-5b · Form 4 URI-agnostic (v1.55)
# ─────────────────────────────────────────────────────────────


def test_form4_iter_compat_with_xmlns():
    """v1.55 · SEC Form 4 XML에 xmlns 추가되어도 파싱 정상."""
    from backend.discovery.activist.us_form4_poller import _iter_compat, _text, _bool_flag
    from xml.etree import ElementTree as ET
    # xmlns 있는 Form 4 시뮬레이션 (미래 SEC 변경 대비)
    xml = b"""<?xml version="1.0"?>
    <ownershipDocument xmlns="http://www.sec.gov/edgar/ownership">
      <reportingOwner>
        <reportingOwnerRelationship>
          <isOfficer>true</isOfficer>
        </reportingOwnerRelationship>
        <reportingOwnerId>
          <rptOwnerName>Test Officer</rptOwnerName>
        </reportingOwnerId>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>"""
    root = ET.fromstring(xml)
    # v1.55 · {*} 로 xmlns 무시 매칭
    officers = _iter_compat(root, "isOfficer")
    assert len(officers) == 1
    assert _bool_flag(root, "isOfficer") is True
    txns = _iter_compat(root, "nonDerivativeTransaction")
    assert len(txns) == 1
    assert _text(root, "rptOwnerName") == "Test Officer"


def test_form4_iter_compat_without_xmlns():
    """v1.55 · xmlns 없는 Form 4 XML 도 정상 (기존 동작 회귀 없음)."""
    from backend.discovery.activist.us_form4_poller import _iter_compat, _bool_flag
    from xml.etree import ElementTree as ET
    xml = b"""<?xml version="1.0"?>
    <ownershipDocument>
      <reportingOwner>
        <isOfficer>true</isOfficer>
      </reportingOwner>
    </ownershipDocument>"""
    root = ET.fromstring(xml)
    officers = _iter_compat(root, "isOfficer")
    assert len(officers) == 1
    assert _bool_flag(root, "isOfficer") is True


def test_score_event_accepts_target_ticker_kwarg():
    """v1.53 · score_event · target_ticker 파라미터 · wolf_pack 정확 계산."""
    from backend.discovery.activist.universe import Activist
    state = ActivistState()
    state.events = [
        _make_evt("a", "cevian", target_ticker="SNN"),
    ]
    activist = Activist(key="impactive", name="Impactive", country="US", tier=2)
    score, label, wp = scoring.score_event(
        activist, "SC 13D", "Smith & Nephew", state,
        target_ticker="SNN",
    )
    assert wp == ["cevian"]
    assert score > 0

    score2, _, wp2 = scoring.score_event(
        activist, "SC 13D", "", state, target_ticker=None,
    )
    assert wp2 == []
