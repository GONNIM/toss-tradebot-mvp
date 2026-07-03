"""Meme Watch Telegram 알림 (Phase 6).

Intensity ≥ 8.0 (🌋 ERUPTING) 또는 Score ≥ 1.0 (🔥🔥 BLAZING) 진입 시
Telegram 알림 발송. 종목별 24시간 cooldown 으로 스팸 방지.

MemeAlertHistory 테이블에 발송 기록 → 다음 turn cooldown 필터.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import MemeAlertHistory
from backend.services.telegram_notifier import is_configured, send_message

logger = logging.getLogger(__name__)

# 알림 임계
_ERUPTING_INTENSITY = 8.0
_BLAZING_SCORE = 1.0
_COOLDOWN_HOURS = 24
_TOP_N_TO_CHECK = 50


def _format_alert(
    alert_type: str,
    score,
    intensity,
    meta,
    volume,
) -> str:
    """Markdown 메시지 생성.

    헤더에 두 지표 라벨 병기 (Score BLAZING + Intensity ERUPTING) — 두 개념
    (폭등 가능성 예측 vs 현재 상승 강도 실측) 사용자 혼동 방지.
    """
    name = (meta.name if meta else "") or score.ticker
    market = (meta.market if meta else "?") or "?"

    # 헤더 라벨 — 두 조건 모두 만족 시 병기
    header_parts = []
    if intensity is not None and intensity.intensity >= _ERUPTING_INTENSITY:
        header_parts.append(f"{intensity.emoji} {intensity.label}")
    if score.score >= _BLAZING_SCORE:
        header_parts.append(f"{score.emoji} {score.label}")
    if not header_parts:
        # 임계 미만 (알림 발송 판정 미도달 — 방어 코드)
        header_parts.append(f"{score.emoji} {score.label}")

    lines = [
        f"{' · '.join(header_parts)} — *{name}*",
        f"`{score.ticker}` · {market}",
        "─────────────",
        f"Meme Score:  *{score.score:.3f}*  {score.emoji} {score.label}",
        "             _(폭등 가능성 예측)_",
    ]
    if intensity is not None:
        lines += [
            f"Intensity:   *{intensity.intensity:.1f}/10*  {intensity.emoji} {intensity.label}",
            "             _(현재 상승 강도 실측)_",
        ]
    lines.append("─────────────")

    if volume is not None and volume.close is not None:
        if market == "KRX":
            price_str = f"{int(volume.close):,}원"
        else:
            price_str = f"${volume.close:.2f}"
        price_line = f"현재가: *{price_str}*"
        if volume.return_1d_pct is not None:
            price_line += f"  ·  1D *{volume.return_1d_pct:+.1f}%*"
        lines.append(price_line)

    lines += [
        "",
        "https://optimus8.cafe24.com/meme-watch",
    ]
    return "\n".join(lines)


async def check_and_send_alerts(top_n: int = _TOP_N_TO_CHECK) -> dict:
    """Top N 종목에서 ERUPTING/BLAZING 감지 → Telegram 발송 + 이력 저장."""
    stats = {
        "candidates": 0,
        "eligible": 0,
        "sent": 0,
        "skipped_cooldown": 0,
        "skipped_below_threshold": 0,
        "errors": 0,
    }
    if not is_configured():
        logger.info("[meme_alert] TELEGRAM_* env 미설정 — skip")
        return stats

    from backend.discovery.meme_watch.top import compute_top_memes

    results = await compute_top_memes(top_n=top_n)
    stats["candidates"] = len(results)
    if not results:
        return stats

    now = datetime.now()
    cutoff = now - timedelta(hours=_COOLDOWN_HOURS)

    async with get_session() as session:
        # 최근 24h 발송된 (ticker, alert_type) 세트
        recent_rows = (
            await session.execute(
                select(MemeAlertHistory.ticker, MemeAlertHistory.alert_type).where(
                    MemeAlertHistory.triggered_at >= cutoff
                )
            )
        ).all()
        recent_set = set((r[0], r[1]) for r in recent_rows)

        for r in results:
            score = r["score"]
            intensity = r.get("intensity")
            meta = r.get("meta")
            volume = r.get("volume")

            # 임계 판정 — ERUPTING 우선 (더 강한 시그널)
            alert_type: Optional[str] = None
            if intensity is not None and intensity.intensity >= _ERUPTING_INTENSITY:
                alert_type = "ERUPTING"
            elif score.score >= _BLAZING_SCORE:
                alert_type = "BLAZING"
            else:
                stats["skipped_below_threshold"] += 1
                continue

            stats["eligible"] += 1
            key = (score.ticker, alert_type)
            if key in recent_set:
                stats["skipped_cooldown"] += 1
                continue

            text = _format_alert(alert_type, score, intensity, meta, volume)
            try:
                sent = await send_message(text)
            except Exception as e:
                logger.exception(f"[meme_alert] {score.ticker} send failed: {e}")
                stats["errors"] += 1
                continue

            if sent:
                session.add(
                    MemeAlertHistory(
                        ticker=score.ticker,
                        alert_type=alert_type,
                        triggered_at=now,
                        payload=json.dumps(
                            {
                                "score": score.score,
                                "intensity": (
                                    intensity.intensity if intensity else None
                                ),
                                "name": (meta.name if meta else None),
                                "market": (meta.market if meta else None),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                stats["sent"] += 1

        await session.commit()

    logger.info(f"[meme_alert] done stats={stats}")
    return stats
