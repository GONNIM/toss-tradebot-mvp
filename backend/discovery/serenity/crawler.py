"""Serenity 트윗 아카이브 → SQLite serenity_tweets 동기화.

Phase L2 · 2026-08-02 · 문서 02 §3 스켈레톤을 SQLAlchemy async 로 재작성.

원천: vendor/serenity-tracker/data/aleabitoreddit_tweets.json (yan-labs, git submodule)
목적: 신규 tweet_id 만 SerenityTweet 테이블에 append (증분)

수동 갱신 절차:
    cd vendor/serenity-tracker && python update.py   # xreach 인증 필요
    cd ../.. && python -m backend.scripts.serenity_crawl

Cron: 매일 06:00 KST (Phase L8 등록 예정 · 현재는 CLI 수동)
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.services.db import get_session
from backend.services.models import SerenityTweet

logger = logging.getLogger(__name__)


def _resolve_tracker_dir(explicit: Optional[Path] = None) -> Path:
    """SERENITY_TRACKER_DIR env → 기본값 vendor/serenity-tracker → HOME 폴백."""
    if explicit:
        return explicit
    env_val = os.environ.get("SERENITY_TRACKER_DIR")
    if env_val:
        return Path(env_val).expanduser()
    # 프로젝트 root 의 vendor/serenity-tracker 우선
    project_root = Path(__file__).resolve().parents[3]
    default = project_root / "vendor" / "serenity-tracker"
    if default.exists():
        return default
    return Path.home() / "GON-Dev" / "serenity-tracker"


def load_archive_tweets(tracker_dir: Optional[Path] = None) -> list[dict]:
    """aleabitoreddit_tweets.json 로드 · yan-labs 원본 스키마 그대로."""
    tracker_dir = _resolve_tracker_dir(tracker_dir)
    archive_path = tracker_dir / "data" / "aleabitoreddit_tweets.json"
    if not archive_path.exists():
        raise FileNotFoundError(f"Serenity 아카이브 없음: {archive_path}")
    with archive_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"예상 list · 실제 {type(data).__name__}")
    return data


def _parse_iso(raw: Optional[str]) -> datetime:
    """createdAtISO 필수 파싱 · 실패 시 ValueError."""
    if not raw:
        raise ValueError("createdAtISO 없음")
    # ISO 8601 · '+00:00' or 'Z' 대응
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _to_row(tweet: dict) -> Optional[SerenityTweet]:
    """yan-labs JSON 한 건 → SerenityTweet ORM 인스턴스. 불량 데이터는 None."""
    try:
        tweet_id = int(tweet["id"])
    except (KeyError, ValueError, TypeError):
        logger.warning("tweet_id 파싱 실패 · skip")
        return None

    try:
        posted_at = _parse_iso(tweet.get("createdAtISO"))
    except ValueError as exc:
        logger.warning("posted_at 파싱 실패 · id=%s · %s", tweet_id, exc)
        return None

    text = tweet.get("text") or ""
    url = f"https://x.com/aleabitoreddit/status/{tweet_id}"

    reply_to: Optional[int] = None
    if tweet.get("inReplyToTweetId"):
        try:
            reply_to = int(tweet["inReplyToTweetId"])
        except (ValueError, TypeError):
            reply_to = None

    quoted_id: Optional[int] = None
    if tweet.get("quotedStatusId") or tweet.get("quotedTweetId"):
        raw = tweet.get("quotedStatusId") or tweet.get("quotedTweetId")
        try:
            quoted_id = int(raw) if raw else None
        except (ValueError, TypeError):
            quoted_id = None

    metrics_json = json.dumps(tweet.get("metrics") or {}, ensure_ascii=False)
    # raw_json 은 원문 그대로 (감사·재추출 대비). 크기 대략 트윗당 1~3KB.
    raw = json.dumps(tweet, ensure_ascii=False)

    return SerenityTweet(
        id=str(uuid.uuid4()),
        tweet_id=tweet_id,
        url=url,
        posted_at=posted_at,
        text=text,
        reply_to_id=reply_to,
        quoted_id=quoted_id,
        metrics=metrics_json,
        raw_json=raw,
    )


async def _existing_tweet_ids(candidate_ids: Iterable[int]) -> set[int]:
    """DB 에 이미 있는 tweet_id 서브셋 조회 · 배치 크기 무관."""
    ids = list(candidate_ids)
    if not ids:
        return set()
    async with get_session() as session:
        result = await session.execute(
            select(SerenityTweet.tweet_id).where(SerenityTweet.tweet_id.in_(ids))
        )
        return set(result.scalars().all())


async def sync_tweets(
    tracker_dir: Optional[Path] = None,
    batch_size: int = 500,
) -> dict:
    """신규 트윗만 upsert.

    반환: {"inserted": N, "skipped": M, "invalid": K, "total_archive": T}
    """
    archive = load_archive_tweets(tracker_dir)
    total = len(archive)
    logger.info("[serenity] archive 로드 · total=%d", total)

    # 1) 모든 tweet_id 후보 수집
    candidates: list[tuple[int, dict]] = []
    invalid = 0
    for t in archive:
        try:
            tid = int(t["id"])
        except (KeyError, ValueError, TypeError):
            invalid += 1
            continue
        candidates.append((tid, t))

    # 2) 기존 tweet_id 조회 · IN 절 크기 안전 위해 배치 처리
    existing: set[int] = set()
    for i in range(0, len(candidates), batch_size):
        chunk_ids = [tid for tid, _ in candidates[i:i + batch_size]]
        existing |= await _existing_tweet_ids(chunk_ids)

    new_rows = [(_to_row(t), tid) for tid, t in candidates if tid not in existing]
    new_rows = [(row, tid) for row, tid in new_rows if row is not None]

    if not new_rows:
        return {
            "inserted": 0,
            "skipped": len(candidates),
            "invalid": invalid,
            "total_archive": total,
        }

    # 3) 배치 삽입 · 개별 IntegrityError 는 스킵 카운트에 합산
    inserted = 0
    dedup_skip = 0
    for i in range(0, len(new_rows), batch_size):
        chunk = new_rows[i:i + batch_size]
        async with get_session() as session:
            for row, _ in chunk:
                session.add(row)
            try:
                await session.commit()
                inserted += len(chunk)
            except IntegrityError:
                await session.rollback()
                # 개별 재시도 (race condition · duplicate 대응)
                for row, tid in chunk:
                    async with get_session() as s2:
                        s2.add(row)
                        try:
                            await s2.commit()
                            inserted += 1
                        except IntegrityError:
                            await s2.rollback()
                            dedup_skip += 1
                            logger.debug("[serenity] dedup skip · tweet_id=%s", tid)

    return {
        "inserted": inserted,
        "skipped": len(existing) + dedup_skip,
        "invalid": invalid,
        "total_archive": total,
    }
