"""KRX 관리종목 · 매매거래정지 수집기 · Phase 7 · P4-5.

수집 (일 1회):
  - 관리종목 리스트 (KIND · investwarn/adminissue.do)
  - 매매거래정지 리스트 (KIND · investwarn/tradinghaltissue.do)
  - 회사명↔종목코드 매핑 (KIND · corpgeneral/corpList.do · EUC-KR · 하루 캐시)

전략:
  - data.krx.co.kr JSON API 는 2026년부터 로그인 강제화 봉쇄됨.
  - KIND (kind.krx.co.kr) HTML fragment 파싱이 로그인 없이 통과하는 유일 경로.
  - 관리 111건 · 정지 125건 · corpList 2,759건 실측 통과. 매칭률 94% (미매칭 = ETF/우선주 · 스크리너 대상 아님).

산출: PowderKegKrxIssue append-only 스냅샷 (kind=admin/halt · snapshot_date=오늘 KST).
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
from backend.services.models import PowderKegKrxIssue

logger = logging.getLogger(__name__)


BASE = "https://kind.krx.co.kr"
UA = {"User-Agent": "Mozilla/5.0 (compatible; toss-tradebot-mvp/1.0)"}
TIMEOUT = 20


# ─────────────────────────────────────────────────────────────
# in-memory 캐시 (name→ticker · corpList 1.2MB · 하루 재사용)
# ─────────────────────────────────────────────────────────────
_corp_cache: dict[str, Any] = {"map": None, "ts": 0.0}
_CACHE_TTL_SEC = 24 * 3600


def _today_kst_str() -> str:
    kst = timezone(timedelta(hours=9))
    return datetime.now(tz=kst).date().isoformat()


def _market_from_alt(alt: str) -> str:
    if not alt:
        return "?"
    if "코스닥" in alt:
        return "KOSDAQ"
    if "유가증권" in alt or "코스피" in alt:
        return "KOSPI"
    return alt.strip()


# ─────────────────────────────────────────────────────────────
# HTML 파서 · 관리종목 (3열: 종목명+뱃지 · 지정일 · 사유)
# ─────────────────────────────────────────────────────────────
_ADMIN_RE = re.compile(
    r"<tr>\s*<td class=\"first\"><img[^>]*alt='(?P<alt>[^']+)'[^>]*>\s*"
    r"(?P<name>[^<]+?)</a>(?P<mid>.*?)</td>\s*"
    r"<td class=\"txc\">(?P<dd>[^<]+)</td>\s*"
    r"<td>(?P<reason>[^<]+)</td>",
    re.S,
)


def _parse_admin_html(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in _ADMIN_RE.finditer(html):
        rows.append({
            "market": _market_from_alt(m["alt"]),
            "name": m["name"].strip(),
            "reason": m["reason"].strip(),
            "designation_date": m["dd"].strip(),
            "is_admin_badge": "kwan" in (m["mid"] or ""),   # 관리종목 뱃지 존재 여부 (실 관리종목 이중 확증)
        })
    return rows


# ─────────────────────────────────────────────────────────────
# HTML 파서 · 거래정지 (3열: 번호 · 종목명+뱃지 · 사유 · 지정일 없음)
# ─────────────────────────────────────────────────────────────
_HALT_RE = re.compile(
    r"<tr[^>]*>\s*<td class=\"first txc\">[^<]+</td>\s*"
    r"<td><img[^>]*alt='(?P<alt>[^']+)'[^>]*>\s*(?P<name>[^<]+?)</a>(?P<mid>.*?)</td>\s*"
    r"<td>(?P<reason>[^<]+)</td>",
    re.S,
)


def _parse_halt_html(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for m in _HALT_RE.finditer(html):
        rows.append({
            "market": _market_from_alt(m["alt"]),
            "name": m["name"].strip(),
            "reason": m["reason"].strip(),
            "designation_date": None,     # KIND halt Sub 응답은 지정일 미제공
            "is_admin_badge": "kwan" in (m["mid"] or ""),
        })
    return rows


# ─────────────────────────────────────────────────────────────
# corpList (EUC-KR HTML 표 · 회사명→종목코드 매핑)
# ─────────────────────────────────────────────────────────────
_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_TICKER_RE = re.compile(r"^\d{6}$")


def _parse_corp_list_html(html: str) -> dict[str, str]:
    """corpList.do 응답 → {회사명: 6자리 종목코드}."""
    out: dict[str, str] = {}
    for tr in _TR_RE.findall(html):
        tds = [_TAG_RE.sub("", t).strip() for t in _TD_RE.findall(tr)]
        # 회사명 · 업종 · 종목코드 · ... 순서 (KIND corpList searchType=13)
        if len(tds) >= 3 and _TICKER_RE.match(tds[2]):
            out[tds[0]] = tds[2]
    return out


# ─────────────────────────────────────────────────────────────
# Fetch 함수 (실 HTTP · 재시도 2회)
# ─────────────────────────────────────────────────────────────
def _post_with_retry(url: str, data: dict, referer: str, retries: int = 2) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            r = requests.post(
                url,
                headers={**UA, "Referer": referer, "X-Requested-With": "XMLHttpRequest"},
                data=data,
                timeout=TIMEOUT,
            )
            r.encoding = "utf-8"
            if r.status_code == 200 and len(r.text) > 500:
                return r.text
            logger.warning("[krx_admin] %s attempt %d · status=%d len=%d", url, attempt, r.status_code, len(r.text))
        except Exception as exc:   # noqa: BLE001
            last_exc = exc
            logger.warning("[krx_admin] %s attempt %d · exception %s", url, attempt, exc)
        time.sleep(1.5)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"KIND fetch failed after {retries+1} attempts · {url}")


def fetch_admin_issues() -> list[dict[str, Any]]:
    """KIND 관리종목 리스트 (약 100~120건)."""
    html = _post_with_retry(
        f"{BASE}/investwarn/adminissue.do",
        data={"method": "searchAdminIssueSub", "currentPageSize": "500",
              "pageIndex": "1", "orderMode": "1", "orderStat": "D"},
        referer=f"{BASE}/investwarn/adminissue.do?method=searchAdminIssueMain",
    )
    return _parse_admin_html(html)


def fetch_trading_halt() -> list[dict[str, Any]]:
    """KIND 매매거래정지 리스트 (약 100~150건)."""
    html = _post_with_retry(
        f"{BASE}/investwarn/tradinghaltissue.do",
        data={"method": "searchTradingHaltIssueSub", "currentPageSize": "500",
              "pageIndex": "1", "marketType": "0", "forward": "tradinghaltissue_sub"},
        referer=f"{BASE}/investwarn/tradinghaltissue.do?method=searchTradingHaltIssueMain",
    )
    return _parse_halt_html(html)


def fetch_name_to_ticker(force: bool = False) -> dict[str, str]:
    """KIND corpList.do (EUC-KR · 1.2MB · 하루 캐시).

    Returns: {회사명: 6자리 종목코드}
    """
    now = time.time()
    if not force and _corp_cache["map"] is not None and (now - _corp_cache["ts"]) < _CACHE_TTL_SEC:
        return _corp_cache["map"]

    r = requests.get(
        f"{BASE}/corpgeneral/corpList.do",
        params={"method": "download", "searchType": "13"},
        headers=UA,
        timeout=60,
    )
    r.encoding = "euc-kr"
    m = _parse_corp_list_html(r.text)
    _corp_cache["map"] = m
    _corp_cache["ts"] = now
    logger.info("[krx_admin] corpList refreshed · %d entries", len(m))
    return m


# ─────────────────────────────────────────────────────────────
# 스냅샷 refresh (오늘 KST · append-only 삽입)
# ─────────────────────────────────────────────────────────────
async def refresh_admin_issue_snapshot(snapshot_date: Optional[str] = None) -> dict[str, Any]:
    """관리종목 + 거래정지 리스트 fetch → name→ticker 매핑 → PowderKegKrxIssue 삽입.

    같은 (ticker, kind, snapshot_date) 조합이 이미 있으면 skip (idempotent within a day).
    """
    snapshot_date = snapshot_date or _today_kst_str()
    stats = {
        "snapshot_date": snapshot_date,
        "total_admin": 0, "total_halt": 0,
        "matched": 0, "unmatched": 0,
        "inserted": 0, "skipped_dup": 0,
        "errors": 0,
        "sample_unmatched": [],
    }

    try:
        admin_rows = fetch_admin_issues()
    except Exception as exc:   # noqa: BLE001
        logger.exception("[krx_admin] adminissue fetch 실패")
        stats["errors"] += 1
        admin_rows = []
    try:
        halt_rows = fetch_trading_halt()
    except Exception as exc:   # noqa: BLE001
        logger.exception("[krx_admin] tradinghalt fetch 실패")
        stats["errors"] += 1
        halt_rows = []
    try:
        name_to_ticker = fetch_name_to_ticker()
    except Exception as exc:   # noqa: BLE001
        logger.exception("[krx_admin] corpList fetch 실패 · 매핑 불가")
        stats["errors"] += 1
        return stats

    stats["total_admin"] = len(admin_rows)
    stats["total_halt"] = len(halt_rows)

    async with get_session() as session:
        for kind, rows in (("admin", admin_rows), ("halt", halt_rows)):
            for row in rows:
                name = row["name"]
                ticker = name_to_ticker.get(name)
                if not ticker:
                    stats["unmatched"] += 1
                    if len(stats["sample_unmatched"]) < 10:
                        stats["sample_unmatched"].append({"kind": kind, "name": name})
                    continue
                stats["matched"] += 1

                # idempotent: 같은 (ticker, kind, snapshot_date) 이미 있으면 skip
                existing = (await session.execute(
                    select(PowderKegKrxIssue).where(
                        PowderKegKrxIssue.ticker == ticker,
                        PowderKegKrxIssue.kind == kind,
                        PowderKegKrxIssue.snapshot_date == snapshot_date,
                    ).limit(1)
                )).scalar_one_or_none()
                if existing is not None:
                    stats["skipped_dup"] += 1
                    continue

                session.add(PowderKegKrxIssue(
                    ticker=ticker,
                    name=name,
                    kind=kind,
                    reason=row.get("reason"),
                    designation_date=row.get("designation_date"),
                    snapshot_date=snapshot_date,
                ))
                stats["inserted"] += 1

    logger.info("[krx_admin.refresh] %s", stats)
    return stats


# ─────────────────────────────────────────────────────────────
# 조회 헬퍼 (screener 통합용)
# ─────────────────────────────────────────────────────────────
async def latest_snapshot_date() -> Optional[str]:
    async with get_session() as session:
        stmt = (
            select(PowderKegKrxIssue.snapshot_date)
            .order_by(PowderKegKrxIssue.snapshot_date.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def is_currently_designated(ticker: str, snapshot_date: Optional[str] = None) -> Optional[dict[str, Any]]:
    """대상 티커가 최근 스냅샷의 관리/정지 리스트에 있는지 확인.

    Returns:
        None  · 스냅샷 미수집 (데이터 부족 · c10=None)
        dict  · 최근 스냅샷의 지정 row (kind, reason, designation_date)
                 · 리스트에 없으면 특수 {"kind": None} 형태 (c10=True 판정)
    """
    snap = snapshot_date or await latest_snapshot_date()
    if snap is None:
        return None
    async with get_session() as session:
        stmt = (
            select(PowderKegKrxIssue)
            .where(PowderKegKrxIssue.ticker == ticker, PowderKegKrxIssue.snapshot_date == snap)
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return {"kind": None, "snapshot_date": snap}
    return {
        "kind": row.kind, "reason": row.reason,
        "designation_date": row.designation_date, "snapshot_date": snap,
    }


async def designation_history(ticker: str, lookback_days: int = 3 * 365) -> list[dict[str, Any]]:
    """최근 N일간 이 티커의 지정 이력."""
    kst = timezone(timedelta(hours=9))
    cutoff = (datetime.now(tz=kst).date() - timedelta(days=lookback_days)).isoformat()
    async with get_session() as session:
        stmt = (
            select(PowderKegKrxIssue)
            .where(
                PowderKegKrxIssue.ticker == ticker,
                PowderKegKrxIssue.snapshot_date >= cutoff,
            )
            .order_by(PowderKegKrxIssue.snapshot_date.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {"kind": r.kind, "reason": r.reason,
         "designation_date": r.designation_date, "snapshot_date": r.snapshot_date}
        for r in rows
    ]
