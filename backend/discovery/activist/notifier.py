"""Activist Radar Telegram 알림 포맷.

프리픽스: [ACTIVIST-{country} · <filer_short> · <target>]
"""
from __future__ import annotations

import logging

from backend.services.notifier import TelegramNotifier

from . import alerts as alert_priority
from .state import ActivistEvent
from .universe import Activist

logger = logging.getLogger(__name__)

_INTENSITY_ICON = {
    "REGIME_CHANGE": "🚨",  # Phase D · 13G→13D 전환
    "INSIDER": "👤",         # Phase E · 임원 매매 (activism 진입 종목)
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
    direction: str = "",   # INSIDER 세분화용
) -> bool:
    """우선순위 판정 후 발송. min_level 미달 시 skip (False 반환)."""
    priority = alert_priority.intensity_to_priority(evt.intensity_label, direction)
    if not alert_priority.should_send(priority):
        return False

    icon = _INTENSITY_ICON.get(evt.intensity_label, "📣")
    p_icon = alert_priority.PRIORITY_ICON.get(priority, "")
    tag = f"[ACTIVIST-{evt.country} · {_short(evt.filer_name, 18)} · {evt.form}]"
    title = f"{p_icon}{icon} {tag} {evt.intensity_label} ({evt.score})"

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
        "REGIME_CHANGE": "→ 🚨 passive → active 태세 전환 · 최상 신호 · 즉시 검토",
        "INSIDER":       "→ 👤 activism 진입 종목의 임원 매매 · 동조/이탈 방향 상세 확인",
        "CRITICAL":      "→ 즉시 검토 · Wolf Pack 또는 신규 SC 13D 강 신호",
        "STRONG":        "→ 관심 · 지분 변동·수정본",
        "WATCH":         "→ 참고 · passive 성 · 저강도",
        "NOTE":          "→ 기록",
    }.get(evt.intensity_label)
    if hint:
        lines.append(hint)

    body = "\n".join(lines)
    ok = await notifier.send_info(title, body)

    # ─── Execution Layer 라우팅 (v2 트랙 C · Phase 1) ───
    # CRITICAL/REGIME_CHANGE/STRONG 만 매수 시그널 · WATCH/NOTE 는 정보성
    _INTENSITY_STRENGTH = {
        "REGIME_CHANGE": 95,
        "CRITICAL":      90,
        "STRONG":        70,
        "INSIDER":       60 if direction == "buy" else 40,
    }
    if ok and evt.target_ticker:
        strength = _INTENSITY_STRENGTH.get(evt.intensity_label)
        if strength is not None:
            try:
                from backend.execution.signal_router import (
                    SignalEvent as _SignalEvent,
                    get_signal_router,
                )
                router = get_signal_router()
                if router:
                    await router.route(
                        _SignalEvent(
                            ticker=evt.target_ticker,
                            action="buy",
                            strength=strength,
                            source="activist",
                            signal_id=f"activist-{evt.country}-{evt.accession}-{evt.form}",
                            metadata={
                                "filer": evt.filer_name,
                                "form": evt.form,
                                "intensity": evt.intensity_label,
                                "filing_date": evt.filing_date,
                                "insider_direction": direction,
                            },
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[activist] router 실패 — %s", exc)
    return ok


async def send_wolf_pack(
    notifier: TelegramNotifier,
    group,   # wolf_pack.WolfPackGroup
    is_new: bool,
    new_filer_name: str = "",
) -> bool:
    """Wolf Pack 형성·강화 알림 전용 포맷 · 우선순위 판정.

    is_new=True: 첫 형성 (2번째 activist 진입)
    is_new=False: 강화 (activist 추가 진입)
    """
    priority = alert_priority.intensity_to_priority(group.intensity_label)
    if not alert_priority.should_send(priority):
        return False

    style_icon = {
        "CRITICAL_PACK": "🐺🐺🌋",
        "STRONG_PACK":   "🐺🔥",
        "PACK":          "🐺",
    }.get(group.intensity_label, "🐺")
    p_icon = alert_priority.PRIORITY_ICON.get(priority, "")

    kind = "형성" if is_new else "강화"
    title = (
        f"{p_icon}{style_icon} [WOLF PACK · {group.country} · {group.target_ticker}] "
        f"{group.intensity_label} ({group.intensity_score}) {kind}"
    )

    first = group.entries[0] if group.entries else None
    last = group.entries[-1] if group.entries else None

    lines = [
        f"🎯 {(group.target_desc or '')[:60]} ({group.target_ticker})",
        f"👥 {group.activist_count}명 activist · Tier1 {group.tier1_count}명 · {group.days_span}일 span",
    ]
    if first:
        lines.append(
            f"🥇 최초: T{first.tier} {first.filer_name} · {first.form} · {first.filing_date}"
        )
    if last and last.filer_key != (first.filer_key if first else ""):
        lines.append(
            f"⚡ 최신: T{last.tier} {last.filer_name} · {last.form} · {last.filing_date}"
        )
    if new_filer_name and new_filer_name != (last.filer_name if last else ""):
        lines.append(f"➕ 이번 추가: {new_filer_name}")

    hint = {
        "CRITICAL_PACK": "→ 🌋 Tier1 3명+ 동시 진입 · 매매 개시 확률 최상",
        "STRONG_PACK":   "→ 🔥 다중 activist 동시 · 확신 강 신호",
        "PACK":          "→ ⚠️ 관심 · 2명 이상 activist 동시 진입",
    }.get(group.intensity_label)
    if hint:
        lines.append(hint)

    body = "\n".join(lines)
    ok = await notifier.send_info(title, body)

    # ─── Execution Layer 라우팅 (v2 트랙 C · Phase 1) ───
    # Wolf Pack 형성/강화 시 매수 시그널 · CRITICAL_PACK 이 최고 강도
    _PACK_STRENGTH = {
        "CRITICAL_PACK": 100,
        "STRONG_PACK":   85,
        "PACK":          70,
    }
    if ok and group.target_ticker:
        strength = _PACK_STRENGTH.get(group.intensity_label)
        if strength is not None:
            try:
                from backend.execution.signal_router import (
                    SignalEvent as _SignalEvent,
                    get_signal_router,
                )
                router = get_signal_router()
                if router:
                    await router.route(
                        _SignalEvent(
                            ticker=group.target_ticker,
                            action="buy",
                            strength=strength,
                            source="activist",
                            signal_id=f"wolf-{group.country}-{group.target_ticker}-{kind}-{group.days_span}",
                            metadata={
                                "wolf_pack": True,
                                "intensity": group.intensity_label,
                                "activist_count": group.activist_count,
                                "tier1_count": group.tier1_count,
                                "days_span": group.days_span,
                                "kind": kind,
                            },
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[activist·wolf] router 실패 — %s", exc)
    return ok
