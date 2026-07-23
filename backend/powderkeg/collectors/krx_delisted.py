"""KIND 상장폐지 종목 수집기 · Phase 7 · P2-1.

수집 (일 1회 또는 수동):
  - kind.krx.co.kr/investwarn/delcompany.do (POST · forward=delcompany_down)
  - EUC-KR HTML 표 · 6열: 번호 · 회사명 · 종목코드(6자리) · 폐지일자 · 폐지사유 · 비고

용도:
  - PowderKegDelistedIssue 스냅샷 append (매 refresh 마다 새 row)
  - P2-1 재무 백필 대상 후보 (부실 상폐 위주 · 이관성 사유 제외)
  - P2-2 PIT 백테스트 생존 편향 해소용

Referer 필수 (P4-5 KIND 접근 패턴 재활용).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import requests
from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import PowderKegDelistedIssue

logger = logging.getLogger(__name__)


BASE = "https://kind.krx.co.kr"
UA = {"User-Agent": "Mozilla/5.0 (compatible; toss-tradebot-mvp/1.0)"}
TIMEOUT = 30

# 이관성 사유 (신규 상장 유지 · 부실 상폐가 아님) — 재무 백필 대상 제외
EXCLUDE_KEYWORDS = [
    "이전상장", "피흡수합병", "완전자회사", "유가증권시장 상장",
    "코스닥시장 상장", "스팩", "해산 사유", "재상장",
]


def _today_kst_str() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(tz=kst).date().isoformat()


def _is_transitional(reason: Optional[str], note: Optional[str]) -> bool:
    text = f"{reason or ''} {note or ''}"
    return any(k in text for k in EXCLUDE_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# HTML 파서 · KIND delcompany 엑셀 다운로드 (6열)
# ─────────────────────────────────────────────────────────────
_TR_RE = re.compile(r"<tr>\s*(<td[^>]*>.*?</td>\s*){6}\s*</tr>", re.S)
_ROW_RE = re.compile(
    r"<tr>\s*"
    r"<td[^>]*>(?P<no>\d+)</td>\s*"
    r"<td[^>]*>(?P<name>[^<]+)</td>\s*"
    r"<td[^>]*>(?P<ticker>[0-9]{6})</td>\s*"
    r"<td[^>]*>(?P<date>[0-9\-]+)</td>\s*"
    r"<td[^>]*>(?P<reason>[^<]*)</td>\s*"
    r"<td[^>]*>(?P<note>[^<]*)</td>\s*"
    r"</tr>",
    re.S,
)


def _parse_delisted_html(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in _ROW_RE.finditer(html):
        reason = (m["reason"] or "").strip()
        note = (m["note"] or "").strip()
        rows.append({
            "ticker": m["ticker"].strip(),
            "corp_name": m["name"].strip(),
            "delisted_date": m["date"].strip(),
            "reason": reason,
            "note": note,
            "is_transitional": _is_transitional(reason, note),
        })
    return rows


# ─────────────────────────────────────────────────────────────
# Fetch · KIND delcompany.do (POST + EUC-KR)
# ─────────────────────────────────────────────────────────────
def fetch_delisted_list(
    from_date: str,
    to_date: str,
    market_type: str = "",
    retries: int = 2,
) -> list[dict[str, Any]]:
    """KIND 상장폐지 종목 리스트.

    Args:
        from_date, to_date: YYYY-MM-DD
        market_type: "" (전체) · "1" (유가증권) · "2" (코스닥) · "6" (코넥스)
    """
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                f"{BASE}/investwarn/delcompany.do",
                headers={
                    **UA,
                    "Referer": f"{BASE}/investwarn/delcompany.do?method=searchDelCompanyMain",
                    "X-Requested-With": "XMLHttpRequest",
                },
                data={
                    "method": "searchDelCompanySub",
                    "forward": "delcompany_down",
                    "currentPageSize": "3000",
                    "pageIndex": "1",
                    "tabType": "1",
                    "marketType": market_type,
                    "fromDate": from_date,
                    "toDate": to_date,
                },
                timeout=TIMEOUT,
            )
            r.encoding = "euc-kr"
            if r.status_code == 200 and len(r.text) > 500:
                return _parse_delisted_html(r.text)
            logger.warning("[krx_delisted] attempt %d · status=%d len=%d", attempt, r.status_code, len(r.text))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("[krx_delisted] attempt %d · exception %s", attempt, exc)
        time.sleep(1.5)
    if last_exc:
        raise last_exc
    return []


# ─────────────────────────────────────────────────────────────
# Snapshot refresh (append-only · KOSPI+KOSDAQ 각각 조회로 market 태그)
# ─────────────────────────────────────────────────────────────
async def refresh_delisted_snapshot(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    snapshot_date: Optional[str] = None,
) -> dict[str, Any]:
    """상장폐지 종목 리스트 refresh · PowderKegDelistedIssue append.

    - KOSPI · KOSDAQ 각각 별도 조회 → market 필드 채움 (KONEX 제외)
    - 같은 (ticker, snapshot_date) 중복은 skip
    """
    snapshot_date = snapshot_date or _today_kst_str()
    kst = timezone(timedelta(hours=9))
    if to_date is None:
        to_date = datetime.now(tz=kst).date().isoformat()
    if from_date is None:
        from_date = (datetime.now(tz=kst).date() - timedelta(days=5 * 365)).isoformat()

    stats = {
        "snapshot_date": snapshot_date,
        "from_date": from_date, "to_date": to_date,
        "kospi": 0, "kosdaq": 0,
        "total": 0, "inserted": 0, "skipped_dup": 0,
        "excluded_transitional": 0,
        "target_candidates": 0,   # 이관성 제외 · Powderkeg 재무 백필 대상
        "errors": 0,
    }

    all_rows: list[dict[str, Any]] = []
    try:
        kospi_rows = fetch_delisted_list(from_date, to_date, market_type="1")
        for r in kospi_rows:
            r["market"] = "KOSPI"
        all_rows.extend(kospi_rows)
        stats["kospi"] = len(kospi_rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[krx_delisted] KOSPI fetch 실패")
        stats["errors"] += 1

    try:
        kosdaq_rows = fetch_delisted_list(from_date, to_date, market_type="2")
        for r in kosdaq_rows:
            r["market"] = "KOSDAQ"
        all_rows.extend(kosdaq_rows)
        stats["kosdaq"] = len(kosdaq_rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[krx_delisted] KOSDAQ fetch 실패")
        stats["errors"] += 1

    stats["total"] = len(all_rows)

    async with get_session() as session:
        for row in all_rows:
            if row["is_transitional"]:
                stats["excluded_transitional"] += 1
            else:
                stats["target_candidates"] += 1

            existing = (await session.execute(
                select(PowderKegDelistedIssue).where(
                    PowderKegDelistedIssue.ticker == row["ticker"],
                    PowderKegDelistedIssue.snapshot_date == snapshot_date,
                ).limit(1)
            )).scalar_one_or_none()
            if existing is not None:
                stats["skipped_dup"] += 1
                continue

            session.add(PowderKegDelistedIssue(
                ticker=row["ticker"],
                corp_name=row["corp_name"],
                market=row.get("market"),
                delisted_date=row["delisted_date"],
                reason=row["reason"],
                note=row["note"] or None,
                is_transitional=row["is_transitional"],
                snapshot_date=snapshot_date,
            ))
            stats["inserted"] += 1

    logger.info("[krx_delisted.refresh] %s", stats)
    return stats


# ─────────────────────────────────────────────────────────────
# 조회 헬퍼 (P2-1 재무 백필용)
# ─────────────────────────────────────────────────────────────
async def list_backfill_candidates(snapshot_date: Optional[str] = None) -> list[dict[str, Any]]:
    """이관성 제외 · Powderkeg 재무 백필 대상 후보 (KOSPI+KOSDAQ 공통주 상폐사).

    Returns: [{ticker, corp_name, market, delisted_date, reason}, ...]
    """
    async with get_session() as session:
        if snapshot_date is None:
            snapshot_date = (await session.execute(
                select(PowderKegDelistedIssue.snapshot_date)
                .order_by(PowderKegDelistedIssue.snapshot_date.desc())
                .limit(1)
            )).scalar_one_or_none()
        if snapshot_date is None:
            return []
        stmt = (
            select(PowderKegDelistedIssue)
            .where(
                PowderKegDelistedIssue.snapshot_date == snapshot_date,
                PowderKegDelistedIssue.is_transitional == False,   # noqa: E712
            )
            .order_by(PowderKegDelistedIssue.delisted_date.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "ticker": r.ticker, "corp_name": r.corp_name,
            "market": r.market, "delisted_date": r.delisted_date,
            "reason": r.reason,
        }
        for r in rows
    ]
