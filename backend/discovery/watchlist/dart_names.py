"""DART 상장사 이름표 → 종목코드별 이름 · 화면 빈칸만 채운다 (1030-04).

backend/data/dart_corp_codes.json = {corp_name: {corp_code, stock_code}} (3,959곳 · biotech 스크립트가 만든 사본).
matcher 사전에는 넣지 않는다 — DART 정식명(「현대자동차」)은 기사에 쓰는 이름(「현대차」)과 달라
뉴스 매칭에 쓰면 오탐·누락이 늘어난다. 이 파일은 이름이 비어 있는 행의 표시용이다.
data/ 는 .gitignore 라 git add -f 로 추적 (1030-04) · 그래도 없으면 빈 표 (finalize 가 화약고 DB 표를 먼저 봄).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parents[2] / "data" / "dart_corp_codes.json"
_cache: Optional[dict[str, str]] = None


def dart_names(path: Optional[Path] = None) -> dict[str, str]:
    """{stock_code: corp_name} · 한 번 읽고 캐시 (path 를 주면 캐시 없이 읽음 · 테스트용)."""
    global _cache
    if path is None and _cache is not None:
        return _cache
    p = path or _PATH
    names: dict[str, str] = {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        for corp_name, info in raw.items():
            code = (info or {}).get("stock_code") if isinstance(info, dict) else None
            if code:
                names.setdefault(str(code), str(corp_name))
    except (OSError, ValueError) as exc:
        logger.warning("[dart_names] 이름표 없음 · %s · %s", p.name, exc)
    if path is None:
        _cache = names
    return names
