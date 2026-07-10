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
_COOLDOWN_HOURS = 8                # Phase 6-D: 24h → 8h 단축
_TOP_N_TO_CHECK = 50

# 재알림 규칙 (cooldown 안이라도 시그널 급상승 시 즉시 재발송)
_RETRIGGER_SCORE_DELTA = 0.3
_RETRIGGER_INTENSITY_DELTA = 3.0


def _format_alert(
    alert_type: str,
    score,
    intensity,
    meta,
    volume,
    prev_score: Optional[float] = None,
    prev_intensity: Optional[float] = None,
) -> str:
    """Markdown 메시지 생성.

    헤더에 두 지표 라벨 병기 (Score BLAZING + Intensity ERUPTING) — 두 개념
    (폭등 가능성 예측 vs 현재 상승 강도 실측) 사용자 혼동 방지.
    """
    name = (meta.name if meta else "") or score.ticker
    market = (meta.market if meta else "?") or "?"

    # 헤더 라벨 — 두 조건 모두 만족 시 병기 + retrigger 표시
    header_parts = []
    if intensity is not None and intensity.intensity >= _ERUPTING_INTENSITY:
        header_parts.append(f"{intensity.emoji} {intensity.label}")
    if score.score >= _BLAZING_SCORE:
        header_parts.append(f"{score.emoji} {score.label}")
    if not header_parts:
        header_parts.append(f"{score.emoji} {score.label}")

    is_retrigger = prev_score is not None or prev_intensity is not None
    retrigger_tag = " 🔺 UP" if is_retrigger else ""

    lines = [
        f"{' · '.join(header_parts)}{retrigger_tag} — *{name}*",
        f"`{score.ticker}` · {market}",
        "─────────────",
        f"Meme Score:  *{score.score:.3f}*  {score.emoji} {score.label}"
        + (f"  _(이전 {prev_score:.3f}, +{score.score - prev_score:.2f})_"
           if prev_score is not None and is_retrigger else ""),
        "             _(폭등 가능성 예측)_",
    ]
    if intensity is not None:
        intensity_line = (
            f"Intensity:   *{intensity.intensity:.1f}/10*  "
            f"{intensity.emoji} {intensity.label}"
        )
        if prev_intensity is not None and is_retrigger:
            intensity_line += (
                f"  _(이전 {prev_intensity:.1f}, +{intensity.intensity - prev_intensity:.1f})_"
            )
        lines.append(intensity_line)
        lines.append("             _(현재 상승 강도 실측)_")
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
    """Top N 종목에서 ERUPTING/BLAZING 감지 → Telegram 발송 + 이력 저장.

    Phase 6-D: cooldown 8h + 시그널 급상승 (Score +0.3 or Intensity +3.0) 시
    cooldown 무시 재발송 (🔺 UP 표시).
    """
    stats = {
        "candidates": 0,
        "eligible": 0,
        "sent_new": 0,
        "sent_retrigger": 0,
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
        # 최근 cooldown 시간 내 (ticker, alert_type) → payload — 상승 delta 판정
        recent_rows = (
            await session.execute(
                select(
                    MemeAlertHistory.ticker,
                    MemeAlertHistory.alert_type,
                    MemeAlertHistory.payload,
                ).where(MemeAlertHistory.triggered_at >= cutoff)
            )
        ).all()
        recent_map: dict[tuple[str, str], dict] = {}
        for tk, at, pl in recent_rows:
            try:
                recent_map[(tk, at)] = json.loads(pl or "{}")
            except (ValueError, TypeError):
                recent_map[(tk, at)] = {}

        for r in results:
            score = r["score"]
            intensity = r.get("intensity")
            meta = r.get("meta")
            volume = r.get("volume")

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

            # cooldown 판정 — 이전 발송 있으면 상승 delta 확인
            prev_score: Optional[float] = None
            prev_intensity: Optional[float] = None
            is_retrigger = False
            if key in recent_map:
                prev = recent_map[key]
                prev_score = prev.get("score")
                prev_intensity = prev.get("intensity")
                # 상승 delta 계산
                score_up = (
                    score.score - prev_score if prev_score is not None else 0.0
                )
                intensity_up = (
                    (intensity.intensity if intensity else 0.0)
                    - (prev_intensity if prev_intensity is not None else 0.0)
                )
                if (
                    score_up >= _RETRIGGER_SCORE_DELTA
                    or intensity_up >= _RETRIGGER_INTENSITY_DELTA
                ):
                    is_retrigger = True
                else:
                    stats["skipped_cooldown"] += 1
                    continue

            text = _format_alert(
                alert_type,
                score,
                intensity,
                meta,
                volume,
                prev_score=prev_score if is_retrigger else None,
                prev_intensity=prev_intensity if is_retrigger else None,
            )
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
                                "retrigger": is_retrigger,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                if is_retrigger:
                    stats["sent_retrigger"] += 1
                else:
                    stats["sent_new"] += 1

                # ─── Execution Layer 라우팅 (v2 트랙 C · Phase 1) ───
                # EXECUTION_ENABLED=false 시 get_signal_router() 가 None 반환 → skip
                try:
                    from backend.execution.signal_router import (
                        SignalEvent,
                        get_signal_router,
                    )
                    router = get_signal_router()
                    if router:
                        intensity_val = (
                            intensity.intensity if intensity is not None else 0.0
                        )
                        # ERUPTING 80~100 / BLAZING 50~70 강도 매핑
                        if alert_type == "ERUPTING":
                            strength = min(100, 80 + int(intensity_val - _ERUPTING_INTENSITY))
                        else:
                            strength = min(70, 50 + int((score.score - _BLAZING_SCORE) * 20))
                        await router.route(
                            SignalEvent(
                                ticker=score.ticker,
                                action="buy",
                                strength=strength,
                                source="meme_stock",
                                signal_id=f"meme-{alert_type.lower()}-{score.ticker}-{now.strftime('%Y%m%d%H%M')}",
                                metadata={
                                    "alert_type": alert_type,
                                    "score": score.score,
                                    "intensity": intensity_val,
                                },
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[meme_alert] router 실패 — %s", exc)

        await session.commit()

    logger.info(f"[meme_alert] done stats={stats}")
    return stats
