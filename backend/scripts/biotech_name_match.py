"""WP29 · 회사명 매칭기 (공통 병목 · H1a/H6/H5 재사용).

정규화 규칙 (사전 커밋):
- 소문자화
- 구두점 제거 (.,()-/&·)
- 법인 접미어 (반복 가능) 제거: inc · corp · co · ltd · plc · ag · sa · nv · as · llc · holdings · incorporated · corporation · limited · company
- 흔한 업종 단어 (pharmaceuticals · pharmaceutical · pharma · therapeutics · biosciences · biotech · bio) **는 보존** (오탐 방지)

매칭:
- 1차 · 완전 일치 (normalized string 동일)
- 2차 · 토큰 집합 Jaccard ≥ 0.8 (자동 채택 금지 · 후보 CSV 로만 · 검수 표기)
- ADR: 동일 정규화명 복수 → **미국 상장 (exchange in NYSE/NASDAQ/AMEX) 우선**
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import re
import subprocess
from collections import defaultdict
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_name_match")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

# 반복 제거 가능 (긴 것 먼저)
CORP_SUFFIXES = [
    "incorporated", "corporation", "limited", "company",
    "holdings", "llc", "plc", "inc", "corp", "ltd", "co", "ag", "sa", "nv", "as",
]

_PUNCT_RE = re.compile(r"[.,()\-/&·]+")
_SPACE_RE = re.compile(r"\s+")
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "NYSE ARCA", "BATS", "NYSE MKT"}


def normalize_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower()
    # 국제 법인 형태 사전 치환 (punct 제거 전 · "a/s", "n/v" 등)
    s = re.sub(r"\ba\s*/\s*s\b", "", s)
    s = re.sub(r"\bn\s*/\s*v\b", "", s)
    s = re.sub(r"\bs\s*/\s*a\b", "", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    # 반복 접미어 제거 (예: "abc inc corp" → "abc")
    while True:
        tokens = s.split()
        if not tokens:
            break
        if tokens[-1] in CORP_SUFFIXES:
            s = " ".join(tokens[:-1])
        else:
            break
    return s.strip()


def tokens(name: str) -> set[str]:
    return {t for t in normalize_name(name).split() if t}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_index(entries: list[dict], name_key: str = "name", ticker_key: str = "ticker", exchange_key: str = "exchange") -> dict:
    """entries → {normalized: [{ticker,name,exchange,...}, ...]}."""
    idx: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        n = e.get(name_key, "")
        norm = normalize_name(n)
        if not norm:
            continue
        idx[norm].append({
            "ticker": e.get(ticker_key, ""),
            "name": n,
            "exchange": e.get(exchange_key, ""),
            **{k: v for k, v in e.items() if k not in (name_key, ticker_key, exchange_key)},
        })
    return idx


def _prefer_us(candidates: list[dict]) -> dict:
    """복수 후보 → 미국 상장 우선."""
    us = [c for c in candidates if (c.get("exchange") or "").upper() in US_EXCHANGES]
    return us[0] if us else candidates[0]


def match_exact(query: str, idx: dict) -> dict | None:
    key = normalize_name(query)
    if not key:
        return None
    hits = idx.get(key)
    if not hits:
        return None
    return _prefer_us(hits)


def match_jaccard(query: str, idx: dict, threshold: float = 0.8, max_candidates: int = 5) -> list[tuple[float, dict]]:
    qs = tokens(query)
    if not qs:
        return []
    out = []
    for key, hits in idx.items():
        cs = set(key.split())
        j = jaccard(qs, cs)
        if j >= threshold and normalize_name(query) != key:  # 완전 매치는 제외
            out.append((j, _prefer_us(hits)))
    out.sort(key=lambda x: -x[0])
    return out[:max_candidates]


# 사용 진입점 (H1a/H6 재매핑 시 호출) ---------------------------------

def load_sec_company_index() -> dict:
    """SEC company_tickers.json 캐시 로드."""
    cache = DATA_DIR / "sec_company_tickers.json"
    if not cache.exists():
        return {}
    data = json.loads(cache.read_text())
    entries = []
    for _, e in data.items():
        entries.append({
            "ticker": str(e.get("ticker", "")).upper(),
            "name": e.get("title", ""),
            "exchange": "NASDAQ",  # SEC 는 exchange 미기재 · 기본 US 상장 가정
            "cik": str(e.get("cik_str", "")),
        })
    return build_index(entries)


def load_tiingo_index() -> dict:
    """Tiingo universe_skeleton_v2 → ticker only (회사명 부재)."""
    p = DATA_DIR / "universe_skeleton_v2_add7af7.csv"
    entries = []
    with p.open() as f:
        for row in csv.DictReader(f):
            entries.append({"ticker": row["ticker"], "name": row["ticker"], "exchange": row["exchange"]})
    # Tiingo 자체는 회사명 없음 → SEC index 로 병합 (WP29 · SEC 우선 · 미매핑 시 Tiingo 확장)
    return build_index(entries)


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("WP29 · name matcher · module OK")


if __name__ == "__main__":
    main()
