"""Activist Radar Telegram 알림 포맷.

프리픽스: [ACTIVIST-{country} · <filer_short> · <target>]
"""
from __future__ import annotations

import logging

from backend.services.notifier import TelegramNotifier

from .state import ActivistEvent
from .universe import Activist

logger = logging.getLogger(__name__)

_INTENSITY_ICON = {
    "CRITICAL": "🌋",
    "STRONG": "🔥",
    "WATCH": "⚠️",
    "NOTE": "📝",
}


def _short(name: str, limit: int = 20) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


async def send_event(
    notifier: TelegramNotifier,
    evt: ActivistEvent,
) -> bool:
    icon = _INTENSITY_ICON.get(evt.intensity_label, "📣")
    tag = f"[ACTIVIST-{evt.country} · {_short(evt.filer_name, 18)} · {evt.form}]"
    title = f"{icon} {tag} {evt.intensity_label} ({evt.score})"

    lines = [
        f"Filer: {evt.filer_name}",
        f"Form:  {evt.form}",
        f"Filing date: {evt.filing_date}",
        f"Accession:   {evt.accession}",
        f"Target: {evt.target_desc or '(desc 없음 · 상세 확인 필요)'}",
    ]
    if evt.target_ticker:
        lines.append(f"Ticker: {evt.target_ticker}")
    if evt.wolf_pack:
        lines.append(f"🐺 Wolf Pack (30d): {', '.join(evt.wolf_pack)}")

    hint = {
        "CRITICAL": "→ 즉시 검토 · Wolf Pack 또는 신규 SC 13D 강 신호",
        "STRONG":   "→ 관심 · 지분 변동·수정본",
        "WATCH":    "→ 참고 · passive 성 · 저강도",
        "NOTE":     "→ 기록",
    }.get(evt.intensity_label)
    if hint:
        lines.append(hint)

    body = "\n".join(lines)
    return await notifier.send_info(title, body)
