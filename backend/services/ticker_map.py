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
    # Korea 대기업 · Serenity 자주 언급
    "SAMSUNG": "005930.KS",
    "SKHYNIX": "000660.KS",
    "SK HYNIX": "000660.KS",
    "SKHY": "000660.KS",
    "SKHYV": "HXSCL",            # SK Hynix OTC ADR 실 심볼
    "SKHYY": "HXSCL",
    "SMHSF": "010140.KS",        # Samsung Heavy Industries
    "SKC": "011790.KS",          # SKC 소재
    # 상해 STAR (688xxx) · 자동 규칙(6자리→.KS)이 잘못 잡음 · 명시 override
    "688017": "688017.SS",
    # Compound semi / photonics / memory · US·유럽·아시아 대기업
    "AIXA": "AIXA.DE",           # AIXTRON · Germany
    "AJINY": "AJINY",            # Ajinomoto ADR (OTC · yfinance 커버 확인)
    "ALCHIP": "3661.TW",         # Alchip TW
    "ALAB": "ALAB",              # Astera Labs US
    "AUO": "2409.TW",            # AU Optronics TW
    "ASE": "3711.TW",            # ASE Group TW
    "ASEH": "ASX",               # ASE Holdings ADR
    "ASMC": "ASML",              # ASML NL · alias
    "ASML": "ASML",
    "ASMPT": "0522.HK",          # ASM Pacific HK
    "BESI": "BESI.AS",           # BE Semiconductor NL
    "DISCO": "6146.T",           # Disco Corp JP
    "FURUKAWA": "5801.T",        # Furukawa Electric JP
    "HARMONICDRIVE": "6324.T",   # Harmonic Drive JP
    "IQE": "IQE.L",              # IQE LSE
    "LPKF": "LPKF.DE",           # LPKF Laser · Xetra
    "MACRONIX": "2337.TW",       # Macronix
    "MTK": "2454.TW",            # MediaTek
    "NIDGY": "NJDCY",            # Nidec ADR 실 심볼
    "RESONAC": "4004.T",         # Resonac JP
    "RIBER": "ALRIB.PA",         # Riber SA · Paris
    "SHUNSIN": "6451.TW",        # Shunsin Technology TW
    "SILEX": "SLX.AX",           # Silex Systems · Sydney
    "SOI": "SOI",                # Soitec ADR
    "SOITEC": "SOIT.PA",         # Soitec Paris
    "TSEM": "TSEM",              # Tower Semi (Israel)
    "TOSOH": "4042.T",           # Tosoh Corp JP
    "TOWA": "6315.T",            # Towa Corp JP
    "ULVAC": "6728.T",           # Ulvac JP
    "WIN": "3105.TWO",           # WIN Semiconductors · 대만 장외 (TPEx) · 1102-07: .TW 는 0행
    "WINBOND": "2344.TW",        # Winbond Electronics TW
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
    # ─── 1102-07 (2026-11-03) · 서버 실패 종목 · 로컬 yfinance longName 대조로 확정 ───
    # 같은 4자리 번호가 대만·일본 둘 다 있는 경우가 있어 자동 추측하지 않고 여기 적는다.
    "3374": "3374.TWO",          # Xintec (TPEx) · 3374.T 는 Naigai Tec (다른 회사)
    "XINTEC": "3374.TWO",
    "3675": "3675.TWO",          # Eris Technology (TPEx) · 3675.T 는 Cross Marketing
    "3675.TW": "3675.TWO",
    "6693": "6693.TWO",          # Inergy Technology (TPEx)
    "6693.TW": "6693.TWO",
    "7712": "7712.TWO",          # Potens Semiconductor (TPEx)
    "7712.TW": "7712.TWO",
    "8147": "8147.TWO",          # Nextronics Engineering (TPEx) · 8147.T 는 Tomita
    "NEXTRONICS": "8147.TWO",
    "3625": "3625.TWO",          # C-Tech United (TPEx) · 3625.T 는 Techfirm
    "6976": "6976.T",            # Taiyo Yuden (JP) · 6976.TWO 는 Acepodia (다른 회사)
    "6976.TW": "6976.T",
    "6315": "6315.T",            # TOWA (JP)
    "6324": "6324.T",            # Harmonic Drive Systems (JP)
    "4092": "4092.T",            # Nippon Chemical Industrial (JP)
    "2768": "2768.T",            # Sojitz (JP)
    "2481": "2481.TW",           # PANJIT (TW) · 2481.T 는 Townnews-Sha
    "KYEC": "2449.TW",           # King Yuan Electronics
    "PSMC": "6770.TW",           # Powerchip Semiconductor Manufacturing
    "ETRON": "5351.TWO",         # Etron Technology (TPEx)
    "ESMT": "3006.TW",           # Elite Semiconductor Microelectronics
}

# 「거래소:번호」 원문 (TPEX:3625 · TYO:6976) → 접미어 · 1102-07
_EXCHANGE_PREFIX: dict[str, str] = {
    "TPEX": ".TWO", "TWO": ".TWO",
    "TPE": ".TW", "TWSE": ".TW",
    "TYO": ".T", "TSE": ".T",
    "KRX": ".KS",
}

# ─── Private / 브랜드명 / 미상장 · yfinance 호출 스킵 ────────────
_PRIVATE_OR_BRAND: frozenset[str] = frozenset({
    # Robotics · humanoid (거의 대부분 사설)
    "AGILITY", "APPTRONIK", "FIGURE", "BOSTONDYNAMICS", "UNITREE", "LEADERDRIVE",
    "XBOT",
    # Optical/CPO · China private
    "INNOLIGHT", "AYAR",
    # AI · foundation model 사설
    "OPENAI",
    # Memory · IPO 예정
    "KIOXIA", "CXMT",
    # 부품·소재 사설
    "ADVAN", "ALRIB", "AURO", "AUROS", "CMXT", "CNEX", "CRBS",
    "ENNR", "ENPL", "ENPLAS", "FOCI", "FON", "GNC", "HARPO",
    "HAYL", "HB", "HPELF",
    "MSSCORP", "MSSCORPS",
    "OE SOLUTIONS", "SAMYANG NC CHEM", "YC CHEM",
    "RASA", "RIBER".upper() if False else "RIBER_SKIP_PLACEHOLDER",   # RIBER 는 매핑됨 · placeholder 제거
    # 일반 카테고리·약어·지수 (실 티커 아님)
    "CPO", "FIT", "KOSPI", "MEMORY", "PHOTONICS", "SPACE",
    # Unknown / 오타 / duplicate (매핑 불가)
    "UNKNOWN", "P4O", "PLY", "PROJ", "SHA0", "SHUN", "SSDI",
    "TYNT", "VNP", "WIM", "WINS", "WSEM", "WSTM", "XINT",
    "LPK", "LPKK", "MACOM",
    # 상장폐지
    "SIVB",   # Silicon Valley Bank 파산 2023
    # 명확 미상장·회사명 축약 (Serenity 원문 그대로)
    "KCC", "KLA",   # KCC 는 국내 상장 (002380.KS) · KLA 는 KLAC · 필요 시 명시 매핑 승격
    # class share (특수 · A/B share · yfinance 미지원)
    "HPS.A", "HSP.A",
    # 800V · 규격 이름 · 티커 아님
    "800V",
    # 1102-07: 비상장 (YMTC) · 합병 상장폐지 (SPIL → ASE 2018) · 이름만으로 회사를 못 정함 (WALSIN 1605/2492 · SUMIMOTO · MACRO)
    "YMTC", "SPIL", "WALSIN", "SUMIMOTO", "MACRO",
})
# placeholder 자체는 skip 리스트에서 노출되지 않아야 · rebuild
_PRIVATE_OR_BRAND = frozenset(x for x in _PRIVATE_OR_BRAND if x != "RIBER_SKIP_PLACEHOLDER")


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

    # 「거래소:번호」 (1102-07) · 번호가 명시 매핑에 있으면 그것을 따른다
    if ":" in ticker:
        exch, _, code = ticker.partition(":")
        if code in _YFINANCE_SYMBOL:
            return _YFINANCE_SYMBOL[code]
        suffix = _EXCHANGE_PREFIX.get(exch)
        if suffix and code:
            return code + suffix

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
