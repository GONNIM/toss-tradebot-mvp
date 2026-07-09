"""DART OpenAPI client — 한국 공시 catalyst 시그널.

URL:
  list:     https://opendart.fss.or.kr/api/list.json
  corpCode: https://opendart.fss.or.kr/api/corpCode.xml (ZIP)

인증: 무료 DART_API_KEY (https://opendart.fss.or.kr).
Rate limit: 분당 ~100 호출 (보수적 사용 — 매시간 1회 + 페이지네이션).

공시 유형 (pblntf_ty):
- A: 정기공시   B: 주요사항보고   C: 발행공시   D: 지분공시
- E: 기타       F: 외부감사       G: 펀드       H: 자산유동화
- I: 거래소공시 J: 공정위공시
"""
from __future__ import annotations

import io
import logging
import os
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://opendart.fss.or.kr/api"
_TIMEOUT_SEC = 15.0
_PAGE_COUNT = 100


@dataclass(frozen=True)
class DartDisclosure:
    corp_code: str          # DART 고유 코드 (8자리)
    corp_name: str
    stock_code: Optional[str]   # KRX 종목 코드 (6자리, 비상장 시 None)
    rcept_no: str           # 접수번호 (공시 고유 ID)
    rcept_dt: str           # YYYYMMDD
    report_nm: str          # 공시 제목
    pblntf_ty: str          # 공시 유형 (A~J)
    corp_cls: str           # Y(유가)/K(코스닥)/N(코넥스)
    flr_nm: str = ""        # 제출인 (activist 매칭용 · Phase B 활용)


@dataclass(frozen=True)
class CorpCodeEntry:
    corp_code: str
    corp_name: str
    stock_code: Optional[str]
    modify_date: str


def is_configured() -> bool:
    """DART_API_KEY 환경변수 설정 여부."""
    return bool(os.getenv("DART_API_KEY", "").strip())


def _api_key() -> str:
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DART_API_KEY 환경변수 미설정 — "
            "https://opendart.fss.or.kr 에서 발급 후 backend/.env 에 등록"
        )
    return key


async def fetch_corp_codes() -> list[CorpCodeEntry]:
    """DART 전체 기업 목록 — corp_code ↔ stock_code 매핑.

    응답: ZIP(CORPCODE.xml). 약 100,000개 entry. 비상장도 포함 — stock_code 비어있는 entry 다수.
    """
    url = f"{_BASE}/corpCode.xml"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                url, params={"crtfc_key": _api_key()}, timeout=30.0
            )
            resp.raise_for_status()
            content = resp.content
        except Exception as e:
            logger.exception(f"[dart] corpCode fetch failed: {e}")
            return []

    # ZIP 풀기
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xml_name = zf.namelist()[0]
            xml_bytes = zf.read(xml_name)
    except zipfile.BadZipFile:
        # API 에러일 경우 JSON 응답 옴
        logger.warning(f"[dart] corpCode response not ZIP: {content[:200]!r}")
        return []

    # XML 파싱
    out: list[CorpCodeEntry] = []
    root = ElementTree.fromstring(xml_bytes)
    for item in root.findall("list"):
        sc = (item.findtext("stock_code") or "").strip()
        out.append(
            CorpCodeEntry(
                corp_code=(item.findtext("corp_code") or "").strip(),
                corp_name=(item.findtext("corp_name") or "").strip(),
                stock_code=(sc if sc and sc != " " else None),
                modify_date=(item.findtext("modify_date") or "").strip(),
            )
        )

    logger.info(f"[dart] corpCode entries: {len(out)}")
    return out


async def fetch_recent_disclosures(
    bgn_de: Optional[date] = None,
    end_de: Optional[date] = None,
    pblntf_ty: str = "B",   # 주요사항보고 — catalyst 가장 강함
    pblntf_detail_ty: Optional[str] = None,  # 세부 (예: "D001" 대량보유상황보고서)
    only_listed: bool = True,
) -> list[DartDisclosure]:
    """DART 공시 검색 — 기본 최근 1일 + 주요사항보고.

    Args:
        bgn_de: 시작일 (None → 어제)
        end_de: 종료일 (None → 오늘)
        pblntf_ty: 공시 유형 ("B" 주요사항 / "C" 발행 / "D" 지분 / "I" 거래소)
        pblntf_detail_ty: 세부 (예: "D001" 대량보유·"D002" 임원주요주주)
        only_listed: stock_code 있는 종목만 (비상장 제외)
    """
    if bgn_de is None or end_de is None:
        end_de = date.today()
        bgn_de = end_de - timedelta(days=1)

    base_params = {
        "crtfc_key": _api_key(),
        "bgn_de": bgn_de.strftime("%Y%m%d"),
        "end_de": end_de.strftime("%Y%m%d"),
        "pblntf_ty": pblntf_ty,
        "page_count": _PAGE_COUNT,
    }
    if pblntf_detail_ty:
        base_params["pblntf_detail_ty"] = pblntf_detail_ty

    results: list[DartDisclosure] = []
    async with httpx.AsyncClient() as client:
        page_no = 1
        while True:
            params = {**base_params, "page_no": page_no}
            try:
                resp = await client.get(
                    f"{_BASE}/list.json", params=params, timeout=_TIMEOUT_SEC
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"[dart] page {page_no} failed: {e}")
                break

            status = data.get("status")
            if status != "000":
                # "013" = no result, "020" = key 한도 초과 등
                msg = data.get("message", "")
                if status != "013":
                    logger.warning(f"[dart] API status={status}: {msg}")
                break

            for item in data.get("list", []):
                sc = (item.get("stock_code") or "").strip()
                if only_listed and (not sc or sc == " "):
                    continue
                results.append(
                    DartDisclosure(
                        corp_code=item.get("corp_code", ""),
                        corp_name=item.get("corp_name", ""),
                        stock_code=(sc if sc else None),
                        rcept_no=item.get("rcept_no", ""),
                        rcept_dt=item.get("rcept_dt", ""),
                        report_nm=item.get("report_nm", ""),
                        pblntf_ty=item.get("pblntf_ty", ""),
                        corp_cls=item.get("corp_cls", ""),
                        flr_nm=(item.get("flr_nm") or "").strip(),
                    )
                )

            total_page = int(data.get("total_page", 1))
            if page_no >= total_page:
                break
            page_no += 1

    logger.info(
        f"[dart] pblntf_ty={pblntf_ty} {bgn_de}~{end_de}: {len(results)} 공시"
    )
    return results
