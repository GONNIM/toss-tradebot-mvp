"""수주산업(건설·조선·플랜트) seed 데이터 · Phase 7 · 3차 리뷰 P2.

⚠️ 배경: 수주산업은 발주처 선수금(=계약부채)이 cash_and_equivalents 에 섞여
    저장되면서 조건 2 (순현금/시총 > 40%) 를 부풀림. total_debt 는 차입금·사채
    만이라 계약부채 미포함 → 순현금 과대평가.

    조정 순현금 = cash - total_debt - contract_liabilities   (조정식 · P2)

📌 v1 은 대표 상장 종목 하드코딩 · v2 는 KRX sector_code 자동 판별로 대체 예정.
    2026년 상장 종목 기준. 상폐·인수합병 시 사용자가 수동 갱신 필요.

용도:
- screener.py 조건 2 계산 시 `is_order_industry(ticker)` True 면 조정식 적용
- 원 net_cash 와 조정 net_cash 둘 다 로그·UI 병기 (P2-4)

참고 · 3rd-review-response.md §9 · 서희건설 재검증 근거.
"""
from __future__ import annotations


# (ticker, name, sector) · 건설/조선/플랜트 대표 상장 종목 (2026 기준)
ORDER_INDUSTRY_TICKERS: dict[str, tuple[str, str]] = {
    # ─── 건설 (수주 · 분양 선수금 이슈) ─────────
    "000720": ("현대건설",          "건설"),
    "006360": ("GS건설",            "건설"),
    "009410": ("태영건설",          "건설"),
    "013580": ("계룡건설산업",      "건설"),
    "014790": ("HL D&I",            "건설"),
    "021320": ("KCC건설",           "건설"),
    "028260": ("삼성물산",          "건설"),   # 건설 부문 · 부분 해당
    "035890": ("서희건설",          "건설"),   # first-passed-result.md 대상
    "047040": ("대우건설",          "건설"),
    "294870": ("HDC현대산업개발",   "건설"),
    "375500": ("DL이앤씨",          "건설"),
    # ─── 조선 (선수금 · 대형 프로젝트) ──────────
    "009540": ("HD한국조선해양",    "조선"),
    "010140": ("삼성중공업",        "조선"),
    "010620": ("HD현대미포",        "조선"),
    "042660": ("한화오션",          "조선"),   # 구 대우조선해양
    "329180": ("HD현대중공업",      "조선"),
    # ─── 플랜트/EPC (수주 · 진행률 인식) ────────
    "051600": ("한전KPS",           "플랜트"),
    "267250": ("HD현대일렉트릭",    "플랜트"),   # 근사
}


def is_order_industry(ticker: str) -> bool:
    """수주산업 명시 시드 여부 · 조건 2 조정식 적용 판별.

    v1 · 하드코딩 · v2 · sector_code 자동 판별로 대체 예정.
    """
    return ticker in ORDER_INDUSTRY_TICKERS


def order_industry_info(ticker: str) -> tuple[str, str] | None:
    """(name, sector) 반환 · 판별 실패 시 None."""
    return ORDER_INDUSTRY_TICKERS.get(ticker)


# ─── 금융업 시드 (계약부채 조정 스킵 대상) · P2-4e ────────
# 은행·증권·보험 · "계약부채" 계정이 예수부채·보험계약 부채 성격이라
# 순현금 조정에서 차감하면 왜곡. 이 리스트는 조건 2 조정에서 스킵.
FINANCIAL_INDUSTRY_TICKERS: dict[str, tuple[str, str]] = {
    # 은행
    "024110": ("기업은행",       "은행"),
    "055550": ("신한지주",       "은행"),
    "086790": ("하나금융지주",   "은행"),
    "105560": ("KB금융",         "은행"),
    "316140": ("우리금융지주",   "은행"),
    "138930": ("BNK금융지주",    "은행"),
    "175330": ("JB금융지주",     "은행"),
    "139130": ("DGB금융지주",    "은행"),
    # 증권
    "078020": ("LS증권",         "증권"),
    "016360": ("삼성증권",       "증권"),
    "006800": ("미래에셋증권",   "증권"),
    "030200": ("KT",             "통신"),   # 통신은 조정 대상 아님 (별건 예방)
    "003540": ("대신증권",       "증권"),
    "003470": ("유안타증권",     "증권"),
    # 보험
    "032830": ("삼성생명",       "보험"),
    "088350": ("한화생명",       "보험"),
    "000810": ("삼성화재",       "보험"),
    "005830": ("DB손해보험",     "보험"),
}


def is_financial_industry(ticker: str) -> bool:
    """금융업(은행·증권·보험) 여부 · 계약부채 조정에서 스킵."""
    return ticker in FINANCIAL_INDUSTRY_TICKERS


def financial_industry_info(ticker: str) -> tuple[str, str] | None:
    return FINANCIAL_INDUSTRY_TICKERS.get(ticker)


# ─── 자동 판별 임계 · P2-4e ────────────────────────────────
#   contract_liabilities / market_cap > 이 임계이면 수주업종으로 자동 취급.
#   무료체험·구독형 등 소액 계약부채는 조정 스킵 (오탐 방지).
#   3% · 실측 · 다우데이타(10%) 조정 · SK이노(0.9%) 미조정.
CONTRACT_LIAB_RATIO_AUTO_THRESHOLD = 0.03


def should_apply_contract_liab_adjustment(
    ticker: str,
    contract_liab: float,
    market_cap: float,
) -> bool:
    """조건 2 계약부채 조정식 적용 여부.

    우선순위:
    1. 금융업 (은행·증권·보험) 이면 False (예수부채 성격)
    2. 명시 시드 (order_industry_seed) 있으면 True
    3. cl/market_cap > CONTRACT_LIAB_RATIO_AUTO_THRESHOLD 이면 True (자동)
    """
    if is_financial_industry(ticker):
        return False
    if is_order_industry(ticker):
        return True
    if market_cap and market_cap > 0 and contract_liab:
        return (contract_liab / market_cap) > CONTRACT_LIAB_RATIO_AUTO_THRESHOLD
    return False
