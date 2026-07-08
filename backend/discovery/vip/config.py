"""VIP 환경변수 · JSON override 로딩.

우선순위: `.env` (기본) → `data/vip_overrides.json` (런타임 override).
override 는 UI/API 편집을 위해 프로세스 재시작 없이 tick 마다 재로드된다.

env 미설정 시 감시 비활성. `VIP_AVG_PRICE > 0` + `VIP_ENABLED=true` 조건.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from backend.services import config as env_config

from . import overrides as vip_overrides

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VipConfig:
    enabled: bool
    ticker: str                    # 네이버 reuters code (예: WEN.O)
    company_name: str              # 알림 표기 (예: Wendy's)
    tag: str                       # 태그 프리픽스 (예: WEN → [VIP-WEN · …])
    avg_price: float
    qty: float
    tp1_pct: float
    tp2_pct: float
    stop_pct: float                # 음수 (예: -0.05)
    trail_arm_pct: float
    trail_giveback_pct: float
    poll_sec_market: int
    poll_sec_after: int
    activist_enabled: bool
    activist_cik: str
    activist_name: str
    activist_keywords: List[str] = field(default_factory=list)
    activist_poll_sec: int = 300
    sec_ua: str = "MemeStockResearch/1.0 sung2011103@naver.com"

    @property
    def is_active(self) -> bool:
        return self.enabled and self.avg_price > 0.0

    @property
    def is_activist_active(self) -> bool:
        return (
            self.activist_enabled
            and bool(self.activist_cik)
            and bool(self.activist_keywords)
        )


def _get_float(key: str, default: float) -> float:
    raw = env_config.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"[vip.config] {key}={raw!r} float 실패 — 기본값 {default}")
        return default


def _get_int(key: str, default: int) -> int:
    raw = env_config.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[vip.config] {key}={raw!r} int 실패 — 기본값 {default}")
        return default


def _get_bool(key: str, default: bool) -> bool:
    raw = env_config.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_str(key: str, default: str) -> str:
    raw = env_config.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip()


def _split_keywords(raw: str) -> List[str]:
    return [tok.strip().upper() for tok in raw.split(",") if tok.strip()]


def _derive_tag(ticker: str) -> str:
    """티커에서 태그 자동 추출 — 첫 번째 '.' 앞부분 (WEN.O → WEN)."""
    return ticker.split(".")[0].strip().upper() or "TICKER"


def load() -> VipConfig:
    """env 로 기본값 구성 → JSON overrides 로 activist 관련 필드 override."""
    ticker = _get_str("VIP_TICKER", "WEN.O")
    tag = _get_str("VIP_TAG", _derive_tag(ticker))

    activist_keywords_env = env_config.get("VIP_ACTIVIST_KEYWORDS") or ""
    activist_keywords = _split_keywords(activist_keywords_env)

    over = vip_overrides.load()

    activist_enabled = _get_bool("VIP_ACTIVIST_ENABLED", False)
    activist_cik = _get_str("VIP_ACTIVIST_CIK", "")
    activist_name = _get_str("VIP_ACTIVIST_NAME", "")

    # overrides 적용 (present 만)
    if "activist_enabled" in over:
        activist_enabled = bool(over["activist_enabled"])
    if "activist_cik" in over and over["activist_cik"]:
        activist_cik = str(over["activist_cik"]).strip()
    if "activist_name" in over and over["activist_name"]:
        activist_name = str(over["activist_name"]).strip()
    if "activist_keywords" in over and isinstance(over["activist_keywords"], list):
        activist_keywords = [str(k).strip().upper() for k in over["activist_keywords"] if str(k).strip()]

    return VipConfig(
        enabled=_get_bool("VIP_ENABLED", False),
        ticker=ticker,
        company_name=_get_str("VIP_COMPANY_NAME", ticker),
        tag=tag,
        avg_price=_get_float("VIP_AVG_PRICE", 0.0),
        qty=_get_float("VIP_QTY", 0.0),
        tp1_pct=_get_float("VIP_TP1_PCT", 0.07),
        tp2_pct=_get_float("VIP_TP2_PCT", 0.15),
        stop_pct=_get_float("VIP_STOP_PCT", -0.05),
        trail_arm_pct=_get_float("VIP_TRAIL_ARM_PCT", 0.10),
        trail_giveback_pct=_get_float("VIP_TRAIL_GIVEBACK_PCT", 0.03),
        poll_sec_market=_get_int("VIP_POLL_SEC_MARKET", 30),
        poll_sec_after=_get_int("VIP_POLL_SEC_AFTER", 300),
        activist_enabled=activist_enabled,
        activist_cik=activist_cik,
        activist_name=activist_name,
        activist_keywords=activist_keywords,
        activist_poll_sec=_get_int("VIP_ACTIVIST_POLL_SEC", 300),
        sec_ua=_get_str(
            "SEC_EDGAR_UA",
            "Suauncle-Research suauncle-contact@gmail.com",
        ),
    )
