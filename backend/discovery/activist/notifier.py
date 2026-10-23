"""Activist Radar Telegram 알림 포맷.

제목: `<아이콘> 행동주의 · <강한/참고 신호> · <종목> <점수>점` (1023-05 · 풀이는 alert_text)
"""
from __future__ import annotations

import logging

from backend.services import alert_text as at
from backend.services.notification_settings import activist_category
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


def _filing_url(country: str, cik, accession: str) -> str:
    if country == "KR":
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={accession}" if accession else ""
    from .hints import sec_filing_detail_url

    return sec_filing_detail_url(cik, accession)


def _target_text(desc: str, ticker) -> str:
    desc = _short(desc or "대상 회사 이름 없음", 40)
    return f"{at.esc(desc)}({at.esc(ticker)})" if ticker else at.esc(desc)


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
    category = activist_category(evt.intensity_label)
    who = evt.target_ticker or _short(evt.target_desc or evt.filer_name, 14)
    title = at.title(category, at.esc(f"{who} {evt.score}점"), icon)

    lines = [
        f"{at.esc(_short(evt.filer_name, 40))} → {_target_text(evt.target_desc, evt.target_ticker)}",
        f"{at.sec_form_text(evt.form)} · {at.md(evt.filing_date)}",
        f"신호: {at.ACTIVIST_LEVEL.get(evt.intensity_label, at.esc(evt.intensity_label))} ({evt.score}점)",
    ]
    if evt.wolf_pack:
        lines.append(f"30일 안 함께 들어온 운용사: {at.esc(', '.join(evt.wolf_pack))}")
    url = _filing_url(evt.country, evt.target_cik, evt.accession)
    if url:
        lines.append(f"원문: {url}")
    lines.append(at.link(category))

    body = "\n".join(lines)
    ok = await notifier.send_info(title, body, category=activist_category(evt.intensity_label))

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
                # Super Signal 원천 (Router 무관 · 항상 로깅)
                try:
                    from backend.discovery.super_signal.signal_hit import record_hit
                    await record_hit(
                        ticker=evt.target_ticker,
                        source="activist",
                        signal_id=f"activist-{evt.country}-{evt.accession}-{evt.form}",
                        action="buy",
                        strength=strength,
                        metadata={
                            "filer": evt.filer_name,
                            "form": evt.form,
                            "intensity": evt.intensity_label,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[activist] signal_hit 실패 — %s", exc)
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

    category = activist_category(group.intensity_label)
    kind = "형성" if is_new else "강화"
    title = at.title(category, at.esc(f"{group.target_ticker} 여러 운용사 {kind}"), "🐺")

    first = group.entries[0] if group.entries else None
    last = group.entries[-1] if group.entries else None

    lines = [
        _target_text(group.target_desc, group.target_ticker),
        f"30일 안에 {group.activist_count}곳 (상위 운용사 {group.tier1_count}곳) · {group.days_span}일 사이",
    ]
    if first:
        lines.append(f"처음: {at.esc(first.filer_name)} · {at.sec_form_text(first.form)} · {at.md(first.filing_date)}")
    if last and last.filer_key != (first.filer_key if first else ""):
        lines.append(f"최근: {at.esc(last.filer_name)} · {at.sec_form_text(last.form)} · {at.md(last.filing_date)}")
    if new_filer_name and new_filer_name != (last.filer_name if last else ""):
        lines.append(f"이번에 더해짐: {at.esc(new_filer_name)}")
    lines.append(f"신호: {at.ACTIVIST_LEVEL.get(group.intensity_label, at.esc(group.intensity_label))} ({group.intensity_score}점)")
    lines.append(at.link(category))

    body = "\n".join(lines)
    ok = await notifier.send_info(title, body, category=activist_category(group.intensity_label))

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
                # Super Signal 원천 (Wolf Pack 은 activist 소스로 집계)
                try:
                    from backend.discovery.super_signal.signal_hit import record_hit
                    await record_hit(
                        ticker=group.target_ticker,
                        source="activist",
                        signal_id=f"wolf-{group.country}-{group.target_ticker}-{kind}-{group.days_span}",
                        action="buy",
                        strength=strength,
                        metadata={
                            "wolf_pack": True,
                            "intensity": group.intensity_label,
                            "activist_count": group.activist_count,
                            "kind": kind,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[activist·wolf] signal_hit 실패 — %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[activist·wolf] router 실패 — %s", exc)
    return ok
