"""알림용 한국 종목명 읽기 조회 (1023-05 · 2026-10-23).

DB 칸 추가 없이 이미 있는 표에서 이름을 찾는다. 조회가 실패·지연돼도 알림은 그대로 나가야 하므로
예외와 시간 초과는 None 으로 돌려준다 (호출 측은 「종목명 확인 안 됨 (코드)」로 표시).
순서: 화약고 시장 스냅샷 최신 → 실주문 유니버스 → 화약고 목록 최신 → KRX 메타 (채우는 잡이 없어 마지막).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 2.0


def _session():
    from backend.services.db import get_session

    return get_session()


async def _query(ticker: str) -> Optional[str]:
    from sqlalchemy import select

    from backend.services.models import KrxMarketSnapshot, KrxStockMeta, LiveTapeUniverse, PowderKegList

    stmts = (
        select(KrxMarketSnapshot.name)
        .where(KrxMarketSnapshot.ticker == ticker, KrxMarketSnapshot.name.is_not(None), KrxMarketSnapshot.name != "")
        .order_by(KrxMarketSnapshot.snapshot_date.desc()).limit(1),
        select(LiveTapeUniverse.name).where(LiveTapeUniverse.ticker == ticker).limit(1),
        select(PowderKegList.name)
        .where(PowderKegList.ticker == ticker, PowderKegList.name.is_not(None), PowderKegList.name != "")
        .order_by(PowderKegList.run_id.desc()).limit(1),
        select(KrxStockMeta.name).where(KrxStockMeta.ticker == ticker).limit(1),
    )
    async with _session() as session:
        for stmt in stmts:
            name = (await session.execute(stmt)).scalar()
            if name:
                return name
    return None


async def lookup_kr_name(ticker: str, cache: Optional[dict[str, Optional[str]]] = None) -> Optional[str]:
    """종목 코드 → 이름. 못 찾거나 실패하면 None. cache 는 한 번 실행 안에서만 쓴다."""
    if cache is not None and ticker in cache:
        return cache[ticker]
    try:
        name = await asyncio.wait_for(_query(ticker), TIMEOUT_SEC)
    except Exception as exc:  # noqa: BLE001 — 시간 초과 포함 · 알림을 막지 않는다
        logger.warning(f"[stock-names] {ticker} 이름 조회 실패: {exc.__class__.__name__}")
        name = None
    if name is None:
        logger.warning(f"[stock-names] {ticker} 이름을 찾지 못함")
    if cache is not None:
        cache[ticker] = name
    return name


# ─────────────────────────────────────────────────────────────────
# 1119-02 · 한꺼번에 찾기 (화면 응답 · 알림용). 한 건 조회(lookup_kr_name)는 위 그대로 둔다.
# ─────────────────────────────────────────────────────────────────
CHUNK = 500            # SQLite 변수 한도 대비 · 500개씩 IN 조회
MEMO_TTL_SEC = 600     # 서버 안 기억 10분
_memo: dict[tuple[str, str], tuple[float, Optional[str]]] = {}
_bg_tasks: set = set()   # 떼어 보낸 작업 참조 (끝나기 전에 사라지지 않게 · 끝나면 지움)


def clear_memo() -> None:
    _memo.clear()


def _clean(name, code: str) -> Optional[str]:
    """빈칸이거나 코드와 같으면 「못 찾음」."""
    n = (name or "").strip()
    return n if n and n != code else None


def _memo_get(market: str, code: str, now: float):
    hit = _memo.get((market, code))
    if hit and now - hit[0] < MEMO_TTL_SEC:
        return True, hit[1]
    return False, None


def peek_name(code: str) -> Optional[str]:
    """기억된 이름만 읽는다 (새 조회 없음 · 주문 경로 알림용). 없으면 None."""
    from backend.services.broker_links import is_kr_code

    market = "KR" if is_kr_code(code) else "US"
    return _memo_get(market, code, time.monotonic())[1]


def _chunks(items: list[str]):
    for i in range(0, len(items), CHUNK):
        yield items[i:i + CHUNK]


async def _kr_table(idx: int, chunk: list[str]) -> dict[str, str]:
    """표 하나에서 코드 묶음의 이름을 한 번에 읽는다 (날짜가 쌓이는 표는 코드별 최신 한 행만)."""
    from sqlalchemy import and_, func, select

    from backend.services.models import KrxMarketSnapshot as M, KrxStockMeta, LiveTapeUniverse, PowderKegList as P

    if idx == 0:
        sub = (select(M.ticker.label("t"), func.max(M.snapshot_date).label("d"))
               .where(M.ticker.in_(chunk), M.name.is_not(None), M.name != "").group_by(M.ticker).subquery())
        stmt = select(M.ticker, M.name).join(sub, and_(M.ticker == sub.c.t, M.snapshot_date == sub.c.d))
    elif idx == 1:
        stmt = select(LiveTapeUniverse.ticker, LiveTapeUniverse.name).where(LiveTapeUniverse.ticker.in_(chunk))
    elif idx == 2:
        sub = (select(P.ticker.label("t"), func.max(P.run_id).label("d"))
               .where(P.ticker.in_(chunk), P.name.is_not(None), P.name != "").group_by(P.ticker).subquery())
        stmt = select(P.ticker, P.name).join(sub, and_(P.ticker == sub.c.t, P.run_id == sub.c.d))
    else:
        stmt = select(KrxStockMeta.ticker, KrxStockMeta.name).where(KrxStockMeta.ticker.in_(chunk))
    out: dict[str, str] = {}
    async with _session() as session:
        for code, name in (await session.execute(stmt)).all():
            n = _clean(name, code)
            if n:
                out.setdefault(code, n)
    return out


async def _us_table(idx: int, chunk: list[str]) -> dict[str, str]:
    from sqlalchemy import select

    from backend.services.models import MemeUniverse, TickerUniverse

    if idx == 0:
        stmt = select(TickerUniverse.symbol, TickerUniverse.company_name).where(TickerUniverse.symbol.in_(chunk))
    else:
        stmt = select(MemeUniverse.ticker, MemeUniverse.name).where(MemeUniverse.market == "US", MemeUniverse.ticker.in_(chunk))
    out: dict[str, str] = {}
    async with _session() as session:
        for code, name in (await session.execute(stmt)).all():
            n = _clean(name, code)
            if n:
                out.setdefault(code, n)
    return out


async def _lookup_many(market: str, codes: Iterable[str], table_fn, tables: int) -> dict[str, str]:
    now = time.monotonic()
    found: dict[str, str] = {}
    todo: list[str] = []
    for c in dict.fromkeys(c for c in codes if c):
        hit, name = _memo_get(market, c, now)
        if hit:
            if name:
                found[c] = name
        else:
            todo.append(c)
    if not todo:
        return found
    state = {"failed": False}
    got: dict[str, str] = {}

    async def run() -> None:
        for idx in range(tables):
            missing = [c for c in todo if c not in got]
            if not missing:
                return
            for chunk in _chunks(missing):
                try:
                    got.update(await table_fn(idx, chunk))
                except Exception as exc:  # noqa: BLE001 — 그 표만 건너뛴다
                    state["failed"] = True
                    logger.warning(f"[stock-names] {market} 표 {idx} 읽기 실패: {exc.__class__.__name__}")

    complete = False
    try:
        await asyncio.wait_for(run(), TIMEOUT_SEC)
        complete = not state["failed"]
    except asyncio.TimeoutError:
        logger.warning(f"[stock-names] {market} 이름 조회 시간 초과 · 찾은 {len(got)}/{len(todo)}개만 사용")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[stock-names] {market} 이름 조회 실패: {exc.__class__.__name__}")
    stamp = time.monotonic()
    for c in todo:
        if c in got:
            _memo[(market, c)] = (stamp, got[c])
            found[c] = got[c]
        elif complete:           # 표를 끝까지 읽고도 없을 때만 「못 찾음」을 기억한다
            _memo[(market, c)] = (stamp, None)
    return found


async def lookup_kr_names(codes: Iterable[str]) -> dict[str, str]:
    """한국 종목 코드 묶음 → {코드: 이름} (못 찾은 코드는 빠짐). 출처 순서는 lookup_kr_name 과 같다."""
    return await _lookup_many("KR", codes, _kr_table, 4)


async def lookup_us_names(tickers: Iterable[str]) -> dict[str, str]:
    """미국 티커 묶음 → {티커: 회사명} (못 찾은 티커는 빠짐). TickerUniverse → MemeUniverse(US)."""
    return await _lookup_many("US", tickers, _us_table, 2)


async def lookup_names(codes: Iterable[str]) -> dict[str, str]:
    """시장을 섞어 받는다 (한국 판별은 is_kr_code). 실패해도 예외 없이 찾은 것만 돌려준다."""
    from backend.services.broker_links import is_kr_code

    uniq = [c for c in dict.fromkeys(str(c) for c in codes if c)]
    kr = [c for c in uniq if is_kr_code(c)]
    us = [c for c in uniq if not is_kr_code(c)]
    out: dict[str, str] = {}
    try:
        if kr:
            out.update(await lookup_kr_names(kr))
        if us:
            out.update(await lookup_us_names(us))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[stock-names] 묶음 조회 실패: {exc.__class__.__name__}")
    return out


def warm_names_bg(codes: Iterable[str]) -> None:
    """이름을 기억에 미리 채운다 (떼어 보냄 · 기다리지 않음 · 예외는 로그 1줄). 이벤트 루프가 없으면 건너뜀."""
    items = [c for c in dict.fromkeys(codes) if c]
    if not items:
        return
    try:
        task = asyncio.get_running_loop().create_task(_warm(items))
    except RuntimeError:
        return
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _warm(items: list[str]) -> None:
    try:
        await lookup_names(items)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[stock-names] 미리 읽기 실패: {exc.__class__.__name__}")


async def fill_names(items, code_key: str = "ticker", name_key: str = "name") -> None:
    """응답 행(딕셔너리 또는 pydantic 객체) 목록에 name 칸을 채운다. 이미 이름이 있으면 그대로 둔다.
    이름 조회가 실패해도 예외 없이 name 은 비워 둔다 (목록 전체가 실패하지 않음)."""
    rows = list(items or [])

    def get(r, k):
        return r.get(k) if isinstance(r, dict) else getattr(r, k, None)

    def put(r, k, v):
        if isinstance(r, dict):
            r[k] = v
        else:
            setattr(r, k, v)

    need = [get(r, code_key) for r in rows if get(r, code_key) and not get(r, name_key)]
    if not need:
        return
    names = await lookup_names(need)
    for r in rows:
        c = get(r, code_key)
        if c and not get(r, name_key):
            put(r, name_key, names.get(c))
