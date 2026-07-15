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


@dataclass(frozen=True)
class DartMajorStock:
    """DART 대량보유상황보고 상세 (majorstock.json)."""
    rcept_no: str
    rcept_dt: str
    corp_code: str
    corp_name: str
    report_tp: str          # 신규보고 · 변동보고 · 변경보고
    repror: str             # 대표보고자
    stkqy: Optional[float]         # 보유주식수
    stkqy_irds: Optional[float]    # 보유주식 증감
    stkrt: Optional[float]         # 보유비율 (%)
    stkrt_irds: Optional[float]    # 보유비율 증감 (%)
    ctr_stkqy: Optional[float]     # 주요체결 주식수
    ctr_stkrt: Optional[float]     # 주요체결 비율
    report_resn: str        # 보고사유 (예: 장내매수 · 장내매도 · 신규보고)


def _to_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


async def fetch_majorstock(corp_code: str) -> list[DartMajorStock]:
    """DART 대량보유상황보고 상세 목록 (회사 전체 이력).

    Args:
        corp_code: DART 회사코드 (8자리)
    Returns:
        DartMajorStock 리스트 (최신순)
    """
    if not corp_code:
        return []
    params = {"crtfc_key": _api_key(), "corp_code": corp_code}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_BASE}/majorstock.json", params=params, timeout=_TIMEOUT_SEC
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[dart] majorstock {corp_code} 실패: {e}")
            return []

    status = data.get("status")
    if status != "000":
        if status != "013":
            logger.warning(f"[dart] majorstock API status={status}: {data.get('message', '')}")
        return []

    out: list[DartMajorStock] = []
    for item in data.get("list", []):
        out.append(DartMajorStock(
            rcept_no=item.get("rcept_no", ""),
            rcept_dt=item.get("rcept_dt", ""),
            corp_code=item.get("corp_code", ""),
            corp_name=item.get("corp_name", ""),
            report_tp=(item.get("report_tp") or "").strip(),
            repror=(item.get("repror") or "").strip(),
            stkqy=_to_float(item.get("stkqy")),
            stkqy_irds=_to_float(item.get("stkqy_irds")),
            stkrt=_to_float(item.get("stkrt")),
            stkrt_irds=_to_float(item.get("stkrt_irds")),
            ctr_stkqy=_to_float(item.get("ctr_stkqy")),
            ctr_stkrt=_to_float(item.get("ctr_stkrt")),
            report_resn=(item.get("report_resn") or "").strip(),
        ))
    return out


# ─── 재무제표·감사의견 (Phase 7-1b Powder Keg) ─────────────
@dataclass(frozen=True)
class DartFinancialItem:
    """단일 회계 항목 · fnlttSinglAcntAll.json 응답 파싱."""
    account_id: str          # ifrs-full_CashAndCashEquivalents 등 표준 ID
    account_nm: str          # "현금및현금성자산" 등 한글명
    sj_div: str              # BS / IS / CIS / CF / SCE
    fs_div: str              # CFS(연결) / OFS(별도)
    fs_nm: str               # "연결재무제표" / "재무제표"
    thstrm_amount: Optional[float]   # 당기금액
    frmtrm_amount: Optional[float]   # 전기금액
    ord: Optional[int]               # 정렬 순서


async def fetch_financial_statement(
    corp_code: str,
    bsns_year: int,
    reprt_code: str,       # 11011(사업)·11012(반기)·11013(1분기)·11014(3분기)
    fs_div: str = "CFS",   # CFS(연결) 우선 · 미제출 시 OFS(별도) fallback 필요
) -> list[DartFinancialItem]:
    """DART 단일회사 전체 재무제표 (fnlttSinglAcntAll.json).

    Docs: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020
    """
    if not corp_code:
        return []
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_BASE}/fnlttSinglAcntAll.json", params=params, timeout=_TIMEOUT_SEC
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[dart] fnlttSingl {corp_code}/{bsns_year}/{reprt_code} 실패: {e}")
            return []

    status = data.get("status")
    if status != "000":
        if status != "013":  # 013 = no data (연결/별도 미제출)
            logger.warning(f"[dart] fnlttSingl status={status} · {data.get('message', '')}")
        return []

    out: list[DartFinancialItem] = []
    for item in data.get("list", []):
        out.append(DartFinancialItem(
            account_id=(item.get("account_id") or "").strip(),
            account_nm=(item.get("account_nm") or "").strip(),
            sj_div=(item.get("sj_div") or "").strip(),
            fs_div=(item.get("fs_div") or "").strip(),
            fs_nm=(item.get("fs_nm") or "").strip(),
            thstrm_amount=_to_float(item.get("thstrm_amount")),
            frmtrm_amount=_to_float(item.get("frmtrm_amount")),
            ord=int(item["ord"]) if str(item.get("ord", "")).isdigit() else None,
        ))
    return out


@dataclass(frozen=True)
class DartAuditOpinion:
    """감사의견 · accnutAdtorNmNdAdtOpinion.json 응답."""
    bsns_year: str
    adtor: str                      # 감사인 명칭
    adt_reprt_opinion: str          # 감사보고서 감사의견 (적정 / 한정 / 부적정 / 의견거절)
    emphs_matter: Optional[str]     # 강조사항 등
    core_report_matter: Optional[str]   # 핵심감사사항


async def fetch_audit_opinion(
    corp_code: str,
    bsns_year: int,
    reprt_code: str = "11011",   # 사업보고서 기준 감사의견
) -> Optional[DartAuditOpinion]:
    """DART 감사인의 명칭 및 감사의견 (accnutAdtorNmNdAdtOpinion.json).

    Docs: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019013
    """
    if not corp_code:
        return None
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_BASE}/accnutAdtorNmNdAdtOpinion.json", params=params, timeout=_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[dart] adtOpinion {corp_code}/{bsns_year} 실패: {e}")
            return None

    status = data.get("status")
    if status != "000":
        return None
    items = data.get("list") or []
    if not items:
        return None
    item = items[0]
    return DartAuditOpinion(
        bsns_year=str(item.get("bsns_year", "")),
        adtor=(item.get("adtor") or "").strip(),
        adt_reprt_opinion=(item.get("adt_reprt_opinion") or "").strip(),
        emphs_matter=(item.get("emphs_matter") or "").strip() or None,
        core_report_matter=(item.get("core_report_matter") or "").strip() or None,
    )


# ─── 최대주주 현황 · 자기주식 (Phase 7-1f Powder Keg) ─────
@dataclass(frozen=True)
class DartMajorShareholderRow:
    """사업보고서 최대주주 현황 (hyslrSttus.json) 단일 항목."""
    nm: str                     # 성명 (또는 법인명)
    relate: str                 # 최대주주와의 관계 (본인 · 특수관계인 등)
    stock_knd: str              # 주식 종류
    bsis_posesn_stock_co: Optional[float]     # 기초 소유주식수
    bsis_posesn_stock_qota_rt: Optional[float]  # 기초 소유주식 지분율(%)
    trmend_posesn_stock_co: Optional[float]   # 기말 소유주식수
    trmend_posesn_stock_qota_rt: Optional[float]  # 기말 소유주식 지분율(%)


async def fetch_major_shareholder_status(
    corp_code: str,
    bsns_year: int,
    reprt_code: str = "11011",
) -> list[DartMajorShareholderRow]:
    """사업보고서 최대주주 현황 (hyslrSttus.json).

    Docs: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019004
    반환: 본인 + 특수관계인 모두 포함.
    """
    if not corp_code:
        return []
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_BASE}/hyslrSttus.json", params=params, timeout=_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[dart] hyslrSttus {corp_code}/{bsns_year} 실패: {e}")
            return []

    status = data.get("status")
    if status != "000":
        return []

    out: list[DartMajorShareholderRow] = []
    for item in data.get("list", []):
        out.append(DartMajorShareholderRow(
            nm=(item.get("nm") or "").strip(),
            relate=(item.get("relate") or "").strip(),
            stock_knd=(item.get("stock_knd") or "").strip(),
            bsis_posesn_stock_co=_to_float(item.get("bsis_posesn_stock_co")),
            bsis_posesn_stock_qota_rt=_to_float(item.get("bsis_posesn_stock_qota_rt")),
            trmend_posesn_stock_co=_to_float(item.get("trmend_posesn_stock_co")),
            trmend_posesn_stock_qota_rt=_to_float(item.get("trmend_posesn_stock_qota_rt")),
        ))
    return out


@dataclass(frozen=True)
class DartTreasuryStockRow:
    """자기주식 취득·처분 현황 (tesstkAcqsDspsSttus.json)."""
    stock_knd: str
    acqs_mth1: str              # 취득방법
    stock_co: Optional[float]   # 주식수
    stock_pnc: Optional[float]  # 지분율(%)


async def fetch_treasury_stock(
    corp_code: str,
    bsns_year: int,
    reprt_code: str = "11011",
) -> list[DartTreasuryStockRow]:
    """자기주식 취득·처분 현황 (tesstkAcqsDspsSttus.json).

    Docs: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019005
    """
    if not corp_code:
        return []
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": str(bsns_year),
        "reprt_code": reprt_code,
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{_BASE}/tesstkAcqsDspsSttus.json", params=params, timeout=_TIMEOUT_SEC,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"[dart] tesstkSttus {corp_code}/{bsns_year} 실패: {e}")
            return []

    status = data.get("status")
    if status != "000":
        return []

    out: list[DartTreasuryStockRow] = []
    for item in data.get("list", []):
        out.append(DartTreasuryStockRow(
            stock_knd=(item.get("stock_knd") or "").strip(),
            acqs_mth1=(item.get("acqs_mth1") or "").strip(),
            stock_co=_to_float(item.get("stock_co")),
            stock_pnc=_to_float(item.get("stock_pnc")),
        ))
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
