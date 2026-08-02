"""Ticker 심볼 매핑 · Phase L5 · 2026-08-02.

Serenity signals 는 X 트윗에서 추출된 원문 심볼 (예: `SIVE`, `138080.KQ`).
yfinance 는 Yahoo 표준 심볼 (예: `SIVE.ST`, `138080.KS`)이 필요.

원본: docs/plans/serenity-integration/03-implementation-plan.md §L5 예시.
확장 여지: DB 테이블로 이관 or 별도 YAML config.
"""
from __future__ import annotations

# 시장별 접미어 규칙 (KRX 는 KQ→KS 대체)
_YFINANCE_SYMBOL: dict[str, str] = {
    # Stockholm (SEK-listed)
    "SIVE": "SIVE.ST",
    # Korea · KRX (트윗 원문이 KQ 로 오는 경우 KS 로 매핑)
    "138080.KQ": "138080.KS",
    # Taiwan (TWO 표기 유지)
    "3231.TWO": "3231.TWO",
    # US ADR · 있는 그대로
    "SKHYV": "SKHYV",
    # Korea local
    "SKHY": "000660.KS",
    # 나머지 US · yfinance 심볼과 동일 (NBIS · AXTI · LITE · AAOI · COHR · CRWV · IREN 등)
}


def to_yfinance_symbol(raw: str) -> str:
    """트윗 원문 티커 → yfinance 심볼.

    - 매핑에 있으면 반환
    - `.KQ` 접미어는 `.KS` 로 자동 승격 (Yahoo 는 KQ 미지원)
    - 그 외는 대문자 정규화 후 그대로
    """
    if not raw:
        return raw
    ticker = raw.strip().upper()
    if ticker in _YFINANCE_SYMBOL:
        return _YFINANCE_SYMBOL[ticker]
    if ticker.endswith(".KQ"):
        return ticker[:-3] + ".KS"
    return ticker


def register_mapping(raw: str, yahoo: str) -> None:
    """런타임 매핑 확장 (테스트·1회성 override)."""
    _YFINANCE_SYMBOL[raw.strip().upper()] = yahoo.strip()
