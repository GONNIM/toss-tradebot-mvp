"""1102-04: 로그 소음 줄이기 · 실패 신호는 남는지."""
import logging
import warnings

import httpx
import pytest

from backend.discovery.data_sources.stocktwits import client as st


@pytest.mark.asyncio
async def test_stocktwits_403_one_warning_per_batch(monkeypatch, caplog):
    def handler(request):
        return httpx.Response(403, request=request)

    real = httpx.AsyncClient
    monkeypatch.setattr(st.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(st, "_BETWEEN_REQ_SEC", 0)
    with caplog.at_level(logging.INFO, logger=st.logger.name):
        out = await st.fetch_sentiment_batch(["AAA", "BBB", "CCC"])
    assert out == {}
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1 and "HTTP 403 3종목" in warns[0].getMessage()
    assert any("batch: 0 / 3 success" in r.getMessage() for r in caplog.records)


def test_apscheduler_executor_info_off_errors_kept():
    import backend.api.main  # noqa: F401  (basicConfig 뒤 레벨 설정)

    lg = logging.getLogger("apscheduler.executors.default")
    assert not lg.isEnabledFor(logging.INFO)
    assert lg.isEnabledFor(logging.ERROR) and lg.isEnabledFor(logging.WARNING)


def test_pytrends_filter_only_that_warning():
    import importlib

    import backend.discovery.data_sources.google_trends.client as gt

    def hidden(module: str, message: str) -> bool:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.reload(gt)   # 모듈 머리의 필터를 맨 앞에 다시 등록 (pytest 가 테스트마다 필터를 되돌림)
            warnings.warn_explicit(message, FutureWarning, "x.py", 1, module=module, registry={})
        return not w

    assert hidden("pytrends.request", "Downcasting object dtype arrays on .fillna is deprecated")
    assert not hidden("pytrends.request", "다른 경고")
    assert not hidden("pandas.core", "Downcasting object dtype arrays on .fillna is deprecated")
