"""Stocktwits — 종목별 message sentiment (무인증, 200 QPH).

각 ticker stream 에서 최근 30 messages 의 Bullish/Bearish 비율.
sentiment_delta = (Bullish − Bearish) / total ∈ [-1, +1].
"""
from backend.discovery.data_sources.stocktwits.client import (
    StocktwitsSentiment,
    fetch_sentiment,
    fetch_sentiment_batch,
)

__all__ = ["StocktwitsSentiment", "fetch_sentiment", "fetch_sentiment_batch"]
