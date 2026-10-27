"""Finnhub 키 없음·무효 회귀 (1023-03).

- 401·403 → FinnhubKeyError (예전에는 「profile not found」 로 묻힘)
- universe 갱신은 첫 키 오류에서 멈추고 알림 1회
- 알림은 하루 1회 · 발송 성공 때만 기록 · 테스트에서 실제 발송 0건 (send_warning 대체)
"""
from __future__ import annotations

import httpx
import pytest

from backend.discovery.data_sources.base import DataSourceError
from backend.discovery.data_sources.finnhub import FinnhubClient, FinnhubKeyError


def _client(status: int, body: dict) -> FinnhubClient:
    c = FinnhubClient(api_key="")
    c._client = httpx.AsyncClient(
        base_url=c.base_url,
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)),
    )
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_key_error_raised(status):
    c = _client(status, {"error": "Please use an API key."})
    with pytest.raises(FinnhubKeyError, match=str(status)):
        await c.get_company_profile("AAPL")
    with pytest.raises(FinnhubKeyError):
        await c.get_earnings_calendar(from_date="2026-10-27", to_date="2026-11-10")
    await c._client.aclose()


@pytest.mark.asyncio
async def test_empty_profile_still_not_found():
    c = _client(200, {})
    with pytest.raises(DataSourceError, match="profile not found") as ei:
        await c.get_company_profile("ZZZZ")
    assert not isinstance(ei.value, FinnhubKeyError)
    await c._client.aclose()


@pytest.mark.asyncio
async def test_universe_refresh_stops_and_alerts_once(monkeypatch):
    from backend.scheduler import cron

    calls: list[str] = []

    class _Finnhub:
        async def get_company_profile(self, ticker):
            calls.append(ticker)
            raise FinnhubKeyError("Finnhub 키 없음·무효 (401)")

    async def _enter(clients):
        return {"finnhub": _Finnhub(), "stooq": object()}

    async def _exit(clients):
        return None

    alerts: list[str] = []

    async def _alert(exc):
        alerts.append(str(exc))

    monkeypatch.setattr(cron, "_build_clients", lambda: {})
    monkeypatch.setattr(cron, "_enter_clients", _enter)
    monkeypatch.setattr(cron, "_exit_clients", _exit)
    monkeypatch.setattr(cron, "_alert_finnhub_key", _alert)

    await cron.run_universe_refresh()
    assert calls == [cron.WATCHLIST[0]]
    assert alerts == ["Finnhub 키 없음·무효 (401)"]


@pytest.mark.asyncio
async def test_alert_once_per_day(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as notifier_mod

    sent: list[tuple[str, str]] = []

    async def _send_warning(self, title, body, **kw):
        sent.append((title, body))
        return True

    monkeypatch.setattr(notifier_mod.TelegramNotifier, "send_warning", _send_warning)
    monkeypatch.setattr(cron, "_llm_fallback_alerted", {})

    await cron._alert_finnhub_key(FinnhubKeyError("Finnhub 키 없음·무효 (401)"))
    await cron._alert_finnhub_key(FinnhubKeyError("Finnhub 키 없음·무효 (401)"))
    assert len(sent) == 1
    assert "Finnhub" in sent[0][0] and "FINNHUB_API_KEY" in sent[0][1]


@pytest.mark.asyncio
async def test_alert_not_recorded_when_send_fails(monkeypatch):
    from backend.scheduler import cron
    from backend.services import notifier as notifier_mod

    async def _send_warning(self, title, body, **kw):
        return False

    monkeypatch.setattr(notifier_mod.TelegramNotifier, "send_warning", _send_warning)
    monkeypatch.setattr(cron, "_llm_fallback_alerted", {})
    await cron._alert_finnhub_key(FinnhubKeyError("x"))
    assert "finnhub" not in cron._llm_fallback_alerted
