"""미국 SEC Form 4 폴러 · Phase F (실측 튜닝 반영).

XML 파싱 정밀화 (2026-07-09 실 파일 스키마 실측):
- transactionCode 별 매매 성격 판정
  P = Open Market Purchase (실 매수 · 강신호)
  S = Open Market Sale (실 매도)
  M = Exercise/Vest of Derivative (옵션·RSU 실제 매매 아님)
  A = Award/Grant (무상 수여)
  G = Bona Fide Gift (증여)
  F = Payment of Tax by Withholding
  D = Sale back to Issuer
- non-Derivative + Derivative 두 트랜잭션 세트 모두 파싱
- reporter 직책 (isDirector · isOfficer · isTenPercentOwner) 확인
- 총 매매 금액 (transactionShares × transactionPricePerShare) 합산
- 매수 판정: P 코드가 있고 A/D 코드가 A → BUY_OPEN_MARKET
- 매도 판정: S 코드가 있고 A/D 코드가 D → SELL_OPEN_MARKET
- 나머지 (M/A/G/F 등) → NON_TRADE (매매 시그널 아님 · 알림 강도 하향)

index.json URL 버그 수정: {accession}-index.json → index.json (실제 SEC 파일명).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx

from backend.discovery.vip.activist_tracker import fetch_recent as fetch_recent_filings

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 10.0
_RECENT_DAYS = 7
_FORM4_XML_BASE = "https://www.sec.gov/Archives/edgar/data"

# 트랜잭션 코드 → 타입 분류
_CODE_TYPE = {
    "P": "PURCHASE",         # Open Market Purchase — 강 매수
    "S": "SALE",             # Open Market Sale — 매도
    "M": "OPTION_EXERCISE",  # 옵션·RSU 행사 (실 매매 아님)
    "A": "GRANT",            # 무상 수여
    "G": "GIFT",             # 증여
    "F": "TAX_WITHHOLD",     # 세금 원천징수
    "D": "SALE_TO_ISSUER",   # 회사 매도
    "V": "VOLUNTARY",        # 자발적 보고
    "X": "OPTION_EXERCISE",  # 옵션 만기·행사
    "C": "CONVERSION",       # 전환
}

# 매매 시그널로 취급할 타입 (알림 대상)
_TRADING_TYPES = {"PURCHASE", "SALE", "SALE_TO_ISSUER"}


@dataclass(frozen=True)
class Form4Filing:
    subject_cik: str
    subject_ticker: str
    subject_name: str
    accession: str
    form: str
    filing_date: str
    primary_desc: str
    # ─ 튜닝 후 세분화 필드 ─
    tx_type: str = "UNKNOWN"           # PURCHASE / SALE / OPTION_EXERCISE / GRANT / GIFT / MIXED / NON_TRADE / UNKNOWN
    direction: str = "UNKNOWN"          # BUY / SELL / MIXED / NON_TRADE / UNKNOWN (하위 호환)
    reporter_name: str = ""
    reporter_title: str = ""            # officerTitle (예: SVP, CFO)
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: bool = False
    total_value_usd: Optional[float] = None
    total_shares: Optional[float] = None


def _is_recent(filing_date: str) -> bool:
    try:
        d = datetime.strptime(filing_date, "%Y-%m-%d").date()
        return (date.today() - d).days <= _RECENT_DAYS
    except (TypeError, ValueError):
        return False


def _accession_url_path(cik: str, accession: str) -> str:
    cik_num = str(cik).lstrip("0") or "0"
    acc_no_dashes = accession.replace("-", "")
    return f"{_FORM4_XML_BASE}/{cik_num}/{acc_no_dashes}"


async def _fetch_form4_xml(cik: str, accession: str, ua: str) -> Optional[bytes]:
    """Form 4 primary XML 다운로드. URL: `{path}/index.json` 에서 xml 파일명 확인."""
    idx_url = f"{_accession_url_path(cik, accession)}/index.json"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(idx_url, headers={"User-Agent": ua})
            resp.raise_for_status()
            idx = resp.json()
    except Exception as e:
        logger.debug(f"[form4] index fetch 실패 {accession}: {e}")
        return None

    items = idx.get("directory", {}).get("item") or []
    # form4.xml 우선 · 다음으로 아무 .xml 파일 (index-headers.html 제외)
    xml_name = None
    for it in items:
        name = it.get("name", "")
        if name == "form4.xml":
            xml_name = name
            break
    if not xml_name:
        for it in items:
            name = it.get("name", "")
            if name.endswith(".xml") and "index" not in name:
                xml_name = name
                break
    if not xml_name:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SEC) as client:
            resp = await client.get(
                f"{_accession_url_path(cik, accession)}/{xml_name}",
                headers={"User-Agent": ua},
            )
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.debug(f"[form4] XML fetch 실패 {accession}: {e}")
        return None


def _value_text(elem, path: str) -> str:
    """element/path/value 텍스트 (없으면 빈 문자열)."""
    node = elem.find(f".//{path}/value")
    if node is not None and node.text:
        return node.text.strip()
    return ""


def _bool_flag(root, tag: str) -> bool:
    """rptOwner 등 boolean flag (예: <isOfficer>true</isOfficer>)."""
    for n in root.iter(tag):
        if n.text and n.text.strip().lower() == "true":
            return True
    return False


def _text(root, tag: str) -> str:
    for n in root.iter(tag):
        if n.text:
            return n.text.strip()
    return ""


def _iter_transactions(root) -> list:
    """non-derivative + derivative 모든 트랜잭션 순회."""
    out = []
    for txn in root.iter("nonDerivativeTransaction"):
        out.append(("nonDerivative", txn))
    for txn in root.iter("derivativeTransaction"):
        out.append(("derivative", txn))
    return out


def _parse_form4(xml_bytes: bytes) -> dict:
    """Form 4 XML → {tx_type, direction, reporter, ..., total_value_usd, total_shares}.

    tx_type 결정 순서:
        1) 트랜잭션 별 code + A/D 조합으로 개별 분류
        2) 종합: PURCHASE 만 있고 SALE 없음 → PURCHASE (BUY)
                SALE 만 있고 PURCHASE 없음 → SALE (SELL)
                PURCHASE + SALE → MIXED
                거래성 트랜잭션 없음 (M/A/G/F/...) → NON_TRADE
                파싱 실패 → UNKNOWN
    """
    default = {
        "tx_type": "UNKNOWN", "direction": "UNKNOWN",
        "reporter_name": "", "reporter_title": "",
        "is_director": False, "is_officer": False, "is_ten_percent_owner": False,
        "total_value_usd": None, "total_shares": None,
    }
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return default

    reporter_name = _text(root, "rptOwnerName")
    reporter_title = _text(root, "officerTitle")
    is_director = _bool_flag(root, "isDirector")
    is_officer = _bool_flag(root, "isOfficer")
    is_10p = _bool_flag(root, "isTenPercentOwner")

    types_seen: List[str] = []
    total_value = 0.0
    total_shares_signed = 0.0   # A=+, D=-

    for kind, txn in _iter_transactions(root):
        code = _value_text(txn, "transactionCoding/transactionCode")
        # 상위 매매 성격
        code_type = _CODE_TYPE.get(code.upper(), "OTHER")
        # A(acquired) / D(disposed)
        ad = _value_text(txn, "transactionAmounts/transactionAcquiredDisposedCode").upper()
        # 세분화: P + A → PURCHASE · S + D → SALE 만 실 매매 (기타 조합은 위 code_type 유지)
        if code_type == "PURCHASE" and ad != "A":
            code_type = "OTHER"
        if code_type == "SALE" and ad != "D":
            code_type = "OTHER"

        types_seen.append(code_type)

        # 금액·주수 합산
        try:
            shares = float(_value_text(txn, "transactionAmounts/transactionShares") or 0)
        except ValueError:
            shares = 0.0
        try:
            price = float(_value_text(txn, "transactionAmounts/transactionPricePerShare") or 0)
        except ValueError:
            price = 0.0
        val = shares * price
        if val > 0:
            total_value += val
        # 실 매매 트랜잭션만 signed shares 합산
        if code_type == "PURCHASE":
            total_shares_signed += shares
        elif code_type in ("SALE", "SALE_TO_ISSUER"):
            total_shares_signed -= shares

    # 종합 판정
    has_p = "PURCHASE" in types_seen
    has_s = ("SALE" in types_seen) or ("SALE_TO_ISSUER" in types_seen)
    if has_p and has_s:
        tx_type, direction = "MIXED", "MIXED"
    elif has_p:
        tx_type, direction = "PURCHASE", "BUY"
    elif has_s:
        tx_type, direction = "SALE", "SELL"
    elif types_seen and all(t in ("OPTION_EXERCISE", "GRANT", "GIFT", "TAX_WITHHOLD", "CONVERSION", "VOLUNTARY", "OTHER") for t in types_seen):
        tx_type, direction = "NON_TRADE", "NON_TRADE"
    else:
        tx_type, direction = "UNKNOWN", "UNKNOWN"

    return {
        "tx_type": tx_type,
        "direction": direction,
        "reporter_name": reporter_name,
        "reporter_title": reporter_title,
        "is_director": is_director,
        "is_officer": is_officer,
        "is_ten_percent_owner": is_10p,
        "total_value_usd": (total_value if total_value > 0 else None),
        "total_shares": (total_shares_signed if abs(total_shares_signed) > 0 else None),
    }


async def poll_new_form4(
    watchlist: List[dict],   # [{ticker, cik, name}, ...]
    ua: str,
    is_seen_fn,
    parse_xml: bool = True,
) -> List[Form4Filing]:
    results: List[Form4Filing] = []
    for w in watchlist:
        cik = w.get("cik")
        ticker = w.get("ticker")
        name = w.get("name") or ""
        if not cik or not ticker:
            continue
        try:
            filings = await fetch_recent_filings(cik, ua)
        except Exception as e:
            logger.warning(f"[form4] {cik} fetch 실패: {e}")
            continue

        for f in filings:
            if f.form != "4":
                continue
            if not _is_recent(f.filing_date):
                continue
            if not f.accession:
                continue
            if is_seen_fn(cik, f.accession):
                continue

            parsed = {}
            if parse_xml:
                xml_bytes = await _fetch_form4_xml(cik, f.accession, ua)
                if xml_bytes:
                    parsed = _parse_form4(xml_bytes)

            results.append(Form4Filing(
                subject_cik=cik,
                subject_ticker=ticker,
                subject_name=name,
                accession=f.accession,
                form=f.form,
                filing_date=f.filing_date,
                primary_desc=f.primary_desc or "",
                tx_type=parsed.get("tx_type", "UNKNOWN"),
                direction=parsed.get("direction", "UNKNOWN"),
                reporter_name=parsed.get("reporter_name", ""),
                reporter_title=parsed.get("reporter_title", ""),
                is_director=parsed.get("is_director", False),
                is_officer=parsed.get("is_officer", False),
                is_ten_percent_owner=parsed.get("is_ten_percent_owner", False),
                total_value_usd=parsed.get("total_value_usd"),
                total_shares=parsed.get("total_shares"),
            ))
    return results
