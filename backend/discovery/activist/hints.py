"""사용자 친화적 힌트·설명·URL 조립 헬퍼.

각 이벤트에 표시할 부가 정보:
- form_hint: 폼 코드 → 짧은 한글 설명 (예: SC 13D → "지분 5%↑ 신규 · 경영권 개입")
- action_hint: 강도 라벨 → 추천 액션 (예: CRITICAL → "즉시 검토")
- filer_search_url: SEC/DART 활동주주 필링 목록 페이지
- filing_detail_url: 개별 필링 상세 페이지 (SEC filer CIK 기반)
"""
from __future__ import annotations

from typing import Optional


# ─── 폼 코드 → 한글 짧은 설명 ───────────────────────
_FORM_HINTS = {
    # 미국 SEC
    "SC 13D":          "지분 5%↑ 신규 신고 · 경영권 개입 목적 (강)",
    "SC 13D/A":        "지분 5%↑ 변동·수정본 · 경영권 개입 지속",
    "SCHEDULE 13D":    "지분 5%↑ 신규 신고 · 경영권 개입 목적 (강)",
    "SCHEDULE 13D/A":  "지분 5%↑ 변동·수정본 · 경영권 개입 지속",
    "SC 13G":          "지분 5%↑ 신규 신고 · 재무투자 목적 (passive)",
    "SC 13G/A":        "지분 5%↑ 변동 · passive",
    "SCHEDULE 13G":    "지분 5%↑ 신규 · passive",
    "SCHEDULE 13G/A":  "지분 5%↑ 변동 · passive",
}


def form_hint(form: str) -> str:
    """폼 문자열 → 짧은 한글 설명. 대량보유(KR)·Form 4는 별도 파싱."""
    if not form:
        return ""
    # exact match
    if form in _FORM_HINTS:
        return _FORM_HINTS[form]
    # KR: "대량보유 (MANAGEMENT) · 5.20% ▲0.50%"
    if "대량보유" in form:
        if "MANAGEMENT" in form:
            return "5%↑ 대량보유 · 경영권 개입 목적 (강)"
        if "PASSIVE" in form:
            return "5%↑ 대량보유 · 단순투자 (약)"
        return "5%↑ 대량보유 신고"
    # Form 4 (US 임원 매매)
    if form.startswith("Form 4"):
        if "매수" in form:
            return "임원·주요주주 실 매수 · 신뢰 신호"
        if "매도" in form:
            return "임원·주요주주 실 매도 · 이탈 가능"
        if "non-trade" in form:
            return "옵션 행사·수여·증여 · 실 매매 아님"
        return "임원·주요주주 매매 신고"
    # D002 (KR 임원)
    if "D002" in form:
        return "임원·주요주주 특정증권 매매 신고"
    return ""


# ─── 강도 라벨 → 추천 액션 ─────────────────────────
_ACTION_HINTS = {
    "REGIME_CHANGE": "🚨 즉시 검토 · passive → active 태세 전환 · 최상 신호",
    "CRITICAL":      "⚠️ 즉시 검토 · Tier 1 신규 대량 지분 or Wolf Pack",
    "STRONG":        "🔎 관심 · 지분 변동·수정본 · Tier 1",
    "INSIDER":       "💡 참고 · 내부자 매매 (activism 진입 종목)",
    "WATCH":         "📎 참고 · passive · 저강도",
    "NOTE":          "📝 기록만 · 알림 없음",
    "CRITICAL_PACK": "🐺🌋 즉시 검토 · Wolf Pack · 다중 activist",
    "STRONG_PACK":   "🐺🔥 관심 · Wolf Pack",
    "PACK":          "🐺 관심 · 2명 이상 activist 진입",
}


def action_hint(intensity_label: str) -> str:
    return _ACTION_HINTS.get(intensity_label, "📎 참고")


# ─── SEC EDGAR URL 조립 ────────────────────────────
def sec_filing_detail_url(filer_cik: Optional[str], accession: str) -> str:
    """SEC 개별 필링 상세 페이지 (디렉토리 인덱스).

    URL 규칙: filer(reporting entity) CIK 기반, trailing slash 필수.
    예: https://www.sec.gov/Archives/edgar/data/2027951/000101143826000400/
    """
    if not filer_cik or not accession:
        return ""
    cik_num = str(filer_cik).lstrip("0") or "0"
    acc_no_dashes = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_no_dashes}/"


def sec_filer_search_url(filer_cik: Optional[str]) -> str:
    """SEC EDGAR 활동주주 필링 목록 (browse-edgar UI)."""
    if not filer_cik:
        return ""
    cik_num = str(filer_cik).lstrip("0") or "0"
    return (
        f"https://www.sec.gov/cgi-bin/browse-edgar?"
        f"action=getcompany&CIK={cik_num}&type=SC+13&dateb=&owner=include&count=40"
    )


# ─── DART URL 조립 ─────────────────────────────────
def dart_filing_detail_url(rcept_no: str) -> str:
    """DART 개별 공시 상세 뷰어."""
    if not rcept_no:
        return ""
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def dart_filer_search_url(filer_name: str) -> str:
    """DART 회사·공시자 검색 (검색 팝업)."""
    from urllib.parse import quote
    if not filer_name:
        return ""
    return f"https://opendart.fss.or.kr/main.do?searchKeyword={quote(filer_name)}"
