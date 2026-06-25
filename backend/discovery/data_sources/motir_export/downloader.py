"""산업통상부(motir) 월간 수출입동향 PDF 다운로더.

매월 1일경 발표 자료를 KDI 경제교육·정보센터(eiec.kdi.re.kr)에서 다운로드.
KDI URL 패턴: callDownload.do?num={KDI_ID}&filenum=1&dtime={timestamp}
  - dtime 토큰은 cosmetic — 임의의 timestamp 문자열로 동작 확인됨 (2026-06-24).
  - num 은 자료마다 다름 → KDI_NUM_CATALOG 에 매월 발표 후 추가.

본 모듈의 책임:
- 발표월 → 표준 로컬 경로 매핑
- KDI num 카탈로그 조회
- HTTP fetch + 파일 저장 + PDF 검증

자동 num 발견 (KDI 검색 페이지 fetch) 은 향후 개선 사항.
현재는 사용자가 매월 신규 num 을 카탈로그에 등록.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


DEFAULT_PDF_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "research" / "motir_exports"
)


# KDI 자료 num 카탈로그 — 발표월별 (2025-06 ~ 2026-06 검증 완료)
#
# **갱신 방법**: 매월 1일 새 발표 자료 게시 후 https://eiec.kdi.re.kr 검색
# "수출입 동향" → 신규 자료 클릭 → URL 의 num 값 등재.
#
# Key = report_month (발표월, "YYYY-MM"). Value = KDI num.
KDI_NUM_CATALOG: dict[str, int] = {
    "2025-06": 267271,  # 25-05 자료 (잠정)
    "2025-07": 268265,  # 25-06 자료 (+ 25 상반기)
    "2025-08": 269418,
    "2025-09": 270413,
    "2025-10": 271930,
    "2025-11": 272893,
    "2025-12": 274124,
    "2026-01": 275598,  # 25 연간 + 25-12 자료
    "2026-02": 276561,
    "2026-03": 277470,
    "2026-04": 278872,
    "2026-05": 280536,
    "2026-06": 281941,  # 26-05 자료
    # 매월 1일 신규 자료 게시 후 본 dict 에 등재.
}


# 확정치 자료 num (별도 게시)
KDI_NUM_CONFIRMED_CATALOG: dict[str, int] = {
    "2025-06": 267615,  # 25-05 자료 확정치
    # 향후 매월 확정치 발표 시 등재.
}


# ─────────────────────────────────────────────────────────────────
# 경로 규약
# ─────────────────────────────────────────────────────────────────


def data_month(report_month: date) -> date:
    """발표월 → 데이터 월 (발표 직전월)."""
    if report_month.month == 1:
        return date(report_month.year - 1, 12, 1)
    return date(report_month.year, report_month.month - 1, 1)


def get_pdf_path(
    report_month: date,
    base_dir: Path | None = None,
) -> Path:
    """발표월 → 표준 PDF 경로 (motir_export_YYYY-MM.pdf — 데이터 월 기준)."""
    dm = data_month(report_month)
    base = base_dir if base_dir is not None else DEFAULT_PDF_DIR
    return base / f"motir_export_{dm.year:04d}-{dm.month:02d}.pdf"


def ensure_local_pdf(report_month: date, base_dir: Path | None = None) -> Path:
    """로컬에 PDF 존재 확인 (다운로드 안 함)."""
    path = get_pdf_path(report_month, base_dir)
    if not path.exists():
        raise FileNotFoundError(f"motir PDF 미존재: {path}")
    return path


# ─────────────────────────────────────────────────────────────────
# HTTP 다운로드
# ─────────────────────────────────────────────────────────────────


KDI_DOWNLOAD_URL = "https://eiec.kdi.re.kr/policy/callDownload.do"
DTIME_PLACEHOLDER = "20260101000000"  # cosmetic — KDI 가 검증하지 않음 (2026-06 확인)


def _report_month_key(report_month: date) -> str:
    return f"{report_month.year:04d}-{report_month.month:02d}"


def resolve_kdi_num(report_month: date, *, confirmed: bool = False) -> int:
    """발표월 → KDI num 조회.

    Args:
        confirmed: True 면 확정치 num (KDI_NUM_CONFIRMED_CATALOG) 조회.
    """
    catalog = KDI_NUM_CONFIRMED_CATALOG if confirmed else KDI_NUM_CATALOG
    key = _report_month_key(report_month)
    num = catalog.get(key)
    if num is None:
        flavor = "확정치" if confirmed else "잠정치"
        raise KeyError(
            f"KDI {flavor} 카탈로그에 {key} 없음. "
            f"https://eiec.kdi.re.kr 에서 신규 num 확인 후 catalog 갱신 필요."
        )
    return num


async def download_kdi_pdf(
    report_month: date,
    *,
    confirmed: bool = False,
    base_dir: Path | None = None,
    overwrite: bool = False,
    timeout: float = 60.0,
) -> Path:
    """KDI 에서 발표월 PDF 다운로드 → 표준 로컬 경로 저장.

    Args:
        report_month: 발표월 (매월 1일).
        confirmed: 확정치 자료 다운로드. False = 잠정치.
        overwrite: 이미 로컬에 있어도 재다운로드.
        timeout: HTTP 타임아웃.

    Returns:
        저장된 PDF 경로.

    Raises:
        KeyError: 카탈로그 미등재
        httpx.HTTPError: 다운로드 실패
        ValueError: 응답이 PDF 가 아님
    """
    base = base_dir if base_dir is not None else DEFAULT_PDF_DIR
    base.mkdir(parents=True, exist_ok=True)
    target = get_pdf_path(report_month, base_dir=base)

    if target.exists() and not overwrite:
        logger.info(f"[motir_download] already present: {target}")
        return target

    num = resolve_kdi_num(report_month, confirmed=confirmed)
    params = {"num": str(num), "filenum": "1", "dtime": DTIME_PLACEHOLDER}
    headers = {"User-Agent": "toss-tradebot-mvp/0.1 (motir export downloader)"}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        logger.info(
            f"[motir_download] GET {KDI_DOWNLOAD_URL}?num={num} → {target.name}"
        )
        response = await client.get(KDI_DOWNLOAD_URL, params=params, headers=headers)
        response.raise_for_status()
        content = response.content

    if not content.startswith(b"%PDF"):
        raise ValueError(
            f"KDI 응답이 PDF 형식 아님 ({len(content)} bytes, "
            f"head={content[:16]!r}). num={num} 또는 dtime 정책 변경 가능성."
        )

    target.write_bytes(content)
    logger.info(f"[motir_download] saved {target} ({len(content)} bytes)")
    return target
