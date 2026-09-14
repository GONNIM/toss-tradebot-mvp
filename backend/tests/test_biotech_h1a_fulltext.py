"""WP9 · H1a full_text 파싱 fixture 테스트 (5건)."""
from __future__ import annotations

from backend.scripts import biotech_h1a_fulltext as mod


def test_parse_dates_first_date_after_pub():
    text = (
        "SUMMARY: The Food and Drug Administration.\n"
        "DATES: The meeting will be held on October 15, 2024, from 8 a.m. to 5 p.m.\n"
        "ADDRESSES: ...\n"
    )
    d = mod.parse_dates_section(text, "2024-08-15")
    assert d == "2024-10-15"


def test_parse_dates_ignores_past_date():
    text = (
        "DATES: A prior meeting was held on January 3, 2023.\n"
        "Next meeting: November 3, 2024.\n"
    )
    d = mod.parse_dates_section(text, "2024-09-01")
    assert d == "2024-11-03"


def test_parse_dates_returns_none_when_no_future_date():
    text = "DATES: Committee met on February 1, 2020.\n"
    d = mod.parse_dates_section(text, "2024-05-01")
    assert d is None


def test_parse_agenda_extracts_sponsor():
    text = (
        "AGENDA: The Committee will discuss NDA 219999 for lecanemab (Leqembi), submitted by Eisai Inc., "
        "for the treatment of Alzheimer's disease.\n"
        "The Oncologic Drugs Advisory Committee will convene.\n"
    )
    agenda = mod.parse_agenda_section(text)
    assert "Eisai" in agenda["sponsor"]
    assert agenda["committee"] == "Oncologic Drugs Advisory Committee"


def test_event_eligible_short_lead():
    ok, reason = mod.event_eligible("2024-10-13", "2024-10-15")
    assert ok is False
    assert reason == "short_lead"
    ok2, reason2 = mod.event_eligible("2024-09-01", "2024-10-15")
    assert ok2 is True
    assert reason2 == ""
