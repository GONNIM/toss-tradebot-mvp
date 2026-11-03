"""1102-07: Serenity 심볼 · 대만 장외 .TWO · 일본 .T · 거래소:번호 · 비상장 · 주간 재시도."""
from datetime import date
from types import SimpleNamespace

import pytest

from backend.discovery.serenity.price_snapshot import _skip_until_weekly_retry
from backend.services.ticker_map import is_private_or_brand, to_yfinance_symbol


@pytest.mark.parametrize("raw,want", [
    ("3374", "3374.TWO"), ("XINTEC", "3374.TWO"), ("3675.TW", "3675.TWO"), ("WIN", "3105.TWO"),
    ("6976", "6976.T"), ("6976.TW", "6976.T"), ("TYO:6976", "6976.T"), ("TPEX:3625", "3625.TWO"),
    ("6315", "6315.T"), ("2768", "2768.T"), ("KYEC", "2449.TW"), ("NEXTRONICS", "8147.TWO"),
    ("2313", "2313.TW"),          # 명시 매핑 없는 4자리는 기존대로 .TW
    ("TPE:2330", "2330.TW"),
])
def test_symbols(raw, want):
    assert to_yfinance_symbol(raw) == want


@pytest.mark.parametrize("raw", ["YMTC", "SPIL", "WALSIN", "SUMIMOTO", "MACRO"])
def test_private_added(raw):
    assert is_private_or_brand(raw)


def test_no_longer_private():
    assert not is_private_or_brand("TPEX:3625") and not is_private_or_brand("NEXTRONICS")


def _row(close=None, error="history 부족", snap="2026-10-20", sym="WOKS"):
    return SimpleNamespace(close=close, error=error, snapshot_date=snap, yahoo_symbol=sym)


def test_weekly_retry_skips_old_failure_except_monday():
    tue = date(2026, 11, 3)
    mon = date(2026, 11, 9)
    assert _skip_until_weekly_retry(_row(), "WOKS", tue) is True
    assert _skip_until_weekly_retry(_row(), "WOKS", mon) is False


def test_weekly_retry_does_not_skip():
    tue = date(2026, 11, 3)
    assert _skip_until_weekly_retry(None, "X", tue) is False                       # 처음 보는 종목
    assert _skip_until_weekly_retry(_row(close=10.0, error=None), "WOKS", tue) is False   # 성공 종목
    assert _skip_until_weekly_retry(_row(snap="2026-11-01"), "WOKS", tue) is False  # 7일 안 실패
    assert _skip_until_weekly_retry(_row(sym="3374.TW"), "3374.TWO", tue) is False  # 매핑 고침 → 바로 재조회
    assert _skip_until_weekly_retry(_row(error="private/브랜드"), "WOKS", tue) is False
