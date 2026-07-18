"""DART 재무제표 수집기 · Phase 7-1b.

수집:
  - 재무상태표 (BS): 현금및현금성자산 · 단기금융상품 · 총차입금 · 자본총계 · 이익잉여금
  - 손익계산서 (IS): 영업이익 · 당기순이익 · 이자수익
  - 감사의견 (accnutAdtorNmNdAdtOpinion)

as-of 규약 (§7-1):
  - reference_date · 회계 기말 (bsns_year + 분기 종결)
  - release_date · 공시 실제 접수일 (rcept_dt · v1.6 · fetch_report_receipt_date 조회)
    · 조회 실패 시 fallback = datetime.now() (기존 동작 유지 · 데이터 부재 방어)
  - 정정 재보고 시 unique 제약으로 최신 release_date 우선

fs_div (연결 vs 별도):
  - CFS 우선 · 없으면 OFS fallback

계정과목 매핑: K-IFRS 표준 account_id + 한글명 fallback.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from backend.discovery.data_sources.dart.client import (
    DartFinancialItem,
    fetch_audit_opinion,
    fetch_financial_statement,
    fetch_report_receipt_date,
)
from backend.services.db import get_session
from backend.services.models import FinancialSnapshot

logger = logging.getLogger(__name__)


# ─── 계정과목 매핑 ──────────────────────────────────
# account_id (K-IFRS 표준) · 없으면 account_nm 로 fallback
_MAPPING_ID: dict[str, str] = {
    # 재무상태표
    "ifrs-full_CashAndCashEquivalents": "cash_and_equivalents",
    "ifrs-full_CurrentInvestments": "short_term_investments",       # 유동금융자산 근사
    "ifrs-full_Equity": "total_equity",
    "ifrs-full_RetainedEarnings": "retained_earnings",
    "ifrs-full_Assets": "total_assets",
    "ifrs-full_CurrentAssets": "current_assets",
    "ifrs-full_CurrentLiabilities": "current_liabilities",
    # v1.30 · 3차 리뷰 P2 · 계약부채 (수주산업 조정 net_cash)
    "ifrs-full_ContractLiabilities": "contract_liabilities",
    "ifrs-full_CurrentContractLiabilities": "contract_liabilities",
    # 손익계산서
    "ifrs-full_Revenue": "revenue",
    "ifrs-full_GrossProfit": "gross_profit",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_FinanceIncome": "interest_income",   # 금융수익 근사
    # 현금흐름표
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "cash_flow_from_operations",
}

_MAPPING_NM_KEYWORDS: dict[str, tuple[str, ...]] = {
    # account_nm 로 fallback (K-IFRS 자유표기 대응)
    "cash_and_equivalents": ("현금및현금성자산",),
    "short_term_investments": ("단기금융상품", "당기손익-공정가치 측정 금융자산"),
    "total_equity": ("자본총계",),
    "retained_earnings": ("이익잉여금", "결손금"),
    "total_assets": ("자산총계",),
    "current_assets": ("유동자산",),
    "current_liabilities": ("유동부채",),
    # v1.30 · 3차 리뷰 P2 · 계약부채·선수금 (수주산업 조정)
    #   K-IFRS 1115 이후 "계약부채" 표기가 표준 · 이전 "선수금" 도 함께 매칭.
    "contract_liabilities": ("계약부채", "선수금"),
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "gross_profit": ("매출총이익",),
    "operating_income": ("영업이익",),          # 영업이익(손실) 포함
    "net_income": ("당기순이익",),               # 당기순이익(손실) 포함
    "interest_income": ("이자수익",),
    "cash_flow_from_operations": ("영업활동현금흐름", "영업활동으로 인한 현금흐름"),
    # 총차입금 별도 로직 (여러 계정 합산)
}

_DEBT_KEYWORDS = (
    # v1.31 · 3차 리뷰 P2-4b hotfix (2026-07-18)
    #   서희건설 · 차입금 표기 "차입금등(유동)", "차입금등(비유동)" → substring 미매치.
    #   기존 "단기차입금"·"장기차입금"만으론 놓침 → 조건 2 부풀림 (40.6% 오판 · 실제 16%).
    #   "차입금등" · "리스부채" 를 substring 로 대체·확장.
    "단기차입금",
    "유동성장기부채",
    "유동성장기차입금",
    "장기차입금",
    "차입금등",         # NEW · "차입금등(유동)", "차입금등(비유동)" · 서희 등 중소 건설사
    "사채",
    "리스부채",         # substring · "유동 리스부채", "비유동 리스부채", "유동성리스부채" 커버
)


@dataclass
class ParsedFinancials:
    cash_and_equivalents: Optional[float] = None
    short_term_investments: Optional[float] = None
    total_debt: Optional[float] = None
    total_equity: Optional[float] = None
    retained_earnings: Optional[float] = None
    contract_liabilities: Optional[float] = None    # v1.30 · P2 · 수주산업 조정
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    interest_income: Optional[float] = None
    cash_flow_from_operations: Optional[float] = None
    matched_items: dict[str, str] = field(default_factory=dict)   # field → account_nm 매칭 로그


def parse_financial_items(items: list[DartFinancialItem]) -> ParsedFinancials:
    """DART 응답 → 스키마 필드 매핑.

    - 재무상태표 (BS) 우선 · 손익계산서 (IS) 값 분리
    - account_id 매칭 우선 · 실패 시 account_nm keyword substring
    - total_debt 는 _DEBT_KEYWORDS 합산 (여러 계정)
    """
    result = ParsedFinancials()
    debt_sum = 0.0
    debt_found = False

    for item in items:
        if item.thstrm_amount is None:
            continue
        # 1. account_id 매칭
        field_name = _MAPPING_ID.get(item.account_id)
        # 2. account_nm keyword fallback
        if field_name is None:
            for f, keywords in _MAPPING_NM_KEYWORDS.items():
                if any(k in item.account_nm for k in keywords):
                    field_name = f
                    break

        if field_name is not None:
            # BS 항목은 BS 만 · IS 항목은 IS 만 · CF 는 CF 만 (섞임 방지)
            bs_fields = {
                "cash_and_equivalents", "short_term_investments",
                "total_equity", "retained_earnings",
                "total_assets", "current_assets", "current_liabilities",
                "contract_liabilities",   # v1.30 · P2
            }
            is_fields = {
                "operating_income", "net_income", "interest_income",
                "revenue", "gross_profit",
            }
            cf_fields = {"cash_flow_from_operations"}
            if field_name in bs_fields and item.sj_div != "BS":
                continue
            if field_name in is_fields and item.sj_div not in ("IS", "CIS"):
                continue
            if field_name in cf_fields and item.sj_div != "CF":
                continue
            # 첫 매칭만 채택 (총계 vs 세부 혼동 방지)
            if getattr(result, field_name) is None:
                setattr(result, field_name, item.thstrm_amount)
                result.matched_items[field_name] = item.account_nm

        # 3. 총차입금 · 여러 계정 합산 (BS 만)
        if item.sj_div == "BS":
            for kw in _DEBT_KEYWORDS:
                if kw in item.account_nm and item.thstrm_amount > 0:
                    debt_sum += item.thstrm_amount
                    debt_found = True
                    break

    if debt_found:
        result.total_debt = debt_sum
        result.matched_items["total_debt"] = f"sum:{','.join(_DEBT_KEYWORDS[:2])}..."
    return result


# ─── 수집 오케스트레이션 ─────────────────────────
_REPORT_QUARTER_END = {
    "11011": (12, 31),   # 사업보고서 · 12월 결산
    "11012": (6, 30),    # 반기
    "11013": (3, 31),    # 1분기
    "11014": (9, 30),    # 3분기
}


def _reference_date(bsns_year: int, reprt_code: str) -> Optional[str]:
    q = _REPORT_QUARTER_END.get(reprt_code)
    if q is None:
        return None
    m, d = q
    return f"{bsns_year:04d}-{m:02d}-{d:02d}"


async def collect_financial_snapshot(
    ticker: str,
    corp_code: str,
    bsns_year: int,
    reprt_code: str,
    release_date: Optional[datetime] = None,
    fs_div_preference: tuple[str, ...] = ("CFS", "OFS"),
) -> Optional[int]:
    """단일 회사 · 단일 회계기간 재무 스냅샷 수집·저장.

    Returns: 저장된 row id · 실패 시 None.
    """
    parsed: Optional[ParsedFinancials] = None
    raw_items: list[DartFinancialItem] = []
    used_fs_div = ""
    for fs_div in fs_div_preference:
        items = await fetch_financial_statement(corp_code, bsns_year, reprt_code, fs_div=fs_div)
        if not items:
            continue
        p = parse_financial_items(items)
        # 최소한 자본총계 or 순이익 잡히면 채택
        if p.total_equity or p.net_income or p.operating_income:
            parsed = p
            raw_items = items
            used_fs_div = fs_div
            break

    if parsed is None:
        logger.info("[dart_fin] %s/%s/%s · 재무 데이터 없음", ticker, bsns_year, reprt_code)
        return None

    # 감사의견 · 사업보고서 (11011) 만 · 반기/분기는 미비율
    audit_opinion: Optional[str] = None
    if reprt_code == "11011":
        op = await fetch_audit_opinion(corp_code, bsns_year, reprt_code)
        if op:
            audit_opinion = op.adt_reprt_opinion

    reference_date = _reference_date(bsns_year, reprt_code)
    if reference_date is None:
        return None
    # v1.6 · release_date 실제 접수일 (rcept_dt) 조회 · Phase 0 as-of 규약 정합
    if release_date is not None:
        release_dt = release_date
    else:
        rcept_d = await fetch_report_receipt_date(corp_code, bsns_year, reprt_code)
        if rcept_d is not None:
            release_dt = datetime(rcept_d.year, rcept_d.month, rcept_d.day, tzinfo=timezone.utc)
        else:
            # fallback · list.json 조회 실패 시 collected_at (기존 동작)
            release_dt = datetime.now(tz=timezone.utc)
            logger.info(
                "[dart_fin] %s/%s/%s · rcept_dt 조회 실패 · collected_at fallback",
                ticker, bsns_year, reprt_code,
            )

    # v1.31 · P2-4b hotfix · 진단용 부채/차입/계약 관련 원 계정 sample 보관.
    #   기존은 matched_items 만 저장 · 서희 계약부채 파싱 실패 원인 규명 불가능했음.
    _DIAG_KEYWORDS = ("부채", "차입", "사채", "리스", "선수", "계약")
    diag_items = [
        {
            "sj": it.sj_div,
            "id": (it.account_id or "")[:80],
            "nm": (it.account_nm or "")[:60],
            "amt": it.thstrm_amount,
        }
        for it in raw_items
        if it.sj_div == "BS"
        and it.account_nm
        and any(k in it.account_nm for k in _DIAG_KEYWORDS)
    ][:60]   # 상한 60개 (용량 방어)

    raw_json = json.dumps({
        "fs_div_used": used_fs_div,
        "matched_items": parsed.matched_items,
        "item_count": len(raw_items),
        "diag_bs_liab_items": diag_items,   # v1.31 · 진단 sample
    }, ensure_ascii=False)

    async with get_session() as session:
        # 정정 재보고 처리: unique(ticker, reference_date, report_code)
        stmt = select(FinancialSnapshot).where(
            FinancialSnapshot.ticker == ticker,
            FinancialSnapshot.reference_date == reference_date,
            FinancialSnapshot.report_code == reprt_code,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            # 새 release_date 가 더 최신이면 갱신 · 아니면 skip
            # SQLite 는 tzinfo 유실 · naive 비교로 통일
            existing_dt = existing.release_date
            new_dt = release_dt.replace(tzinfo=None) if release_dt.tzinfo else release_dt
            if existing_dt.tzinfo is not None:
                existing_dt = existing_dt.replace(tzinfo=None)
            if existing_dt >= new_dt:
                return existing.id
            row = existing
        else:
            row = FinancialSnapshot(
                ticker=ticker, corp_code=corp_code,
                reference_date=reference_date, report_code=reprt_code,
                release_date=release_dt,
            )
            session.add(row)

        # 갱신
        row.corp_code = corp_code
        row.release_date = release_dt
        row.cash_and_equivalents = parsed.cash_and_equivalents
        row.short_term_investments = parsed.short_term_investments
        row.total_debt = parsed.total_debt
        row.total_equity = parsed.total_equity
        row.retained_earnings = parsed.retained_earnings
        row.total_assets = parsed.total_assets
        row.current_assets = parsed.current_assets
        row.current_liabilities = parsed.current_liabilities
        row.contract_liabilities = parsed.contract_liabilities   # v1.30 · P2
        row.revenue = parsed.revenue
        row.gross_profit = parsed.gross_profit
        row.operating_income = parsed.operating_income
        row.net_income = parsed.net_income
        row.interest_income = parsed.interest_income
        row.cash_flow_from_operations = parsed.cash_flow_from_operations
        row.audit_opinion = audit_opinion
        row.raw_json = raw_json
        await session.flush()
        row_id = row.id
    return row_id


async def collect_batch(
    targets: list[tuple[str, str]],    # [(ticker, corp_code), ...]
    bsns_year: int,
    reprt_code: str,
) -> dict[str, Any]:
    """batch · 유니버스 순회 수집.

    Rate limit 배려: 순차 실행 (concurrency 1) · sleep 없음 (DART 분당 100 · 여유).
    """
    stats = {"total": len(targets), "collected": 0, "empty": 0, "failed": 0}
    for ticker, corp_code in targets:
        try:
            row_id = await collect_financial_snapshot(ticker, corp_code, bsns_year, reprt_code)
            if row_id is not None:
                stats["collected"] += 1
            else:
                stats["empty"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dart_fin] %s 수집 실패 · %s", ticker, exc)
            stats["failed"] += 1
    logger.info("[dart_fin.batch] year=%d report=%s · %s", bsns_year, reprt_code, stats)
    return stats
