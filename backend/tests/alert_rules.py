"""알림 문구 규칙 검사 도우미 (1023-05) — 테스트 전용."""
from __future__ import annotations

import unicodedata

SITE = "https://optimus8.cafe24.com/"
BANNED = (
    "DO NOT TOUCH", "URGENT", "rows", "confidence=", "P&L", "Accession", "Filer", "order_uuid",
    "tape_score", "VALIDATED", "hypothesis", "캐비어트", "Picks", "Sector Leaders", "Meme Score",
    "Intensity", "ERUPTING", "BLAZING", "step:", "detail:", "매수 후보", "매수가", "예측수익가", "즉시 검토",
)


def _icons(text: str) -> int:
    return sum(1 for c in text if unicodedata.category(c) == "So")


def violations(title: str, body: str) -> list[str]:
    out = []
    if len(title) > 40:
        out.append(f"제목 {len(title)}자")
    lines = [l for l in body.split("\n") if l.strip()]
    if len(lines) > 10:
        out.append(f"본문 {len(lines)}줄")
    if _icons(title) != 1 or not title or unicodedata.category(title[0]) != "So":
        out.append(f"제목 아이콘 {_icons(title)}개")
    if SITE not in body:
        out.append("절대 링크 없음")
    for w in BANNED:
        if w in title or w in body:
            out.append(f"금지 낱말 {w}")
    return out
