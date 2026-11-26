"""국내 공시 수집 (1119-03 ② · 기획서 ② 「임원 공시 수집 2단계」 · 「5% 공시」).

흐름 (회사 하나):
  (1) elestock · majorstock 을 부른다 (바깥 호출 · DB 거래 밖).
  (2) 새 줄만 저장한다 (row_key 고유 · 다시 돌려도 중복 없음).
  (3) 임원 줄은 증감 수가 0 보다 큰 건만, 5% 줄은 신규 보고만 원문을 받는다. 원문은 접수번호로 캐시한다.
  (4) 줄마다 processed_at 을 적고, 과거 채우기는 회사마다 처리 표시(dart_collect_cursor)를 남긴다.
      매일 수집은 최근 며칠만 받으므로 회사 처리 표시를 남기지 않는다 (과거 채우기가 그 회사를 건너뛰지 않게).
바깥 호출은 DB 쓰기 거래 안에서 하지 않는다 (교훈 #20 · 짧은 세션으로 나눠 쓴다).
기존 화면 · API · 알림 · 점수에는 연결하지 않는다 (막음 6).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional

import httpx
from sqlalchemy import select

from backend.discovery.data_sources.dart import client as dart_client
from backend.services.db import get_session

from .collect_models import DartCollectCursor, DartDocCache, DartInsiderRow, DartMajorstockRow
from .dart_parse import (
    MajorItem, document_zip_to_text, parse_elestock_item, parse_holding_purpose,
    parse_insider_trade_lines, parse_majorstock_item,
)

logger = logging.getLogger(__name__)

DART_BASE = "https://opendart.fss.or.kr/api"
_TIMEOUT = 20.0
DAILY_LOOKBACK_DAYS = 3        # 서버가 하루 쉬었어도 이어 받는다 (같은 줄은 row_key 로 중복 없음)
DAILY_MAX_CORPS = 300
DAILY_MAX_DOCS = 300
DAILY_MAX_CALLS = 1500          # 하루 한도(보통 20,000)의 한 자리 수 %
DAILY_GAP_SEC = 0.5
ENABLE_ENV = "BIG_HANDS_COLLECT_ENABLED"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def collect_enabled() -> bool:
    """기본 꺼짐. 켜는 것은 사용자 승인 뒤에 환경변수로만 (병합만으로 운영 호출이 늘지 않게)."""
    return os.getenv(ENABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class CallLimit(Exception):
    """이번 실행의 호출 상한에 닿음."""


class RateLimited(Exception):
    """DART 가 한도 초과(020)를 알림 · 오늘은 더 부르지 않는다."""


class DartCollector:
    """호출 수 · 간격 · 상한을 한곳에서 지킨다. 시험은 http 와 sleep 을 바꿔 끼운다."""

    def __init__(
        self, *, key: Optional[str] = None, http: Optional[httpx.AsyncClient] = None,
        gap_sec: float = 1.0, max_calls: int = 1000,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._key = key
        self._http = http
        self.gap_sec = gap_sec
        self.max_calls = max_calls
        self._sleep = sleep
        self.calls = 0
        self._first = True

    def _api_key(self) -> str:
        return self._key or dart_client._api_key()

    async def _get(self, name: str, params: dict[str, Any]) -> httpx.Response:
        if self.calls >= self.max_calls:
            raise CallLimit(f"호출 상한 {self.max_calls}")
        if not self._first and self.gap_sec > 0:
            await self._sleep(self.gap_sec)
        self._first = False
        self.calls += 1
        http = self._http or httpx.AsyncClient()
        try:
            return await http.get(f"{DART_BASE}/{name}", params={"crtfc_key": self._api_key(), **params}, timeout=_TIMEOUT)
        finally:
            if self._http is None:
                await http.aclose()

    async def _json_list(self, name: str, params: dict[str, Any]) -> Optional[list[dict[str, Any]]]:
        """성공이면 목록(없음 013 은 빈 목록) · 한도 초과는 예외 · 그 밖의 실패는 None (처리 표시를 하지 않는다)."""
        try:
            resp = await self._get(name, params)
            resp.raise_for_status()
            data = resp.json()
        except (CallLimit, RateLimited):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[big_hands.dart] %s 실패 · %s", name, type(exc).__name__)   # 주소 · 키는 로그에 안 남김
            return None
        status = data.get("status")
        if status == "000":
            return list(data.get("list") or [])
        if status == "013":
            return []
        if status == "020":
            raise RateLimited("DART 요청 한도 초과(020)")
        logger.warning("[big_hands.dart] %s status=%s", name, status)
        return None

    async def fetch_elestock(self, corp_code: str) -> Optional[list[dict[str, Any]]]:
        return await self._json_list("elestock.json", {"corp_code": corp_code})

    async def fetch_majorstock(self, corp_code: str) -> Optional[list[dict[str, Any]]]:
        return await self._json_list("majorstock.json", {"corp_code": corp_code})

    async def fetch_document_text(self, rcept_no: str) -> tuple[str, Optional[str]]:
        """(상태, 글) · 상태 ok | missing | error. error 는 캐시하지 않는다."""
        try:
            resp = await self._get("document.xml", {"rcept_no": rcept_no})
        except (CallLimit, RateLimited):
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[big_hands.dart] document 실패 · %s", type(exc).__name__)
            return "error", None
        if resp.status_code >= 500:
            return "error", None
        text = document_zip_to_text(resp.content)
        if text is None:
            return "missing", None
        return "ok", text


@dataclass
class CorpStats:
    insider_new: int = 0
    major_new: int = 0
    docs_fetched: int = 0
    doc_cache_hits: int = 0
    failed_corps: int = 0

    def add(self, o: "CorpStats") -> None:
        self.insider_new += o.insider_new
        self.major_new += o.major_new
        self.docs_fetched += o.docs_fetched
        self.doc_cache_hits += o.doc_cache_hits
        self.failed_corps += o.failed_corps


# ── 저장 ────────────────────────────────────────────────────────────────

async def _save_insider(items: Iterable, since: Optional[date], names: dict[str, str]) -> list[str]:
    """새 줄만 저장하고 새로 쓴 row_key 목록을 돌려준다."""
    new_keys: list[str] = []
    async with get_session() as session:
        for it in items:
            if since is not None and it.rcept_date < since:
                continue
            exists = (await session.execute(select(DartInsiderRow.id).where(DartInsiderRow.row_key == it.key))).first()
            if exists is not None:
                continue
            need_doc = (it.change_qty or 0) > 0
            session.add(DartInsiderRow(
                row_key=it.key, rcept_no=it.rcept_no, corp_code=it.corp_code, stock_code=it.stock_code,
                rcept_date=it.rcept_date, report_nm=names.get(it.rcept_no), repror=it.repror, position=it.position,
                is_main_holder=it.is_main_holder, hold_qty=it.hold_qty, change_qty=it.change_qty,
                hold_rate=it.hold_rate, change_rate=it.change_rate,
                doc_status=None if need_doc else "none", processed_at=None if need_doc else _now(),
            ))
            new_keys.append(it.key)
    return new_keys


async def _save_major(items: Iterable[MajorItem], since: Optional[date], names: dict[str, str]) -> list[str]:
    new_keys: list[str] = []
    async with get_session() as session:
        for it in items:
            if since is not None and it.rcept_date < since:
                continue
            exists = (await session.execute(select(DartMajorstockRow.id).where(DartMajorstockRow.row_key == it.key))).first()
            if exists is not None:
                continue
            need_doc = "신규" in it.report_tp
            session.add(DartMajorstockRow(
                row_key=it.key, rcept_no=it.rcept_no, corp_code=it.corp_code, stock_code=it.stock_code,
                rcept_date=it.rcept_date, report_nm=names.get(it.rcept_no), report_tp=it.report_tp, repror=it.repror,
                hold_qty=it.hold_qty, change_qty=it.change_qty, hold_rate=it.hold_rate, change_rate=it.change_rate,
                report_resn=it.report_resn, doc_status=None if need_doc else "none",
                processed_at=None if need_doc else _now(),
            ))
            new_keys.append(it.key)
    return new_keys


async def _get_or_fetch_doc(collector: DartCollector, rcept_no: str, stats: CorpStats) -> tuple[str, Optional[str]]:
    async with get_session() as session:
        cached = await session.get(DartDocCache, rcept_no)
        if cached is not None:
            stats.doc_cache_hits += 1
            return cached.status, cached.body_text
    status, text = await collector.fetch_document_text(rcept_no)        # 바깥 호출 · DB 거래 밖
    stats.docs_fetched += 1
    if status != "error":
        async with get_session() as session:
            if await session.get(DartDocCache, rcept_no) is None:
                session.add(DartDocCache(rcept_no=rcept_no, status=status, body_text=text))
    return status, text


async def _process_insider_docs(collector: DartCollector, corp_code: str, stats: CorpStats, doc_budget: list[int]) -> None:
    async with get_session() as session:
        pending = (await session.execute(select(DartInsiderRow.row_key, DartInsiderRow.rcept_no, DartInsiderRow.rcept_date).where(
            DartInsiderRow.corp_code == corp_code, DartInsiderRow.processed_at.is_(None),
        ).order_by(DartInsiderRow.rcept_date))).all()
    for row_key, rcept_no, rcept_date in pending:
        if doc_budget[0] <= 0:
            return
        status, text = await _get_or_fetch_doc(collector, rcept_no, stats)
        doc_budget[0] -= 1
        if status == "error":
            continue                                    # 처리 표시를 하지 않아 다음에 다시 시도
        lines = parse_insider_trade_lines(text) if text else []
        # 한 접수번호에 매매 줄이 여럿이면 접수일에 가장 가까운 줄 하나만 줄에 싣는다 (나머지는 원문 캐시에 남음)
        best = min(lines, key=lambda x: abs((x.trade_date - rcept_date).days)) if lines else None
        async with get_session() as session:
            row = (await session.execute(select(DartInsiderRow).where(DartInsiderRow.row_key == row_key))).scalar_one()
            if best is not None:
                row.trade_date, row.method, row.unit_price = best.trade_date, best.method[:60], best.unit_price
                row.doc_status = "parsed"
            else:
                row.doc_status = "missing" if status == "missing" else "unparsed"
            row.processed_at = _now()


async def _process_major_docs(collector: DartCollector, corp_code: str, stats: CorpStats, doc_budget: list[int]) -> None:
    async with get_session() as session:
        pending = (await session.execute(select(DartMajorstockRow.row_key, DartMajorstockRow.rcept_no, DartMajorstockRow.report_nm).where(
            DartMajorstockRow.corp_code == corp_code, DartMajorstockRow.processed_at.is_(None),
        ).order_by(DartMajorstockRow.rcept_date))).all()
    for row_key, rcept_no, report_nm in pending:
        if doc_budget[0] <= 0:
            return
        status, text = await _get_or_fetch_doc(collector, rcept_no, stats)
        doc_budget[0] -= 1
        if status == "error":
            continue
        purpose = parse_holding_purpose(text or "", report_nm)
        async with get_session() as session:
            row = (await session.execute(select(DartMajorstockRow).where(DartMajorstockRow.row_key == row_key))).scalar_one()
            row.purpose = purpose
            row.doc_status = "parsed" if purpose else ("missing" if status == "missing" else "unparsed")
            row.processed_at = _now()


async def _mark_cursor(corp_code: str, kind: str, rows_seen: int, table: Any) -> None:
    """원문 단계가 남은 줄이 없을 때만 처리 완료로 적는다 (상한에 걸려 남았으면 다음에 이어 받는다)."""
    async with get_session() as session:
        left = (await session.execute(select(table.id).where(
            table.corp_code == corp_code, table.processed_at.is_(None)).limit(1))).first()
        done_at = None if left is not None else _now()
        cur = await session.get(DartCollectCursor, (corp_code, kind))
        if cur is None:
            session.add(DartCollectCursor(corp_code=corp_code, kind=kind, rows_seen=rows_seen, processed_at=done_at))
        else:
            cur.rows_seen, cur.processed_at = rows_seen, done_at


async def collect_corp(
    collector: DartCollector, corp_code: str, *, kinds: tuple[str, ...] = ("elestock", "majorstock"),
    since: Optional[date] = None, doc_budget: Optional[list[int]] = None, names: Optional[dict[str, str]] = None,
    mark_cursor: bool = True,
) -> CorpStats:
    """회사 하나를 끝까지 처리한다. 호출이 실패하면 그 종류의 처리 표시를 하지 않는다(다음에 다시)."""
    stats = CorpStats()
    budget = doc_budget if doc_budget is not None else [10**9]
    nm = names or {}
    if "elestock" in kinds:
        raw = await collector.fetch_elestock(corp_code)
        if raw is None:
            stats.failed_corps = 1
        else:
            items = [i for i in (parse_elestock_item({**r, "corp_code": r.get("corp_code") or corp_code}) for r in raw) if i]
            stats.insider_new += len(await _save_insider(items, since, nm))
            await _process_insider_docs(collector, corp_code, stats, budget)
            if mark_cursor:
                await _mark_cursor(corp_code, "elestock", len(items), DartInsiderRow)
    if "majorstock" in kinds:
        raw = await collector.fetch_majorstock(corp_code)
        if raw is None:
            stats.failed_corps = 1
        else:
            items = [i for i in (parse_majorstock_item({**r, "corp_code": r.get("corp_code") or corp_code}) for r in raw) if i]
            stats.major_new += len(await _save_major(items, since, nm))
            await _process_major_docs(collector, corp_code, stats, budget)
            if mark_cursor:
                await _mark_cursor(corp_code, "majorstock", len(items), DartMajorstockRow)
    return stats


# ── 매일 수집 ───────────────────────────────────────────────────────────

async def _list_disclosures(bgn: date, end: date, detail: str):
    return await dart_client.fetch_recent_disclosures(
        bgn_de=bgn, end_de=end, pblntf_ty="D", pblntf_detail_ty=detail, only_listed=True,
    )


async def collect_daily(
    today: Optional[date] = None, *, collector: Optional[DartCollector] = None,
    lister: Callable[[date, date, str], Awaitable[list]] = _list_disclosures,
) -> dict[str, Any]:
    """장 마감 뒤 1회. 최근 며칠의 임원(D002) · 5%(D001) 공시 목록에서 회사를 찾아 그 회사만 받는다.

    목록 호출은 하루 몇 쪽이라 회사 수천 곳을 모두 부르는 것보다 훨씬 적다.
    """
    if not dart_client.is_configured() and collector is None:
        logger.info("[big_hands_dart_collect] DART 키 없음 · 건너뜀")
        return {"skipped": "no_key"}
    end = today or datetime.now(timezone(timedelta(hours=9))).date()
    bgn = end - timedelta(days=DAILY_LOOKBACK_DAYS)
    col = collector or DartCollector(gap_sec=DAILY_GAP_SEC, max_calls=DAILY_MAX_CALLS)
    insiders = await lister(bgn, end, "D002")
    majors = await lister(bgn, end, "D001")
    names = {d.rcept_no: d.report_nm for d in [*insiders, *majors]}
    ins_corps = sorted({d.corp_code for d in insiders if d.corp_code})
    maj_corps = sorted({d.corp_code for d in majors if d.corp_code})
    corps = sorted(set(ins_corps) | set(maj_corps))[:DAILY_MAX_CORPS]
    total, budget = CorpStats(), [DAILY_MAX_DOCS]
    done, stopped = 0, None
    for corp in corps:
        kinds = tuple(k for k, s in (("elestock", ins_corps), ("majorstock", maj_corps)) if corp in s)
        try:
            total.add(await collect_corp(col, corp, kinds=kinds, since=bgn, doc_budget=budget, names=names, mark_cursor=False))
        except CallLimit:
            stopped = "call_limit"
            break
        except RateLimited:
            stopped = "rate_limited"
            break
        done += 1
    summary = {
        "window": f"{bgn}~{end}", "corps_found": len(set(ins_corps) | set(maj_corps)), "corps_done": done,
        "insider_new": total.insider_new, "major_new": total.major_new,
        "docs_fetched": total.docs_fetched, "doc_cache_hits": total.doc_cache_hits,
        "failed_corps": total.failed_corps, "dart_calls": col.calls, "stopped": stopped,
    }
    logger.info("[big_hands_dart_collect] %s", summary)
    return summary
