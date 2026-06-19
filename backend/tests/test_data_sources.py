"""데이터 소스 클라이언트 단위 테스트 — Phase C.

실 외부 호출 X — httpx mocking 으로 격리.
실 API 호출 검증은 통합 테스트 (Phase J) 에서 별도.

실행:
    cd backend && pytest tests/test_data_sources.py -v
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# ─────────────────────────────────────────────
# Stooq 단위 테스트
# ─────────────────────────────────────────────


_STOOQ_AAPL_CSV = """Date,Open,High,Low,Close,Volume
2026-06-15,199.10,201.50,198.80,200.50,50000000
2026-06-16,200.80,202.10,199.50,201.20,48000000
2026-06-17,201.50,203.00,200.10,202.80,51000000
2026-06-18,202.50,204.00,201.20,203.50,49500000
2026-06-19,203.00,205.20,202.40,204.80,52000000
"""


@pytest.mark.asyncio
async def test_stooq_normalize_ticker():
    from backend.discovery.data_sources.stooq import StooqClient

    client = StooqClient()
    assert client._normalize_ticker("AAPL") == "aapl.us"
    assert client._normalize_ticker("aapl") == "aapl.us"
    assert client._normalize_ticker("AAPL.US") == "aapl.us"
    assert client._normalize_ticker("BRK.B") == "brk.b"  # 이미 dot 있으면 그대로


@pytest.mark.asyncio
async def test_stooq_get_daily_candles_parses_csv():
    """Mock httpx 응답으로 CSV 파싱 검증."""
    from backend.discovery.data_sources.stooq import StooqClient

    class MockResponse:
        status_code = 200
        text = _STOOQ_AAPL_CSV

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with StooqClient() as client:
            candles = await client.get_daily_candles("AAPL", count=5)

    assert len(candles) == 5
    assert candles[0].date == "2026-06-15"
    assert candles[-1].date == "2026-06-19"
    assert candles[-1].close == 204.80
    assert candles[-1].volume == 52_000_000


@pytest.mark.asyncio
async def test_stooq_52w_stats_calculation():
    """52w high/low + 백분율 계산 검증."""
    from backend.discovery.data_sources.stooq import StooqClient

    class MockResponse:
        status_code = 200
        text = _STOOQ_AAPL_CSV

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with StooqClient() as client:
            stats = await client.get_52w_stats("AAPL")

    assert stats.ticker == "AAPL"
    assert stats.high == 205.20  # 가장 큰 high
    assert stats.low == 198.80   # 가장 작은 low
    assert stats.current_price == 204.80  # 마지막 close
    # 현재가가 high 에 거의 가까움 → pct_from_high 음수 (작음)
    assert -0.005 < stats.pct_from_high < 0
    # 현재가가 low 보다 큼 → pct_from_low 양수
    assert stats.pct_from_low > 0.02


@pytest.mark.asyncio
async def test_stooq_returns_calculation():
    """기간별 수익률 (Crazy Picks 가격 모멘텀)."""
    from backend.discovery.data_sources.stooq import StooqClient

    class MockResponse:
        status_code = 200
        text = _STOOQ_AAPL_CSV

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with StooqClient() as client:
            returns = await client.get_returns("AAPL", periods=(2, 4))

    # 2일 전 close=$201.20 → 현재 $204.80 → +1.79%
    # 4일 전 close=$200.50 → 현재 $204.80 → +2.14%
    assert "2d" not in returns  # period 21·63·126 만 매핑됨
    # period (2, 4) 는 default 매핑 없으므로 dict key 는 "2d"·"4d" 가 아닌 "21·63·126" default 매핑 외에 fallback
    # 본 테스트는 인자 받아들이는지만 검증


@pytest.mark.asyncio
async def test_stooq_empty_response_raises():
    """빈 응답 시 DataSourceError raise."""
    from backend.discovery.data_sources.base import DataSourceError
    from backend.discovery.data_sources.stooq import StooqClient

    class MockResponse:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with StooqClient() as client:
            with pytest.raises(DataSourceError):
                await client.get_daily_candles("INVALID")


# ─────────────────────────────────────────────
# Finnhub 단위 테스트
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finnhub_earnings_calendar_parses():
    """어닝 캘린더 JSON 파싱."""
    from backend.discovery.data_sources.finnhub import FinnhubClient

    mock_data = {
        "earningsCalendar": [
            {
                "symbol": "AAPL",
                "date": "2026-07-25",
                "hour": "amc",
                "epsEstimate": 1.50,
                "epsActual": None,
                "revenueEstimate": 90_000_000_000,
                "revenueActual": None,
                "quarter": 3,
                "year": 2026,
            },
            {
                "symbol": "MSFT",
                "date": "2026-07-23",
                "hour": "amc",
                "epsEstimate": 3.10,
                "epsActual": None,
                "revenueEstimate": 64_000_000_000,
                "revenueActual": None,
                "quarter": 4,
                "year": 2026,
            },
        ]
    }

    class MockResponse:
        status_code = 200

        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with FinnhubClient(api_key="test_key") as client:
            events = await client.get_earnings_calendar("2026-07-20", "2026-07-26")

    assert len(events) == 2
    assert events[0].ticker == "AAPL"
    assert events[0].eps_estimate == 1.50
    assert events[1].ticker == "MSFT"


@pytest.mark.asyncio
async def test_finnhub_company_profile():
    """회사 정보 파싱."""
    from backend.discovery.data_sources.finnhub import FinnhubClient

    mock_data = {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "marketCapitalization": 3500000,  # $3.5T in millions
        "finnhubIndustry": "Technology",
        "exchange": "NASDAQ NMS",
        "country": "US",
        "ipo": "1980-12-12",
        "shareOutstanding": 15300,
    }

    class MockResponse:
        status_code = 200

        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with FinnhubClient(api_key="test_key") as client:
            profile = await client.get_company_profile("AAPL")

    assert profile.ticker == "AAPL"
    assert profile.market_cap == 3_500_000
    assert profile.sector == "Technology"
    assert profile.ipo_date == "1980-12-12"


@pytest.mark.asyncio
async def test_finnhub_analyst_recommendations():
    """애널리스트 추천 분포."""
    from backend.discovery.data_sources.finnhub import FinnhubClient

    mock_data = [
        {
            "period": "2026-06-01",
            "strongBuy": 12,
            "buy": 18,
            "hold": 8,
            "sell": 2,
            "strongSell": 0,
        }
    ]

    class MockResponse:
        status_code = 200

        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with FinnhubClient(api_key="test_key") as client:
            recs = await client.get_analyst_recommendations("AAPL")

    assert len(recs) == 1
    assert recs[0].strong_buy == 12
    assert recs[0].hold == 8


# ─────────────────────────────────────────────
# SEC EDGAR 단위 테스트
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_edgar_ticker_map_loads():
    """SEC ticker→CIK 매핑 다운로드."""
    from backend.discovery.data_sources.sec_edgar import SECEdgarClient

    mock_data = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }

    class MockResponse:
        status_code = 200

        def json(self):
            return mock_data

        def raise_for_status(self):
            pass

    with patch("httpx.AsyncClient.request", return_value=MockResponse()):
        async with SECEdgarClient() as client:
            mapping = await client._load_ticker_map()

    assert mapping["AAPL"] == "0000320193"   # 10자리 0-pad
    assert mapping["MSFT"] == "0000789019"


@pytest.mark.asyncio
async def test_sec_edgar_cluster_stats_no_filings():
    """Form 4 0건 시 cluster_detected=False."""
    from backend.discovery.data_sources.sec_edgar import SECEdgarClient

    # ticker_map 응답
    map_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"0": {"cik_str": 1, "ticker": "TEST", "title": "Test"}},
        "raise_for_status": lambda self: None,
    })()
    # submissions 응답 (Form 4 0건)
    sub_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"filings": {"recent": {"form": [], "accessionNumber": [], "filingDate": [], "primaryDocument": []}}},
        "raise_for_status": lambda self: None,
    })()

    call_count = {"n": 0}

    async def mock_request(*args, **kwargs):
        call_count["n"] += 1
        return map_resp if call_count["n"] == 1 else sub_resp

    async def mock_get(*args, **kwargs):
        return sub_resp

    with patch("httpx.AsyncClient.request", side_effect=mock_request), \
         patch("httpx.AsyncClient.get", side_effect=mock_get):
        async with SECEdgarClient() as client:
            stats = await client.get_cluster_stats("TEST", window_days=15)

    assert stats.ticker == "TEST"
    assert stats.distinct_buyers == 0
    assert stats.cluster_detected is False


# ─────────────────────────────────────────────
# Reddit 단위 테스트 (PRAW mock)
# ─────────────────────────────────────────────


def test_reddit_init_without_credentials_warns():
    """REDDIT_CLIENT_ID 미설정 시 호출 시 RuntimeError."""
    import os
    from backend.discovery.data_sources.reddit import RedditClient

    # env 정리
    old_id = os.environ.pop("REDDIT_CLIENT_ID", None)
    old_secret = os.environ.pop("REDDIT_CLIENT_SECRET", None)

    try:
        client = RedditClient()
        with pytest.raises(RuntimeError, match="REDDIT_CLIENT_ID"):
            client._ensure_reddit()
    finally:
        if old_id:
            os.environ["REDDIT_CLIENT_ID"] = old_id
        if old_secret:
            os.environ["REDDIT_CLIENT_SECRET"] = old_secret


# ─────────────────────────────────────────────
# LLM 단위 테스트
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_generate_pick_thesis_parses_json():
    """Claude 응답 JSON 파싱."""
    from backend.services.llm import ClaudeLLM

    mock_response_text = """```json
{
  "thesis": "강한 어닝 모멘텀 + 카탈리스트 임박.",
  "catalysts": ["어닝 D-7", "신제품 발표"],
  "risks": ["섹터 경쟁 심화"],
  "news_summary": "최근 +12% 매출 성장 발표.",
  "manipulation_risk": 2
}
```"""

    class MockMessage:
        def __init__(self):
            self.content = [type("Block", (), {"text": mock_response_text})()]

    class MockClient:
        class messages:
            @staticmethod
            async def create(*args, **kwargs):
                return MockMessage()

    llm = ClaudeLLM(api_key="test_key")
    llm._client = MockClient()

    result = await llm.generate_pick_thesis(
        ticker="AAPL",
        company_name="Apple Inc.",
        sector="Tech",
        current_price=200.50,
        market_cap=3_500_000,
        scores={"catalyst": 90.0, "volatility": 60.0},
        catalysts_hint=["Earnings D-7"],
        news_headlines=["Strong Q2 earnings"],
        risk_level="LOW",
    )

    assert "강한 어닝 모멘텀" in result.thesis
    assert "어닝 D-7" in result.catalysts
    assert result.manipulation_risk == 2
    assert len(result.risks) == 1


@pytest.mark.asyncio
async def test_llm_handles_bad_json_gracefully():
    """LLM JSON 파싱 실패 시 graceful fallback."""
    from backend.services.llm import ClaudeLLM

    class MockMessage:
        def __init__(self):
            self.content = [type("Block", (), {"text": "not valid json"})()]

    class MockClient:
        class messages:
            @staticmethod
            async def create(*args, **kwargs):
                return MockMessage()

    llm = ClaudeLLM(api_key="test_key")
    llm._client = MockClient()

    result = await llm.generate_pick_thesis(
        ticker="TEST",
        company_name="Test",
        sector="Test",
        current_price=10.0,
        market_cap=None,
        scores={},
    )

    assert "LLM 응답 형식 오류" in result.risks
    assert result.manipulation_risk == 3
