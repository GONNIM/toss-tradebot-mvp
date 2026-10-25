"""1025-08 · 토스 참고 환율 (USD→KRW) — 원본 · 캐시 · 대체값을 구분한다."""
from __future__ import annotations

import pytest

from backend.services import fx


class _FakeToss:
    def __init__(self, result=None, exc: Exception | None = None):
        self.result = result
        self.exc = exc
        self.calls: list[dict] = []

    def get(self, path, *, params=None, use_account_header=True):
        self.calls.append({"path": path, "params": params, "acct": use_account_header})
        if self.exc:
            raise self.exc
        return self.result


@pytest.fixture(autouse=True)
def _reset():
    fx.reset_cache()
    yield
    fx.reset_cache()


def _ok(rate="1380.5"):
    return {"baseCurrency": "USD", "quoteCurrency": "KRW", "rate": rate, "midRate": "1375",
            "validFrom": "2026-10-25T23:23:31.000+09:00", "validUntil": "2026-10-25T23:28:27.000+09:00"}


def test_parses_toss_rate_with_required_params():
    c = _FakeToss(_ok())
    q = fx.usd_krw(client=c, now=1000.0)
    assert q.rate == 1380.5 and q.source == "toss" and q.valid_from.startswith("2026-10-25")
    assert c.calls == [{"path": "/api/v1/exchange-rate",
                        "params": {"baseCurrency": "USD", "quoteCurrency": "KRW"}, "acct": False}]


def test_cache_within_5_minutes_then_refetch():
    c = _FakeToss(_ok())
    fx.usd_krw(client=c, now=1000.0)
    q = fx.usd_krw(client=c, now=1000.0 + 299)
    assert q.source == "cached" and q.rate == 1380.5 and len(c.calls) == 1
    fx.usd_krw(client=c, now=1000.0 + 301)
    assert len(c.calls) == 2


def test_failure_uses_last_success_as_cached():
    fx.usd_krw(client=_FakeToss(_ok("1390")), now=1000.0)
    q = fx.usd_krw(client=_FakeToss(exc=RuntimeError("down")), now=2000.0)
    assert q.rate == 1390.0 and q.source == "cached"


def test_no_success_ever_is_fallback_1330():
    q = fx.usd_krw(client=_FakeToss(exc=RuntimeError("down")), now=1000.0)
    assert q.rate == fx.FALLBACK_USD_KRW == 1330.0 and q.source == "fallback"


def test_parse_failure_is_not_cached_success():
    bad = _FakeToss({"rate": "abc"})
    q = fx.usd_krw(client=bad, now=1000.0)
    assert q.source == "fallback"
    # 다음 호출은 캐시로 취급하지 않고 다시 묻는다
    good = _FakeToss(_ok())
    q2 = fx.usd_krw(client=good, now=1001.0)
    assert q2.source == "toss" and len(good.calls) == 1


def test_nonpositive_rate_rejected():
    assert fx.usd_krw(client=_FakeToss({"rate": "0"}), now=1.0).source == "fallback"
