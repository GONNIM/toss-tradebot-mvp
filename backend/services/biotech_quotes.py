"""1111-01 · 바이오 후보 종목 가격·전문가 의견 칸 (표시 전용).

사용자 결정 (2026-11-11): ㉠① 순위표·소문 목록 종목 칸 접힘 · ㉡② 애널리스트 목표가 원자료 + AI 요약 · ㉢① 기본 칸 + 보유 현금·공매도 비율
· 「1111-01 계획 승인 ㉠①」 = AI 요약 대상 종목만 SEC 8-K 보도자료를 하루 30종목까지 새로 받는다.
계획: docs/plans/biotech-quote/2026-11-11-plan.md · Fable 2026-11-11-1111-01-01 (조건부 GO · 막음 3 반영).

지키는 것
- 표시만: 여기서 만든 값은 점수 · 순위 · 후보 선정 · 경보 · 알림에 쓰지 않는다 (PENDING 영구 규칙 17행).
- 자체 계산 없음: 목표가까지 몇 % 같은 값을 만들지 않는다. 야후 원자료를 그대로 저장한다.
- 1102-08 교훈: 바깥 받기(yfinance · SEC · LLM)는 세션을 열기 전에 끝낸다. 받기에 성공한 종목만 짧은 세션으로 쓰고 바로 커밋한다.
  세션이 열려 있는 동안 네트워크 호출 0 (시험이 _session 감시로 확인).
- 표 두 개는 swing_long_close 와 분리 (보유 종목 잡과 덮어쓰기 충돌 없음 · Fable 1차 막음 1).
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import math
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from backend.services.models import BiotechLongClose, BiotechQuoteDaily

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")

MAX_TICKERS = 150            # 한 번에 받는 종목 상한 (레이더 점수 높은 순 → 소문 목록 순)
KEEP_DAYS = 30               # 후보에서 빠진 뒤 보존 · 하루 기록 보존
FIRST_PERIOD = "6y"          # 처음 받을 때 (5년 + 40주 여유)
RECENT_PERIOD = "1mo"        # 그다음부터 최근 약 20거래일만 받아 덮어씀
LONG_KEEP_DAYS = 6 * 366     # 일봉 보존 길이
PAUSE_SEC = 1.0              # 종목 사이 쉼 (야후 · SEC)
FETCH_TIMEOUT = 60.0         # 종목당 받기 제한
SUMMARY_DAILY_CAP = 30       # AI 요약 하루 상한 (㉡② 비용 상한)
SEC_TICKERS_PER_DAY = 30     # ㉠① 회사 공시를 볼 종목 하루 상한
SEC_QUOTE_DAILY_REQ = 90     # 위 30종목 × (제출 목록 · 색인 · 보도자료) 최대 요청 수
SEC_LOOKBACK_DAYS = 120      # 최근 8-K 를 찾는 기간
CANDIDATE_CACHE_SEC = 300.0
LIVE_CACHE_SEC = 60.0        # 현재가 캐시 (Fable 1차 막음 4)

OPINION_HEAD = "전문가 의견 모음 · 추정 · 보장 아님"
SUMMARY_HEAD = "자동 요약 · 진위 미검증 · 추정 · 보장 아님"
GRADE_NOTE = "증권사 표기 원문 (번역 · 해석 안 함)"
USE_NOTE = "표시 전용 · 점수 · 순위 · 경보에 쓰지 않음"
SOURCE_YAHOO = "야후 (yfinance)"
SOURCE_NAVER = "네이버 실시간"
SOURCE_REGISTRY = "ClinicalTrials.gov 등록부 주간 사본"
SOURCE_SEC = "SEC 8-K 보도자료"

# 거래소 코드 → 네이버 미국 종목 코드 꼬리 (나스닥 .O · 뉴욕 없음 · 아멕스 .K)
_NAVER_SUFFIX = {"NMS": ".O", "NGM": ".O", "NCM": ".O", "NAS": ".O", "NASDAQ": ".O",
                 "NYQ": "", "NYS": "", "NYSE": "", "ASE": ".K", "AMX": ".K", "PCX": ".K"}
_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")

# ── AI 요약 문구 필터 (Fable 2차 질문 1) ─────────────────────────────
# 기존 biotech_llm.FORBIDDEN_RE 에서 「목표가 · 목표 주가 · price target」 만 뺀다. 나머지(전망 · buy · sell · upside 등)는 그대로.
# 계산으로 읽히는 말(여력 · 괴리)과 신호 낱말(11/08 · 11/10 규칙)은 더 막는다. 경보 요약(biotech_h77)은 기존 필터 그대로.
QUOTE_FORBIDDEN_RE = re.compile(
    r"매수하|매도하|매수를 권|매도를 권|사세요|파세요|사야|팔아야|추천|권유|권장|주가 전망|전망|"
    r"오를 것|내릴 것|상승할|하락할|급등할|급락할|오를 가능성|수익을 기대|기대 수익|여력|괴리|"
    r"골든|데드|크로스|교차|정배열|역배열|"
    r"\bbuy\b|\bsell\b|outperform|underperform|upside|downside",
    re.IGNORECASE,
)
_TARGET_RE = re.compile(r"목표가|목표 주가|price target", re.IGNORECASE)
_CITE_RE = re.compile(r"\[(\d+)\]")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
MAX_LINES = 3

SUMMARY_SYSTEM = (
    "너는 수집된 사실을 한국어로 짧게 정리하는 도구다. 규칙:\n"
    "1) 아래 번호 붙은 자료에 적힌 내용만 쓴다. 자료에 없는 사실 · 배경지식 · 추측을 쓰지 않는다.\n"
    "2) 최대 3줄. 한 줄에 한 문장. 문장 끝마다 근거 자료 번호를 [1] 처럼 붙인다.\n"
    "3) 매수 · 매도 권유, 주가 전망, 추천 표현을 쓰지 않는다. 직접 계산(차이 % · 여력 등)을 하지 않는다.\n"
    "4) 애널리스트 목표가는 자료 [3] · [4] 에 적힌 숫자만 그대로 옮기고 그 번호를 붙인다. 증권사 등급 이름은 쓰지 말고 의견 분포 숫자로 쓴다.\n"
    "5) 자료끼리 숫자가 다르면(예: 의견 수와 분포 합) 둘 다 적는다.\n"
    "6) 등록부 날짜와 상태는 등록부에 적힌 사실로만 쓴다. 자료에 없으면 결과가 나왔다거나 기다린다고 단정하지 않는다.\n"
    "7) 회사 공시에 일정이 적혀 있으면 그 문장을 출처 번호와 함께 옮긴다.\n"
    "8) 줄 앞에 기호나 번호 목록을 붙이지 않는다."
)

Fetcher = Callable[[str, str], Awaitable[dict]]            # (ticker, period) → 받은 자료
SecFetcher = Callable[[str, Optional[dict], "SecBudget"], Awaitable[Optional[dict]]]
Summarizer = Callable[[str, str, str], Awaitable[dict]]     # (ticker, system, user) → {text, provider, model}


def _session():
    """시험이 바꿔 끼울 수 있게 한 곳에서만 세션을 연다."""
    from backend.services.db import get_session

    return get_session()


def _kst_today(now: Optional[datetime] = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(KST).date()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(f)


def normalize(ticker: str) -> Optional[str]:
    t = (ticker or "").strip().upper()
    return t if _TICKER_RE.match(t) else None


# ─────────────────────────────────────────────────────────────────
# 후보 종목 (레이더 CSV + 소문 목록) — 파일만 읽음 · 외부 호출 0
# ─────────────────────────────────────────────────────────────────

_CAND_CACHE: dict[str, Any] = {"at": 0.0, "list": []}


async def load_candidates(limit: int = MAX_TICKERS) -> list[str]:
    """레이더 점수 높은 순 → 그다음 소문 목록 종목 (목록 순) · 중복 제거 · 최대 limit (Fable 2차 권고 7)."""
    from backend.api.routes import biotech as R

    out: list[str] = []
    seen: set[str] = set()

    def _add(t: str) -> None:
        n = normalize(t)
        if n and n not in seen:
            seen.add(n)
            out.append(n)

    path = R._latest_radar_csv()
    if path and path.exists():
        with path.open() as f:
            rows = list(csv.DictReader(f))

        def _score(r: dict) -> float:
            return _num(r.get("score")) or 0.0

        for r in sorted(rows, key=_score, reverse=True):
            _add(r.get("ticker", ""))
    try:
        rumor = await R.get_rumor_json(date=None, _admin="biotech_quotes")
        for r in rumor.rows:
            _add(r.ticker)
    except Exception as exc:  # noqa: BLE001 — 소문 목록이 없어도 레이더 종목은 받는다
        logger.warning("[biotech_quotes] 소문 목록 읽기 실패 · %s", type(exc).__name__)
    total = len(out)
    if total > limit:
        logger.info("[biotech_quotes] 후보 %d개 · 상한 %d개까지만", total, limit)
    return out[:limit]


async def candidate_set() -> set[str]:
    """조회 API 용 · 5분 캐시 (아무 기호나 바깥 호출하지 않게 후보만 허용 · Fable 1차 막음 4)."""
    now = time.monotonic()
    if now - _CAND_CACHE["at"] > CANDIDATE_CACHE_SEC or not _CAND_CACHE["list"]:
        _CAND_CACHE["list"] = await load_candidates(limit=10_000)
        _CAND_CACHE["at"] = now
    return set(_CAND_CACHE["list"])


# ─────────────────────────────────────────────────────────────────
# 야후 받기 (세션 밖)
# ─────────────────────────────────────────────────────────────────

def _changes(df) -> list[dict]:
    out: list[dict] = []
    if df is None or getattr(df, "empty", True):
        return out
    try:
        df = df.sort_index(ascending=False)
    except Exception:  # noqa: BLE001
        pass
    for idx, r in df.head(5).iterrows():
        out.append({
            "date": str(idx)[:10],
            "firm": str(r.get("Firm") or ""),
            "to_grade": str(r.get("ToGrade") or ""),
            "from_grade": str(r.get("FromGrade") or ""),
            "action": str(r.get("Action") or ""),
            "pt_now": _num(r.get("currentPriceTarget")) or None,
            "pt_prior": _num(r.get("priorPriceTarget")) or None,
        })
    return out


def _dist(df) -> dict:
    if df is None or getattr(df, "empty", True):
        return {}
    try:
        row = df[df["period"] == "0m"].iloc[0]
    except Exception:  # noqa: BLE001
        return {}
    return {k: _int(row.get(k)) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}


async def default_fetch(ticker: str, period: str) -> dict:
    """yfinance 한 종목 (info · 의견 분포 · 등급 변경 · 일봉 종가). 동기 호출은 스레드에서."""

    def _call() -> dict:
        import yfinance as yf

        t = yf.Ticker(ticker.replace(".", "-"))
        info = t.info or {}
        try:
            dist = _dist(t.recommendations_summary)
        except Exception:  # noqa: BLE001
            dist = {}
        try:
            changes = _changes(t.upgrades_downgrades)
        except Exception:  # noqa: BLE001
            changes = []
        hist = t.history(period=period, auto_adjust=False)
        closes = [(idx.date(), float(v)) for idx, v in hist["Close"].dropna().items() if float(v) > 0] if not hist.empty else []
        return {"info": info, "dist": dist, "changes": changes, "closes": closes}

    return await asyncio.to_thread(_call)


def quote_fields(raw: dict) -> dict:
    """받은 원자료 → 저장할 칸 (계산 없음 · 없으면 None)."""
    info = raw.get("info") or {}
    sdate = info.get("dateShortInterest")
    short_asof = None
    if _num(sdate):
        short_asof = datetime.fromtimestamp(float(sdate), tz=timezone.utc).date()
    analyst = {
        "n_opinions": _int(info.get("numberOfAnalystOpinions")),
        "rec_key": info.get("recommendationKey") or None,
        "dist": raw.get("dist") or {},
        "targets": {k: _num(info.get(f"target{k.title()}Price")) for k in ("mean", "median", "high", "low")},
        "changes": raw.get("changes") or [],
    }
    return {
        "exchange": (info.get("exchange") or None),
        "price_close": _num(info.get("currentPrice") or info.get("regularMarketPrice")),
        "volume": _num(info.get("regularMarketVolume") or info.get("volume")),
        "avg_volume": _num(info.get("averageVolume")),
        "market_cap": _num(info.get("marketCap")),
        "low_52w": _num(info.get("fiftyTwoWeekLow")),
        "high_52w": _num(info.get("fiftyTwoWeekHigh")),
        "total_cash": _num(info.get("totalCash")),
        "short_pct_float": _num(info.get("shortPercentOfFloat")),
        "short_asof": short_asof,
        "analyst_json": json.dumps(analyst, ensure_ascii=False),
    }


# ─────────────────────────────────────────────────────────────────
# 하루 1회 잡
# ─────────────────────────────────────────────────────────────────

async def _read_state(tickers: list[str]) -> dict[str, dict]:
    """받기 전에 짧게 읽기만: 일봉 행 수 · 최근 하루 기록의 요약 칸 (세션은 바로 닫힘)."""
    state: dict[str, dict] = {t: {"n_long": 0, "prev": None} for t in tickers}
    async with _session() as s:
        for t, n in (await s.execute(select(BiotechLongClose.ticker, func.count()).group_by(BiotechLongClose.ticker))).all():
            if t in state:
                state[t]["n_long"] = int(n)
        sub = select(BiotechQuoteDaily.ticker, func.max(BiotechQuoteDaily.asof_date).label("d")).group_by(BiotechQuoteDaily.ticker).subquery()
        rows = (await s.execute(select(BiotechQuoteDaily).join(
            sub, (BiotechQuoteDaily.ticker == sub.c.ticker) & (BiotechQuoteDaily.asof_date == sub.c.d)))).scalars().all()
        for r in rows:
            if r.ticker in state:
                state[r.ticker]["prev"] = {"sec8k_json": r.sec8k_json, "summary_json": r.summary_json,
                                           "summary_input_hash": r.summary_input_hash,
                                           "summary_checked_at": r.summary_checked_at}
    return state


async def _write_ticker(ticker: str, today: date, fields: dict, closes: list[tuple[date, float]],
                        prev: Optional[dict], full: bool) -> int:
    """한 종목만 · 짧은 세션 · 바로 커밋. 네트워크 호출 없음."""
    now = _utcnow()
    rows = sorted({d: c for d, c in closes if c and c > 0}.items())
    async with _session() as s:
        if rows:
            if full:
                await s.execute(delete(BiotechLongClose).where(BiotechLongClose.ticker == ticker))
            else:
                await s.execute(delete(BiotechLongClose).where(BiotechLongClose.ticker == ticker,
                                                               BiotechLongClose.trade_date >= rows[0][0]))
            s.add_all([BiotechLongClose(ticker=ticker, trade_date=d, close=c, fetched_at=now) for d, c in rows])
            await s.execute(delete(BiotechLongClose).where(BiotechLongClose.ticker == ticker,
                                                           BiotechLongClose.trade_date < today - timedelta(days=LONG_KEEP_DAYS)))
        await s.execute(delete(BiotechQuoteDaily).where(BiotechQuoteDaily.ticker == ticker, BiotechQuoteDaily.asof_date == today))
        carry = prev or {}
        s.add(BiotechQuoteDaily(ticker=ticker, asof_date=today, fetched_at=now, **fields,
                                sec8k_json=carry.get("sec8k_json"), summary_json=carry.get("summary_json"),
                                summary_input_hash=carry.get("summary_input_hash"),
                                summary_checked_at=carry.get("summary_checked_at")))
    return len(rows)


async def _prune(candidates: list[str], today: date) -> dict:
    """후보에서 빠진 지 30일 지난 종목의 두 표 행 삭제 · 하루 기록 30일 넘은 행 삭제 (종목마다 짧은 세션)."""
    cut = today - timedelta(days=KEEP_DAYS)
    keep = set(candidates)
    async with _session() as s:
        last = dict((await s.execute(select(BiotechQuoteDaily.ticker, func.max(BiotechQuoteDaily.asof_date))
                                     .group_by(BiotechQuoteDaily.ticker))).all())
        long_tickers = set((await s.execute(select(BiotechLongClose.ticker).distinct())).scalars().all())
    dropped = [t for t in (set(last) | long_tickers) if t not in keep and (last.get(t) is None or last[t] < cut)]
    for t in sorted(dropped):
        async with _session() as s:
            await s.execute(delete(BiotechLongClose).where(BiotechLongClose.ticker == t))
            await s.execute(delete(BiotechQuoteDaily).where(BiotechQuoteDaily.ticker == t))
    async with _session() as s:
        res = await s.execute(delete(BiotechQuoteDaily).where(BiotechQuoteDaily.asof_date < cut))
    return {"dropped": len(dropped), "old_rows": res.rowcount or 0}


async def run_quotes(now: Optional[datetime] = None, fetch: Optional[Fetcher] = None,
                     sec_fetch: Optional[SecFetcher] = None, summarize: Optional[Summarizer] = None,
                     candidates: Optional[list[str]] = None, pause: float = PAUSE_SEC,
                     budget: Optional["SecBudget"] = None) -> dict:
    """화~토 08:45 KST (cron 서비스). 1) 받기 → 종목마다 쓰기 2) AI 요약 (하루 30) 3) 정리."""
    fetch = fetch or default_fetch
    today = _kst_today(now)
    cands = candidates if candidates is not None else await load_candidates()
    state = await _read_state(cands)
    ok, failures, long_rows = 0, 0, 0
    for i, t in enumerate(cands):
        if i and pause:
            await asyncio.sleep(pause)
        full = state[t]["n_long"] == 0
        try:
            raw = await asyncio.wait_for(fetch(t, FIRST_PERIOD if full else RECENT_PERIOD), FETCH_TIMEOUT)
            fields = quote_fields(raw)
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패가 다른 종목을 막지 않음 · 전날 행 그대로
            failures += 1
            logger.warning("[biotech_quotes] 받기 실패 · %s · %s", t, type(exc).__name__)
            continue
        long_rows += await _write_ticker(t, today, fields, raw.get("closes") or [], state[t]["prev"], full)
        ok += 1
    summ = await run_summaries(cands, today, sec_fetch=sec_fetch, summarize=summarize, pause=pause, budget=budget)
    pr = await _prune(cands, today)
    logger.info("[biotech_quotes] 후보 %d · 저장 %d · 실패 %d · 일봉 %d행 · 요약 %s · 정리 %s",
                len(cands), ok, failures, long_rows, summ, pr)
    if cands and ok == 0:
        raise RuntimeError("바이오 종목 시세를 한 종목도 받지 못함")
    return {"candidates": len(cands), "ok": ok, "failures": failures, "long_rows": long_rows, "summary": summ, "prune": pr}


# ─────────────────────────────────────────────────────────────────
# AI 요약 (㉡②) · SEC 8-K (㉠①)
# ─────────────────────────────────────────────────────────────────

class SecBudget:
    """하루 SEC 요청 장부 (biotech 공용 장부 · 분류 quote_8k) · 이 일 상한 90 · 공용 상한 300."""

    def __init__(self, ledger=None, shared_cap: int = 300) -> None:
        self.ledger = ledger
        self.blocked = False
        self._local = 0
        self.shared_cap = shared_cap

    def used(self) -> int:
        """오늘 이 일이 쓴 SEC 요청 수 (장부가 있으면 장부 · 없으면 이번 실행)."""
        return int(self.ledger.counts.get("quote_8k", 0)) if self.ledger is not None else self._local

    def can(self) -> bool:
        if self.blocked or self.used() >= SEC_QUOTE_DAILY_REQ:
            return False
        return self.ledger is None or self.ledger.total() < self.shared_cap

    def add(self) -> None:
        self._local += 1
        if self.ledger is not None:
            self.ledger.add("quote_8k")


async def default_sec_fetch(ticker: str, prev: Optional[dict], budget: SecBudget) -> Optional[dict]:
    """최근 120일 안 보도자료가 붙은 8-K 하나 (항목 9.01 + 8.01/7.01) · 제목 · 첫 문단.

    같은 접수 번호를 이미 저장했으면 제출 목록 1회만 쓰고 저장값을 다시 쓴다. 403·429 는 그날 SEC 를 멈춘다.
    """
    from backend.api.routes import biotech as R

    cik = next((c for c, tk in R._cik_ticker_map().items() if tk == ticker), None)
    if not cik:
        return None

    def _call() -> Optional[dict]:
        from backend.scripts.biotech_h77_alert_brief import exhibit_lead, exhibit_target, exhibit_title
        from backend.scripts.biotech_sec_common import REQ_INTERVAL, build_client

        def _get(client, url: str) -> Optional[str]:
            if not budget.can():
                return None
            time.sleep(REQ_INTERVAL)
            budget.add()
            r = client.get(url, timeout=25.0)
            if r.status_code in (403, 429):
                budget.blocked = True
                raise RuntimeError(f"SEC HTTP {r.status_code}")
            return r.text if r.status_code == 200 else None

        with build_client() as client:
            txt = _get(client, f"https://data.sec.gov/submissions/CIK{cik}.json")
            if not txt:
                return None
            rec = json.loads(txt).get("filings", {}).get("recent", {})
            since = (date.today() - timedelta(days=SEC_LOOKBACK_DAYS)).isoformat()
            for i, form in enumerate(rec.get("form", [])):
                if form != "8-K" or rec["filingDate"][i] < since:
                    continue
                if not exhibit_target(rec.get("items", [""] * (i + 1))[i]):
                    continue
                acc = rec["accessionNumber"][i]
                if prev and prev.get("accession") == acc:
                    return prev
                idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index.htm"
                idx = _get(client, idx_url) or ""
                m = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?EX-99(?:\.1)?(?:(?!</tr>).)*?</tr>", idx, re.S | re.I)
                href = re.search(r'href="([^"]+)"', m.group(0)) if m else None
                if not href:
                    return {"accession": acc, "filing_date": rec["filingDate"][i], "title": "", "lead": "", "url": idx_url}
                doc_url = "https://www.sec.gov" + href.group(1).replace("/ix?doc=", "")
                doc = _get(client, doc_url) or ""
                title = exhibit_title(doc)
                return {"accession": acc, "filing_date": rec["filingDate"][i], "title": title,
                        "lead": exhibit_lead(doc, title), "url": doc_url}
        return None

    return await asyncio.to_thread(_call)


def safe_lead(lead: str) -> str:
    """요약 입력 전 문장마다 필터 · 걸린 문장은 뺌 (biotech_h77.safe_lead_for_llm 과 같은 방식 · 새 필터)."""
    return " ".join(s for s in _SENT_SPLIT_RE.split(lead or "") if s.strip() and not QUOTE_FORBIDDEN_RE.search(s)).strip()


def registry_facts(ticker: str) -> Optional[dict]:
    """대표 시험의 등록부 사실 (주간 AACT 사본) · 파일만 읽음."""
    from backend.api.routes import biotech as R

    note = R._latest_candidate_notes().get(ticker, "")
    nct = (R._note_fields(note) or {}).get("nct_id", "") if note else ""
    if not nct:
        return None
    m = R._snapshot_by_nct().get(nct) or {}
    return {"nct_id": nct, "phase": m.get("phase", ""), "status": m.get("overall_status", ""),
            "pcd": m.get("primary_completion_date", ""), "pcd_type": m.get("primary_completion_date_type", ""),
            "last_update": m.get("last_update_posted_date", "")}


def build_sources(asof: date, reg: Optional[dict], sec: Optional[dict], analyst: dict) -> list[str]:
    """번호 붙일 출처 목록 [1] 등록부 [2] 회사 8-K [3] 목표가·의견 [4] 최근 변경 (없는 칸은 「없음」으로 자리만 둠)."""
    if reg:
        s1 = (f"{SOURCE_REGISTRY}: {reg['nct_id']} · 단계 {reg['phase'] or '없음'} · 상태 {reg['status'] or '없음'} · "
              f"1차 완료 날짜 {reg['pcd'] or '없음'} ({reg['pcd_type'] or '구분 없음'}) · 마지막 갱신 {reg['last_update'] or '없음'}")
    else:
        s1 = f"{SOURCE_REGISTRY}: 대표 시험 없음"
    if sec and (sec.get("title") or sec.get("lead")):
        s2 = f"{SOURCE_SEC} ({sec.get('filing_date', '')}) 제목: {sec.get('title') or '제목 없음'} · 첫 문단: {safe_lead(sec.get('lead', '')) or '없음'}"
    else:
        s2 = f"{SOURCE_SEC}: 최근 {SEC_LOOKBACK_DAYS}일 안 보도자료 없음"
    d = analyst.get("dist") or {}
    tg = analyst.get("targets") or {}
    dsum = sum(v for v in d.values() if isinstance(v, int)) if d else None
    s3 = (f"{SOURCE_YAHOO} 조회일 {asof.isoformat()}: 애널리스트 의견 수 {analyst.get('n_opinions')} · 의견 분포 "
          f"강력 매수 {d.get('strongBuy')} / 매수 {d.get('buy')} / 보유 {d.get('hold')} / 매도 {d.get('sell')} / 강력 매도 {d.get('strongSell')}"
          f" (분포 합 {dsum}) · 목표가 평균 {tg.get('mean')} · 중앙 {tg.get('median')} · 최고 {tg.get('high')} · 최저 {tg.get('low')} (달러)")
    ch = analyst.get("changes") or []
    s4 = f"{SOURCE_YAHOO} 최근 등급·목표가 변경: " + ("; ".join(
        f"{c['date']} {c['firm']} 목표가 {c.get('pt_prior')}→{c.get('pt_now')}" for c in ch) if ch else "없음")
    return [s1, s2, s3, s4]


def validate_summary(text: str, n_sources: int) -> tuple[list[str], list[dict]]:
    """출처 번호 없음·범위 밖 → 폐기 · 금지어 → 폐기 · 목표가 문장은 [3]·[4] 번호가 있을 때만 · 최대 3줄."""
    kept: list[str] = []
    dropped: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-•*·0123456789.) ").strip()
        if not line:
            continue
        cites = [int(x) for x in _CITE_RE.findall(line)]
        if not cites or any(c < 1 or c > n_sources for c in cites):
            dropped.append({"reason": "no_or_bad_citation", "line": line[:200]})
            continue
        if QUOTE_FORBIDDEN_RE.search(line):
            dropped.append({"reason": "forbidden_word", "line": line[:200]})
            continue
        if _TARGET_RE.search(line) and not ({3, 4} & set(cites)):
            dropped.append({"reason": "target_without_source", "line": line[:200]})
            continue
        kept.append(line)
    return kept[:MAX_LINES], dropped


def input_hash(sources: list[str]) -> str:
    return hashlib.sha256("\n".join(sources).encode("utf-8")).hexdigest()


async def default_summarize(ticker: str, system: str, user: str) -> dict:
    """Anthropic 1순위 → Z.ai (FallbackLLM · 2026-10-23 결정)."""
    from backend.services.llm import FallbackLLM

    async with FallbackLLM() as llm:
        return await asyncio.wait_for(llm.complete_text(ticker, system, user), FallbackLLM.call_timeout)


def _user_prompt(ticker: str, sources: list[str]) -> str:
    body = "\n".join(f"[{i}] {s}" for i, s in enumerate(sources, 1))
    return f"종목 {ticker} 에 대해 수집된 자료:\n{body}\n\n위 자료만으로 3줄 이내로 정리하라."


async def run_summaries(cands: list[str], today: date, sec_fetch: Optional[SecFetcher] = None,
                        summarize: Optional[Summarizer] = None, pause: float = PAUSE_SEC,
                        reg_lookup: Optional[Callable[[str], Optional[dict]]] = None,
                        budget: Optional[SecBudget] = None) -> dict:
    """오늘 저장된 종목 가운데 가장 오래 전에 확인한 30종목 · 입력이 같으면 LLM 호출 0 · LLM 하루 30건."""
    sec_fetch = sec_fetch or default_sec_fetch
    summarize = summarize or default_summarize
    reg_lookup = reg_lookup or registry_facts
    order = {t: i for i, t in enumerate(cands)}
    async with _session() as s:
        rows = (await s.execute(select(BiotechQuoteDaily).where(BiotechQuoteDaily.asof_date == today))).scalars().all()
        todays = [(r.ticker, r.summary_checked_at, r.analyst_json, r.sec8k_json, r.summary_input_hash) for r in rows if r.ticker in order]
        made_today = 0
        for r in rows:
            sj = json.loads(r.summary_json) if r.summary_json else {}
            if (sj.get("made_at") or "")[:10] == today.isoformat():
                made_today += 1
    todays.sort(key=lambda x: (x[1] is not None, x[1] or datetime.min, order[x[0]]))
    picked = todays[:SEC_TICKERS_PER_DAY]
    if budget is None:
        try:
            from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecDailyLedger

            budget = SecBudget(SecDailyLedger.load(), SEC_DAILY_CAP)
        except Exception:  # noqa: BLE001
            budget = SecBudget(None)
    ledger = budget.ledger
    called, same, sec_err, llm_err = 0, 0, 0, 0
    for i, (t, _checked, analyst_json, sec_json, old_hash) in enumerate(picked):
        if i and pause:
            await asyncio.sleep(pause)
        prev_sec = json.loads(sec_json) if sec_json else None
        sec = prev_sec
        if not budget.blocked:
            try:
                sec = await sec_fetch(t, prev_sec, budget)
            except Exception as exc:  # noqa: BLE001
                sec_err += 1
                logger.warning("[biotech_quotes] SEC 받기 실패 · %s · %s", t, type(exc).__name__)
        analyst = json.loads(analyst_json) if analyst_json else {}
        sources = build_sources(today, reg_lookup(t), sec, analyst)
        h = input_hash(sources)
        summary_update: Optional[dict] = None
        if h == old_hash:
            same += 1
        elif made_today + called < SUMMARY_DAILY_CAP:
            try:
                res = await summarize(t, SUMMARY_SYSTEM, _user_prompt(t, sources))
                kept, dropped = validate_summary(res.get("text", ""), len(sources))
                summary_update = {"ok": bool(kept), "lines": kept, "dropped": len(dropped), "model": res.get("model"),
                                  "provider": res.get("provider"), "sources": sources,
                                  "made_at": f"{today.isoformat()}T{datetime.now(KST):%H:%M}"}
                called += 1
            except Exception as exc:  # noqa: BLE001
                llm_err += 1
                logger.warning("[biotech_quotes] 요약 실패 · %s · %s", t, type(exc).__name__)
        async with _session() as s:
            row = (await s.execute(select(BiotechQuoteDaily).where(
                BiotechQuoteDaily.ticker == t, BiotechQuoteDaily.asof_date == today))).scalar_one_or_none()
            if row is not None:
                row.summary_checked_at = _utcnow()
                if sec is not None:
                    row.sec8k_json = json.dumps(sec, ensure_ascii=False)
                if summary_update is not None:
                    row.summary_json = json.dumps(summary_update, ensure_ascii=False)
                    row.summary_input_hash = h
    if ledger is not None:
        try:
            ledger.save()
        except Exception:  # noqa: BLE001
            pass
    return {"picked": len(picked), "llm": called, "same_input": same, "sec_requests": budget.used(),
            "sec_errors": sec_err, "llm_errors": llm_err}


# ─────────────────────────────────────────────────────────────────
# 조회 (화면 요청 · 저장값 + 네이버 현재가 1건)
# ─────────────────────────────────────────────────────────────────

_LIVE: dict[str, tuple[float, Optional[dict]]] = {}
LiveFetcher = Callable[[str], Awaitable[Any]]


def naver_codes(ticker: str, exchange: Optional[str]) -> list[str]:
    suf = _NAVER_SUFFIX.get((exchange or "").upper())
    if suf is not None:
        return [f"{ticker}{suf}"]
    return [f"{ticker}.O", ticker, f"{ticker}.K"]


async def live_price(ticker: str, exchange: Optional[str], fetch: Optional[LiveFetcher] = None) -> Optional[dict]:
    """네이버 현재가 · 종목별 60초 캐시 · 실패면 None (화면은 저장 종가와 「실시간 실패」)."""
    now = time.monotonic()
    hit = _LIVE.get(ticker)
    if hit and now - hit[0] < LIVE_CACHE_SEC:
        return hit[1]
    if fetch is None:
        from backend.discovery.vip.price_client import fetch_us_quote as fetch
    out: Optional[dict] = None
    for code in naver_codes(ticker, exchange):
        q = await fetch(code)
        if q is not None:
            out = {"price": q.close_price, "change_pct": q.fluctuations_ratio, "market_status": q.market_status,
                   "traded_at": q.local_traded_at, "source": SOURCE_NAVER}
            break
    _LIVE[ticker] = (now, out)
    return out


async def quote_view(ticker: str, live_fetch: Optional[LiveFetcher] = None, now: Optional[datetime] = None) -> dict:
    """GET /api/v1/biotech/quote/{ticker} 본문. 문장은 고정 머리말만 · 판정 문장 없음."""
    from backend.services.holdings_swing import build_chart

    async with _session() as s:
        row = (await s.execute(select(BiotechQuoteDaily).where(BiotechQuoteDaily.ticker == ticker)
                               .order_by(BiotechQuoteDaily.asof_date.desc()).limit(1))).scalar_one_or_none()
        longs = (await s.execute(select(BiotechLongClose.trade_date, BiotechLongClose.close)
                                 .where(BiotechLongClose.ticker == ticker).order_by(BiotechLongClose.trade_date))).all()
    # 세션을 닫은 뒤에 바깥 호출
    live = await live_price(ticker, row.exchange if row else None, live_fetch)
    et_today = (now or datetime.now(timezone.utc)).astimezone(ET).date()
    chart = build_chart("US", ([d for d, _ in longs], [c for _, c in longs], "yahoo"), et_today) if longs else None
    analyst = json.loads(row.analyst_json) if row and row.analyst_json else {}
    dist = analyst.get("dist") or {}
    dsum = sum(v for v in dist.values() if isinstance(v, int)) if dist else None
    n_op = analyst.get("n_opinions")
    has_opinion = bool(n_op) or bool(dsum)
    summary = json.loads(row.summary_json) if row and row.summary_json else None
    sec = json.loads(row.sec8k_json) if row and row.sec8k_json else None
    return {
        "ticker": ticker,
        "asof": row.asof_date.isoformat() if row else None,
        "live": live,
        "live_note": None if live else "실시간 실패 · 저장 종가를 보여 드립니다",
        "basics": None if row is None else {
            "price_close": row.price_close, "volume": row.volume, "avg_volume": row.avg_volume,
            "market_cap": row.market_cap, "low_52w": row.low_52w, "high_52w": row.high_52w,
            "total_cash": row.total_cash, "short_pct_float": row.short_pct_float,
            "short_asof": row.short_asof.isoformat() if row.short_asof else None,
            "source": SOURCE_YAHOO,
        },
        "chart": chart,
        "opinion": None if not has_opinion else {
            "head": OPINION_HEAD, "grade_note": GRADE_NOTE, "n_opinions": n_op, "dist": dist, "dist_sum": dsum,
            "count_mismatch": bool(n_op is not None and dsum is not None and n_op != dsum),
            "targets": analyst.get("targets") or {}, "changes": analyst.get("changes") or [], "source": SOURCE_YAHOO,
        },
        "summary": None if not summary or not summary.get("ok") else {
            "head": SUMMARY_HEAD, "lines": summary.get("lines", []), "sources": summary.get("sources", []),
            "model": summary.get("model"), "made_at": summary.get("made_at"),
        },
        "sec8k": sec if sec and (sec.get("title") or sec.get("lead")) else None,
        "use_note": USE_NOTE,
    }
