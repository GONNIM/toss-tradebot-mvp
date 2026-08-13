"""Serenity 트윗 → SerenitySignal 추출 · z.ai GLM-5.2.

Phase L3 · 2026-08-02 · 문서 02 §4 스켈레톤을 SQLAlchemy async + z.ai openai SDK 호환 재작성.

원천:
    serenity_tweets 테이블 · L2 crawler 로 채워짐
목표:
    SerenitySignal upsert · (tweet_id, ticker) unique · SerenityTweet 하나가 여러 signals 가능

env:
    ZAI_API_KEY (필수 · 미설정 시 RuntimeError)
    ZAI_BASE_URL (default: https://api.z.ai/api/paas/v4)
    ZAI_MODEL    (default: glm-4.6 · 문서 예시는 glm-5.2 · 미출시 시점엔 glm-4.6 안전)

주의:
    실 API 호출 · 비용 발생. process_pending_tweets 호출 전 사용자 승인 필요.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import and_, func, not_, select, update
from sqlalchemy.exc import IntegrityError

from backend.services.db import get_session
from backend.services.models import (
    SERENITY_EVIDENCE_TYPES,
    SERENITY_SENTIMENTS,
    SERENITY_THESIS_TYPES,
    SerenitySignal,
    SerenityTweet,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "system.md"


def load_system_prompt() -> str:
    """system.md 로드 · 매 호출마다 파일에서 (튜닝 시 재기동 없이 반영)."""
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def _openai_client():
    """z.ai openai-호환 client. ZAI_API_KEY 미설정 시 명시 에러."""
    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        raise RuntimeError("ZAI_API_KEY 미설정 · Serenity extractor 사용 불가")
    from openai import OpenAI
    return OpenAI(
        api_key=api_key,
        base_url=os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4"),
    )


def _sanitize_signal(raw: dict) -> Optional[dict]:
    """z.ai 응답 signal 한 건 검증·정규화 · 불량 시 None."""
    ticker = raw.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip():
        return None
    ticker = ticker.strip().lstrip("$").upper()[:20]

    sentiment = raw.get("sentiment")
    if sentiment not in SERENITY_SENTIMENTS:
        return None

    thesis_type = raw.get("thesis_type")
    if thesis_type and thesis_type not in SERENITY_THESIS_TYPES:
        thesis_type = None

    evidence_type = raw.get("evidence_type")
    if evidence_type and evidence_type not in SERENITY_EVIDENCE_TYPES:
        evidence_type = None

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reasoning = raw.get("reasoning") or raw.get("extracted_reasoning") or None
    if isinstance(reasoning, str):
        reasoning = reasoning.strip() or None

    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "thesis_type": thesis_type,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "reasoning": reasoning,
    }


def extract_signals(
    tweet_text: str,
    tweet_context: Optional[dict[str, Any]] = None,
    *,
    client=None,
) -> list[dict]:
    """z.ai 호출 · 트윗 → sanitized signals list. 실패 시 예외 raise."""
    client = client or _openai_client()
    model = os.environ.get("ZAI_MODEL", "glm-4.6")

    user_block = f"# 트윗\n{tweet_text}"
    if tweet_context:
        user_block += f"\n\n# 컨텍스트\n{json.dumps(tweet_context, ensure_ascii=False)}"

    # z.ai 확장 · glm-5.x 계열은 reasoning 기본 ON · signal 추출엔 불필요·비용 낭비.
    # glm-4.x 는 미지원 필드 무시 (실측 확인 · Sunday z.ai spec).
    extra_body: dict[str, Any] = {"thinking": {"type": "disabled"}}

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,
        max_tokens=1500,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": user_block},
        ],
        extra_body=extra_body,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[serenity] z.ai JSON 파싱 실패 · raw=%s", raw[:200])
        return []

    signals = parsed.get("signals") or []
    if not isinstance(signals, list):
        return []
    out = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        clean = _sanitize_signal(s)
        if clean:
            out.append(clean)
    return out


async def load_pending_tweets(limit: int = 50) -> list[SerenityTweet]:
    """processed_at IS NULL 트윗 최근순 조회.

    (2026-08-13 사고 대응) signals 존재 여부가 아니라 processed_at 마킹으로 판단.
    signals=[] 응답도 정상 결과로 처리 · 무한 루프 원천 차단.
    """
    async with get_session() as session:
        stmt = (
            select(SerenityTweet)
            .where(SerenityTweet.processed_at.is_(None))
            .order_by(SerenityTweet.posted_at.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())


async def count_pending_tweets() -> int:
    """미처리 트윗 총 수 (dry-run · pending_before/after 산출용)."""
    async with get_session() as session:
        stmt = select(func.count()).select_from(SerenityTweet).where(
            SerenityTweet.processed_at.is_(None)
        )
        return int((await session.execute(stmt)).scalar_one())


async def _mark_processed(tweet_id: int) -> None:
    """z.ai 응답 성공 시 processed_at 마킹 (signals 유무 무관)."""
    async with get_session() as session:
        await session.execute(
            update(SerenityTweet)
            .where(SerenityTweet.tweet_id == tweet_id)
            .values(processed_at=datetime.utcnow())
        )
        await session.commit()


async def _persist_signals(tweet_id: int, signals: list[dict]) -> int:
    """(tweet_id, ticker) unique 대응 · IntegrityError race 시 개별 재시도."""
    if not signals:
        return 0
    rows = [
        SerenitySignal(
            id=str(uuid.uuid4()),
            tweet_id=tweet_id,
            ticker=s["ticker"],
            sentiment=s["sentiment"],
            thesis_type=s["thesis_type"],
            evidence_type=s["evidence_type"],
            confidence=s["confidence"],
            extracted_reasoning=s["reasoning"],
        )
        for s in signals
    ]
    inserted = 0
    async with get_session() as session:
        for row in rows:
            session.add(row)
        try:
            await session.commit()
            inserted = len(rows)
        except IntegrityError:
            await session.rollback()
            for row in rows:
                async with get_session() as s2:
                    s2.add(row)
                    try:
                        await s2.commit()
                        inserted += 1
                    except IntegrityError:
                        await s2.rollback()
                        logger.debug(
                            "[serenity] dup signal skip · tweet_id=%s · ticker=%s",
                            tweet_id, row.ticker,
                        )
    return inserted


async def process_pending_tweets(
    batch_size: int = 50,
    *,
    concurrency: int = 4,
    client=None,
) -> dict:
    """미처리 트윗 배치 z.ai 추출 → serenity_signals upsert + processed_at 마킹.

    반환:
      {"tweets": N,               # 이번 배치 처리 완료 (마킹) 트윗 수
       "signals_inserted": M,     # 이번 배치 신규 signal 삽입 수
       "failed": K,               # z.ai 예외 (재시도 대상 · 마킹 X)
       "pending_before": B,       # 실행 직전 미처리 트윗 총 수
       "pending_after": A}        # 실행 직후 미처리 트윗 총 수

    무한 루프 방지 (2026-08-13 사고 대응):
      - z.ai 응답 성공 시 signals 유무 무관 processed_at 마킹
      - pending_after >= pending_before AND tweets > 0 → RuntimeError (마킹 결함 감지)
    """
    pending_before = await count_pending_tweets()
    pending = await load_pending_tweets(limit=batch_size)
    if not pending:
        return {
            "tweets": 0, "signals_inserted": 0, "failed": 0,
            "pending_before": pending_before, "pending_after": pending_before,
        }

    client = client or _openai_client()
    sem = asyncio.Semaphore(concurrency)
    stats = {"tweets": 0, "signals_inserted": 0, "failed": 0}

    async def _one(tw: SerenityTweet) -> None:
        async with sem:
            try:
                signals = await asyncio.to_thread(
                    extract_signals,
                    tw.text,
                    {"posted_at": tw.posted_at.isoformat()},
                    client=client,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[serenity] extract 실패 · tweet_id=%s · %s", tw.tweet_id, exc)
                stats["failed"] += 1
                return
            inserted = await _persist_signals(tw.tweet_id, signals)
            await _mark_processed(tw.tweet_id)
            stats["tweets"] += 1
            stats["signals_inserted"] += inserted

    await asyncio.gather(*[_one(t) for t in pending])

    pending_after = await count_pending_tweets()
    stats["pending_before"] = pending_before
    stats["pending_after"] = pending_after

    # 무한 루프 감지 (마킹 결함 · 회귀 방지 · 사고 재현 시 즉시 exception)
    if stats["tweets"] > 0 and pending_after >= pending_before:
        raise RuntimeError(
            f"[serenity] 무한 루프 감지 · pending_before={pending_before} "
            f"pending_after={pending_after} tweets={stats['tweets']} · "
            "processed_at 마킹 실패. 코드 결함 조사 필요."
        )

    return stats
