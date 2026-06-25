"""관세청 cntyMmUtPrviExpAcrs API 클라이언트 (B-2k).

REST GET + XML 응답. 표준 라이브러리만 사용 (lxml 의존성 회피).
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

import httpx

from backend.services import config as svc_config

logger = logging.getLogger(__name__)


# itemUsdAmtNN → 국가 코드 매핑 (기술문서 Table 4 기준)
COUNTRY_CODES: dict[str, str] = {
    "itemUsdAmt00": "TOTAL",
    "itemUsdAmt01": "CN",   # 중국
    "itemUsdAmt02": "US",   # 미국
    "itemUsdAmt03": "EU",   # 유럽연합
    "itemUsdAmt04": "VN",   # 베트남
    "itemUsdAmt05": "HK",   # 홍콩
    "itemUsdAmt06": "JP",   # 일본
    "itemUsdAmt07": "TW",   # 대만
    "itemUsdAmt08": "IN",   # 인도
    "itemUsdAmt09": "SG",   # 싱가포르
    "itemUsdAmt10": "MY",   # 말레이시아
}


@dataclass(frozen=True)
class CountryAmount:
    country_code: str        # 'TOTAL' / 'CN' / 'US' / ...
    usd_amount_thousand: float


@dataclass(frozen=True)
class CustomsInterimRow:
    month: str               # 'YYYY-MM'
    period: str              # '01~10' / '01~20' / '01~31'
    amounts: list[CountryAmount]


class CustomsInterimError(Exception):
    """관세청 API 호출/파싱 실패."""


class CustomsInterimClient:
    """관세청 10일 단위 잠정 통계 API 클라이언트."""

    PATH = "/getCntyMmUtPrviExpAcrs"
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key or svc_config.customs_api_key()
        self.endpoint = (endpoint or svc_config.customs_endpoint()).rstrip("/")
        self.timeout = timeout

    async def fetch(
        self,
        strt_yymm: str,
        end_yymm: str,
    ) -> list[CustomsInterimRow]:
        """[strt_yymm, end_yymm] 구간 잠정 통계 — strt/end 는 'YYYYMM' 형식."""
        if not (len(strt_yymm) == 6 and strt_yymm.isdigit()):
            raise CustomsInterimError(f"invalid strt_yymm: {strt_yymm!r}")
        if not (len(end_yymm) == 6 and end_yymm.isdigit()):
            raise CustomsInterimError(f"invalid end_yymm: {end_yymm!r}")

        params = {
            "serviceKey": self.api_key,
            "strtYymm": strt_yymm,
            "endYymm": end_yymm,
        }
        url = f"{self.endpoint}{self.PATH}"
        logger.info(f"[customs] GET {url} {strt_yymm}~{end_yymm}")

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            body = response.text

        return self._parse_xml(body)

    @staticmethod
    def _parse_xml(body: str) -> list[CustomsInterimRow]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as e:
            raise CustomsInterimError(f"XML parse error: {e}") from e

        # 결과 코드 확인
        result_code = root.findtext(".//header/resultCode") or ""
        result_msg = root.findtext(".//header/resultMsg") or ""
        if result_code != "00":
            raise CustomsInterimError(
                f"API error {result_code}: {result_msg}"
            )

        rows: list[CustomsInterimRow] = []
        for item in root.findall(".//body/items/item"):
            month_raw = (item.findtext("priodMon") or "").strip()  # 'YYYYMM'
            period_raw = (item.findtext("priodDt") or "").strip()  # '01~10' 등
            if not month_raw or not period_raw or len(month_raw) != 6:
                continue
            month = f"{month_raw[:4]}-{month_raw[4:6]}"

            amounts: list[CountryAmount] = []
            for xml_tag, country_code in COUNTRY_CODES.items():
                raw_value = item.findtext(xml_tag)
                if raw_value is None:
                    continue
                cleaned = raw_value.strip().replace(",", "").replace(" ", "")
                if not cleaned:
                    continue
                try:
                    amounts.append(
                        CountryAmount(
                            country_code=country_code,
                            usd_amount_thousand=float(cleaned),
                        )
                    )
                except ValueError:
                    logger.warning(
                        f"[customs] {month}/{period_raw}/{country_code} parse fail: {raw_value!r}"
                    )

            if amounts:
                rows.append(
                    CustomsInterimRow(
                        month=month,
                        period=period_raw,
                        amounts=amounts,
                    )
                )

        return rows
