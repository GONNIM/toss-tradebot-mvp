"""WP100 · 레딧 경보 조건 · 24시간 한정 · 레딧 기준선 7일 미만 수집 중 · 3건 이상 & 평소 2배 이상 · 평균과 같으면 비경보."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.scripts import biotech_h48v3_confirm as cf
from backend.scripts.biotech_alert_rule import judge

NOW = datetime(2026, 10, 3, 22, 0, tzinfo=timezone.utc)


def test_only_posts_within_24h_counted():
    posts = [{"updated": (NOW - timedelta(hours=2)).isoformat()}, {"updated": (NOW - timedelta(hours=30)).isoformat()},
             {"updated": "2026-09-18T10:00:00+00:00"}, {"updated": ""}]
    assert len(cf.posts_within(posts, NOW)) == 1


BASE = {"st_baseline_n": "9", "st_baseline_mult": "0.0", "apewisdom_24h": "0"}


def test_reddit_baseline_under_7_days_is_collecting():
    assert judge({**BASE, "reddit_rss_matches": "10", "reddit_baseline_n": "3", "reddit_baseline_mean": "0"}) == (False, "rss_collecting")
    assert judge({**BASE, "reddit_rss_matches": "10"}) == (False, "rss_collecting")      # WP100 이전 행 (기준선 열 없음)


def test_three_or_more_and_twice_mean_is_alert():
    assert judge({**BASE, "reddit_rss_matches": "4", "reddit_baseline_n": "7", "reddit_baseline_mean": "1.5"}) == (True, "rss")
    assert judge({**BASE, "reddit_rss_matches": "3", "reddit_baseline_n": "8", "reddit_baseline_mean": "0"}) == (True, "rss")   # 평균 하한 1 → 2배 = 2


def test_three_or_more_but_equal_to_mean_is_not_alert():
    assert judge({**BASE, "reddit_rss_matches": "3", "reddit_baseline_n": "7", "reddit_baseline_mean": "3"}) == (False, "none")
