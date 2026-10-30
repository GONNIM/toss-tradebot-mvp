"""Watchlist 신호 출처 분류 · 점수(scoring)·저장(store)·화면용 /sources 가 같은 표를 쓴다 (1030-04)."""
from __future__ import annotations

# 뉴스 출처 → 언론사 (같은 언론이 피드 둘이면 한 곳으로 센다 · 점수의 「서로 다른 언론사 수」)
NEWS_PUBLISHER: dict[str, str] = {
    "news_yhap": "einfomax",            # 연합인포맥스 증권
    "news_einfomax_all": "einfomax",    # 연합인포맥스 전체
    "news_fnnews": "fnnews",
    "news_hankyung": "hankyung",
    "news_yonhap": "yonhap",            # 연합뉴스 경제
    "news_yna_market": "yonhap",        # 연합뉴스 마켓
    "news_mk": "mk",
    "news_sedaily": "sedaily",
    "news_etoday": "etoday",
}
NEWS_SOURCES = set(NEWS_PUBLISHER)

# 순위 신호 출처 (rank_signals.py 가 저장) · source 열 길이 30 필요 (모델 확장 · 마이그레이션)
INTEREST_SOURCES = {"rank_individual_netbuy", "rank_toss_amount", "rank_toss_volume"}
PREV_DAY_SOURCES = {"rank_market_amount", "rank_market_volume"}

YOUTUBE_SOURCES = {"youtube_shuka", "youtube_sampro", "youtube_hantoo", "youtube_jungpro"}

# 이벤트: 점수에 드는 출처 · dart_caution 은 점수 0 이라 여기 없다
EVENT_SOURCES = {"dart_disclosure", "assembly", "moef_rss", "motie_rss", "msit_rss", "molit_rss"}
CAUTION_SOURCE = "dart_caution"

# 옛 종토방 (수집 중단 · robots 금지) · 과거 행이 남아 있어도 점수에 안 넣는다
LEGACY_BOARD_SOURCES = {"board_naver"}

RANK_KIND_LABEL: dict[str, str] = {
    "rank_individual_netbuy": "개인 순매수",
    "rank_toss_amount": "토스증권 체결 거래대금",
    "rank_toss_volume": "토스증권 체결 거래량",
    "rank_market_amount": "시장 거래대금",
    "rank_market_volume": "시장 거래량",
}


def category_of(source: str) -> str | None:
    """출처 → 칸 (news · interest · youtube · event · prev_day) · 점수 밖이면 None."""
    if source in NEWS_SOURCES:
        return "news"
    if source in INTEREST_SOURCES:
        return "interest"
    if source in YOUTUBE_SOURCES:
        return "youtube"
    if source in EVENT_SOURCES:
        return "event"
    if source in PREV_DAY_SOURCES:
        return "prev_day"
    return None
