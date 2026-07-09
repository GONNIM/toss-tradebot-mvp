"""SC 13D primary_desc → subject company CIK · ticker 매핑 · Phase F.

문제: SEC EDGAR filer 관점 recent filings 응답에는 subject company CIK 없음.
primary_desc 만 있음 (예: "THE WENDY'S COMPANY - 13D - AMENDMENT NO. 60").

해결: SEC 무료 company_tickers.json (~800KB, 10K entry) 을 하루 1회 캐시 →
정규화 매칭으로 subject 추출.

한계:
- primary_desc 비어있는 경우 매칭 불가 (SCHEDULE 13D/A 최신 필링 다수)
- 회사명 표기 차이·자회사 매칭 오류 여지
- 매칭 실패 시 target_ticker None · watchlist 자동 등재 안 됨 (안전 fallback)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_URL = "https://www.sec.gov/files/company_tickers.json"
_TIMEOUT_SEC = 15.0
_TTL_SEC = 24 * 3600  # 1일 캐시

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_DIR.parent
_CACHE_PATH = _PROJECT_ROOT / "data" / "sec_company_tickers.json"


@dataclass(frozen=True)
class SubjectCompany:
    cik: str        # 10-digit zero-padded
    ticker: str
    name: str       # 원본 title
    norm_name: str  # 정규화 이름


_index: Dict[str, SubjectCompany] = {}   # norm_name → SubjectCompany (여러 매칭 첫 항목)
_ticker_index: Dict[str, SubjectCompany] = {}
_index_built_at: float = 0.0


# ─── 회사명 정규화 ─────────────────────────────────
_REMOVE_SUFFIXES = [
    "corporation", "corp", "company", "co", "inc", "incorporated",
    "ltd", "limited", "plc", "llc", "lp", "l.p.", "l.l.c.",
    "holdings", "holding", "group", "the",
]
_REMOVE_PATTERN = re.compile(r"[\s\.\-\,\'\"\(\)\&/]")


def _normalize(name: str) -> str:
    """공격적 정규화 — 접미어·특수문자 제거·대소문자 통일."""
    if not name:
        return ""
    s = name.lower()
    # 접미어 제거 (긴 것부터)
    for suf in sorted(_REMOVE_SUFFIXES, key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(suf)}\b", "", s)
    s = _REMOVE_PATTERN.sub("", s)
    return s


async def _fetch_and_cache(ua: str) -> Optional[Dict[str, dict]]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(_URL, headers={"User-Agent": ua})
            resp.raise_for_status()
            data = resp.json()
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data
    except Exception as e:
        logger.warning(f"[subject_resolver] fetch 실패: {e}")
        return None


def _load_cache() -> Optional[Dict[str, dict]]:
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"[subject_resolver] cache load 실패: {e}")
        return None


async def ensure_index(ua: str) -> None:
    """필요 시 인덱스 초기화 · TTL 24h."""
    global _index, _ticker_index, _index_built_at
    now = time.time()
    if _index and (now - _index_built_at) < _TTL_SEC:
        return

    data = _load_cache()
    cache_valid = False
    if data:
        try:
            mtime = _CACHE_PATH.stat().st_mtime
            cache_valid = (now - mtime) < _TTL_SEC
        except OSError:
            cache_valid = False

    if not cache_valid:
        fetched = await _fetch_and_cache(ua)
        if fetched:
            data = fetched
        # fetched 실패 · cache 도 없으면 이전 in-mem 인덱스 유지

    if not data:
        return

    idx: Dict[str, SubjectCompany] = {}
    tidx: Dict[str, SubjectCompany] = {}
    for k, entry in data.items():
        cik_num = entry.get("cik_str")
        ticker = entry.get("ticker")
        title = entry.get("title") or ""
        if not cik_num or not ticker or not title:
            continue
        cik_str = str(cik_num).zfill(10)
        norm = _normalize(title)
        if not norm:
            continue
        sc = SubjectCompany(cik=cik_str, ticker=str(ticker).upper(), name=title, norm_name=norm)
        # 동일 norm 이 이미 있으면 첫 항목 유지 (SEC 순서 = 대체로 시가총액 순)
        idx.setdefault(norm, sc)
        tidx.setdefault(sc.ticker, sc)

    _index = idx
    _ticker_index = tidx
    _index_built_at = now


def _extract_name_from_desc(primary_desc: str) -> str:
    """primary_desc 에서 대상 회사명 부분 추출.

    예: "THE WENDY'S COMPANY - 13D - AMENDMENT NO. 60" → "THE WENDY'S COMPANY"
       "AMERICAN INTERNATIONAL GROUP INC - SC 13D/A" → "AMERICAN INTERNATIONAL GROUP INC"
    구분자: " - " 또는 대문자 form 이름 등장 시점
    """
    if not primary_desc:
        return ""
    text = primary_desc.strip()
    # " - " 로 자르기 (첫 세그먼트만)
    if " - " in text:
        text = text.split(" - ", 1)[0]
    # form 이름 패턴 이후 자르기
    text = re.split(r"\s+(?:SC\s*)?13[DG]\b", text, maxsplit=1)[0]
    text = re.split(r"\s+SCHEDULE\s+13[DG]\b", text, maxsplit=1)[0]
    return text.strip()


async def resolve(primary_desc: str, ua: str) -> Optional[SubjectCompany]:
    """primary_desc → SubjectCompany. 매칭 실패 시 None."""
    await ensure_index(ua)
    if not _index:
        return None

    name = _extract_name_from_desc(primary_desc)
    if not name:
        return None
    norm = _normalize(name)
    if not norm:
        return None

    # 정확 매치 우선
    exact = _index.get(norm)
    if exact:
        return exact

    # substring 매치 (더 긴 회사명 우선)
    candidates: List[Tuple[int, SubjectCompany]] = []
    for k, sc in _index.items():
        if norm and (norm in k or k in norm) and min(len(norm), len(k)) >= 4:
            candidates.append((len(k), sc))
    if not candidates:
        return None
    # 이름 길이 가까운 것 선호 (오탐 억제)
    candidates.sort(key=lambda t: abs(t[0] - len(norm)))
    return candidates[0][1]


def index_size() -> int:
    return len(_index)
