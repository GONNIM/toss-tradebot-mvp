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


# KDI 자료 num 시드 카탈로그 — 초기 신뢰 데이터 (2025-06 ~ 2026-06 검증 완료)
#
# 2026-08-14 개편: 매월 수동 등재 → discovery.py 자동 크롤로 대체.
# 본 dict 는 시드 (초기 fallback) 로만 유지 · 신규 자료는 kdi_num_cache.json 에 자동 축적.
# 조회 순서: (1) 파일 캐시 → (2) 시드 catalog → (3) 실시간 KDI 크롤 (async 경로만).
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
    """발표월 → KDI num 조회 (sync · 캐시 + 시드).

    조회 순서:
      1. 파일 캐시 (kdi_num_cache.json · discovery.refresh_kdi_cache 로 갱신)
      2. 시드 catalog (본 파일 하드코딩 · 초기 신뢰 데이터)
      → 둘 다 miss 면 KeyError · async 컨텍스트라면 resolve_kdi_num_async 사용 권장

    Args:
        confirmed: True 면 확정치 catalog (별도 · 캐시 미지원).
    """
    # 확정치는 별도 · 잠정치만 캐시 통합
    if confirmed:
        key = _report_month_key(report_month)
        num = KDI_NUM_CONFIRMED_CATALOG.get(key)
        if num is None:
            raise KeyError(
                f"KDI 확정치 카탈로그에 {key} 없음. "
                f"https://eiec.kdi.re.kr 에서 확정치 자료 확인 후 catalog 갱신 필요."
            )
        return num

    # 잠정치: 캐시 → 시드 순
    from backend.discovery.data_sources.motir_export.discovery import resolve_num_from_cache

    key = _report_month_key(report_month)
    cached = resolve_num_from_cache(report_month)
    if cached is not None:
        logger.debug(f"[resolve_kdi_num] {key} → {cached} (cache)")
        return cached
    seeded = KDI_NUM_CATALOG.get(key)
    if seeded is not None:
        logger.debug(f"[resolve_kdi_num] {key} → {seeded} (seed)")
        return seeded
    raise KeyError(
        f"KDI 잠정치 num 미확인: {key}. "
        f"discovery.refresh_kdi_cache() 로 캐시 갱신 후 재시도 필요."
    )


async def resolve_kdi_num_async(report_month: date, *, confirmed: bool = False) -> int:
    """async · sync 조회 실패 시 KDI 실시간 크롤 → 캐시 갱신 후 재조회.

    scheduler 등 async 컨텍스트에서 최신성 보장 필요 시 사용.
    """
    try:
        return resolve_kdi_num(report_month, confirmed=confirmed)
    except KeyError:
        if confirmed:
            raise  # 확정치는 크롤 미지원
        logger.info(
            f"[resolve_kdi_num_async] {_report_month_key(report_month)} miss → KDI 실시간 크롤"
        )
        from backend.discovery.data_sources.motir_export.discovery import refresh_kdi_cache

        await refresh_kdi_cache()
        # 재시도 (캐시 갱신됨)
        return resolve_kdi_num(report_month, confirmed=False)


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

    # async 경로 · 캐시 miss 시 KDI 크롤로 자동 fallback
    num = await resolve_kdi_num_async(report_month, confirmed=confirmed)
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
