"""칸별 「수집 중인가」 판정 · 점수 재정규화(scoring)와 화면 /watchlist/sources 가 같은 함수를 쓴다 (1030-04).

수집하지 않는 칸을 0점으로 두면 점수 합이 작아져 항상 낮아 보인다 →
점수는 수집 중인 칸끼리만 비율을 다시 맞추고, 화면은 0 대신 「수집 안 함」을 보여 준다.
키 값은 다루지 않고 있는지(참/거짓)만 돌려준다.
"""
from __future__ import annotations

from backend.services import config

from . import assembly, gov_press, youtube

CATEGORIES = ("news", "interest", "youtube", "event", "prev_day")


def dart_configured() -> bool:
    from backend.discovery.data_sources.dart.client import is_configured

    return is_configured()


def toss_configured() -> bool:
    return bool(config.get("TOSS_CLIENT_ID") and config.get("TOSS_CLIENT_SECRET"))


def collecting_categories() -> dict[str, bool]:
    toss = toss_configured()
    return {
        "news": True,                       # RSS · 키 없음
        "interest": toss,                   # 토스 순위 · 개인 순매수
        "youtube": youtube._api_key() is not None,
        "event": dart_configured() or assembly._api_key() is not None or bool(gov_press.configured_sources()),
        "prev_day": toss,                   # 토스 시장 거래대금·거래량 순위
    }
