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


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def parse_principles_financials(items: Iterable[DartFinancialItem]) -> PrinciplesFinancials:
    """DART 응답 → PrinciplesFinancials.

    account_id 매칭 우선 · 실패 시 account_nm keyword substring.
    net_income_owner 미매치 시 net_income 로 fallback (호출자 결정).
    """
    out = PrinciplesFinancials()
    for item in items:
        # 1. account_id 매칭 (재무제표만 · 현금흐름표는 sj_div=CF)
        field_name = _MAPPING_ID.get(item.account_id)
        if field_name is None:
            # 2. account_nm 매칭
            nm = _norm(item.account_nm)
            for f, kws in _MAPPING_NM_KEYWORDS.items():
                if any(kw in nm for kw in kws):
                    field_name = f
                    break
        if field_name is None:
            continue
        if getattr(out, field_name) is not None:
            continue  # 이미 매칭 · 첫 매칭 유지
        val = item.thstrm_amount
        if val is None:
            continue
        setattr(out, field_name, val)
        out.matched[field_name] = item.account_nm
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


async def fetch_dividend_matter(
    corp_code: str,
    bsns_year: int,
) -> Optional[DividendMatter]:
    """DART 배당에 관한 사항 (alotMatter.json · 사업보고서만 · reprt_code=11011).

    Docs: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019005
    응답 필드 se (구분) 중 "주당 현금배당금(원)" · stock_knd = "보통주" 값 사용.
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
    for row in data.get("list", []):
        se = (row.get("se") or "").strip()
        stock_knd = (row.get("stock_knd") or "").strip()
        # 보통주 주당 현금배당금
        if "주당 현금배당금" in se and stock_knd in ("보통주", ""):
            raw = row.get("thstrm") or "0"
            try:
                v = float(str(raw).replace(",", "").strip() or 0)
                if v > 0:
                    dps_common = v
                    break
            except ValueError:
                continue

    return DividendMatter(
        corp_code=corp_code,
        bsns_year=bsns_year,
        dividend_per_share_common=dps_common,
    )
