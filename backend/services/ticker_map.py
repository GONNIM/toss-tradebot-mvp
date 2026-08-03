"""Ticker 심볼 매핑 · Phase L5 · L9 확장 (2026-08-03).

Serenity signals 는 X 트윗 추출 원문 심볼 · yfinance 표준 심볼로 매핑.

카테고리
    1. 자동 접미어 규칙 (한국 6자리 → .KS · 대만 4자리 → .TW · 명시 매핑 우선)
    2. 명시 매핑 (US ADR · 유럽 · 홍콩 · 일본 대기업)
    3. Private / 브랜드명 / 미상장 skip 리스트 (yfinance 호출 안 함)

원본: docs/plans/serenity-integration/03-implementation-plan.md §L5.
Phase L9 (2026-08-03) 확장 · 서버 실 실패 티커 60개 분석 기반.
"""
from __future__ import annotations

import re

# ─── 명시 매핑 · 원문 심볼 → yfinance ─────────────────────────────
_YFINANCE_SYMBOL: dict[str, str] = {
    # Stockholm (SEK-listed)
    "SIVE": "SIVE.ST",
    # Korea · KRX (트윗 원문이 KQ 로 오는 경우 KS 로 매핑)
    "138080.KQ": "138080.KS",
    # US ADR · 있는 그대로
    "SKHYV": "SKHYV",
    "SKHY": "000660.KS",
    "SKHYNIX": "000660.KS",
    # Compound semi / photonics · US·유럽·아시아 대기업
    "AIXA": "AIXA.DE",           # AIXTRON · Germany
    "AJINY": "AJINY",            # Ajinomoto ADR
    "ALCHIP": "3661.TW",         # Alchip TW
    "ALAB": "ALAB",              # Astera Labs US
    "AUO": "2409.TW",            # AU Optronics TW
    "ASE": "3711.TW",            # ASE Group TW (adr 별도)
    "ASEH": "ASX",               # ASE Holdings ADR
    "ASMC": "ASML",              # ASML NL · alias
    "ASML": "ASML",
    "ASMPT": "0522.HK",          # ASM Pacific HK
    "BESI": "BESI.AS",           # BE Semiconductor NL
    "DISCO": "6146.T",           # Disco Corp JP
    "FURUKAWA": "5801.T",        # Furukawa Electric JP
    "HARMONICDRIVE": "6324.T",   # Harmonic Drive JP
    "IQE": "IQE.L",              # IQE LSE
    "SOI": "SOI",                # Soitec Euronext (US ADR)
    "SOITEC": "SOIT.PA",         # Soitec Paris
    "TSEM": "TSEM",              # Tower Semi (Israel)
    "XFAB": "XFAB.PA",           # X-Fab
    "COHR": "COHR",
    "POET": "POET",
    "LITE": "LITE",
    "AAOI": "AAOI",
    "NBIS": "NBIS",
    "AXTI": "AXTI",
    "CRWV": "CRWV",
    "IREN": "IREN",
    "CIFR": "CIFR",
    "WULF": "WULF",
    "CCXI": "CCXI",
    "AEHR": "AEHR",
    "MRVL": "MRVL",
    "AVGO": "AVGO",
    "MTSI": "MTSI",
    "GFS": "GFS",
    "JBL": "JBL",
    "LPK": "LPK",
    "RDDT": "RDDT",
    "SNDK": "SNDK",
    "MU": "MU",
    "AMD": "AMD",
    "NVDA": "NVDA",
    "INTC": "INTC",
    "META": "META",
    "MSFT": "MSFT",
    "AMZN": "AMZN",
    "GOOGL": "GOOGL",
    "GOOG": "GOOG",
    "BE": "BE",
    "VST": "VST",
    "CEG": "CEG",
    "PWR": "PWR",
    "ETN": "ETN",
    "XLU": "XLU",
    "RKLB": "RKLB",
    "ASTS": "ASTS",
    "SPCX": "SPCX",
}

# ─── Private / 브랜드명 / 미상장 · yfinance 호출 스킵 ────────────
_PRIVATE_OR_BRAND: frozenset[str] = frozenset({
    # Robotics · humanoid (거의 대부분 사설)
    "AGILITY", "APPTRONIK", "FIGURE", "BOSTONDYNAMICS",
    # Optical/CPO · China private
    "INNOLIGHT", "AYAR",
    # Memory · IPO 예정
    "KIOXIA", "CXMT",
    # 부품·소재 사설
    "ADVAN", "ALRIB", "AURO", "AUROS", "CMXT", "CNEX", "CRBS",
    "ENNR", "ENPL", "ENPLAS", "FOCI", "FON", "GNC", "HARPO",
    "HAYL", "HB", "HPELF",
    # 일반 카테고리·약어 (실 티커 아님)
    "CPO", "FIT",
    # 명확 미상장·회사명 축약 (Serenity 원문 그대로)
    "KCC", "KLA",   # KCC 는 국내 상장 (002380.KS) · KLA 는 KLAC · 필요 시 명시 매핑 승격
    # class share (특수 · A/B share)
    "HPS.A", "HSP.A",
    # 800V · 규격 이름 · 티커 아님
    "800V",
})


def _auto_suffix(ticker: str) -> str | None:
    """자동 접미어 규칙 (명시 매핑 없을 때만 fallback).

    - 6자리 숫자 → KRX (.KS)
    - 4자리 숫자 → 대만 (.TW) or 일본 (.T) · 대만 우선 (Serenity 도메인)
    - 3~5자리 숫자 → 일본 (.T)
    - .KQ 접미어 → .KS (KRX Yahoo 미지원)
    - .TW/.T/.HK 접미어 → 그대로
    """
    if ticker.endswith(".KQ"):
        return ticker[:-3] + ".KS"
    if re.fullmatch(r"\d{6}", ticker):
        return ticker + ".KS"
    if re.fullmatch(r"\d{4}", ticker):
        return ticker + ".TW"
    if re.fullmatch(r"\d{5}", ticker):
        return ticker + ".T"
    # 이미 접미어 있는 경우 그대로 유지
    if "." in ticker:
        return ticker
    return None


def to_yfinance_symbol(raw: str) -> str:
    """트윗 원문 티커 → yfinance 심볼.

    우선순위:
      1. private/브랜드명 skip 리스트 → 원문 그대로 (호출 시 실패 유도)
      2. 명시 매핑
      3. 자동 접미어 규칙
      4. 대문자 정규화 후 그대로 (미국 US 티커 가정)
    """
    if not raw:
        return raw
    ticker = raw.strip().upper()

    # private / 브랜드명 · 원문 그대로 반환 (스냅샷 실행 시 is_private 헬퍼 참조)
    if ticker in _PRIVATE_OR_BRAND:
        return ticker

    if ticker in _YFINANCE_SYMBOL:
        return _YFINANCE_SYMBOL[ticker]

    auto = _auto_suffix(ticker)
    if auto:
        return auto

    return ticker


def is_private_or_brand(raw: str) -> bool:
    """yfinance 호출 스킵 여부. 사설·브랜드명·규격 이름 판별."""
    if not raw:
        return True
    return raw.strip().upper() in _PRIVATE_OR_BRAND


def register_mapping(raw: str, yahoo: str) -> None:
    """런타임 매핑 확장 (테스트·1회성 override)."""
    _YFINANCE_SYMBOL[raw.strip().upper()] = yahoo.strip()
