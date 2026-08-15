"""산업통상부 월간 수출입동향 PDF 파서 단위 테스트.

기준 PDF: backend/data/research/motir_exports/motir_export_2026-05.pdf
(2026-06-01 발표, '25.5월 ~ '26.5월 13개월 시계열)

PDF 부재 시 skip — CI 환경/타 개발기에서 안전.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.discovery.data_sources.motir_export import (
    ENRICHED_17_ITEMS,
    ITEM_ORDER_15,
    REGION_ORDER_10,
    parse_item_timeseries,
    parse_region_timeseries,
    report_to_months,
)
from backend.discovery.data_sources.motir_export.parser import _parse_block
from backend.discovery.data_sources.motir_export.downloader import (
    data_month,
    get_pdf_path,
)


PDF_PATH = (
    Path(__file__).resolve().parents[1]
    / "data" / "research" / "motir_exports" / "motir_export_2026-05.pdf"
)
REPORT_MONTH = date(2026, 6, 1)


# ─────────────────────────────────────────────────────────────────
# downloader 경로 규약
# ─────────────────────────────────────────────────────────────────


def test_data_month_normal():
    assert data_month(date(2026, 6, 1)) == date(2026, 5, 1)


def test_data_month_january_rolls_back():
    assert data_month(date(2026, 1, 1)) == date(2025, 12, 1)


def test_get_pdf_path_naming():
    p = get_pdf_path(date(2026, 6, 1))
    assert p.name == "motir_export_2026-05.pdf"


# ─────────────────────────────────────────────────────────────────
# report_to_months 헬퍼
# ─────────────────────────────────────────────────────────────────


def test_report_to_months_13_months():
    months = report_to_months(REPORT_MONTH)
    assert len(months) == 13
    assert months[0] == date(2025, 5, 1)
    assert months[-1] == date(2026, 5, 1)


def test_report_to_months_year_rollover():
    months = report_to_months(date(2026, 2, 1))  # 1월 보고서
    assert months[-1] == date(2026, 1, 1)
    assert months[0] == date(2025, 1, 1)


# ─────────────────────────────────────────────────────────────────
# 통합: 실제 PDF 파싱
# ─────────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_item_timeseries_completeness():
    records = parse_item_timeseries(PDF_PATH, REPORT_MONTH)
    # 17 품목 × 13 월 = 221 행 (15 메인 + 별표 농수산·화장품)
    assert len(records) == 17 * 13
    assert {r.item for r in records} == set(ENRICHED_17_ITEMS)


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_consumer_supplement_items():
    """별표 보강: 농수산식품·화장품 13개월 시계열 확인."""
    records = parse_item_timeseries(PDF_PATH, REPORT_MONTH)
    by_item = {r.item: [r for r in records if r.item == r.item] for r in records}
    farm = [r for r in records if r.item == "농수산식품"]
    cosmetic = [r for r in records if r.item == "화장품"]
    assert len(farm) == 13
    assert len(cosmetic) == 13


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_main_table_auto_detect_on_short_pdf():
    """2025-06 PDF (23p 단축형, 메인 표가 p15) — 페이지 자동 탐지 검증."""
    short_pdf = (
        Path(__file__).resolve().parents[1]
        / "data" / "research" / "motir_exports" / "motir_export_2025-06.pdf"
    )
    if not short_pdf.exists():
        pytest.skip(f"PDF not present: {short_pdf}")
    records = parse_item_timeseries(short_pdf, date(2025, 7, 1))
    assert len(records) == 17 * 13
    assert {r.item for r in records} == set(ENRICHED_17_ITEMS)


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_item_known_values():
    records = parse_item_timeseries(PDF_PATH, REPORT_MONTH)
    by_key = {(r.item, r.month): r for r in records}

    # 반도체 26.5월 = 37,157 백만$, +169.4%
    r = by_key[("반도체", date(2026, 5, 1))]
    assert r.value_musd == 37157.0
    assert r.yoy_pct is not None and abs(r.yoy_pct - 169.4) < 0.05

    # 자동차 26.5월 = △5.9
    r = by_key[("자동차", date(2026, 5, 1))]
    assert r.yoy_pct is not None and abs(r.yoy_pct - (-5.9)) < 0.05

    # 컴퓨터(SSD) 26.5월 = +290.7%
    r = by_key[("컴퓨터", date(2026, 5, 1))]
    assert r.yoy_pct is not None and abs(r.yoy_pct - 290.7) < 0.05


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_region_timeseries_completeness():
    records = parse_region_timeseries(PDF_PATH, REPORT_MONTH)
    assert len(records) == 10 * 13
    assert {r.region for r in records} == set(REGION_ORDER_10)


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_region_known_values():
    records = parse_region_timeseries(PDF_PATH, REPORT_MONTH)
    by_key = {(r.region, r.month): r for r in records}

    r = by_key[("중국", date(2026, 5, 1))]
    assert r.value_musd == 18895.0
    assert r.yoy_pct is not None and abs(r.yoy_pct - 80.9) < 0.05

    r = by_key[("미국", date(2026, 5, 1))]
    assert r.value_musd == 15972.0
    assert r.yoy_pct is not None and abs(r.yoy_pct - 59.1) < 0.05

    # 중동 26.5월 = △7.7
    r = by_key[("중동", date(2026, 5, 1))]
    assert r.yoy_pct is not None and abs(r.yoy_pct - (-7.7)) < 0.05


@pytest.mark.skipif(
    not PDF_PATH.exists(),
    reason=f"reference PDF not present: {PDF_PATH}",
)
def test_item_known_glyph_defect_documented():
    """문서화된 한계 — PDF 글리프 결함으로 반도체 25.5월 YoY 부호 누락.

    실제 △21.2 → 추출 21.2 (양수). B-2b cross-validation 보강 예정.
    본 테스트는 해당 결함이 알려진 한계임을 코드에서 명시.
    """
    records = parse_item_timeseries(PDF_PATH, REPORT_MONTH)
    by_key = {(r.item, r.month): r for r in records}
    r = by_key[("반도체", date(2025, 5, 1))]
    # 현재 추출값 = 21.2 (부호 누락). B-2b cross-validation 후 -21.2 로 정정 예정.
    # 본 assertion 은 현 상태를 명시 — 정정 후 본 테스트도 갱신.
    assert r.yoy_pct is not None and abs(r.yoy_pct - 21.2) < 0.05


# ─────────────────────────────────────────────────────────────────
# 순서 재배치 안전성 (2026-08-15 · KDI 발행 형식 변경 대응)
# ─────────────────────────────────────────────────────────────────


def _make_synthetic_table(order: tuple[str, ...]) -> list[list[str]]:
    """15품목 임의 순서로 47행 표 합성 · 헤더 2행 + 15품목×3행."""
    header1 = ["품목명", "구분", "2025.05", "2025.06", "2025.07", "2025.08", "2025.09",
               "2025.10", "2025.11", "2025.12", "2026.01", "2026.02", "2026.03",
               "2026.04", "2026.05"]
    header2 = ["", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
    rows: list[list[str]] = [header1, header2]
    # 각 품목마다 (값·YoY·share) 3행 · 값=인덱스, YoY=인덱스, share=인덱스
    for i, name in enumerate(order, start=1):
        month_vals = [str(1000 * i + k) for k in range(13)]
        yoy_vals = [str(i + k * 0.1) for k in range(13)]
        share_vals = [f"{i * 0.1 + k * 0.01:.2f}" for k in range(13)]
        rows.append([name, "값"] + month_vals)
        rows.append(["", "증감률"] + yoy_vals)
        rows.append(["", "비중"] + share_vals)
    return rows


def test_parse_block_preserves_data_when_order_changes():
    """순서 재배치 시 각 품목의 값이 이름 기준으로 정확 매핑 (index 미의존)."""
    # 산업통상부 2026-07 발표 실사례 · 반도체 top 재배치
    reshuffled = (
        "반도체", "선박", "무선통신기기", "일반기계", "석유화학",
        "철강제품", "자동차", "석유제품", "디스플레이", "섬유",
        "가전", "자동차부품", "컴퓨터", "바이오헬스", "이차전지",
    )
    table = _make_synthetic_table(reshuffled)
    months = report_to_months(date(2026, 8, 1))
    records = _parse_block(table, months, ITEM_ORDER_15, has_share=True)

    # 반도체(재배치 후 1번째): 값 = 1000*i + k · i=1, k=0 → 1000
    by_key = {(r.item, r.month): r for r in records}
    semi_first = by_key[("반도체", months[0])]
    assert semi_first.value_musd == 1000, (
        f"순서 재배치 후 반도체 첫 월 값 mismatch · expected=1000 got={semi_first.value_musd}"
    )
    # 선박(재배치 후 2번째): 값 = 1000*2 + 0 = 2000
    ship_first = by_key[("선박", months[0])]
    assert ship_first.value_musd == 2000, (
        f"순서 재배치 후 선박 첫 월 값 mismatch · expected=2000 got={ship_first.value_musd}"
    )

    # 15품목 전부 15×13 = 195행
    assert len(records) == 15 * 13
    assert {r.item for r in records} == set(ITEM_ORDER_15)


def test_parse_block_ignores_unknown_item():
    """예상 세트에 없는 품목 (예: 신규 추가) 는 skip · 남은 15품목 정상 파싱."""
    # unknown 하나 앞에 삽입 + 15품목 그대로 (중복 없음)
    order = ("미지의품목XYZ",) + ITEM_ORDER_15
    table = _make_synthetic_table(order)
    months = report_to_months(date(2026, 8, 1))
    records = _parse_block(table, months, ITEM_ORDER_15, has_share=True)

    items = {r.item for r in records}
    assert "미지의품목XYZ" not in items, "예상 외 품목이 결과에 포함됨"
    assert items == set(ITEM_ORDER_15), (
        f"15품목 완주 실패 · missing={set(ITEM_ORDER_15) - items}"
    )
