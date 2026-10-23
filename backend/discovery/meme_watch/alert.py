"""Meme Watch Telegram 알림 (Phase 6).

Intensity ≥ 8.0 (급등 진행) 또는 Score ≥ 1.0 (급등 전 단계) 진입 시
Telegram 알림 발송. 종목별 24시간 cooldown 으로 스팸 방지.

MemeAlertHistory 테이블에 발송 기록 → 다음 turn cooldown 필터.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from backend.services import alert_text as at
from backend.services.db import get_session
from backend.services.models import MemeAlertHistory
from backend.services.notifier import Level, TelegramNotifier

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
) -> tuple[str, str]:
    """(제목, 본문) — 한국어 · 사실만 · 실측(상승 강도)과 추정(급등 전 단계 점수)을 구분해 적는다 (1023-05)."""
    erupting = alert_type == "ERUPTING"
    category = "meme_erupting" if erupting else "meme_blazing"
    name = meta.name if meta and meta.name else None
    is_retrigger = prev_score is not None or prev_intensity is not None
    tail = " · 다시 오름" if is_retrigger else ""
    if name:
        title = at.title(category, name, "🌋" if erupting else "🔥", keep=f"({score.ticker}){tail}")
    else:
        title = at.title(category, "", "🌋" if erupting else "🔥", keep=f"{score.ticker}{tail}")

    market = (meta.market if meta else None) or ""
    lines = []
    if volume is not None and volume.close is not None:
        price = f"{int(volume.close):,}원" if market == "KRX" else at.usd(volume.close)
        day = f"오늘 {volume.return_1d_pct:+.1f}% · " if volume.return_1d_pct is not None else ""
        lines.append(f"{day}지금 {price}")
    if intensity is not None:
        prev = f" · 직전 {prev_intensity:.1f}" if prev_intensity is not None else ""
        lines.append(f"상승 강도 {intensity.intensity:.1f}/10 (실측{prev})")
    prev = f" · 직전 {prev_score:.2f}" if prev_score is not None else ""
    lines.append(f"급등 전 단계 점수 {score.score:.2f} (추정{prev} · 커뮤니티 언급·거래량 등 5가지 · 보장 아님)")
    if market:
        lines.append(f"시장: {at.esc(market)}")
    lines.append(at.link(category))
    return title, "\n".join(lines)


# 처리됨으로 보는 발송 결과 — 이력에 남겨 cooldown 적용 (실패만 다음 회차 재시도)
_HANDLED = {"sent", "queued", "skipped"}


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
    notifier = TelegramNotifier()
    if not notifier.config.bot_token or not notifier.config.chat_id:
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

            title, body = _format_alert(
                alert_type,
                score,
                intensity,
                meta,
                volume,
                prev_score=prev_score if is_retrigger else None,
                prev_intensity=prev_intensity if is_retrigger else None,
            )
            category = "meme_erupting" if alert_type == "ERUPTING" else "meme_blazing"
            try:
                # force=True — 예전 send_message 처럼 TELEGRAM_PROFILE 을 우회 (배포만으로 받는 알림이 바뀌지 않게)
                # 알림 설정(켜기·하루 요약)은 gate 로 그대로 적용
                await notifier.send(Level.INFO, title, body, force=True, category=category, dedupe_id=score.ticker)
            except Exception as e:
                logger.exception(f"[meme_alert] {score.ticker} send failed: {e}")
                stats["errors"] += 1
                continue

            if notifier.last_result in _HANDLED:
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
                        signal_id_str = f"meme-{alert_type.lower()}-{score.ticker}-{now.strftime('%Y%m%d%H%M')}"
                        await router.route(
                            SignalEvent(
                                ticker=score.ticker,
                                action="buy",
                                strength=strength,
                                source="meme_stock",
                                signal_id=signal_id_str,
                                metadata={
                                    "alert_type": alert_type,
                                    "score": score.score,
                                    "intensity": intensity_val,
                                },
                            )
                        )
                    # Super Signal 원천 · Router 무관 (EXECUTION_ENABLED=false 시에도 로깅)
                    try:
                        from backend.discovery.super_signal.signal_hit import record_hit
                        await record_hit(
                            ticker=score.ticker,
                            source="meme_stock",
                            signal_id=f"meme-{alert_type.lower()}-{score.ticker}-{now.strftime('%Y%m%d%H%M')}",
                            action="buy",
                            strength=(
                                min(100, 80 + int((intensity.intensity if intensity else 0.0) - _ERUPTING_INTENSITY))
                                if alert_type == "ERUPTING"
                                else min(70, 50 + int((score.score - _BLAZING_SCORE) * 20))
                            ),
                            metadata={"alert_type": alert_type, "score": score.score},
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[meme_alert] signal_hit 실패 — %s", exc)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[meme_alert] router 실패 — %s", exc)

        await session.commit()

    logger.info(f"[meme_alert] done stats={stats}")
    return stats
