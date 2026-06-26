"""apewisdom.io — Reddit ticker mention aggregator (무인증, 무료).

운영 IP 가 Reddit 자체에 차단된 상황에서 대안. apewisdom 이 Reddit
4 subreddit (wallstreetbets/stocks/pennystocks/options) 데이터를 자체
수집해 ticker 단위로 큐레이션 + 24h 윈도우 모멘텀 (rank_24h_ago,
mentions_24h_ago) 까지 제공.

OAuth 승인 (Phase 2) 후에도 PRAW 와 병행 사용 가능 — 시그널 cross-check.
"""
from backend.discovery.data_sources.apewisdom.client import (
    ApeWisdomMention,
    fetch_filter,
)

__all__ = ["ApeWisdomMention", "fetch_filter"]
