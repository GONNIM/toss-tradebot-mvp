"""WEN VIP 환경변수 로딩 — 매수가·목표·손절 파라미터.

env 미설정 시 감시 비활성 (엔진 skip). AVG_PRICE 필수, 나머지는 기본값.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from backend.services import config as env_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VipConfig:
    enabled: bool
    ticker: str  # 네이버 reuters code (예: WEN.O)
    avg_price: float
    qty: float
    tp1_pct: float
    tp2_pct: float
    stop_pct: float          # 음수 (예: -0.05)
    trail_arm_pct: float
    trail_giveback_pct: float
    poll_sec_market: int
    poll_sec_after: int
    trian_poll_sec: int
    trian_cik: str
    sec_ua: str

    @property
    def is_active(self) -> bool:
        """감시 활성 조건: enabled + avg_price > 0."""
        return self.enabled and self.avg_price > 0.0


def _get_float(key: str, default: float) -> float:
    raw = env_config.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"[vip.config] {key}={raw!r} float 변환 실패 — 기본값 {default}")
        return default


def _get_int(key: str, default: int) -> int:
    raw = env_config.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"[vip.config] {key}={raw!r} int 변환 실패 — 기본값 {default}")
        return default


def _get_bool(key: str, default: bool) -> bool:
    raw = env_config.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load() -> VipConfig:
    return VipConfig(
        enabled=_get_bool("WEN_VIP_ENABLED", False),
        ticker=(env_config.get("WEN_VIP_TICKER") or "WEN.O").strip(),
        avg_price=_get_float("WEN_VIP_AVG_PRICE", 0.0),
        qty=_get_float("WEN_VIP_QTY", 0.0),
        tp1_pct=_get_float("WEN_VIP_TP1_PCT", 0.07),
        tp2_pct=_get_float("WEN_VIP_TP2_PCT", 0.15),
        stop_pct=_get_float("WEN_VIP_STOP_PCT", -0.05),
        trail_arm_pct=_get_float("WEN_VIP_TRAIL_ARM_PCT", 0.10),
        trail_giveback_pct=_get_float("WEN_VIP_TRAIL_GIVEBACK_PCT", 0.03),
        poll_sec_market=_get_int("WEN_VIP_POLL_SEC_MARKET", 30),
        poll_sec_after=_get_int("WEN_VIP_POLL_SEC_AFTER", 300),
        trian_poll_sec=_get_int("WEN_VIP_TRIAN_POLL_SEC", 300),
        trian_cik=(env_config.get("WEN_VIP_TRIAN_CIK") or "0001345471").strip(),
        sec_ua=(
            env_config.get("SEC_EDGAR_UA")
            or "Suauncle-Research suauncle-contact@gmail.com"
        ).strip(),
    )
