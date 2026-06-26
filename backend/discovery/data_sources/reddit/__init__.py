"""Reddit 데이터 소스 — Phase 1c (공개 JSON endpoint, 무인증).

2025-11 self-service API 폐지 후 OAuth 발급 7일 manual approval 필요.
공개 JSON endpoint (`.json` suffix) 는 무인증으로 사용 가능 + 정책 부합.

OAuth 전환 시점에 client.py 의 fetch 함수만 PRAW 로 교체 가능.
"""
from backend.discovery.data_sources.reddit.client import (
    RedditMention,
    SUBREDDITS,
    extract_tickers,
    fetch_mentions,
    fetch_subreddit_new,
)

__all__ = [
    "RedditMention",
    "SUBREDDITS",
    "extract_tickers",
    "fetch_mentions",
    "fetch_subreddit_new",
]
