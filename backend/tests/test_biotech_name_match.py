"""WP29 · biotech_name_match fixture 5건."""
from __future__ import annotations

from backend.scripts import biotech_name_match as mod


def test_normalize_strips_suffixes_and_punctuation():
    # 접미어 반복 제거 · & 은 punct 제거 · a/s 는 국제 법인 형태 제거
    assert mod.normalize_name("Eli Lilly and Company") == "eli lilly and"
    assert mod.normalize_name("Merck & Co., Inc.") == "merck"
    assert mod.normalize_name("Novo Nordisk A/S") == "novo nordisk"
    assert mod.normalize_name("Vertex Pharmaceuticals Inc.") == "vertex pharmaceuticals"
    assert mod.normalize_name("Vertex Pharmaceuticals") == "vertex pharmaceuticals"


def test_exact_match_prefers_us_listing_for_adr():
    idx = mod.build_index([
        {"name": "Novo Nordisk A/S", "ticker": "NVO", "exchange": "NYSE"},
        {"name": "Novo Nordisk", "ticker": "NOVOB", "exchange": "Copenhagen"},
    ])
    hit = mod.match_exact("Novo Nordisk", idx)
    assert hit is not None
    assert hit["ticker"] == "NVO"  # A/S 제거 후 동일 정규화 · 미국 상장 우선


def test_jaccard_returns_candidates_over_threshold():
    idx = mod.build_index([
        {"name": "Eli Lilly and Company", "ticker": "LLY", "exchange": "NYSE"},
        {"name": "Pfizer Inc", "ticker": "PFE", "exchange": "NYSE"},
    ])
    # 완전 매치는 exclude · 유사 쿼리로 검증
    cands = mod.match_jaccard("Eli Lilly", idx, threshold=0.5)
    assert len(cands) >= 1
    assert cands[0][1]["ticker"] == "LLY"


def test_exact_no_match_when_business_words_preserved_but_different():
    idx = mod.build_index([
        {"name": "Vertex Pharmaceuticals Inc", "ticker": "VRTX", "exchange": "NASDAQ"},
    ])
    assert mod.match_exact("Alnylam Pharmaceuticals", idx) is None
    assert mod.match_exact("Vertex Pharmaceuticals Inc", idx)["ticker"] == "VRTX"


def test_false_positive_short_name_avoided():
    idx = mod.build_index([
        {"name": "TG Therapeutics Inc", "ticker": "TGTX", "exchange": "NASDAQ"},
    ])
    cands = mod.match_jaccard("TG", idx, threshold=0.8)
    assert cands == []
