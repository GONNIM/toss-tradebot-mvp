"""한국 ETF 이름 목록 채우기 (1119-02 · 2026-11-22).

왜: 신호 목록에서 ETF 코드의 이름이 「확인 안 됨」으로 보였다. 이름 표 4곳(스냅샷 · 유니버스 · 화약고 목록 · KRX 메타)에 ETF 가 없다.
어디서: FinanceDataReader `StockListing('ETF/KR')` (열 Symbol · Name) — 원 출처는 네이버 금융 ETF 목록
(`finance.naver.com/api/sise/etfItemList.nhn`, FDR 0.9.202 naver/listing.py). ETN 은 FDR 에 목록이 없어(ETN/KR 은 NotImplementedError) 채우지 않는다.
어떻게 (Fable 11/22 조건부 GO 막음 4 · 5):
- 새 표 krx_etf_name (ticker · name · fetched_at) 에만 쓴다. KrxStockMeta 는 건드리지 않는다 (섹터 리더 모집단이 그 표 전 행을 읽음).
- upsert 만 한다. 지우지 않는다 (목록에서 빠진 코드도 남김).
- 받은 유효 행이 MIN_ROWS(500) 미만이거나 오류면 표를 건드리지 않고 예외를 낸다 → 호출한 잡이 시스템 알림을 보낸다.
- 이름 조회(stock_names)는 이 표를 읽기만 한다. 비로그인 요청이 바깥 호출을 일으키지 않는다.
- 서버 시작 채움: 표가 비었을 때만 · 뒤에서(asyncio.to_thread) · BIOTECH_API_ONLY=1 과 시험(pytest)에서는 안 돎 · 실패해도 시작은 계속.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MIN_ROWS = 500          # 한국 ETF 는 1,000개 넘게 상장 · 이보다 적게 받으면 목록이 잘린 것으로 보고 표를 건드리지 않는다


class EtfListingTooSmall(RuntimeError):
    """받은 유효 ETF 행이 MIN_ROWS 미만 — 표를 바꾸지 않았다."""


def fetch_etf_listing() -> list[tuple[str, str]]:
    """FDR 로 ETF 목록을 받아 (코드, 이름) 목록으로. 동기 · 바깥 호출 · 이벤트 루프 밖(asyncio.to_thread)에서 부른다."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("ETF/KR")
    return clean_rows(zip(df["Symbol"].tolist(), df["Name"].tolist()))


def clean_rows(pairs) -> list[tuple[str, str]]:
    """코드는 문자열 6자 이하 · 이름은 비지 않고 코드와 다른 것만 · 코드 중복은 첫 행."""
    out: dict[str, str] = {}
    for code, name in pairs:
        c = str(code or "").strip()
        n = str(name or "").strip()
        if not c or len(c) > 6 or not n or n == c:
            continue
        out.setdefault(c, n[:100])
    return list(out.items())


async def _ensure_table() -> None:
    """표가 없으면 만든다 (create_all 과 같은 방식 · 멱등). API 보다 cron 이 먼저 뜬 서버에서도 안전하다."""
    from backend.services.db import engine
    from backend.services.models import KrxEtfName

    async with engine.begin() as conn:
        await conn.run_sync(KrxEtfName.__table__.create, checkfirst=True)


async def etf_table_empty() -> bool:
    from sqlalchemy import func, select

    from backend.services.db import get_session
    from backend.services.models import KrxEtfName

    await _ensure_table()
    async with get_session() as session:
        return ((await session.execute(select(func.count()).select_from(KrxEtfName))).scalar() or 0) == 0


async def refresh_etf_names(fetch: Optional[Callable[[], list[tuple[str, str]]]] = None) -> dict[str, int]:
    """ETF 이름 목록을 받아 표에 upsert. 실패하면 예외 (표는 그대로).

    반환: {"fetched": 받은 유효 행, "inserted": 새 행, "updated": 이름이 바뀐 행, "unchanged": 그대로인 행}
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from backend.services.db import get_session
    from backend.services.models import KrxEtfName

    rows = await asyncio.to_thread(fetch or fetch_etf_listing)      # 이벤트 루프를 막지 않는다
    if len(rows) < MIN_ROWS:
        raise EtfListingTooSmall(f"ETF 목록 유효 행 {len(rows)}개 (최소 {MIN_ROWS}개) · 표를 바꾸지 않음")
    await _ensure_table()
    stats = {"fetched": len(rows), "inserted": 0, "updated": 0, "unchanged": 0}
    async with get_session() as session:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        existing = {r.ticker: r for r in (await session.execute(select(KrxEtfName))).scalars().all()}
        for code, name in rows:
            cur = existing.get(code)
            if cur is None:
                session.add(KrxEtfName(ticker=code, name=name, fetched_at=now))
                stats["inserted"] += 1
            else:
                if cur.name != name:
                    cur.name = name
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
                cur.fetched_at = now
        # 목록에서 빠진 코드는 지우지 않는다 (existing - rows 는 그대로 둔다)
    return stats


def startup_fill_allowed() -> bool:
    """서버 시작 채움을 해도 되는가. BIOTECH_API_ONLY=1(로컬 화면 확인) · 시험(pytest)에서는 바깥을 부르지 않는다."""
    if os.environ.get("BIOTECH_API_ONLY", "").lower() in {"1", "true", "yes", "on"}:
        return False
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


async def fill_on_start(
    fetch: Optional[Callable[[], list[tuple[str, str]]]] = None,
    alert: Optional[Callable] = None,
) -> Optional[dict[str, int]]:
    """서버 시작 때 표가 비었을 때만 한 번 채운다. 실패해도 예외를 밖으로 내지 않는다 (로그 + 시스템 알림 시도).

    시작을 기다리게 하지 않으려면 asyncio.create_task 로 떼어 부른다 (cron.py main_daemon).
    """
    if not startup_fill_allowed():
        return None
    try:
        if not await etf_table_empty():
            logger.info("[etf-names] 시작 채움 건너뜀 · 표에 행이 있음")
            return None
        stats = await refresh_etf_names(fetch)
        logger.info(f"[etf-names] 시작 채움 완료 {stats}")
        return stats
    except Exception as exc:  # noqa: BLE001 — 시작은 계속한다
        logger.error(f"[etf-names] 시작 채움 실패 · 표는 그대로: {type(exc).__name__}: {str(exc)[:200]}")
        if alert is not None:
            try:
                await alert(exc)
            except Exception as notify_exc:  # noqa: BLE001
                logger.error(f"[etf-names] 시작 채움 실패 알림 실패: {notify_exc}")
        return None
