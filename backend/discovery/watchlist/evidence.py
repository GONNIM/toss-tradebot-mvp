"""칸별 근거 · 화면이 「왜 이 종목인가」를 보여 주는 재료 (1030-04).

finalize 가 종목마다 만들어 watchlist.source_breakdown 의 `_evidence` 키에 넣고,
list_watchlist 응답이 `evidence` 로 꺼내 준다 (source_breakdown 에서는 `_` 키를 뺀다 → 옛 화면 호환).

모양 (키는 항상 있다 · 없으면 빈 값):
{
  "news":     {"count": 기사 건수, "publishers": 서로 다른 언론사 수,
               "articles": [{"title","source","url","published"}]  최대 3 (가중 큰 순)},
  "interest": [{"source","label","rank","prev_rank","is_new","change_rate_pct"}]   # 개인 관심
  "youtube":  {"count": N, "videos": [{"title","source"}]  최대 3},
  "event":    [{"source","title"}]  최대 3 (DART 허용 공시 · 국회 · 보도자료),
  "caution":  [{"title"}]  최대 3   # 주의 공시 (유상증자·CB 등 · 점수 0)
  "prev_day": [{"source","label","rank","prev_rank","is_new","change_rate_pct"}]
}
"""
from __future__ import annotations

from typing import Any

from . import source_groups as sg

_MAX_ITEMS = 3


def _rank_item(s: dict[str, Any]) -> dict[str, Any]:
    p = s.get("payload") or {}
    rate = p.get("change_rate")
    return {
        "source": s["source"],
        "label": sg.RANK_KIND_LABEL.get(s["source"], s["source"]),
        "rank": p.get("rank"),
        "prev_rank": p.get("prev_rank"),
        "is_new": bool(p.get("is_new")),
        "change_rate_pct": round(rate * 100, 2) if isinstance(rate, (int, float)) else None,
    }


def build_evidence(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """한 종목의 신호 목록 → 칸별 근거."""
    news = [s for s in signals if s.get("source") in sg.NEWS_SOURCES]
    news.sort(key=lambda s: str(s.get("detected_at") or ""), reverse=True)    # 최근 먼저
    news.sort(key=lambda s: -(s.get("intensity") or 0.0))                      # 가중 큰 것 먼저 (안정 정렬)
    articles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for s in news:
        p = s.get("payload") or {}
        title = str(p.get("title") or "").strip()
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        articles.append({
            "title": title, "source": s["source"], "url": p.get("url") or None,
            "published": p.get("published"),
        })
        if len(articles) >= _MAX_ITEMS:
            break

    videos = [
        {"title": str((s.get("payload") or {}).get("title") or ""), "source": s["source"]}
        for s in signals if s.get("source") in sg.YOUTUBE_SOURCES
    ]
    events = [
        {"source": s["source"], "title": str((s.get("payload") or {}).get("title") or "")}
        for s in signals if s.get("source") in sg.EVENT_SOURCES
    ]
    caution = [
        {"title": str((s.get("payload") or {}).get("title") or "")}
        for s in signals if s.get("source") == sg.CAUTION_SOURCE
    ]
    interest = [_rank_item(s) for s in signals if s.get("source") in sg.INTEREST_SOURCES]
    prev_day = [_rank_item(s) for s in signals if s.get("source") in sg.PREV_DAY_SOURCES]
    # 같은 순위 종류가 여러 번 저장돼도 (재실행) 한 줄만
    def _uniq(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for it in items:
            out.setdefault(it["source"], it)
        return list(out.values())

    return {
        "news": {
            "count": len(news),
            "publishers": len({sg.NEWS_PUBLISHER[s["source"]] for s in news}),
            "articles": articles,
        },
        "interest": _uniq(interest),
        "youtube": {"count": len(videos), "videos": videos[:_MAX_ITEMS]},
        "event": events[:_MAX_ITEMS],
        "caution": caution[:_MAX_ITEMS],
        "prev_day": _uniq(prev_day),
    }
