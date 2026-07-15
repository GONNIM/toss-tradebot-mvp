"""DART 최대주주 · 자기주식 수집기 · Phase 7-1f.

수집:
    - hyslrSttus (사업보고서 최대주주 현황) → 본인 지분율(major) + 특수관계인 지분율(related)
    - tesstkAcqsDspsSttus (자기주식 현황) → treasury_pct

로직:
    - relate 필드 · "본인" 인 항목만 major_pct 로 집계 (첫 항목 · 대표 지주회사)
    - 나머지 항목 (특수관계인) · related_pct 합산
    - 최신 stock_qota_rt (기말 지분율) 우선

as-of:
    - reference_date · reprt_code 기준 (11011=YYYY-12-31 · 11012=YYYY-06-30 등)
    - release_date · collected_at (실 접수일자는 별도 조회 · v2)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from backend.discovery.data_sources.dart.client import (
    DartMajorShareholderRow,
    DartTreasuryStockRow,
    fetch_major_shareholder_status,
    fetch_treasury_stock,
)
from backend.services.db import get_session
from backend.services.models import MajorShareholder

logger = logging.getLogger(__name__)


# reprt_code → 회계 기말 (dart_financials 와 동일)
_REPORT_QUARTER_END = {
    "11011": (12, 31),   # 사업
    "11012": (6, 30),    # 반기
    "11013": (3, 31),
    "11014": (9, 30),
}


def _reference_date(bsns_year: int, reprt_code: str) -> Optional[str]:
    q = _REPORT_QUARTER_END.get(reprt_code)
    if q is None:
        return None
    m, d = q
    return f"{bsns_year:04d}-{m:02d}-{d:02d}"


_NORMAL_STOCK_KINDS = ("보통주", "보통주식", "의결권있는주식")

# 최대주주(본인) 로 인정되는 relate 표기 · 공백/구두점 제거 후 매칭
# DART 실 예시: "본인" · "본인/자기주식" · "최대주주" · "최대주주 본인"
_MAJOR_RELATE_LABELS_NORMALIZED = {
    "본인",
    "본인/자기주식",
    "최대주주",
    "최대주주본인",   # "최대주주 본인" 공백 제거
}

# DART 응답에 포함된 합계·계 행 (특수관계인 총합 · 이미 개별 행 합산했으므로 중복 방지 위해 skip)
_SUMMARY_NM_TOKENS = ("계",)


def _is_common_stock(stock_knd: str) -> bool:
    """보통주 · 의결권 주식 여부. 지주회사 지분율 판단 표준.

    공백/구두점 tolerant. 실 DART 예시:
      "보통주" · "보통주식" · "의결권있는 주식" · "의결권 있는 주식"
    """
    s = (stock_knd or "").strip().replace(" ", "")
    if not s:
        # DART 응답에서 stock_knd 결측 시 · 보통주 가정 (오래된 보고서 대응)
        return True
    return any(s.startswith(k) for k in _NORMAL_STOCK_KINDS)


def _is_major_relate(relate: str) -> bool:
    """본인/최대주주 판별 · 공백 tolerant."""
    r = (relate or "").strip().replace(" ", "")
    return r in _MAJOR_RELATE_LABELS_NORMALIZED


def _is_summary_row(nm: str, relate: str) -> bool:
    """DART "계" (합계) 행 판별. 중복 합산 방지 위해 skip."""
    nm_clean = (nm or "").strip().replace(" ", "")
    if not nm_clean:
        return True
    if not (relate or "").strip():
        # relate 비어있고 · nm 이 "계"/"합계" · 명백한 요약 행
        return nm_clean in _SUMMARY_NM_TOKENS or nm_clean in ("합계", "총계")
    # relate 있는 정상 행이라도 · nm 이 "계" 이면 요약 (드문 케이스)
    return nm_clean in _SUMMARY_NM_TOKENS


def _aggregate_shareholders(rows: list[DartMajorShareholderRow]) -> tuple[float, float]:
    """rows → (major_pct 최대주주 본인, related_pct 특수관계인 합산).

    지분율 산정 원칙 (실무 표준 · 오너 경영권 판단):
      1. 보통주 지분율 만 취급 (의결권 기준 · 우선주 배제)
      2. "계" (합계) 행 · 요약 행 skip (개별 shareholder 이미 합산 · 중복 방지)
      3. 최대주주 relate 다양성 지원 · "본인" · "최대주주" 등
      4. 같은 (nm, relate) 다수 행 · 최대값 채택 (보통주 종류 여러가지 대응)

    Returns 값 · 소수 (0.35 = 35%).
    """
    major_by_key: dict[tuple[str, str], float] = {}
    related_by_key: dict[tuple[str, str], float] = {}

    for r in rows:
        if _is_summary_row(r.nm, r.relate):
            continue
        if not _is_common_stock(r.stock_knd):
            continue
        rt = r.trmend_posesn_stock_qota_rt or r.bsis_posesn_stock_qota_rt
        if rt is None:
            continue
        pct = float(rt) / 100.0
        key = (r.nm.strip(), r.relate.strip())
        target = major_by_key if _is_major_relate(r.relate) else related_by_key
        target[key] = max(target.get(key, 0.0), pct)

    major = max(major_by_key.values(), default=0.0)
    related = sum(related_by_key.values())
    return major, related


def _aggregate_treasury(rows: list[DartTreasuryStockRow]) -> float:
    """자기주식 · 최대 지분율."""
    best = 0.0
    for r in rows:
        p = r.stock_pnc
        if p is None:
            continue
        best = max(best, float(p) / 100.0)
    return best


async def collect_shareholder_snapshot(
    ticker: str,
    corp_code: str,
    bsns_year: int,
    reprt_code: str = "11011",
    release_date: Optional[datetime] = None,
) -> Optional[int]:
    """단일 회사 · 단일 회계기간 · MajorShareholder 저장.

    Returns 저장 row id · 데이터 없으면 None.
    """
    reference_date = _reference_date(bsns_year, reprt_code)
    if reference_date is None:
        return None
    release_dt = release_date or datetime.now(tz=timezone.utc)

    rows = await fetch_major_shareholder_status(corp_code, bsns_year, reprt_code)
    if not rows:
        return None
    major_pct, related_pct = _aggregate_shareholders(rows)

    # 자기주식 (선택 · 실패해도 major/related 는 저장)
    treasury_rows = await fetch_treasury_stock(corp_code, bsns_year, reprt_code)
    treasury_pct = _aggregate_treasury(treasury_rows) if treasury_rows else None

    raw_json = json.dumps({
        "shareholders": [
            {
                "nm": r.nm, "relate": r.relate,
                "trmend_pct": r.trmend_posesn_stock_qota_rt,
            }
            for r in rows
        ][:20],
        "treasury": [
            {"acqs_mth1": r.acqs_mth1, "pct": r.stock_pnc}
            for r in treasury_rows
        ][:10] if treasury_rows else [],
    }, ensure_ascii=False)

    async with get_session() as session:
        stmt = select(MajorShareholder).where(
            MajorShareholder.ticker == ticker,
            MajorShareholder.reference_date == reference_date,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        # 정정 재보고 · 최신 release_date 우선 (tz naive 비교)
        if existing:
            e_dt = existing.release_date
            n_dt = release_dt.replace(tzinfo=None) if release_dt.tzinfo else release_dt
            if e_dt.tzinfo is not None:
                e_dt = e_dt.replace(tzinfo=None)
            if e_dt >= n_dt:
                return existing.id
            row = existing
        else:
            row = MajorShareholder(
                ticker=ticker, reference_date=reference_date, release_date=release_dt,
                major_pct=major_pct, related_pct=related_pct,
            )
            session.add(row)
        row.release_date = release_dt
        row.major_pct = major_pct
        row.related_pct = related_pct
        row.treasury_pct = treasury_pct
        row.raw_json = raw_json
        await session.flush()
        return row.id


async def collect_batch(
    targets: list[tuple[str, str]],
    bsns_year: int,
    reprt_code: str = "11011",
) -> dict[str, Any]:
    """batch · targets=[(ticker, corp_code), ...]"""
    stats = {"total": len(targets), "collected": 0, "empty": 0, "failed": 0}
    for ticker, corp_code in targets:
        try:
            row_id = await collect_shareholder_snapshot(ticker, corp_code, bsns_year, reprt_code)
            if row_id is not None:
                stats["collected"] += 1
            else:
                stats["empty"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dart_shareholders] %s 실패 · %s", ticker, exc)
            stats["failed"] += 1
    logger.info("[dart_shareholders.batch] year=%d %s", bsns_year, stats)
    return stats
