"""VIP 알림 포맷팅 — 기존 [[TelegramNotifier]] send_info 재활용.

프리픽스: [VIP-WEN · <이벤트>]  (기존 밈주 봇 채널 공유)
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services.notifier import TelegramNotifier

from .config import VipConfig
from .position import Event
from .trian_tracker import Filing

logger = logging.getLogger(__name__)

_EVENT_ICON = {
    "TP1": "🎯",
    "TP2": "🎯🎯",
    "STOP_APPROACH": "🛑",
    "TRAIL_ARMED": "🔒",
    "TRAIL_GIVEBACK": "📉",
    "TRIAN_FILING": "🕵️",
}

_EVENT_HINT = {
    "TP1": "1차 부분 익절 검토",
    "TP2": "2차 익절 · trailing stop 상향",
    "STOP_APPROACH": "손절 라인 접근",
    "TRAIL_ARMED": "trailing stop 활성 — peak 추적 시작",
    "TRAIL_GIVEBACK": "peak 대비 giveback 발생 · 잠금 검토",
    "TRIAN_FILING": "Trian Partners 신규 필링 감지",
}


def _fmt_price(v: float) -> str:
    return f"{v:.2f}"


def _fmt_pct(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v * 100:.2f}%"


async def send_position_event(
    notifier: TelegramNotifier,
    event: Event,
    cfg: VipConfig,
) -> bool:
    icon = _EVENT_ICON.get(event.name, "📣")
    title = f"{icon} [VIP-WEN · {event.name}] Wendy's {_fmt_price(event.current_price)} USD ({_fmt_pct(event.pnl)})"
    lines = [
        f"진입 {_fmt_price(cfg.avg_price)} → 현재 {_fmt_price(event.current_price)}",
        f"P&L {_fmt_pct(event.pnl)}",
    ]
    if cfg.qty > 0:
        pnl_usd = (event.current_price - cfg.avg_price) * cfg.qty
        lines.append(f"수량 {cfg.qty:g} · 손익 {pnl_usd:+.2f} USD")
    hint = _EVENT_HINT.get(event.name)
    if hint:
        lines.append(f"→ {hint}")
    body = "\n".join(lines)
    return await notifier.send_info(title, body)


async def send_trian_filing(
    notifier: TelegramNotifier,
    filing: Filing,
) -> bool:
    icon = _EVENT_ICON["TRIAN_FILING"]
    title = (
        f"{icon} [VIP-WEN · TRIAN_FILING] {filing.form} · {filing.filing_date}"
    )
    body = "\n".join(
        [
            f"Trian Fund Management L.P. 신규 필링 감지",
            f"Form: {filing.form}",
            f"Accession: {filing.accession}",
            f"Doc: {filing.primary_doc}",
            f"Desc: {filing.primary_desc}",
            f"→ {_EVENT_HINT['TRIAN_FILING']}",
        ]
    )
    return await notifier.send_info(title, body)
