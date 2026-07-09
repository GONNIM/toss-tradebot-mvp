"""한국 activist filer 이름 정규화 · 매칭.

DART 공시 응답 `flr_nm` 은 표기 다양 (예: "얼라인파트너스자산운용" vs "얼라인 파트너스"
vs "Align Partners Asset Management"). Universe SEED 의 activist.key 로 정규화.

기본 정규화:
- 공백·특수문자 제거
- 소문자 변환 (라틴)
- "자산운용", "Asset Management", "AMC", "Capital", "펀드", "Fund" 등 접미어 제거
- ALIASES 사전으로 유사 표기 매핑
"""
from __future__ import annotations

import re
from typing import Optional

# activist key → 후보 표기 리스트 (매칭용, 정규화 전 원문 유지)
ALIASES: dict[str, list[str]] = {
    "align_partners": [
        "얼라인파트너스", "얼라인 파트너스", "얼라인파트너스자산운용",
        "Align Partners", "Align Partners Capital",
    ],
    "kcgi": [
        "KCGI", "케이씨지아이", "케이씨지아이자산운용", "강성부펀드",
    ],
    "vip_asset": [
        "VIP자산운용", "VIP 자산운용", "브이아이피자산운용",
        "VIP Asset Management",
    ],
    "truston_asset": [
        "트러스톤자산운용", "트러스톤 자산운용",
        "Truston Asset Management",
    ],
    "korea_investment_value": [
        "한국투자밸류자산운용", "한국투자밸류", "한투밸류",
        "Korea Investment Value Asset Management",
    ],
    "cha_partners": [
        "차파트너스", "차 파트너스", "차파트너스자산운용",
        "Cha Partners",
    ],
    "value_partners_kr": [
        "밸류파트너스", "밸류파트너스자산운용",
        "Value Partners Korea",
    ],
    "cgcg": [
        "좋은기업지배구조연구소", "CGCG",
        "Center for Good Corporate Governance",
    ],
    "anda_asset": [
        "안다자산운용", "안다 자산운용",
        "Anda Asset Management",
    ],
    "petra_asset": [
        "페트라자산운용", "페트라 자산운용",
        "Petra Asset Management",
    ],
    # 외국계 (한국 활동) — US CIK 와 별개로 한국 신고 시 이름 매칭
    "elliott_kr": [
        "엘리엇", "엘리엇 매니지먼트", "Elliott Management",
        "Elliott Associates", "Elliott Investment Management",
    ],
    "palliser_kr": [
        "Palliser Capital", "팔리서 캐피탈", "팔리저",
    ],
    "silchester_kr": [
        "Silchester International Investors", "실체스터",
    ],
    "dalton_kr": [
        "Dalton Investments", "달튼 인베스트먼츠",
    ],
    "oasis_kr": [
        "Oasis Management", "오아시스 매니지먼트",
    ],
}


_REMOVE_TOKENS_KO = [
    "자산운용", "운용", "매니지먼트",
    "인베스트먼트", "인베스트먼츠",
    # "파트너스"·"캐피탈"·"펀드"·"그룹" 은 activist 이름 핵심이라 유지
]
_REMOVE_TOKENS_EN = [
    "asset management", "investment management",
    "management", "llc", "lp", "ltd", "l.p.", "ltd.",
    "co.", "corp.", "corporation",
    # "capital"·"partners"·"fund"·"group"·"investments" 는 activist 이름 핵심이라 유지
]


def normalize(name: str) -> str:
    """표기 통일: 공백·특수문자 제거 + 접미어 제거 + 소문자."""
    if not name:
        return ""
    s = name.strip().lower()
    # 접미어 제거 (긴 것부터)
    for tok in sorted(_REMOVE_TOKENS_EN, key=len, reverse=True):
        s = s.replace(tok, "")
    for tok in sorted(_REMOVE_TOKENS_KO, key=len, reverse=True):
        s = s.replace(tok, "")
    # 특수문자·공백 제거
    s = re.sub(r"[\s\.\-\(\)\[\]\,\'\"&/]", "", s)
    return s


def match_activist_key(flr_nm: str) -> Optional[str]:
    """DART flr_nm → activist key 매칭. 실패 시 None."""
    if not flr_nm:
        return None
    normalized_input = normalize(flr_nm)
    if not normalized_input:
        return None
    for key, aliases in ALIASES.items():
        for alias in aliases:
            n = normalize(alias)
            if not n:
                continue
            # 양방향 부분 매치 — 최소 4자 이상
            if len(n) >= 4 and (n in normalized_input or normalized_input in n):
                return key
    return None
