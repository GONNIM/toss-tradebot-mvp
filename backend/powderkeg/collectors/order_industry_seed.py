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
    """수주산업 여부 · 조건 2 조정식 적용 판별.

    v1 · 하드코딩 · v2 · sector_code 자동 판별로 대체 예정.
    """
    return ticker in ORDER_INDUSTRY_TICKERS


def order_industry_info(ticker: str) -> tuple[str, str] | None:
    """(name, sector) 반환 · 판별 실패 시 None."""
    return ORDER_INDUSTRY_TICKERS.get(ticker)
