"""네이버 금융 polling API — 실시간 현재가 (B-2 후속)."""
from backend.discovery.data_sources.naver_quote.client import (
    Quote,
    fetch_one,
    fetch_quotes,
)

__all__ = ["Quote", "fetch_one", "fetch_quotes"]
