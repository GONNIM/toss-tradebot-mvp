"""Powder Keg Screener · 임계값·설정 · Phase 7 §7-2.

지시서 §작업 방식: 스크린 임계값은 전부 config 로 외부화.
env 로도 override 가능 · 미설정 시 하드 default 사용.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _f(env_key: str, default: float) -> float:
    v = os.environ.get(env_key)
    return float(v) if v else default


def _i(env_key: str, default: int) -> int:
    v = os.environ.get(env_key)
    return int(v) if v else default


@dataclass(frozen=True)
class ScreenerThresholds:
    """스크리너 10 조건 임계값 (§7-2)."""

    # 1. PBR
    pbr_max: float = 0.5

    # 2. 순현금(현금성+단기금융상품 - 총차입금) / 시가총액
    net_cash_ratio_min: float = 0.40

    # 3. 최대주주+특수관계인 지분율
    major_shareholder_pct_min: float = 0.40

    # 4. 공정위 공시대상기업집단 소속 = False (bool · 코드로 판정)

    # 5. 감사의견 = "적정" (최근 2개 연도) (str · 코드로 판정)

    # 6. 이자수익 교차검증 · 이자수익 / 평균 현금성자산 ≥ (기준금리 - 1.5%p)
    #   기준금리 · 한국은행 최신 기준금리 사용 (env 로 override · 미설정 시 3.25% 가정)
    boK_base_rate: float = 0.0325                    # 기준금리 (연 · 3.25%)
    interest_income_yield_margin: float = 0.015      # 기준금리 - 1.5%p

    # 7. 영업이익 · 최근 3년 중 2년 이상 흑자 (bool · 코드로 판정)

    # 8. 피오트로스키 F-Score ≥ 6 (9 항목)
    piotroski_f_score_min: int = 6

    # 9. 일평균 거래대금 60일 ≥ 1억
    adv_60d_min_krw: float = 100_000_000.0

    # 10. 관리종목/거래정지/감사의견 비적정 이력 3년 (bool · 코드로 판정)


def get_thresholds() -> ScreenerThresholds:
    """env override 를 반영해 로드."""
    return ScreenerThresholds(
        pbr_max=_f("POWDERKEG_PBR_MAX", 0.5),
        net_cash_ratio_min=_f("POWDERKEG_NET_CASH_MIN", 0.40),
        major_shareholder_pct_min=_f("POWDERKEG_OWNER_PCT_MIN", 0.40),
        boK_base_rate=_f("POWDERKEG_BOK_BASE_RATE", 0.0325),
        interest_income_yield_margin=_f("POWDERKEG_INTEREST_MARGIN", 0.015),
        piotroski_f_score_min=_i("POWDERKEG_FSCORE_MIN", 6),
        adv_60d_min_krw=_f("POWDERKEG_ADV_60D_MIN", 100_000_000.0),
    )


# ─── 이벤트 트리거 키워드 (§7-3) ────────────────────────
# Type A · 매수 후보 (오너에게 현금이 필요한 사건)
KEYWORDS_TYPE_A = {
    "A1_owner_legal_risk": ("구속", "기소", "검찰", "압수수색", "송치", "혐의"),  # 개인 사법 (뉴스)
    "A2_owner_inheritance": ("상속", "별세", "사망", "타계"),                       # 상속 관련
    "A3_stock_pledge": ("주식담보제공 계약", "담보제공", "주식질권"),                  # 주식담보 (현금수요)
    "A4_activist_5pct": ("주식등의 대량보유상황", "경영권 영향"),                     # 행동주의 5% 보고
    "A5_capital_return": ("배당 확대", "자기주식 소각", "자사주 소각", "기업가치 제고 계획"),  # 카탈리스트 발화
    "A6_reform_pressure": ("저PBR", "기업가치 제고", "상법 개정"),                    # 정책 압박
}

# Type B · 즉시 제외 (현금이 가짜였거나 사라지는 사건)
KEYWORDS_TYPE_B = {
    "B1_embezzlement": ("횡령·배임 혐의발생", "횡령", "배임"),                          # 자금 소실
    "B2_audit_negative": ("감사의견 비적정", "감사의견 한정", "감사의견 부적정", "감사보고서 제출 지연"),
    "B3_trading_halt": ("거래정지", "상장적격성 실질심사", "관리종목 지정"),
}
