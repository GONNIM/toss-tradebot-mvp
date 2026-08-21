"""DART 재무 fetcher · principles v1.0.2 전용 파서.

기존 backend/discovery/data_sources/dart/client.py (fetch_financial_statement) 재활용.
principles 원칙 4·2·1 계산에 필요한 필드만 파싱:
  - 지배주주순이익 (P1·P2)
  - 영업이익 (P1 supporting)
  - 이자비용 (P4 · 이자보상배율 분모)
  - 부채총계·자본총계 (P4 · 부채비율)
  - 자기주식 취득액 (P2 · 현금흐름표 · 절대값)
  - 주당 배당금 (P3 · 사업보고서 배당사항 alotMatter.json)

TTM 누적 분해 규칙 (v1.0.2 사용자 지시 2건):
  - DART 분기 재무는 누적 기준. Q단독 = 당기 누적 − 직전 분기 누적.
  - 연말 Q4 = 사업보고서 연간값 − 3Q 누적.
  - TTM = 최근 4개 Q단독 합산.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional

import httpx

from backend.discovery.data_sources.dart.client import (
    DartFinancialItem,
    _api_key,
    _BASE,
    _TIMEOUT_SEC,
    fetch_financial_statement,
)

logger = logging.getLogger(__name__)


# ─── reprt_code 매핑 ────────────────────────────────────────────
# DART reprt_code · 분기 인덱스 (1=Q1, 2=Q2H누적, 3=Q3누적, 4=사업보고서)
_REPRT_CODE_BY_Q = {
    1: "11013",  # 1분기
    2: "11012",  # 반기 (Q2 누적)
    3: "11014",  # 3분기 (Q3 누적)
    4: "11011",  # 사업보고서 (연간)
}


# ─── principles 전용 파싱 필드 ─────────────────────────────────
# 원칙 1·2·4 계산에 필요한 최소 필드만 · 필요 시 추가.
_MAPPING_ID: dict[str, str] = {
    # 손익계산서
    "ifrs-full_Revenue": "revenue",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLossAttributableToOwnersOfParent": "net_income_owner",
    "ifrs-full_ProfitLoss": "net_income",  # net_income_owner 미매치 시 fallback
    "ifrs-full_FinanceCosts": "interest_expense",  # 금융비용 (이자비용 근사)
    # 재무상태표
    "ifrs-full_Assets": "total_assets",
    "ifrs-full_Liabilities": "total_liabilities",
    "ifrs-full_Equity": "total_equity",
    # 현금흐름표 · 자기주식 취득 (음수 유출)
    "ifrs-full_PaymentsForRepurchaseOfEntitysOwnShares": "buyback_cashflow",
}

_MAPPING_NM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "영업수익", "수익(매출액)"),
    "operating_income": ("영업이익",),
    # 2026-08-18 fix (삼성전자 자본총계 오매칭 사고):
    # 기존 "지배기업 소유주" keyword 는 자본 계정 ("지배기업의 소유주에게 귀속되는 지분/자본") 과 substring 매칭 오염.
    # → "당기순이익" 명시가 포함된 정확 문구만 허용.
    "net_income_owner": (
        "지배기업의 소유주에게 귀속되는 당기순이익",
        "지배기업 소유주지분 당기순이익",
    ),
    "net_income": ("당기순이익",),
    "interest_expense": ("이자비용", "금융비용"),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "total_equity": ("자본총계",),
    "buyback_cashflow": ("자기주식의 취득", "자기주식 취득", "자기주식취득"),
}


# v1.0.6-rev4 (2026-08-20) · sj_div 필터 (재무제표 영역별 계정 분리)
# BS = 재무상태표 · IS = 손익계산서 · CIS = 포괄손익계산서
# CF = 현금흐름표 · SCE = 자본변동표
# 사고 (verified 표본 대조): sj_div 필터 없이 account_id 만 매칭 · SCE (자본변동표) 안의
# ifrs-full_ProfitLossAttributableToOwnersOfParent 잡음 → 순이익 위치의 자본 변동 값 저장
_FIELD_TO_SJ_DIV: dict[str, tuple[str, ...]] = {
    "revenue": ("IS", "CIS"),
    "operating_income": ("IS", "CIS"),
    "net_income_owner": ("IS", "CIS"),
    "net_income": ("IS", "CIS"),
    "interest_expense": ("IS", "CIS"),
    "total_assets": ("BS",),
    "total_liabilities": ("BS",),
    "total_equity": ("BS",),
    "buyback_cashflow": ("CF",),
}


# v1.0.7 (2026-08-21) · 파서 계약 계약: `_cum` 컬럼은 누적 저장 강제.
# 반기(11012)·3분기(11014) 보고서의 흐름 계정 (IS/CIS/CF/SCE) 은 `thstrm_add_amount`
# (당기누적) 우선 · 부재 시 `thstrm_amount` (Q 단독) fallback.
# 1분기(11013)·사업(11011) 은 thstrm_amount 가 이미 누적 = 정합.
# BS 는 스냅샷이라 accumulation 개념 없음 · 항상 thstrm_amount.
_ADD_REQUIRED_REPRT: frozenset[str] = frozenset({"11012", "11014"})
_ADD_REQUIRED_SJ: frozenset[str] = frozenset({"IS", "CIS", "CF", "SCE"})

# fallback 발생 시 caller(scheduler) 가 캐시 컬럼에 기록하기 위한 매핑.
# net_income 은 net_income_owner 미매치 시 대체로 net_income_owner_cum 컬럼에 저장됨.
_FIELD_TO_CUM_COLUMN: dict[str, str] = {
    "revenue": "revenue_cum",
    "operating_income": "operating_income_cum",
    "net_income_owner": "net_income_owner_cum",
    "net_income": "net_income_owner_cum",
    "interest_expense": "interest_expense_cum",
    "buyback_cashflow": "buyback_cashflow_cum",
}


@dataclass
class PrinciplesFinancials:
    """principles 원칙 계산용 재무 파싱 결과 (한 분기 · 누적값)."""

    revenue: Optional[float] = None
    operating_income: Optional[float] = None
    net_income_owner: Optional[float] = None
    net_income: Optional[float] = None  # fallback
    interest_expense: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    total_equity: Optional[float] = None
    buyback_cashflow: Optional[float] = None  # 원본 부호 (음수 = 유출)
    matched: dict[str, str] = field(default_factory=dict)  # field → account_nm 로그
    # v1.0.7 · cum_fallback (add 없이 thstrm 사용) 발생 필드 (cum 컬럼명 단위).
    # 삼전 등 특이 회사가 thstrm 에 누적을 담는 케이스 처리용. 정합성 미검증 표시.
    fallback_fields: set[str] = field(default_factory=set)


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def parse_principles_financials(
    items: Iterable[DartFinancialItem],
    reprt_code: str = "11011",
) -> PrinciplesFinancials:
    """DART 응답 → PrinciplesFinancials.

    매칭 우선순위 (v1.0.6-rev4 · sj_div 필터 추가):
      1. sj_div 일치 + account_id 매칭
      2. sj_div 일치 + account_nm keyword substring 매칭
      sj_div 불일치 행은 account_id 가 맞아도 배제.

    사고 방지 (2026-08-20 verified 표본 대조): SCE (자본변동표) 안의
    'ifrs-full_ProfitLossAttributableToOwnersOfParent' account_id 는
    자본 변동 값 (당기 순이익 표시 위치) 을 반환 · 실제 IS 순이익 아님.

    v1.0.7 (2026-08-21) · 계약: `_cum` 컬럼은 누적 저장 강제.
      - reprt_code ∈ (11012, 11014) 이고 sj_div ∈ (IS, CIS, CF, SCE) →
        thstrm_add_amount 우선 · 부재 시 thstrm_amount fallback + fallback_fields 기록
      - reprt_code ∈ (11013, 11011) 또는 BS → thstrm_amount 그대로 (누적=단독 정합)
    """
    out = PrinciplesFinancials()
    for item in items:
        sj = item.sj_div or ""
        # 1. account_id 매칭
        field_name = _MAPPING_ID.get(item.account_id)
        # 2. account_nm 매칭 (fallback)
        if field_name is None:
            nm = _norm(item.account_nm)
            for f, kws in _MAPPING_NM_KEYWORDS.items():
                if any(kw in nm for kw in kws):
                    field_name = f
                    break
        if field_name is None:
            continue
        # 3. sj_div 필터 (v1.0.6-rev4 · 계정 영역 확인)
        allowed_sj = _FIELD_TO_SJ_DIV.get(field_name, ())
        if allowed_sj and sj not in allowed_sj:
            continue  # sj_div 불일치 · 배제 (예: SCE 안의 순이익 계정 오매칭 방지)
        if getattr(out, field_name) is not None:
            continue  # 이미 매칭 · 첫 매칭 유지
        # 4. v1.0.7 · 누적 값 선택 (add 우선 · fallback thstrm)
        needs_add = (reprt_code in _ADD_REQUIRED_REPRT) and (sj in _ADD_REQUIRED_SJ)
        if needs_add:
            val = item.thstrm_add_amount
            if val is None:
                val = item.thstrm_amount
                if val is not None:
                    cum_col = _FIELD_TO_CUM_COLUMN.get(field_name)
                    if cum_col:
                        out.fallback_fields.add(cum_col)
        else:
            val = item.thstrm_amount
        if val is None:
            continue
        setattr(out, field_name, val)
        out.matched[field_name] = f"{item.account_nm}[{sj}]"
    return out


# ─── 누적 → Q단독 분해 (v1.0.2 규약) ─────────────────────────

def cumulative_to_quarter(cum_by_q: dict[int, Optional[float]]) -> dict[int, Optional[float]]:
    """누적값 dict {1,2,3,4} → Q단독 dict.

    규약:
      Q1 = Q1_cum
      Q2 = Q2_cum − Q1_cum
      Q3 = Q3_cum − Q2_cum
      Q4 = Q4_cum(사업보고서 연간값) − Q3_cum

    누락 분기는 None. Q1 None 이면 Q2 도 계산 불가 (연쇄).
    """
    result: dict[int, Optional[float]] = {1: None, 2: None, 3: None, 4: None}
    q1 = cum_by_q.get(1)
    q2c = cum_by_q.get(2)
    q3c = cum_by_q.get(3)
    q4c = cum_by_q.get(4)

    result[1] = q1
    if q1 is not None and q2c is not None:
        result[2] = q2c - q1
    if q2c is not None and q3c is not None:
        result[3] = q3c - q2c
    if q3c is not None and q4c is not None:
        result[4] = q4c - q3c
    return result


def ttm_sum(quarter_flow_series: list[Optional[float]]) -> Optional[float]:
    """분기 단독 값 리스트 (시간순) → 최근 4개 합산 (TTM).

    None 이 하나라도 있으면 None 반환 (TTM 정합 불가).
    """
    if len(quarter_flow_series) < 4:
        return None
    last4 = quarter_flow_series[-4:]
    if any(v is None for v in last4):
        return None
    return sum(last4)  # type: ignore[arg-type]


# ─── 배당사항 (P3) ─────────────────────────────────────────────

@dataclass(frozen=True)
class DividendMatter:
    """DART 배당에 관한 사항 (alotMatter.json)."""

    corp_code: str
    bsns_year: int
    dividend_per_share_common: Optional[float]  # 주당 현금배당금 (원) · 보통주
    # v1.0.5 (2026-08-19 · 이슈 C) · 현금배당금총액 (원 · 우선주 포함 · 공시 총액)
    dividend_total_krw: Optional[float] = None
    # 원시 응답 raw list (재파싱 방지 · parser_version 부채)
    raw_rows: Optional[list] = None


def _parse_dart_number(v: Optional[str]) -> Optional[float]:
    """DART 문자열 숫자 파싱 · '1,234' → 1234.0 · '-' → 0.0 (확정 무배당) · None/'' → None."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "None"):
        return None
    if s == "-":
        return 0.0  # 확정 무배당 (None 과 구분)
    try:
        return float(s)
    except ValueError:
        return None


async def fetch_dividend_matter(
    corp_code: str,
    bsns_year: int,
) -> Optional[DividendMatter]:
    """DART 배당에 관한 사항 (alotMatter.json · 사업보고서만 · reprt_code=11011).

    Docs: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019005
    응답 필드:
      - se (구분): "주당 현금배당금(원)" / "현금배당금총액(백만원)" 등
      - stock_knd: "보통주" / "우선주" (또는 공백)
    v1.0.5 · 이슈 C:
      - dividend_per_share_common: 보통주 · 주당 현금배당금
      - dividend_total_krw: 공시 총액 (백만원 단위 → 원 환산 · 우선주 포함)
      - raw_rows: 원시 응답 전체 (재호출 방지 · 향후 필드 추가 대응)
    """
    if not corp_code:
        return None
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": "11011",
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_BASE}/alotMatter.json", params=params, timeout=_TIMEOUT_SEC
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[dart.dividend] {corp_code}/{bsns_year} 실패: {e}")
            return None

    status = data.get("status")
    if status != "000":
        if status != "013":
            logger.warning(
                f"[dart.dividend] status={status} · {data.get('message', '')}"
            )
        return None

    dps_common: Optional[float] = None
    total_millions: Optional[float] = None  # 백만원 단위 원본
    rows = data.get("list", []) or []

    for row in rows:
        se = (row.get("se") or "").strip()
        stock_knd = (row.get("stock_knd") or "").strip()
        raw_thstrm = row.get("thstrm")

        # (1) 보통주 · 주당 현금배당금 (원)
        if "주당 현금배당금" in se and stock_knd in ("보통주", ""):
            v = _parse_dart_number(raw_thstrm)
            if v is not None and v > 0 and dps_common is None:
                dps_common = v

        # (2) 현금배당금총액 (백만원) · v1.0.5 · 우선주 포함 공시 총액
        # 주식배당(주) 행 혼입 금지 · "현금" 필수
        if "현금배당금총액" in se:
            v = _parse_dart_number(raw_thstrm)
            if v is not None and total_millions is None:
                total_millions = v

    # 백만원 → 원 (v1.0.5 · units_convention · charter 명시)
    dividend_total_krw = total_millions * 1_000_000 if total_millions is not None else None

    return DividendMatter(
        corp_code=corp_code,
        bsns_year=bsns_year,
        dividend_per_share_common=dps_common,
        dividend_total_krw=dividend_total_krw,
        raw_rows=rows,
    )
