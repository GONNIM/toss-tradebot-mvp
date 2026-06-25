"""산업통상부(motir) 월간 수출입동향 PDF 파서.

본 모듈은 docs/plans/sector-leaders/01-mvp-design.md 의 B-2a/B-2b 산출물.

발견된 양식 (2025-05 ~ 2026-05 13장 PDF 검증):
- **메인 품목 표**: 모든 PDF에 동일 (47r × 15c). 15품목 (선박~이차전지).
- **5대 유망 소비재 별표**: 모든 PDF에 동일 (12r × 15c).
  농수산식품·화장품·패션의류·생활유아용품·의약품 (각 2행 = 값/증감률, 비중 없음).
- **9+1 지역 표**: 모든 PDF에 동일 (22r × 15c).
- **20품목 확장**: 2026-05 PDF 한 장에만 존재 (17r × 15c 별도 표) — 본 파서는 미사용.

페이지 위치는 PDF 별로 다름 (p15~p32) → 양식 검증으로 자동 탐지.

MVP 1차 분석 대상 17품목 = ENRICHED_17_ITEMS.

지원 추출:
- parse_item_timeseries: 15 메인 + 별표 농수산식품·화장품 = 17품목 × 13개월
- parse_region_timeseries: 10대 지역 × 13개월
- parse_commodity_prices: 원자재 가격 (제한적, 향후 보강)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# 정규식 / 상수
# ─────────────────────────────────────────────────────────────────

_MINUS_RE = re.compile(r"[△▲▵∆−]")  # 모든 음수 기호 변형
_PAREN_NUM_RE = re.compile(r"^\(([^)]+)\)$")


# 15 메인 품목 (참고 표 ② 순서 — 모든 발표월 PDF 일관)
ITEM_ORDER_15 = (
    "선박", "무선통신기기", "일반기계", "석유화학", "철강제품",
    "반도체", "자동차", "석유제품", "디스플레이", "섬유",
    "가전", "자동차부품", "컴퓨터", "바이오헬스", "이차전지",
)


# 5대 유망 소비재 별표 (모든 PDF, 12r × 15c, 각 2행)
CONSUMER_5_ITEMS = (
    "농수산식품", "화장품", "패션의류", "생활유아용품", "의약품",
)


# MVP 1차 분석 대상 17품목 = 15 메인 + 별표 농수산식품·화장품
ENRICHED_17_ITEMS = ITEM_ORDER_15 + ("농수산식품", "화장품")


# 2026-05 PDF 한 장에만 있는 20품목 확장 표 (17r × 15c).
# 단월 데이터라 본 MVP에선 미사용. 참고용 상수.
ITEM_ORDER_20_EXTENSION_2026_05_ONLY = (
    "농수산식품", "화장품", "전기기기", "생활용품", "비철금속",
)


# 9대 + 베트남 = 10개 지역 (모든 PDF 일관)
REGION_ORDER_10 = (
    "중국", "미국", "일본", "아세안", "EU(27)",
    "중동", "중남미", "CIS", "베트남", "인도",
)


# 후방호환: 2026-05 PDF에서만 의미가 있는 ITEM_ORDER_20 alias (deprecated).
# 본 MVP 분석은 ENRICHED_17_ITEMS 또는 ITEM_ORDER_15 사용.
ITEM_ORDER_20 = ITEM_ORDER_15 + ITEM_ORDER_20_EXTENSION_2026_05_ONLY


# ─────────────────────────────────────────────────────────────────
# 데이터 모델
# ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExportItemRecord:
    """품목 × 월별 수출 1행."""

    item: str
    month: date
    value_musd: float
    yoy_pct: Optional[float]    # PDF 글리프/발행 결함 시 None 가능 (B-2b cross-validation 보강)
    share_pct: Optional[float]  # 별표 추출 품목엔 None


@dataclass(frozen=True)
class ExportRegionRecord:
    """지역 × 월별 수출 1행."""

    region: str
    month: date
    value_musd: float
    yoy_pct: Optional[float]


@dataclass(frozen=True)
class CommodityRecord:
    """원자재 가격 1행 (개발 진행 중 — 향후 보강)."""

    name: str
    period_label: str
    value: float
    unit: str


# ─────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────


def _norm_text(s: Optional[str]) -> str:
    if s is None:
        return ""
    return s.replace("\n", "").replace(" ", "").strip()


def _parse_number(s: Optional[str]) -> Optional[float]:
    """텍스트 셀 → float. 음수기호·괄호·콤마 처리. None / 공백 / 'NA' → None."""
    if s is None:
        return None
    raw = s.strip()
    if not raw or raw in ("-", "--", "NA", "N/A"):
        return None
    m = _PAREN_NUM_RE.match(raw)
    if m:
        raw = m.group(1)
    raw = _MINUS_RE.sub("-", raw)
    raw = raw.replace(",", "").replace(" ", "")
    try:
        return float(raw)
    except ValueError:
        return None


def report_to_months(report_month: date) -> list[date]:
    """발표월 → 데이터 시계열 13개월 (T-12 .. T).

    예) 2026-06-01 발표 → [2025-05, ..., 2026-05]
    """
    if report_month.month == 1:
        last = date(report_month.year - 1, 12, 1)
    else:
        last = date(report_month.year, report_month.month - 1, 1)

    months: list[date] = []
    for offset in range(12, -1, -1):
        y, m = last.year, last.month - offset
        while m <= 0:
            m += 12
            y -= 1
        months.append(date(y, m, 1))
    return months


# ─────────────────────────────────────────────────────────────────
# 표 자동 탐지
# ─────────────────────────────────────────────────────────────────


def _find_main_item_table(pdf: pdfplumber.PDF) -> Optional[tuple[int, list[list[Optional[str]]]]]:
    """47r × 15c 메인 품목 표 자동 탐지 (페이지 위치 무관).

    검증: 헤더 row[0][0] = '품목명', 첫 데이터 row[2][0] 에 '선박' 포함.
    """
    for page_idx, page in enumerate(pdf.pages):
        for t in page.extract_tables():
            if not t or len(t) != 47 or not t[0] or len(t[0]) < 14:
                continue
            if t[0][0] != "품목명":
                continue
            if len(t) > 2 and t[2] and t[2][0] and "선박" in t[2][0]:
                return (page_idx, t)
    return None


def _find_consumer_table(pdf: pdfplumber.PDF) -> Optional[tuple[int, list[list[Optional[str]]]]]:
    """5대 유망 소비재 별표 (12r × 15c, '농수산식품' 시작)."""
    for page_idx, page in enumerate(pdf.pages):
        for t in page.extract_tables():
            if not t or len(t) != 12 or not t[0] or len(t[0]) < 14:
                continue
            if t[0][0] != "품목명":
                continue
            if len(t) > 2 and t[2] and t[2][0] and "농수산" in t[2][0]:
                return (page_idx, t)
    return None


def _find_region_table(pdf: pdfplumber.PDF) -> Optional[tuple[int, list[list[Optional[str]]]]]:
    """10개 지역 표 (22r × 15c, '지역' 헤더)."""
    for page_idx, page in enumerate(pdf.pages):
        for t in page.extract_tables():
            if not t or len(t) != 22 or not t[0] or len(t[0]) < 14:
                continue
            if t[0][0] != "지역":
                continue
            return (page_idx, t)
    return None


# ─────────────────────────────────────────────────────────────────
# 블록 파싱 (3행/2행 묶음 공통)
# ─────────────────────────────────────────────────────────────────


def _parse_block(
    table: list[list[Optional[str]]],
    months: list[date],
    expected_order: tuple[str, ...],
    *,
    has_share: bool,
) -> list[ExportItemRecord]:
    """헤더 2행 + 각 품목당 (3 or 2) 행 묶음 → ExportItemRecord 리스트.

    has_share=True: 3행 묶음 (값/증감률/비중) — 메인 15품목 표
    has_share=False: 2행 묶음 (값/증감률) — 별표 5대 유망 소비재, 지역 표
    """
    block_size = 3 if has_share else 2
    data_rows = table[2:]  # 헤더 2행 제외
    out: list[ExportItemRecord] = []

    idx = 0
    i = 0
    while i + (block_size - 1) < len(data_rows) and idx < len(expected_order):
        value_row = data_rows[i]
        if not value_row or not value_row[0]:
            i += 1
            continue
        item_name = _norm_text(value_row[0])
        canonical = expected_order[idx]
        if _norm_text(canonical) != item_name:
            logger.warning(
                f"[motir_export] item mismatch idx={idx}: "
                f"expected={canonical!r} got={item_name!r} — using canonical"
            )

        yoy_row = data_rows[i + 1] if i + 1 < len(data_rows) else []
        share_row = data_rows[i + 2] if has_share and i + 2 < len(data_rows) else None

        for col_idx, month in enumerate(months, start=2):
            if col_idx >= len(value_row):
                break
            v = _parse_number(value_row[col_idx])
            if v is None:
                continue
            y = _parse_number(yoy_row[col_idx]) if col_idx < len(yoy_row) else None
            s = (
                _parse_number(share_row[col_idx])
                if (share_row is not None and col_idx < len(share_row))
                else None
            )
            out.append(
                ExportItemRecord(
                    item=canonical,
                    month=month,
                    value_musd=v,
                    yoy_pct=y,
                    share_pct=s,
                )
            )

        i += block_size
        idx += 1
    return out


# ─────────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────────


def parse_item_timeseries(
    pdf_path: Path | str,
    report_month: date,
    *,
    include_consumer_supplement: bool = True,
) -> list[ExportItemRecord]:
    """15 메인 품목 × 13개월 + (옵션) 별표 농수산식품·화장품 보강.

    Args:
        pdf_path: motir_export_YYYY-MM.pdf 경로
        report_month: 발표월 (예: 2026-06-01)
        include_consumer_supplement: True 면 별표에서 농수산식품·화장품 추출하여 추가
            → 결과는 ENRICHED_17_ITEMS 기준 17품목.

    Returns:
        최대 17 × 13 = 221 행. 별표 미발견 시 15 × 13 = 195 행.

    Raises:
        FileNotFoundError: PDF 부재
        ValueError: 메인 표 미발견
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"motir PDF not found: {pdf_path}")

    months = report_to_months(report_month)
    records: list[ExportItemRecord] = []

    with pdfplumber.open(pdf_path) as pdf:
        # 메인 15품목
        main = _find_main_item_table(pdf)
        if main is None:
            raise ValueError(f"메인 품목 표 미발견 (47r×15c): {pdf_path}")
        _, main_table = main
        records.extend(_parse_block(main_table, months, ITEM_ORDER_15, has_share=True))

        # 별표 보강: 농수산식품·화장품만 픽업
        if include_consumer_supplement:
            cons = _find_consumer_table(pdf)
            if cons is None:
                logger.warning(f"[motir_export] consumer 별표 미발견: {pdf_path}")
            else:
                _, cons_table = cons
                cons_records = _parse_block(
                    cons_table, months, CONSUMER_5_ITEMS, has_share=False
                )
                # MVP 1차에선 농수산식품·화장품만 보강 (다른 3개는 사용 안 함)
                for r in cons_records:
                    if r.item in ("농수산식품", "화장품"):
                        records.append(r)

    logger.info(
        f"[motir_export] parse_item_timeseries({pdf_path.name}): {len(records)} rows"
    )
    return records


def parse_region_timeseries(
    pdf_path: Path | str,
    report_month: date,
) -> list[ExportRegionRecord]:
    """10대 지역 × 13개월 수출 시계열."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"motir PDF not found: {pdf_path}")

    months = report_to_months(report_month)

    with pdfplumber.open(pdf_path) as pdf:
        region = _find_region_table(pdf)
        if region is None:
            raise ValueError(f"지역 표 미발견 (22r×15c): {pdf_path}")
        _, table = region
        # 지역 표는 첫 컬럼이 모두 None (pdfplumber 한계) → REGION_ORDER_10 으로 매핑
        # has_share=False (값/증감률만)
        # 헤더 2행 제외 후 20행 = 10지역 × 2행
        data_rows = table[2:]
        records: list[ExportRegionRecord] = []
        idx = 0
        i = 0
        while i + 1 < len(data_rows) and idx < len(REGION_ORDER_10):
            value_row = data_rows[i]
            yoy_row = data_rows[i + 1]
            region_name = REGION_ORDER_10[idx]
            for col_idx, month in enumerate(months, start=2):
                if col_idx >= len(value_row):
                    break
                v = _parse_number(value_row[col_idx])
                if v is None:
                    continue
                y = _parse_number(yoy_row[col_idx]) if col_idx < len(yoy_row) else None
                records.append(
                    ExportRegionRecord(
                        region=region_name, month=month, value_musd=v, yoy_pct=y
                    )
                )
            i += 2
            idx += 1

    logger.info(
        f"[motir_export] parse_region_timeseries({Path(pdf_path).name}): {len(records)} rows"
    )
    return records


def parse_commodity_prices(
    pdf_path: Path | str,
) -> list[CommodityRecord]:
    """원자재 가격 — PoC 단계, 라벨 좌표 매핑 필요 (다음 sub-Phase 보강)."""
    # 본격 구현은 추후 — 페이지 25 첫 컬럼 None 으로 잡히는 한계 확인됨
    logger.info(f"[motir_export] parse_commodity_prices: stub, 0 rows")
    return []
