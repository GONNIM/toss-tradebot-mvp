"""Meme Watch ticker 필터 — ETF/펀드 제외 (Phase 3-A).

이유: apewisdom mention 1위가 SPY/QQQ 같은 시장 ETF — 매일 언급 폭증이라
밈주 candidate 가 아닌데도 score 1.0 BLAZING. 명시 블랙리스트로 제외.

대상:
- 광범위 지수 ETF (SPY/QQQ/DIA/IWM/VTI)
- 섹터/스타일 ETF (XLF/SOXL/ARKK)
- 레버리지 ETF (TQQQ/SQQQ/SPXL)
- 채권/원자재/변동성 ETF
- 국가별 ETF
- 크립토 ETF
- 인컴 펀드
"""
from __future__ import annotations

ETF_BLACKLIST: frozenset[str] = frozenset({
    # 광범위 지수
    "SPY", "VOO", "IVV", "SPLG", "VV",       # S&P 500
    "QQQ", "QQQM", "ONEQ",                    # NASDAQ 100
    "DIA",                                     # Dow Jones
    "IWM", "IJR", "VB", "IWN", "IWO",         # Russell 2000 / small cap
    "VTI", "ITOT", "VOOG", "MGK",             # Total Market
    "EFA", "VEA", "ACWI", "ACWX", "VEU",      # Developed International
    "EEM", "VWO", "IEMG",                     # Emerging Markets
    # 국가별
    "FXI", "MCHI", "EWJ", "EWZ", "EWG", "EWU", "INDA", "EWY", "EWT",
    # Sector
    "XLF", "XLK", "XLE", "XLV", "XLY", "XLI",
    "XLP", "XLU", "XLB", "XLRE", "XLC",
    "XHB", "XME", "XOP", "XBI", "XAR",
    # Industry / Theme
    "SMH", "SOXX", "SOXL", "SOXS",            # 반도체
    "ARKK", "ARKW", "ARKG", "ARKQ", "ARKF",   # ARK
    "ICLN", "TAN", "PBW",                     # Clean energy
    "ROBO", "BOTZ",                           # Robotics/AI
    "JETS", "AWAY",                           # Travel
    # 레버리지 / Inverse
    "TQQQ", "SQQQ", "UPRO", "SPXL", "SPXU", "SPXS",
    "TMF", "TMV", "FAS", "FAZ", "LABU", "LABD",
    "TNA", "TZA", "URTY", "SRTY",
    # 채권 / 금리
    "TLT", "IEF", "SHY", "BND", "AGG", "BIL", "GOVT",
    "HYG", "JNK", "LQD", "EMB",
    "TBT", "TBF",
    # 원자재 / 통화
    "GLD", "GDX", "GDXJ", "SLV", "USO", "UNG", "UCO", "DBC",
    "UUP", "FXY", "FXE",
    # 변동성
    "VXX", "UVXY", "VIXY", "SVXY", "TVIX",
    # 리츠 / 인컴
    "VNQ", "IYR", "REIT", "SCHD", "VYM", "DVY", "DGRO", "NOBL",
    "JEPI", "JEPQ", "QYLD", "RYLD",
    # 크립토 / Bitcoin
    "BITO", "BITX", "IBIT", "FBTC", "ARKB", "BTCO", "EZBC",
    "ETHA", "ETHE", "FETH",
    # 기타
    "QQQI", "SPYI",
})


def is_blacklisted(ticker: str) -> bool:
    """ETF/펀드 블랙리스트 매칭 — 대소문자 무관."""
    if not ticker:
        return False
    return ticker.strip().upper() in ETF_BLACKLIST
