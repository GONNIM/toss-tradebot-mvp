"""토스 순위 수집 · 새 진입 신호 · 1030-04 (네이버 종토방 대체).

재료 (토스 공식 API · 명세 v1.2.28 · 로컬·테스트에서는 호출하지 않는다):
  · GET /api/v1/rankings/investor-trading  개인 순매수 상위 100 (정규장 뒤 제공 · 20시경까지 값 변동)
  · GET /api/v1/rankings  TOSS_SECURITIES_TRADING_AMOUNT/VOLUME · MARKET_TRADING_AMOUNT/VOLUME  (1d)
  TOP_GAINERS 는 쓰지 않는다 (이미 오른 종목을 쫓는 신호가 된다 · 결정).

흐름
  · 20:30 KST  collect_rank_daily  : 5종류를 새 표 watchlist_rank_daily 에 하루 1회 저장 → 새 진입 신호 생성
  · 09:05~15:05 KST 매시 collect_rank_realtime : 20:30 에 집계가 없을 때의 대비. 토스증권·시장 4종류의
    realtime 순위를 그날 최고 순위로 누적 (kind 접미사 _rt · 개인 순매수는 장중 제공 안 함)
  · 과거 날짜는 토스가 주지 않아 직접 쌓은 것과만 비교한다 → 저장 둘째 날부터 신호가 나는 게 정상

새 진입 = 오늘 100위 안 & 전 거래일 저장분에 없음. 순위 상승(≥ _RISE_MIN_PLACES 계단)도 신호.
추격 제외 = 당일 등락률이 params.watchlist_chase_max_change_pct(기본 10%)를 넘으면 신호 안 줌.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select

from backend.services.db import get_session
from backend.services.models import WatchlistRankDaily

from . import runtime_paths
from .store import next_trade_date, upsert_signal

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

# kind → (토스 type) · 1d 순위 (개인 순매수는 investor-trading 이라 따로)
KINDS_1D: dict[str, str] = {
    "toss_amount": "TOSS_SECURITIES_TRADING_AMOUNT",
    "toss_volume": "TOSS_SECURITIES_TRADING_VOLUME",
    "market_amount": "MARKET_TRADING_AMOUNT",
    "market_volume": "MARKET_TRADING_VOLUME",
}
KIND_INDIVIDUAL = "individual_netbuy"
ALL_KINDS = (KIND_INDIVIDUAL, *KINDS_1D)
RT_SUFFIX = "_rt"

# kind → watchlist_signal.source (개인 관심 칸 3 · 전일 칸 2)
KIND_SOURCE: dict[str, str] = {
    "individual_netbuy": "rank_individual_netbuy",
    "toss_amount": "rank_toss_amount",
    "toss_volume": "rank_toss_volume",
    "market_amount": "rank_market_amount",
    "market_volume": "rank_market_volume",
}

_TOP_N = 100
STATUS_FILE = "rank_status.json"

# ─── 신호 세기 (0~1) ─────────────────────────────────
# 새 진입은 순위가 낮아도(100위) 그 자체로 의미가 있다 → 바닥 0.5 + 순위 위치(1위 → 1.0)를 0.5 만큼 더한다.
_NEW_ENTRY_BASE = 0.5
_NEW_ENTRY_POSITION_WEIGHT = 0.5
# 이미 100위 안에 있던 종목은 20계단 이상 오를 때만 신호 · 60계단이면 상승 몫이 만점.
# 새 진입(최대 1.0)보다 약해야 하므로 상한 0.8 (위치 0.4 + 상승 0.4).
_RISE_MIN_PLACES = 20
_RISE_FULL_PLACES = 60
_RISE_POSITION_WEIGHT = 0.4
_RISE_WEIGHT = 0.4
# 개인 순매수 종목 중 순위 응답에 등락률이 없는 새 진입 종목만 시세를 따로 조회 · 한 번에 최대 이만큼
_CHANGE_LOOKUP_MAX = 80


# ═══════════════════════════════════════════════════════════════
# 순수 함수 (테스트 대상)
# ═══════════════════════════════════════════════════════════════
def rank_intensity(rank: int, prev_rank: Optional[int]) -> Optional[float]:
    """오늘 순위·전 거래일 순위 → 신호 세기 (0~1) · 신호 대상이 아니면 None."""
    position = (_TOP_N + 1 - rank) / _TOP_N
    position = max(0.0, min(1.0, position))
    if prev_rank is None:
        return round(_NEW_ENTRY_BASE + _NEW_ENTRY_POSITION_WEIGHT * position, 4)
    rise = prev_rank - rank
    if rise < _RISE_MIN_PLACES:
        return None
    rise_part = min(1.0, rise / _RISE_FULL_PLACES)
    return round(_RISE_POSITION_WEIGHT * position + _RISE_WEIGHT * rise_part, 4)


def is_chase(change_rate: Optional[float], max_pct: float) -> bool:
    """당일 등락률(소수 비율)이 max_pct(%) 를 넘으면 추격 · 등락률을 모르면 False."""
    if change_rate is None:
        return False
    return change_rate * 100.0 > max_pct


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_ranked_at(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=_KST)


def _kst_date(dt: datetime) -> str:
    return dt.astimezone(_KST).date().isoformat()


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt else None


def parse_ranking_result(result: Any) -> tuple[Optional[datetime], list[dict[str, Any]]]:
    """GET /rankings 응답 result → (rankedAt, [{ticker, rank, amount, change_rate}])."""
    if not isinstance(result, dict):
        return None, []
    items: list[dict[str, Any]] = []
    for it in result.get("rankings") or []:
        ticker, rank = it.get("symbol"), it.get("rank")
        if not ticker or not rank:
            continue
        price = it.get("price") or {}
        items.append({
            "ticker": str(ticker), "rank": int(rank),
            "amount": _to_float(it.get("tradingAmount")),
            "change_rate": _to_float(price.get("changeRate")),
        })
    return _parse_ranked_at(result.get("rankedAt")), items


def parse_individual_result(result: Any) -> tuple[Optional[datetime], list[dict[str, Any]]]:
    """GET /rankings/investor-trading 응답 result → 개인 순매수 (rankedAt, items) · 시세 없음(change_rate None)."""
    ind = (result or {}).get("individual") if isinstance(result, dict) else None
    if not isinstance(ind, dict):
        return None, []
    items = [
        {"ticker": str(it["symbol"]), "rank": int(it["rank"]),
         "amount": _to_float(it.get("netBuyAmount")), "change_rate": None}
        for it in (ind.get("netBuyRankings") or [])
        if it.get("symbol") and it.get("rank")
    ]
    return _parse_ranked_at(ind.get("rankedAt")), items


# ═══════════════════════════════════════════════════════════════
# 토스 호출 (동기 · to_thread 로 실행)
# ═══════════════════════════════════════════════════════════════
def _client(client: Any = None) -> Any:
    if client is not None:
        return client
    from backend.execution.brokers.toss_client import get_toss_client

    return get_toss_client()


def _fetch_1d(client: Any, kind: str) -> tuple[Optional[datetime], list[dict[str, Any]]]:
    env = client.rankings(type=KINDS_1D[kind], market="KR", duration="1d", count=_TOP_N)
    return parse_ranking_result(getattr(env, "result", env))


def _fetch_realtime(client: Any, kind: str) -> tuple[Optional[datetime], list[dict[str, Any]]]:
    env = client.rankings(type=KINDS_1D[kind], market="KR", duration="realtime", count=_TOP_N)
    return parse_ranking_result(getattr(env, "result", env))


def _fetch_individual(client: Any) -> tuple[Optional[datetime], list[dict[str, Any]]]:
    env = client.investor_trading_rankings(count=_TOP_N)
    return parse_individual_result(getattr(env, "result", env))


def _fetch_change_rates(client: Any, tickers: list[str], today: str) -> dict[str, float]:
    """순위 응답에 등락률이 없는 종목의 당일 등락률 (소수 비율).

    GET /api/v1/prices 는 현재가(lastPrice)만 주고 기준가가 없어 (명세 PriceResponse),
    전일 종가는 일봉(candles)에서 가져온다 · today 날짜 봉은 건너뛴다.
    """
    out: dict[str, float] = {}
    tickers = tickers[:_CHANGE_LOOKUP_MAX]
    if not tickers:
        return out
    try:
        prices = client.prices(tickers) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[rank] prices 조회 실패 · %s", exc)
        return out
    last = {str(p.get("symbol")): _to_float(p.get("lastPrice")) for p in prices if isinstance(p, dict)}
    for t in tickers:
        lp = last.get(t)
        if not lp:
            continue
        try:
            candles = client.candles(t, count=3) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("[rank] candles(%s) 실패 · %s", t, exc)
            continue
        base = None
        for c in candles:   # 최신순
            if not isinstance(c, dict):
                continue
            if str(c.get("timestamp") or "")[:10] == today:
                continue
            base = _to_float(c.get("closePrice"))
            break
        if base:
            out[t] = lp / base - 1.0
    return out


# ═══════════════════════════════════════════════════════════════
# 저장
# ═══════════════════════════════════════════════════════════════
async def _replace_rows(
    trade_date: str, kind: str, items: list[dict[str, Any]], ranked_at: Optional[datetime],
) -> int:
    """(trade_date, kind) 의 행을 통째로 교체 · 20시 전후 재조회가 값을 바꿔도 마지막 것이 남는다."""
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    async with get_session() as session:
        await session.execute(delete(WatchlistRankDaily).where(
            WatchlistRankDaily.trade_date == trade_date, WatchlistRankDaily.kind == kind,
        ))
        for it in items:
            session.add(WatchlistRankDaily(
                trade_date=trade_date, kind=kind, ticker=it["ticker"], rank=it["rank"],
                amount=it.get("amount"), change_rate=it.get("change_rate"),
                ranked_at=_naive_utc(ranked_at), captured_at=now,
            ))
    return len(items)


async def _accumulate_best(
    trade_date: str, kind: str, items: list[dict[str, Any]], ranked_at: Optional[datetime],
) -> int:
    """장중 누적 · 종목별 그날 최고(숫자가 작은) 순위만 남긴다 · 바뀐 행 수를 돌려준다."""
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    changed = 0
    async with get_session() as session:
        rows = (await session.execute(select(WatchlistRankDaily).where(
            WatchlistRankDaily.trade_date == trade_date, WatchlistRankDaily.kind == kind,
        ))).scalars().all()
        by_ticker = {r.ticker: r for r in rows}
        for it in items:
            row = by_ticker.get(it["ticker"])
            if row is None:
                session.add(WatchlistRankDaily(
                    trade_date=trade_date, kind=kind, ticker=it["ticker"], rank=it["rank"],
                    amount=it.get("amount"), change_rate=it.get("change_rate"),
                    ranked_at=_naive_utc(ranked_at), captured_at=now,
                ))
                changed += 1
            elif it["rank"] < row.rank:
                row.rank = it["rank"]
                row.amount = it.get("amount")
                row.change_rate = it.get("change_rate")
                row.ranked_at = _naive_utc(ranked_at)
                row.captured_at = now
                changed += 1
    return changed


def read_status() -> dict[str, Any]:
    st = runtime_paths.read_json(STATUS_FILE)
    return st if isinstance(st, dict) else {}


def _write_status(section: str, payload: dict[str, Any]) -> None:
    st = read_status()
    st[section] = payload
    runtime_paths.write_json(STATUS_FILE, st)


# ═══════════════════════════════════════════════════════════════
# 20:30 KST · 하루 1회 저장 + 신호
# ═══════════════════════════════════════════════════════════════
async def collect_rank_daily(client: Any = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """5종류 순위를 저장하고 새 진입 신호를 만든다.

    rankedAt 이 없거나 그 날짜가 오늘(KST)이 아니면 저장하지 않고 상태에 「집계 없음」을 적는다
    (휴장일·집계 전·토스가 직전 영업일 값을 주는 경우). 그날은 장중 누적(_rt)이 대신한다.
    """
    now = now or datetime.now(tz=timezone.utc)
    today = _kst_date(now)
    toss = _client(client)
    kinds_state: dict[str, dict[str, Any]] = {}
    changes: dict[str, float] = {}

    fetchers: dict[str, Any] = {KIND_INDIVIDUAL: lambda: _fetch_individual(toss)}
    for k in KINDS_1D:
        fetchers[k] = (lambda kk=k: _fetch_1d(toss, kk))

    for kind, fetch in fetchers.items():
        try:
            ranked_at, items = await asyncio.to_thread(fetch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[rank] %s 조회 실패 · %s", kind, exc)
            kinds_state[kind] = {"state": "error", "count": 0, "ranked_at": None, "error": str(exc)[:120]}
            continue
        if ranked_at is None or not items:
            kinds_state[kind] = {"state": "no_data", "count": 0, "ranked_at": None}
            continue
        if _kst_date(ranked_at) != today:
            kinds_state[kind] = {"state": "no_data", "count": 0, "ranked_at": ranked_at.isoformat()}
            continue
        for it in items:
            if it["change_rate"] is not None:
                changes.setdefault(it["ticker"], it["change_rate"])
        n = await _replace_rows(today, kind, items, ranked_at)
        kinds_state[kind] = {"state": "saved", "count": n, "ranked_at": ranked_at.isoformat()}

    # 개인 순매수 행에 다른 순위에서 알게 된 등락률을 채운다 (investor-trading 은 시세가 없다)
    if kinds_state.get(KIND_INDIVIDUAL, {}).get("state") == "saved" and changes:
        async with get_session() as session:
            rows = (await session.execute(select(WatchlistRankDaily).where(
                WatchlistRankDaily.trade_date == today, WatchlistRankDaily.kind == KIND_INDIVIDUAL,
            ))).scalars().all()
            for r in rows:
                if r.change_rate is None and r.ticker in changes:
                    r.change_rate = changes[r.ticker]

    signal_stats = await generate_rank_signals(today=today, client=toss, now=now)
    _write_status("daily", {"run_at": now.isoformat(), "date": today, "kinds": kinds_state})
    stats = {"date": today, "kinds": kinds_state, "signals": signal_stats}
    logger.info("[rank] daily %s", stats)
    return stats


# ═══════════════════════════════════════════════════════════════
# 장중 매시 · 20:30 집계가 없을 때의 대비
# ═══════════════════════════════════════════════════════════════
async def collect_rank_realtime(client: Any = None, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(tz=timezone.utc)
    today = _kst_date(now)
    toss = _client(client)
    changed_total = 0
    per_kind: dict[str, int] = {}
    for kind in KINDS_1D:
        try:
            ranked_at, items = await asyncio.to_thread(_fetch_realtime, toss, kind)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[rank] realtime %s 실패 · %s", kind, exc)
            per_kind[kind] = -1
            continue
        # 휴장일에 토스가 직전 영업일 값을 주면 오늘 날짜로 섞지 않는다
        if not items or (ranked_at is not None and _kst_date(ranked_at) != today):
            per_kind[kind] = 0
            continue
        n = await _accumulate_best(today, kind + RT_SUFFIX, items, ranked_at)
        per_kind[kind] = n
        changed_total += n
    _write_status("realtime", {"run_at": now.isoformat(), "date": today, "changed": changed_total})
    return {"date": today, "changed": changed_total, "per_kind": per_kind}


# ═══════════════════════════════════════════════════════════════
# 새 진입 신호
# ═══════════════════════════════════════════════════════════════
async def _effective_rows(trade_date: str, kind: str) -> dict[str, WatchlistRankDaily]:
    """그날의 순위 · 20:30 저장분이 있으면 그것, 없으면 장중 누적(_rt)."""
    kinds = [kind, kind + RT_SUFFIX]
    async with get_session() as session:
        rows = (await session.execute(select(WatchlistRankDaily).where(
            WatchlistRankDaily.trade_date == trade_date, WatchlistRankDaily.kind.in_(kinds),
        ))).scalars().all()
    daily = {r.ticker: r for r in rows if r.kind == kind}
    if daily:
        return daily
    return {r.ticker: r for r in rows if r.kind == kind + RT_SUFFIX}


async def _previous_date(today: str, kind: str) -> Optional[str]:
    async with get_session() as session:
        row = (await session.execute(
            select(WatchlistRankDaily.trade_date)
            .where(WatchlistRankDaily.trade_date < today,
                   WatchlistRankDaily.kind.in_([kind, kind + RT_SUFFIX]))
            .order_by(WatchlistRankDaily.trade_date.desc()).limit(1)
        )).scalar_one_or_none()
    return row


async def generate_rank_signals(today: str, client: Any = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """오늘 순위를 전 거래일 저장분과 비교해 새 진입·상승 신호를 저장한다."""
    from backend.discovery.live_tape.params import get_sniper_params

    now = now or datetime.now(tz=timezone.utc)
    max_pct = float(get_sniper_params().watchlist_chase_max_change_pct)
    sig_date = next_trade_date(now)
    stats: dict[str, Any] = {}

    # 등락률 사전 (오늘 어느 순위에든 있던 값)
    change_map: dict[str, float] = {}
    for kind in ALL_KINDS:
        for t, r in (await _effective_rows(today, kind)).items():
            if r.change_rate is not None:
                change_map.setdefault(t, r.change_rate)

    for kind in ALL_KINDS:
        cur = await _effective_rows(today, kind)
        if not cur:
            stats[kind] = {"state": "오늘 순위 없음"}
            continue
        prev_date = await _previous_date(today, kind)
        if prev_date is None:
            stats[kind] = {"state": "전 거래일 저장분 없음 (둘째 날부터 신호)"}
            continue
        prev = await _effective_rows(prev_date, kind)

        candidates: list[tuple[WatchlistRankDaily, Optional[int], float]] = []
        for ticker, row in cur.items():
            prev_row = prev.get(ticker)
            prev_rank = prev_row.rank if prev_row is not None else None
            intensity = rank_intensity(row.rank, prev_rank)
            if intensity is None:
                continue
            candidates.append((row, prev_rank, intensity))

        # 등락률을 모르는 새 진입 종목만 시세 조회 (개인 순매수)
        need = [r.ticker for r, _, _ in candidates
                if r.change_rate is None and r.ticker not in change_map]
        if need and client is not None:
            fetched = await asyncio.to_thread(_fetch_change_rates, client, need, today)
            change_map.update(fetched)

        saved = excluded = 0
        for row, prev_rank, intensity in candidates:
            rate = row.change_rate if row.change_rate is not None else change_map.get(row.ticker)
            if is_chase(rate, max_pct):
                excluded += 1
                continue
            key = f"{kind}:{today}"
            row_id = await upsert_signal(
                ticker=row.ticker,
                source=KIND_SOURCE[kind],
                signal_type="rank_new" if prev_rank is None else "rank_rise",
                intensity=intensity,
                payload={
                    "key": key, "kind": kind, "rank": row.rank, "prev_rank": prev_rank,
                    "is_new": prev_rank is None, "change_rate": rate, "amount": row.amount,
                    "rank_date": today, "prev_date": prev_date,
                },
                trade_date=sig_date,
                detected_at=now,
                dedup_url=key,
            )
            if row_id is not None:
                saved += 1
        stats[kind] = {"candidates": len(candidates), "saved": saved, "excluded_chase": excluded}
    return stats
