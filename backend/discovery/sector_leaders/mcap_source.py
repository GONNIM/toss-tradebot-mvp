"""섹터 시가총액 갱신 · 출처 고르기 (1122-01).

배경: 섹터 점수 = log10(시총) × 수출 비중 은 KrxStockMeta.market_cap_krw 를 읽는데,
이 표를 고치는 코드가 없어 처음 적재한 값 그대로였다.

구성:
  1. refresh_sector_meta  — 섹터 잡 3개의 재계산 직전 단계. FDR KOSPI+KOSDAQ 에서 매핑 종목만 갱신.
  2. load_mcap_choice     — 재계산 때 쓸 시총 출처 고르기. 「최신 KrxMarketSnapshot」과 「KrxStockMeta」 가운데
                            날짜가 더 새로운 쪽을 한 번에 모든 종목에 쓰고, 그 출처에 없는 종목만 다른 쪽으로 채운다.
  3. pick_last_close      — top10 의 대체 가격 (메타 · 스냅샷 중 날짜가 새로운 쪽).

주의: 11:30 · 12:00 에 받은 값은 장중 값일 수 있다 (추정 · 확인하지 않음).
화면 시총 기준일은 표시하지 않는다 — fetched_at 은 onupdate 라 기준일로 쓸 수 없다 (Fable M4).
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.discovery.data_sources.krx_price.loader import fetch_sector_listing
from backend.services.models import KrxMarketSnapshot, KrxStockMeta

logger = logging.getLogger(__name__)

# 받은 목록(KOSPI+KOSDAQ) 행 수가 이 값 미만이면 부분 응답으로 보고 갱신 전체를 건너뛴다.
# 근거: 11/22 로컬 실측 KOSPI 935 + KOSDAQ 1836 = 2771행 · 운영 스냅샷 2771행. 그 약 72%.
MIN_LISTING_ROWS = 2000
# 매핑 종목 중 유효한 시총을 찾은 비율이 이 값 미만이면 갱신 전체를 건너뛴다 (51쌍 · 49종목이면 40개 미만 · 40 = 49 의 0.8 올림).
MIN_FOUND_RATIO = 0.8
# FDR 목록 받기 제한 시간(초). FDR 내부 requests.get 에 timeout 이 없어 멈추면 잡이 안 끝난다 (1122-04).
# 근거: 11/22 로컬 정상 실측 3회 0.8~1.4초 (KOSPI+KOSDAQ 두 번 받기). 약 20배인 30초로 둔다.
# 주의: wait_for 는 기다리는 쪽만 끊는다. asyncio.to_thread 로 돈 FDR 스레드는 못 죽이고 끝날 때까지 남아 돈다
# (결과는 버려짐 · 다음 잡 때 새 스레드로 다시 받음 · 스레드가 영영 안 끝나면 그만큼 새는 점은 남은 위험).
FETCH_TIMEOUT_SEC = 30.0


def _valid(v: Any) -> Optional[float]:
    """유한하고 0 보다 큰 숫자만 돌려준다. 아니면 None (옛 값 유지)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f <= 0:
        return None
    return f


def _market(r: Any) -> Optional[str]:
    v = r.get("Market")
    return str(v)[:10] if v else None


async def refresh_sector_meta(
    session: AsyncSession,
    codes: Iterable[str],
    *,
    fetcher: Optional[Callable[[], Awaitable[Any]]] = None,
) -> dict:
    """매핑 종목의 시총 · 종가를 KrxStockMeta 에 갱신. 기준 미달이면 아무것도 쓰지 않는다.

    - 유한하고 0 초과인 값만 쓴다. 아니면 그 칸은 옛 값 그대로 (upsert_meta 의 0 → None 덮어쓰기는 쓰지 않음).
    - 쓰기 뒤 commit 은 호출자가 한다.
    """
    wanted = sorted(set(codes))
    stats: dict = {"wanted": len(wanted), "listing_rows": 0, "found": 0,
                   "updated": 0, "inserted": 0, "skipped": False}
    try:
        df = await asyncio.wait_for((fetcher or fetch_sector_listing)(), timeout=FETCH_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        stats["skipped"] = True
        stats["reason"] = f"timeout>{FETCH_TIMEOUT_SEC:g}s"
        logger.warning(f"[krx_meta_refresh] 건너뜀 · 목록 받기가 {FETCH_TIMEOUT_SEC:g}초 안에 끝나지 않음 (재계산은 계속)")
        return stats
    rows = len(df)
    stats["listing_rows"] = rows
    if rows < MIN_LISTING_ROWS:
        stats["skipped"] = True
        stats["reason"] = f"listing_rows<{MIN_LISTING_ROWS}"
        logger.warning(f"[krx_meta_refresh] 건너뜀 · 받은 목록 행 수 {rows} < {MIN_LISTING_ROWS}")
        return stats

    by_code: dict[str, Any] = {}
    for _, r in df.iterrows():
        code = str(r.get("Code") or "").strip()
        if code:
            by_code[code] = r
    usable = {c: by_code[c] for c in wanted
              if c in by_code and _valid(by_code[c].get("Marcap")) is not None}
    stats["found"] = len(usable)
    need = math.ceil(len(wanted) * MIN_FOUND_RATIO)
    if len(usable) < need:
        stats["skipped"] = True
        stats["reason"] = f"found<{need}"
        logger.warning(f"[krx_meta_refresh] 건너뜀 · 유효 시총을 찾은 종목 {len(usable)}/{len(wanted)} < {need}")
        return stats

    existing = {
        m.ticker: m
        for m in (await session.execute(
            select(KrxStockMeta).where(KrxStockMeta.ticker.in_(list(usable)))
        )).scalars()
    }
    for code, r in usable.items():
        marcap = _valid(r.get("Marcap"))
        close = _valid(r.get("Close"))
        shares = _valid(r.get("Stocks"))
        m = existing.get(code)
        if m is None:
            session.add(KrxStockMeta(
                ticker=code, name=str(r.get("Name") or code)[:50], market=_market(r),
                market_cap_krw=marcap, shares_outstanding=shares, last_close=close,
            ))
            stats["inserted"] += 1
            continue
        m.market_cap_krw = marcap
        if close is not None:
            m.last_close = close
        if shares is not None:
            m.shares_outstanding = shares
        mk = _market(r)
        if mk:
            m.market = mk
        stats["updated"] += 1
    logger.info(f"[krx_meta_refresh] 결과 {stats} (11:30·12:00 값은 장중 값일 수 있음 · 추정)")
    return stats


# ─────────────────────────────────────────────────────────────────
# 출처 고르기
# ─────────────────────────────────────────────────────────────────


@dataclass
class McapChoice:
    values: dict[str, float]             # ticker -> 시총
    sources: dict[str, tuple[str, str]]  # ticker -> (출처 "meta"|"snapshot", 날짜 YYYY-MM-DD)
    primary: Optional[str]               # 이번 재계산이 고른 주 출처


def _meta_date(m: Optional[KrxStockMeta]) -> Optional[str]:
    if m is None:
        return None
    f = m.fetched_at
    if isinstance(f, datetime):
        return f.date().isoformat()
    if isinstance(f, date):
        return f.isoformat()
    return None


async def latest_snapshots(session: AsyncSession, codes: list[str]) -> dict[str, KrxMarketSnapshot]:
    """종목마다 가장 최근(snapshot_date) 행."""
    if not codes:
        return {}
    sub = (
        select(KrxMarketSnapshot.ticker.label("t"), func.max(KrxMarketSnapshot.snapshot_date).label("d"))
        .where(KrxMarketSnapshot.ticker.in_(codes))
        .group_by(KrxMarketSnapshot.ticker)
        .subquery()
    )
    rows = (await session.execute(
        select(KrxMarketSnapshot).join(
            sub, (KrxMarketSnapshot.ticker == sub.c.t) & (KrxMarketSnapshot.snapshot_date == sub.c.d)
        )
    )).scalars().all()
    return {r.ticker: r for r in rows}


async def load_mcap_choice(session: AsyncSession, codes: Iterable[str]) -> McapChoice:
    """재계산용 시총. 날짜가 더 새로운 출처를 모든 종목에 쓰고, 그 출처에 없는 종목만 다른 출처로 채운다.

    출처 날짜 = 그 출처에서 유효한 시총을 가진 종목들 중 가장 새로운 날짜. 같으면 메타(방금 갱신한 쪽)를 쓴다.
    """
    wanted = sorted(set(codes))
    metas = {
        m.ticker: m
        for m in (await session.execute(
            select(KrxStockMeta).where(KrxStockMeta.ticker.in_(wanted))
        )).scalars()
    }
    snaps = await latest_snapshots(session, wanted)

    meta_vals = {c: (_valid(m.market_cap_krw), _meta_date(m)) for c, m in metas.items()}
    meta_vals = {c: v for c, v in meta_vals.items() if v[0] is not None and v[1]}
    snap_vals = {c: (_valid(s.market_cap), s.snapshot_date) for c, s in snaps.items()}
    snap_vals = {c: v for c, v in snap_vals.items() if v[0] is not None and v[1]}
    meta_newest = max((d for _, d in meta_vals.values()), default=None)
    snap_newest = max((d for _, d in snap_vals.values()), default=None)

    if meta_newest is None and snap_newest is None:
        return McapChoice({}, {}, None)
    if snap_newest is not None and (meta_newest is None or snap_newest > meta_newest):
        primary, first, second = "snapshot", snap_vals, meta_vals
    else:
        primary, first, second = "meta", meta_vals, snap_vals
    second_name = "meta" if primary == "snapshot" else "snapshot"

    values: dict[str, float] = {}
    sources: dict[str, tuple[str, str]] = {}
    for c in wanted:
        if c in first:
            values[c], d = first[c]
            sources[c] = (primary, d)
            # 주 출처가 메타인데 이 종목만 갱신에서 빠져 날짜가 옛것이고 스냅샷이 더 새로우면 스냅샷으로 채운다 (1122-04)
            if primary == "meta" and c in second and second[c][1] > d:
                old_d = d
                values[c], d = second[c]
                sources[c] = (second_name, d)
                logger.warning(
                    f"[mcap_source] {c} 메타 {old_d} 가 스냅샷 {d} 보다 오래돼 snapshot {d} 로 채움"
                )
        elif c in second:
            values[c], d = second[c]
            sources[c] = (second_name, d)
            logger.warning(f"[mcap_source] {c} 주 출처({primary})에 없어 {second_name} {d} 로 채움")
        else:
            logger.warning(f"[mcap_source] {c} 시총 없음 (점수 0)")
    per_ticker = {c: f"{s[0]}@{s[1]}" for c, s in sources.items()}
    logger.info(
        f"[mcap_source] 주 출처={primary} (meta 최신 {meta_newest} · snapshot 최신 {snap_newest}) 종목별={per_ticker}"
    )
    return McapChoice(values, sources, primary)


def pick_last_close(
    meta: Optional[KrxStockMeta], snap: Optional[KrxMarketSnapshot]
) -> tuple[Optional[float], Optional[str]]:
    """top10 대체 가격 → (가격, 스냅샷 날짜 | None). 날짜가 더 새로운 쪽 · 같으면 메타.

    메타를 쓰면 날짜는 None (예전 동작 그대로). 스냅샷을 쓰면 snapshot_date 를 돌려줘 price_at 에 넣는다.
    """
    m_close = _valid(meta.last_close) if meta is not None else None
    s_close = _valid(snap.close_price) if snap is not None else None
    if m_close is None and s_close is None:
        return None, None
    if s_close is None:
        return m_close, None
    if m_close is None:
        return s_close, snap.snapshot_date
    m_date = _meta_date(meta)
    if snap.snapshot_date and (m_date is None or snap.snapshot_date > m_date):
        return s_close, snap.snapshot_date
    return m_close, None
