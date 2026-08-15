"""KDI num 자동 discovery 테스트.

2026-08-14 사고 (motir catalog 2개월 갱신 누락 → silent skip) 재발 방지.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.discovery.data_sources.motir_export.discovery import (
    KDIEntry,
    _parse_list_html,
    load_cache,
    resolve_num_from_cache,
    save_cache,
)


# ─── HTML 파싱 ───────────────────────────────────────────────────

SAMPLE_HTML = """
<div>
    <li>
        <a href="./materialView.do?num=285003&pg=&pp=40&topic=O">
            <div class="list_txt">
                <p>2026년 7월 수출입 동향</p>
                <span>산업통상부</span>
                <span>2026.08.01
                    <span>36p</span>
                </span>
            </div>
        </a>
    </li>
    <li>
        <a href="./materialView.do?num=285424&pg=&pp=40&topic=O">
            <div class="list_txt">
                <p>2026년 7월 정보통신산업(ICT) 수출입 동향</p>
                <span>과학기술정보통신부</span>
                <span>2026.08.14
                    <span>24p</span>
                </span>
            </div>
        </a>
    </li>
    <li>
        <a href="./materialView.do?num=283602&pg=&pp=40&topic=O">
            <div class="list_txt">
                <p>2026년 6월 및 상반기 수출입 동향</p>
                <span>산업통상부</span>
                <span>2026.07.01
                    <span>48p</span>
                </span>
            </div>
        </a>
    </li>
    <li>
        <a href="./materialView.do?num=275598&pg=&pp=40&topic=O">
            <div class="list_txt">
                <p>2025년 연간 및 12월 수출입 동향</p>
                <span>산업통상부</span>
                <span>2026.01.01
                    <span>52p</span>
                </span>
            </div>
        </a>
    </li>
</div>
"""


def test_parse_extracts_only_motir_export_reports():
    """산업통상부 발행 & '수출입 동향' 정확 매치만 통과 · ICT 등 배제."""
    entries = _parse_list_html(SAMPLE_HTML)

    assert len(entries) == 3, f"산업통상부 3건 예상 · 실제 {len(entries)}"
    nums = [e.num for e in entries]
    assert 285003 in nums  # 2026-08 (2026-07 자료)
    assert 283602 in nums  # 2026-07 (2026-06 자료)
    assert 275598 in nums  # 2026-01 (2025 연간 및 12월)
    assert 285424 not in nums  # ICT 는 배제 (다른 발행기관)


def test_parse_report_month_matches_published_date():
    """발표월(report_month) = published 의 YYYY-MM."""
    entries = _parse_list_html(SAMPLE_HTML)
    by_num = {e.num: e for e in entries}
    assert by_num[285003].report_month == "2026-08"
    assert by_num[285003].published == date(2026, 8, 1)
    assert by_num[283602].report_month == "2026-07"
    assert by_num[275598].report_month == "2026-01"


def test_parse_ignores_unrelated_titles():
    """'수출입 동향' 외 제목 배제 (수출입 현황·최근 경제동향 등)."""
    unrelated_html = """
    <li>
        <a href="./materialView.do?num=285409">
            <div class="list_txt">
                <p>2026년 8월 최근 경제동향</p>
                <span>재정경제부</span>
                <span>2026.08.14<span>20p</span></span>
            </div>
        </a>
    </li>
    <li>
        <a href="./materialView.do?num=285282">
            <div class="list_txt">
                <p>2026년 8월 1일 ~ 8월 10일 수출입 현황</p>
                <span>관세청</span>
                <span>2026.08.12<span>10p</span></span>
            </div>
        </a>
    </li>
    """
    entries = _parse_list_html(unrelated_html)
    assert entries == []


# ─── 캐시 파일 I/O ───────────────────────────────────────────────


def test_cache_roundtrip(tmp_path: Path):
    """save_cache → load_cache 왕복 · 최신순 정렬 확인."""
    cache_path = tmp_path / "kdi_num_cache.json"
    entries = [
        KDIEntry(num=283602, title="2026년 6월 및 상반기 수출입 동향",
                 org="산업통상부", published=date(2026, 7, 1), report_month="2026-07"),
        KDIEntry(num=285003, title="2026년 7월 수출입 동향",
                 org="산업통상부", published=date(2026, 8, 1), report_month="2026-08"),
    ]
    save_cache(entries, path=cache_path)

    loaded = load_cache(cache_path)
    assert loaded == {"2026-07": 283602, "2026-08": 285003}

    # 파일 내부는 최신순 정렬 (published DESC)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["entries"][0]["num"] == 285003
    assert payload["entries"][1]["num"] == 283602
    assert payload["issuing_org"] == "산업통상부"


def test_load_cache_missing_file_returns_empty(tmp_path: Path):
    """캐시 파일 부재 시 빈 dict 반환 · KeyError 아님."""
    assert load_cache(tmp_path / "nonexistent.json") == {}


def test_load_cache_malformed_returns_empty(tmp_path: Path):
    """malformed JSON 은 빈 dict + WARNING · silent proceed."""
    p = tmp_path / "bad.json"
    p.write_text("{ not json }", encoding="utf-8")
    assert load_cache(p) == {}


def test_resolve_num_from_cache_uses_report_month(tmp_path: Path):
    """resolve_num_from_cache 는 date → 'YYYY-MM' key 로 조회."""
    cache_path = tmp_path / "kdi_num_cache.json"
    save_cache(
        [KDIEntry(num=285003, title="2026년 7월 수출입 동향",
                  org="산업통상부", published=date(2026, 8, 1), report_month="2026-08")],
        path=cache_path,
    )
    # discovery.load_cache 는 DEFAULT_CACHE_PATH 사용 · 여기서는 직접 path 전달
    with patch("backend.discovery.data_sources.motir_export.discovery.DEFAULT_CACHE_PATH", cache_path):
        assert resolve_num_from_cache(date(2026, 8, 1)) == 285003
        assert resolve_num_from_cache(date(2026, 9, 1)) is None


# ─── resolve_kdi_num 3단 fallback ────────────────────────────────


def test_resolve_kdi_num_cache_beats_seed(tmp_path: Path):
    """캐시가 시드 catalog 보다 우선 · 캐시가 최신."""
    from backend.discovery.data_sources.motir_export import downloader

    cache_path = tmp_path / "kdi_num_cache.json"
    # 시드에 있는 2026-06 이지만 캐시에서 다른 값으로 override
    save_cache(
        [KDIEntry(num=999999, title="fake", org="산업통상부",
                  published=date(2026, 6, 1), report_month="2026-06")],
        path=cache_path,
    )
    with patch("backend.discovery.data_sources.motir_export.discovery.DEFAULT_CACHE_PATH", cache_path):
        assert downloader.resolve_kdi_num(date(2026, 6, 1)) == 999999


def test_resolve_kdi_num_falls_back_to_seed_when_cache_miss(tmp_path: Path):
    """캐시 miss 시 시드 catalog 조회 · 기존 데이터 계속 사용 가능."""
    from backend.discovery.data_sources.motir_export import downloader

    cache_path = tmp_path / "empty.json"
    with patch("backend.discovery.data_sources.motir_export.discovery.DEFAULT_CACHE_PATH", cache_path):
        # 시드에 있는 2026-06 = 281941
        assert downloader.resolve_kdi_num(date(2026, 6, 1)) == 281941


def test_resolve_kdi_num_raises_on_double_miss(tmp_path: Path):
    """캐시·시드 둘 다 miss → KeyError (async 크롤 fallback 은 별도 API)."""
    from backend.discovery.data_sources.motir_export import downloader

    cache_path = tmp_path / "empty.json"
    with patch("backend.discovery.data_sources.motir_export.discovery.DEFAULT_CACHE_PATH", cache_path):
        with pytest.raises(KeyError, match="2099-12"):
            downloader.resolve_kdi_num(date(2099, 12, 1))


# ─── 회귀 게이트 ─────────────────────────────────────────────────


def test_seed_catalog_still_covers_pre_2026_07():
    """시드 catalog 는 2025-06 ~ 2026-06 원본 데이터 신뢰성 유지."""
    from backend.discovery.data_sources.motir_export.downloader import KDI_NUM_CATALOG

    critical = {
        "2025-06": 267271,
        "2026-01": 275598,
        "2026-06": 281941,
    }
    for month, expected_num in critical.items():
        assert KDI_NUM_CATALOG.get(month) == expected_num, (
            f"시드 {month} 훼손 · 원본 데이터 다운로드 불가 위험"
        )
