"""Google Trends — 검색량 z-score (pytrends 무인증).

5 ticker batch 한도, 시간당 1회 cadence (Captcha 회피).
"""
from backend.discovery.data_sources.google_trends.client import (
    TrendSnapshot,
    fetch_interest,
)

__all__ = ["TrendSnapshot", "fetch_interest"]
