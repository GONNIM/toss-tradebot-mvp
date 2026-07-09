"""Activist Universe — 감시 대상 목록.

로드 순서:
    1. SEED_ACTIVISTS (하드코딩 · 이 파일 · 26 US CIK 확정)
    2. data/activist_universe_overrides.json (사용자 UI 편집 · [[overrides]])
       - 병합: seed + overrides
       - overrides 에서 enabled=false 로 특정 CIK 비활성 가능
       - overrides 에서 신규 CIK 추가 가능

US: SEC EDGAR full-text search 로 실측 확정 (2026-07-09).
KR: Phase B 에서 DART filer 매칭 확정 (현재는 빈 리스트).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from . import overrides as _overrides


@dataclass(frozen=True)
class Activist:
    key: str                       # slug (e.g. "trian_fund_management") - 안정 식별자
    name: str                      # UI 표기용
    country: str                   # "US" | "KR"
    tier: int                      # 1 = 실행력 검증 최상위, 2 = 중간, 3 = 소형/특화
    cik: Optional[str] = None      # SEC EDGAR (US)
    corp_code: Optional[str] = None  # DART (KR, Phase B)
    keywords: List[str] = field(default_factory=list)  # 대상 종목 매칭 (선택)
    enabled: bool = True


# ─────────────────────────────────────────────
# US Tier 1 하드코딩 (2026-07-09 EDGAR 실측 확정 · 26개)
# ─────────────────────────────────────────────
SEED_ACTIVISTS: List[Activist] = [
    Activist("trian_fund_management",       "Trian Fund Management, L.P.",           "US", 1, cik="0001345471"),
    Activist("elliott_investment_mgmt",     "Elliott Investment Management L.P.",    "US", 1, cik="0001791786"),
    Activist("pershing_square",             "Pershing Square Capital Management",    "US", 1, cik="0001336528"),
    Activist("third_point",                 "Third Point LLC",                       "US", 1, cik="0001040273"),
    Activist("starboard_value",             "Starboard Value LP",                    "US", 1, cik="0001517137"),
    Activist("jana_partners",               "Jana Partners LLC",                     "US", 1, cik="0001159159"),
    Activist("cevian_capital",              "Cevian Capital II GP Ltd",              "US", 1, cik="0001365341"),
    Activist("sachem_head",                 "Sachem Head Capital Management LP",     "US", 1, cik="0001582090"),
    Activist("corvex_management",           "Corvex Management LP",                  "US", 1, cik="0001535472"),
    Activist("legion_partners",             "Legion Partners Asset Management",      "US", 2, cik="0001560207"),
    Activist("marcato_capital",             "Marcato Capital Management LLC",        "US", 2, cik="0001541996"),
    Activist("blue_harbour",                "Blue Harbour Group, L.P.",              "US", 2, cik="0001325256"),
    Activist("politan_capital",             "Politan Capital Management LP",         "US", 2, cik="0001885245"),
    Activist("impactive_capital",           "Impactive Capital LP",                  "US", 2, cik="0001786767"),
    Activist("blackwells_capital",          "Blackwells Capital LLC",                "US", 2, cik="0001720183"),
    Activist("ancora_advisors",             "Ancora Advisors, LLC",                  "US", 2, cik="0001446114"),
    Activist("dalton_investments",          "Dalton Investments LLC",                "US", 2, cik="0001388838"),
    Activist("silchester_intl",             "Silchester International Investors LLP","US", 2, cik="0001506409"),
    Activist("cerberus_capital",            "Cerberus Capital Management II, L.P.",  "US", 2, cik="0002027951"),
    Activist("oasis_management",            "Oasis Management Co Ltd.",              "US", 2, cik="0001317904"),
    Activist("casablanca_capital",          "Casablanca Capital LLC",                "US", 2, cik="0001511181"),
    Activist("barington_capital",           "Barington Companies Equity Partners LP","US", 2, cik="0001107149"),

    # ── KR (Phase B · 2026-07-09) ──
    # DART flr_nm 매칭 — corp_code 없이 이름 정규화로 감지 ([[kr_normalizer]]).
    Activist("align_partners",              "얼라인파트너스자산운용",                "KR", 1),
    Activist("kcgi",                        "KCGI (강성부)",                         "KR", 1),
    Activist("vip_asset",                   "VIP자산운용",                           "KR", 1),
    Activist("truston_asset",               "트러스톤자산운용",                      "KR", 1),
    Activist("korea_investment_value",      "한국투자밸류자산운용",                  "KR", 2),
    Activist("cha_partners",                "차파트너스자산운용",                    "KR", 2),
    Activist("value_partners_kr",           "밸류파트너스자산운용",                  "KR", 2),
    Activist("cgcg",                        "좋은기업지배구조연구소 (CGCG)",         "KR", 3),
    Activist("anda_asset",                  "안다자산운용",                          "KR", 2),
    Activist("petra_asset",                 "페트라자산운용",                        "KR", 3),
    # 외국계 (KR 활동) — 한국 신고 시 별도 entry
    Activist("elliott_kr",                  "Elliott (한국 활동)",                   "KR", 1),
    Activist("palliser_kr",                 "Palliser Capital (한국 활동)",          "KR", 1),
    Activist("silchester_kr",               "Silchester International (한국 활동)",  "KR", 2),
    Activist("dalton_kr",                   "Dalton Investments (한국 활동)",        "KR", 2),
    Activist("oasis_kr",                    "Oasis Management (한국 활동)",          "KR", 2),
]


def load() -> List[Activist]:
    """seed + overrides 병합 · 활성 항목만 반환."""
    ov = _overrides.load()
    # key → Activist 매핑 (seed)
    merged: dict[str, Activist] = {a.key: a for a in SEED_ACTIVISTS}

    for entry in ov.get("activists", []) or []:
        key = entry.get("key")
        if not key:
            continue
        if key in merged:
            # 기존 항목 업데이트 (필드별 override)
            base = merged[key]
            merged[key] = Activist(
                key=base.key,
                name=entry.get("name", base.name),
                country=entry.get("country", base.country),
                tier=int(entry.get("tier", base.tier)),
                cik=entry.get("cik", base.cik),
                corp_code=entry.get("corp_code", base.corp_code),
                keywords=list(entry.get("keywords", base.keywords)),
                enabled=bool(entry.get("enabled", base.enabled)),
            )
        else:
            # 신규 항목 추가
            merged[key] = Activist(
                key=key,
                name=entry.get("name", key),
                country=entry.get("country", "US"),
                tier=int(entry.get("tier", 2)),
                cik=entry.get("cik"),
                corp_code=entry.get("corp_code"),
                keywords=list(entry.get("keywords", [])),
                enabled=bool(entry.get("enabled", True)),
            )

    # 삭제 요청 (overrides.disabled_keys 로 완전 비활성)
    for key in ov.get("disabled_keys", []) or []:
        merged.pop(key, None)

    return [a for a in merged.values() if a.enabled]


def all_including_disabled() -> List[Activist]:
    """UI 편집 시 비활성 항목 포함 전체 반환."""
    ov = _overrides.load()
    merged: dict[str, Activist] = {a.key: a for a in SEED_ACTIVISTS}
    for entry in ov.get("activists", []) or []:
        key = entry.get("key")
        if not key:
            continue
        base = merged.get(key)
        if base:
            merged[key] = Activist(
                key=base.key,
                name=entry.get("name", base.name),
                country=entry.get("country", base.country),
                tier=int(entry.get("tier", base.tier)),
                cik=entry.get("cik", base.cik),
                corp_code=entry.get("corp_code", base.corp_code),
                keywords=list(entry.get("keywords", base.keywords)),
                enabled=bool(entry.get("enabled", base.enabled)),
            )
        else:
            merged[key] = Activist(
                key=key,
                name=entry.get("name", key),
                country=entry.get("country", "US"),
                tier=int(entry.get("tier", 2)),
                cik=entry.get("cik"),
                corp_code=entry.get("corp_code"),
                keywords=list(entry.get("keywords", [])),
                enabled=bool(entry.get("enabled", True)),
            )
    return list(merged.values())
