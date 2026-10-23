"""알림 문구 공통 도구 (1023-05 Task 1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import alert_text as at

KST = timezone(timedelta(hours=9))


def test_title_format():
    assert at.title("vip", "Wendy's 1차 목표가 도달", "🎯") == "🎯 VIP 감시 · Wendy's 1차 목표가 도달"


def test_title_truncates_fact_only():
    t = at.title("vip", "가" * 60, "🎯")
    assert len(t) <= 40
    assert t.startswith("🎯 VIP 감시 · ")
    assert t.endswith("…")


def test_unknown_category_needs_label():
    with pytest.raises(ValueError):
        at.title("unknown", "x", "📊")
    assert at.title("unknown", "x", "📊", label="화약고 후보 · 5% 보고") == "📊 화약고 후보 · 5% 보고 · x"
    with pytest.raises(ValueError):
        at.link("unknown")
    assert at.link("unknown", page="/powderkeg") == "자세히: https://optimus8.cafe24.com/powderkeg"


def test_link_absolute():
    assert at.link("powderkeg_dnt") == "자세히: https://optimus8.cafe24.com/powderkeg"


def test_kst_from_utc_naive():
    assert at.kst(datetime(2026, 10, 23, 1, 42)) == "10/23 10:42"
    assert at.kst(datetime(2026, 10, 23, 1, 42, tzinfo=timezone.utc)) == "10/23 10:42"
    assert at.kst(None) == "—"


def test_next_run_rolls_over():
    assert at.next_run(6, 30, now=datetime(2026, 10, 23, 23, 50, tzinfo=KST)) == "10/24 06:30"
    assert at.next_run(6, 30, now=datetime(2026, 10, 23, 5, 0, tzinfo=KST)) == "10/23 06:30"


def test_stock_fallback():
    assert at.stock(None, "012345") == "012345 (종목명 확인 안 됨)"
    assert at.stock("", "012345") == "012345 (종목명 확인 안 됨)"
    assert at.stock("가나다전자", "012345") == "가나다전자(012345)"


def test_escapes_outside_values():
    assert at.stock("S&T모티브", "064960") == "S&amp;T모티브(064960)"
    assert at.esc("mean < -5%") == "mean &lt; -5%"


def test_number_formats():
    assert at.won(102700.0) == "102,700원"
    assert at.usd(2.14) == "$2.14"
    assert at.usd(0.5123) == "$0.5123"
    assert at.pct(0.153) == "+15.3%"
    assert at.pct(-0.0186) == "-1.9%"
    assert at.won(None) == "—" and at.usd(None) == "—" and at.pct(None) == "—"


def test_glossary_tables():
    assert at.POWDERKEG_TYPE["B1"] == "횡령·배임"
    assert at.POWDERKEG_TYPE["A3"] == "담보 제공"
    assert at.EXIT_REASON["hard_sl"] == "손절선 도달"
    assert at.VIP_EVENT["STOP_APPROACH"][1] == "손절선 아래"
