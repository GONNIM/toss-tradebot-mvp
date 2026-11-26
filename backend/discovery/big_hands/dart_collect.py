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
import json
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional

import httpx
from sqlalchemy import select

from backend.discovery.data_sources.dart import client as dart_client
from backend.services.db import get_session

from .collect_models import DartCollectCursor, DartDocCache, DartInsiderRow, DartMajorstockRow
from .dart_parse import (
    MajorItem, document_zip_to_text, number_duplicate_lines, parse_elestock_item, parse_holding_purpose,
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
# document.xml 이 ZIP 대신 돌려주는 오류 글의 status 중 「그 접수번호의 원문이 없음」인 것 (client.py 의 013 · 시험 자료의 014).
# 나머지(010 키 오류 · 011 · 012 · 020 한도 · 021 · 100 · 800 점검 · 900 · 901)는 일시 오류라 캐시하지 않는다.
DOC_MISSING_STATUS = frozenset({"013", "014"})
ERROR_BODY_MAX = 4096          # 오류 글은 작다 · 이보다 큰 본문은 앞부분만 읽는다
LIST_PAGE_COUNT = 100
LIST_MAX_PAGES = 30


def _error_status(content: bytes) -> Optional[str]:
    """ZIP 이 아닌 document.xml 응답의 status. XML(<result><status>)을 먼저 읽고, 없으면 JSON 을 읽는다.

    DART 원문 주소는 오류를 XML 로 돌려준다 (실제 응답 확인 · 010). 외부 엔티티는 읽지 않고(DOCTYPE 이 있으면 XML 은 버림),
    큰 본문은 앞부분만 본다. 맨 앞 BOM 은 떼고 읽는다. 읽지 못하면(인코딩 선언 · 깨진 본문 포함) None.
    """
    head = content[:ERROR_BODY_MAX]
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    if head.lstrip()[:1] == b"<" and b"<!DOCTYPE" not in head.upper() and b"<!ENTITY" not in head.upper():
        try:
            node = ET.fromstring(head).find("status")
            if node is not None and (node.text or "").strip():
                return node.text.strip()
        except Exception:  # noqa: BLE001 · ParseError 말고도 ValueError(EUC-KR 같은 다중 바이트 선언)가 난다
            pass
    try:
        return str(json.loads(head).get("status") or "") or None
    except Exception:  # noqa: BLE001
        return None


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
        text = document_zip_to_text(resp.content)
        if text is not None:
            return "ok", text
        # ZIP 이 아니다 · DART 는 오류를 HTTP 200 과 오류 글(XML · 드물게 JSON)로도 돌려준다. 그 status 를 읽는다.
        status = _error_status(resp.content)
        if status == "020":
            raise RateLimited("DART 요청 한도 초과(020)")
        if resp.status_code == 200 and status in DOC_MISSING_STATUS:
            return "missing", None
        logger.warning("[big_hands.dart] document 받지 못함 · http=%s status=%s", resp.status_code, status)
        return "error", None                     # 4xx · 5xx · 알 수 없는 응답은 캐시하지 않고 다음에 다시 받는다

    async def list_disclosures(self, bgn: date, end: date, detail: str) -> Optional[list["ListedDisclosure"]]:
        """공시 목록(D001·D002). 호출 상한 · 간격을 지킨다. 실패는 None(공시 없음 = 빈 목록과 구분) · 한도 초과는 예외."""
        out: list[ListedDisclosure] = []
        page = 1
        while page <= LIST_MAX_PAGES:
            try:
                resp = await self._get("list.json", {
                    "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"), "pblntf_ty": "D",
                    "pblntf_detail_ty": detail, "page_count": LIST_PAGE_COUNT, "page_no": page})
                resp.raise_for_status()
                data = resp.json()
            except (CallLimit, RateLimited):
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[big_hands.dart] list %s 실패 · %s", detail, type(exc).__name__)
                return None
            status = data.get("status")
            if status == "013":
                return out
            if status == "020":
                raise RateLimited("DART 요청 한도 초과(020)")
            if status != "000":
                logger.warning("[big_hands.dart] list %s status=%s", detail, status)
                return None
            for it in data.get("list") or []:
                if not (it.get("stock_code") or "").strip():
                    continue                                   # 상장 회사만 (기존 목록 읽기와 같은 기준)
                out.append(ListedDisclosure(
                    corp_code=str(it.get("corp_code") or ""), rcept_no=str(it.get("rcept_no") or ""),
                    report_nm=str(it.get("report_nm") or "")))
            if page >= int(data.get("total_page") or 1):
                return out
            page += 1
        logger.warning("[big_hands.dart] list %s 쪽 수 상한 %d 에서 멈춤", detail, LIST_MAX_PAGES)
        return None                                            # 끝까지 못 읽은 목록은 실패로 본다


@dataclass(frozen=True)
class ListedDisclosure:
    corp_code: str
    rcept_no: str
    report_nm: str


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
            items = number_duplicate_lines([i for i in (parse_elestock_item({**r, "corp_code": r.get("corp_code") or corp_code}) for r in raw) if i])
            stats.insider_new += len(await _save_insider(items, since, nm))
            await _process_insider_docs(collector, corp_code, stats, budget)
            if mark_cursor:
                await _mark_cursor(corp_code, "elestock", len(items), DartInsiderRow)
    if "majorstock" in kinds:
        raw = await collector.fetch_majorstock(corp_code)
        if raw is None:
            stats.failed_corps = 1
        else:
            items = number_duplicate_lines([i for i in (parse_majorstock_item({**r, "corp_code": r.get("corp_code") or corp_code}) for r in raw) if i])
            stats.major_new += len(await _save_major(items, since, nm))
            await _process_major_docs(collector, corp_code, stats, budget)
            if mark_cursor:
                await _mark_cursor(corp_code, "majorstock", len(items), DartMajorstockRow)
    return stats


# ── 매일 수집 ───────────────────────────────────────────────────────────

async def collect_daily(
    today: Optional[date] = None, *, collector: Optional[DartCollector] = None,
    lister: Optional[Callable[[date, date, str], Awaitable[Optional[list]]]] = None,
) -> dict[str, Any]:
    """장 마감 뒤 1회. 최근 며칠의 임원(D002) · 5%(D001) 공시 목록에서 회사를 찾아 그 회사만 받는다.

    목록 호출도 호출 상한 · 간격에 들어간다. 목록 호출이 실패하면 빈 목록으로 두지 않고
    요약의 list_failed 에 적는다(「공시 없음」과 구분). lister 는 시험용 · 실패는 None 으로 돌려준다.
    """
    if not dart_client.is_configured() and collector is None:
        logger.info("[big_hands_dart_collect] DART 키 없음 · 건너뜀")
        return {"skipped": "no_key"}
    end = today or datetime.now(timezone(timedelta(hours=9))).date()
    bgn = end - timedelta(days=DAILY_LOOKBACK_DAYS)
    col = collector or DartCollector(gap_sec=DAILY_GAP_SEC, max_calls=DAILY_MAX_CALLS)
    fetch_list = lister or col.list_disclosures
    list_failed: list[str] = []
    stopped = None
    lists: dict[str, list] = {}
    try:
        for detail in ("D002", "D001"):
            got = await fetch_list(bgn, end, detail)
            if got is None:
                list_failed.append(detail)
                got = []
            lists[detail] = got
    except CallLimit:
        stopped = "call_limit"
    except RateLimited:
        stopped = "rate_limited"
    insiders, majors = lists.get("D002", []), lists.get("D001", [])
    if list_failed:
        logger.warning("[big_hands_dart_collect] 공시 목록 호출 실패 %s · 「공시 없음」이 아님", list_failed)
    names = {d.rcept_no: d.report_nm for d in [*insiders, *majors]}
    ins_corps = sorted({d.corp_code for d in insiders if d.corp_code})
    maj_corps = sorted({d.corp_code for d in majors if d.corp_code})
    corps = sorted(set(ins_corps) | set(maj_corps))[:DAILY_MAX_CORPS] if stopped is None else []
    total, budget = CorpStats(), [DAILY_MAX_DOCS]
    done = 0
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
        "list_failed": list_failed,
    }
    logger.info("[big_hands_dart_collect] %s", summary)
    return summary
