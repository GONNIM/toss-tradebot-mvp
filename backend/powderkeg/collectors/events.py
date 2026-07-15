"""이벤트 수집기 · Phase 7-1e.

DART 공시 제목 키워드 매칭 → PowderKegEvent 저장.
Activist Radar DART 폴러 재사용 (fetch_recent_disclosures).

지시서 §7-1-4 · §7-3 이벤트 트리거 (Type A/B):
  - Type A · 매수 후보 (오너에게 현금 필요한 사건)
    · A1 오너 사법 리스크 · A2 상속 · A3 담보제공 · A4 5% 보고 · A5 배당/자사주 · A6 저PBR 압박
  - Type B · 즉시 제외 (자금 소실)
    · B1 횡령배임 · B2 감사의견 비적정 · B3 거래정지

v1 · 지시서 §7-1-4 첫 항목만 (DART 공시)
    뉴스 크롤링은 v2 (§7-1-4 두 번째 항목 · 저작권/robots 리스크)
    LLM classifier 는 Phase 7-3 (§7-3 분류 규칙)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from backend.discovery.data_sources.dart.client import (
    DartDisclosure,
    fetch_recent_disclosures,
)
from backend.services.db import get_session
from backend.services.models import PowderKegEvent

from ..config import KEYWORDS_TYPE_A, KEYWORDS_TYPE_B

logger = logging.getLogger(__name__)


def classify_disclosure(title: str) -> Optional[tuple[str, str]]:
    """공시 제목 → (event_type, matched_keyword).

    Type B 우선 (지시서 §7-3 규칙 · B 발생 시 A 무시).
    None 이면 무관 공시.
    """
    if not title:
        return None

    # Type B 우선 검사
    for event_type, keywords in KEYWORDS_TYPE_B.items():
        for kw in keywords:
            if kw in title:
                return (event_type, kw)

    # Type A 검사
    for event_type, keywords in KEYWORDS_TYPE_A.items():
        for kw in keywords:
            if kw in title:
                return (event_type, kw)

    return None


def _short_event_code(event_type: str) -> str:
    """A1_owner_legal_risk → A1"""
    return event_type.split("_")[0]


async def _already_saved(source: str, source_id: str) -> bool:
    """rcept_no 중복 체크 · 동일 공시 재수집 방지."""
    async with get_session() as session:
        stmt = select(PowderKegEvent.id).where(
            PowderKegEvent.source == source,
            PowderKegEvent.source_id == source_id,
        ).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none() is not None


async def _save_event(
    ticker: str,
    event_type_full: str,
    disclosure: DartDisclosure,
    matched_kw: str,
) -> Optional[int]:
    """PowderKegEvent 저장."""
    if await _already_saved("dart", disclosure.rcept_no):
        return None
    event_code = _short_event_code(event_type_full)
    # rcept_dt YYYYMMDD → datetime
    release_dt: Optional[datetime] = None
    if len(disclosure.rcept_dt) == 8:
        try:
            release_dt = datetime.strptime(disclosure.rcept_dt, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            release_dt = None
    async with get_session() as session:
        row = PowderKegEvent(
            ticker=ticker,
            event_type=event_code,
            source="dart",
            source_id=disclosure.rcept_no,
            title=disclosure.report_nm,
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={disclosure.rcept_no}",
            release_date=release_dt,
        )
        session.add(row)
        await session.flush()
        return row.id


# 지시서 §7-1-1 · §7-3 · 폴링 대상 공시 유형
#   B: 주요사항보고 (횡령·배임·최대주주변경·주식담보 등)
#   D: 지분공시 (대량보유상황보고 · 임원주요주주)
#   I: 거래소공시 (거래정지 · 관리종목)
#   E: 기타 · 배당·자사주 소각 등이 종종 포함
_POLL_TYPES = ("B", "D", "I", "E")


async def poll_powderkeg_events(
    lookback_days: int = 1,
    watched_tickers: Optional[set[str]] = None,
) -> dict:
    """최근 N일 DART 공시 폴링 · 키워드 매칭 · PowderKegEvent 저장.

    Args:
        lookback_days: 조회 기간 (일)
        watched_tickers: 감시 대상 종목 · None 이면 매칭된 모든 종목 저장
                         (Phase 7-2 화약고 리스트 확정 후 그 종목만 감시 권장)

    Returns:
        {"fetched": N, "matched": M, "inserted": I, "type_a": ..., "type_b": ...}
    """
    end = date.today()
    start = end - timedelta(days=max(1, lookback_days))
    stats = {
        "fetched": 0, "matched": 0, "inserted": 0,
        "type_a": 0, "type_b": 0,
        "period": f"{start.isoformat()}~{end.isoformat()}",
    }

    all_disclosures: list[DartDisclosure] = []
    for ptype in _POLL_TYPES:
        try:
            batch = await fetch_recent_disclosures(
                bgn_de=start, end_de=end, pblntf_ty=ptype, only_listed=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[powderkeg.events] pblntf_ty=%s fetch 실패 · %s", ptype, exc)
            continue
        all_disclosures.extend(batch)
    stats["fetched"] = len(all_disclosures)

    for d in all_disclosures:
        if not d.stock_code:
            continue
        if watched_tickers is not None and d.stock_code not in watched_tickers:
            continue
        cls = classify_disclosure(d.report_nm)
        if cls is None:
            continue
        stats["matched"] += 1
        event_type_full, matched_kw = cls
        row_id = await _save_event(d.stock_code, event_type_full, d, matched_kw)
        if row_id is not None:
            stats["inserted"] += 1
            code = _short_event_code(event_type_full)
            if code.startswith("A"):
                stats["type_a"] += 1
            elif code.startswith("B"):
                stats["type_b"] += 1

    logger.info("[powderkeg.events] %s", stats)
    return stats
