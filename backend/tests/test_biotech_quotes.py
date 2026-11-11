"""1111-01 · 바이오 종목 가격·전문가 의견 칸 — 계획 5절 수용 기준 (docs/plans/biotech-quote/2026-11-11-plan.md).

종목 기호는 모두 가짜 값이다 (ZZQA 등 · 실제 종목 아님). 바깥 호출(야후 · SEC · 네이버 · LLM)은 모두 가짜 함수로 바꾼다.
날짜는 시험 안에서 고정한다 (교훈 #5).
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, text

from backend.services import biotech_quotes as bq
from backend.services.models import BiotechLongClose, BiotechQuoteDaily

TOKEN = "biotech_quotes_test_token_32chars"
NOW = datetime(2026, 11, 11, 23, 45, tzinfo=timezone.utc)   # 11/12(목) 08:45 KST
TODAY = date(2026, 11, 12)
A, B, C = "ZZQA", "ZZQB", "ZZQC"


def _closes(n: int, end: date = date(2026, 11, 11)) -> list[tuple[date, float]]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append((d, 10.0 + (len(out) % 7)))
        d -= timedelta(days=1)
    return sorted(out)


def _raw(n_close: int = 1300, n_op: int | None = 10, dist: dict | None = None) -> dict:
    return {
        "info": {"exchange": "NMS", "currentPrice": 12.5, "regularMarketVolume": 1_000_000, "averageVolume": 500_000,
                 "marketCap": 2.7e9, "fiftyTwoWeekLow": 5.0, "fiftyTwoWeekHigh": 20.0, "totalCash": 4.8e8,
                 "shortPercentOfFloat": 0.12, "dateShortInterest": 1793318400, "numberOfAnalystOpinions": n_op,
                 "recommendationKey": "strong_buy", "targetMeanPrice": 30.0, "targetMedianPrice": 28.0,
                 "targetHighPrice": 50.0, "targetLowPrice": 20.0},
        "dist": dist if dist is not None else {"strongBuy": 3, "buy": 8, "hold": 0, "sell": 0, "strongSell": 0},
        "changes": [{"date": "2026-10-12", "firm": "Firm One", "to_grade": "Buy", "from_grade": "Buy", "action": "main",
                     "pt_now": 25.0, "pt_prior": 20.0}],
        "closes": _closes(n_close),
    }


@pytest.fixture
async def clean(monkeypatch):
    from backend.services.db import get_session, init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", TOKEN)
    await init_db()
    async with get_session() as s:
        await s.execute(delete(BiotechLongClose))
        await s.execute(delete(BiotechQuoteDaily))
    bq._LIVE.clear()
    bq._CAND_CACHE.update({"at": 0.0, "list": []})
    yield


async def _no_sec(t, prev, budget):
    return None


async def _no_llm(t, system, user):
    return {"text": "", "provider": "test", "model": "none"}   # 빈 답 → 요약 없음


def _reg(t):
    return {"nct_id": "NCT00000001", "phase": "PHASE1", "status": "RECRUITING", "pcd": "2026-10-30",
            "pcd_type": "ESTIMATED", "last_update": "2026-06-09"}


async def _run(fetch, cands, summarize=_no_llm, sec_fetch=_no_sec, now=NOW):
    return await bq.run_quotes(now=now, fetch=fetch, sec_fetch=sec_fetch, summarize=summarize,
                               candidates=cands, pause=0, budget=bq.SecBudget(None))


# ── 1. 조회 API: 토큰 없음 401 · 후보 아님 404 · 후보 200 ──────────────────

async def test_quote_route_auth_404_200(clean, monkeypatch):
    from backend.api.main import app

    async def _cands():
        return {A}

    async def _live(code):
        return None

    monkeypatch.setattr(bq, "candidate_set", _cands)
    monkeypatch.setattr(bq, "live_price", lambda t, ex, f=None: _live(t))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/biotech/quote/{A}")
        assert r.status_code == 401
        h = {"X-API-Token": TOKEN}
        assert (await ac.get(f"/api/v1/biotech/quote/{B}", headers=h)).status_code == 404
        assert (await ac.get("/api/v1/biotech/quote/bad$$", headers=h)).status_code == 404
        r = await ac.get(f"/api/v1/biotech/quote/{A}", headers=h)
        assert r.status_code == 200
        j = r.json()
        assert j["ticker"] == A and j["live"] is None and j["live_note"].startswith("실시간 실패")


# ── 2. 잡: 종목마다 커밋 · 실패 종목은 전날 행 유지 · 30일 탈락 삭제 · 150 상한 ──────

async def test_job_per_ticker_commit_and_failure_keeps_previous(clean):
    async def ok_fetch(t, period):
        return _raw()

    await _run(ok_fetch, [A, B], now=NOW - timedelta(days=1))

    async def half_fetch(t, period):
        if t == B:
            raise TimeoutError("가짜 실패")
        return _raw(n_close=20)

    out = await _run(half_fetch, [A, B])
    assert out["ok"] == 1 and out["failures"] == 1
    from backend.services.db import get_session

    async with get_session() as s:
        rows = (await s.execute(select(BiotechQuoteDaily.ticker, BiotechQuoteDaily.asof_date))).all()
        n_b = (await s.execute(select(func.count()).where(BiotechLongClose.ticker == B))).scalar()
    assert (A, TODAY) in rows and (B, TODAY - timedelta(days=1)) in rows and (B, TODAY) not in rows
    assert n_b == 1300   # 받기 실패 종목의 일봉 그대로


async def test_job_first_full_then_recent(clean):
    periods = []

    async def fetch(t, period):
        periods.append(period)
        return _raw(n_close=1300 if period == bq.FIRST_PERIOD else 15)

    await _run(fetch, [A], now=NOW - timedelta(days=1))
    await _run(fetch, [A])
    assert periods == [bq.FIRST_PERIOD, bq.RECENT_PERIOD]
    from backend.services.db import get_session

    async with get_session() as s:
        n = (await s.execute(select(func.count()).where(BiotechLongClose.ticker == A))).scalar()
    assert n == 1300   # 최근 15일은 덮어쓰기 · 늘지 않음


async def test_prune_dropped_after_30_days(clean):
    async def fetch(t, period):
        return _raw(n_close=30)

    await _run(fetch, [A, C], now=NOW - timedelta(days=31))
    await _run(fetch, [A], now=NOW - timedelta(days=10))    # C 는 후보에서 빠짐 · 아직 30일 안
    from backend.services.db import get_session

    async with get_session() as s:
        assert (await s.execute(select(func.count()).where(BiotechLongClose.ticker == C))).scalar() == 30
    await _run(fetch, [A])                                   # C 마지막 기록이 31일 전 → 삭제
    async with get_session() as s:
        assert (await s.execute(select(func.count()).where(BiotechLongClose.ticker == C))).scalar() == 0
        assert (await s.execute(select(func.count()).where(BiotechQuoteDaily.ticker == C))).scalar() == 0
        # 하루 기록도 30일 넘은 행은 지움 (A 의 31일 전 행)
        old = (await s.execute(select(func.count()).where(BiotechQuoteDaily.ticker == A,
                                                          BiotechQuoteDaily.asof_date < TODAY - timedelta(days=30)))).scalar()
    assert old == 0


async def test_candidates_order_and_cap(monkeypatch, tmp_path):
    from backend.api.routes import biotech as R

    p = tmp_path / "radar_v1_3_20261111.csv"
    p.write_text("ticker,name,score\nZZL1,x,0.1\nZZH1,x,0.9\nZZM1,x,0.5\n")
    monkeypatch.setattr(R, "_latest_radar_csv", lambda: p)

    class _Row:
        def __init__(self, t):
            self.ticker = t

    class _Rumor:
        rows = [_Row("ZZM1"), _Row("ZZR1"), _Row("ZZR2")]

    async def _rumor(date=None, _admin=None):
        return _Rumor()

    monkeypatch.setattr(R, "get_rumor_json", _rumor)
    assert await bq.load_candidates() == ["ZZH1", "ZZM1", "ZZL1", "ZZR1", "ZZR2"]
    assert await bq.load_candidates(limit=4) == ["ZZH1", "ZZM1", "ZZL1", "ZZR1"]
    assert bq.MAX_TICKERS == 150


# ── 2-1. 세션이 열린 동안 네트워크 호출 0 (Fable 2차 막음 2) ──────────────────

async def test_no_network_while_session_open(clean, monkeypatch):
    real = bq._session
    state = {"open": 0, "violations": 0}

    @asynccontextmanager
    async def watched():
        async with real() as s:
            state["open"] += 1
            try:
                yield s
            finally:
                state["open"] -= 1

    monkeypatch.setattr(bq, "_session", watched)

    def _check():
        if state["open"]:
            state["violations"] += 1

    async def fetch(t, period):
        _check()
        await asyncio.sleep(0)
        return _raw(n_close=40)

    async def sec(t, prev, budget):
        _check()
        return {"accession": "0000000000-26-000001", "filing_date": "2026-11-09", "title": "Q3 results",
                "lead": "Data on track for Q4 2026.", "url": "https://www.sec.gov/x"}

    async def llm(t, system, user):
        _check()
        return {"text": "회사 공시는 12주 자료를 4분기에 낸다고 적었다 [2].", "provider": "anthropic", "model": "m"}

    monkeypatch.setattr(bq, "registry_facts", _reg)
    out = await bq.run_quotes(now=NOW, fetch=fetch, sec_fetch=sec, summarize=llm, candidates=[A, B], pause=0,
                              budget=bq.SecBudget(None))
    assert out["ok"] == 2 and out["summary"]["llm"] == 2
    assert state["violations"] == 0


# ── 3. 쓰기 잠김 시험: 잡이 도는 동안 다른 연결이 계속 쓰기 → 잠김 0 (임시 파일 DB) ──────

async def test_no_lock_with_concurrent_writer(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.services.models import Base

    url = f"sqlite+aiosqlite:///{tmp_path / 'lock.db'}"
    eng = create_async_engine(url, connect_args={"timeout": 2})
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
        await c.execute(text("CREATE TABLE other_writer (id INTEGER PRIMARY KEY, v TEXT)"))
    maker = async_sessionmaker(eng, expire_on_commit=False)

    @asynccontextmanager
    async def file_session():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    monkeypatch.setattr(bq, "_session", file_session)
    other = create_async_engine(url, connect_args={"timeout": 2})
    errors, writes, stop = [], [0], asyncio.Event()

    async def writer():
        while not stop.is_set():
            try:
                async with other.begin() as c:
                    await c.execute(text("INSERT INTO other_writer (v) VALUES ('x')"))
                writes[0] += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
            await asyncio.sleep(0.01)

    async def fetch(t, period):
        await asyncio.sleep(0.02)   # 바깥 받기 흉내 (세션 밖)
        return _raw(n_close=1500)

    task = asyncio.create_task(writer())
    out = await bq.run_quotes(now=NOW, fetch=fetch, sec_fetch=_no_sec, summarize=_no_llm,
                              candidates=[f"ZZW{i}" for i in range(12)], pause=0, budget=bq.SecBudget(None))
    stop.set()
    await task
    await eng.dispose()
    await other.dispose()
    assert out["ok"] == 12 and out["long_rows"] == 12 * 1500
    assert writes[0] > 10
    assert not [e for e in errors if "locked" in e], errors[:3]


# ── 4. 그림 자료 · 5. 현재가 캐시 · 6. 전문가 의견 ───────────────────────────

async def test_view_chart_opinion_and_live_cache(clean):
    async def fetch(t, period):
        return _raw(n_close=1300, n_op=10)

    await _run(fetch, [A])
    calls = []

    class _Q:
        close_price, fluctuations_ratio, market_status, local_traded_at = 13.0, 4.0, "OPEN", "2026-11-11T10:00:00-05:00"

    async def live(code):
        calls.append(code)
        return _Q()

    v = await bq.quote_view(A, live_fetch=live, now=NOW)
    v2 = await bq.quote_view(A, live_fetch=live, now=NOW)
    assert calls == [f"{A}.O"]                 # 60초 안 두 번 → 네이버 1번 · 나스닥 코드
    assert v["live"]["price"] == 13.0 and v2["live"]["price"] == 13.0
    assert v["chart"]["week40"] is not None and len(v["chart"]["daily"]) > 200
    assert v["chart"]["daily"][-1]["m200"] is not None
    op = v["opinion"]
    assert op["head"] == bq.OPINION_HEAD and op["n_opinions"] == 10 and op["dist_sum"] == 11
    assert op["count_mismatch"] is True        # 의견 수와 분포 합이 다르면 둘 다 보이게 표시
    assert op["targets"]["mean"] == 30.0 and op["changes"][0]["to_grade"] == "Buy"   # 등급 원문 그대로
    assert v["basics"]["market_cap"] == 2.7e9 and v["basics"]["source"] == bq.SOURCE_YAHOO
    assert "upside" not in json.dumps(v, default=str).lower()


async def test_view_short_chart_and_no_opinion(clean):
    async def fetch(t, period):
        return _raw(n_close=120, n_op=None, dist={})

    await _run(fetch, [A])

    async def live(code):
        return None

    v = await bq.quote_view(A, live_fetch=live, now=NOW)
    assert v["opinion"] is None                       # 의견 0 → 칸 없음
    assert v["chart"]["daily_note"] == "자료 부족"    # 200일 모자람
    assert v["chart"]["week40"]["note"] == "40주 자료 부족"
    assert v["live"] is None and v["basics"]["price_close"] == 12.5


def test_naver_codes():
    assert bq.naver_codes("ZZQA", "NMS") == ["ZZQA.O"]
    assert bq.naver_codes("ZZQA", "NYQ") == ["ZZQA"]
    assert bq.naver_codes("ZZQA", "ASE") == ["ZZQA.K"]
    assert bq.naver_codes("ZZQA", None) == ["ZZQA.O", "ZZQA", "ZZQA.K"]


# ── 7. AI 요약: 입력 같으면 호출 0 · 하루 30건 · 필터 ───────────────────────

async def test_summary_hash_and_daily_cap(clean, monkeypatch):
    monkeypatch.setattr(bq, "registry_facts", _reg)
    n = {"llm": 0}

    async def llm(t, system, user):
        n["llm"] += 1
        return {"text": "등록부 상태는 모집 중이다 [1].", "provider": "anthropic", "model": "m"}

    async def fetch(t, period):
        return _raw(n_close=30)

    cands = [f"ZZS{i:02d}" for i in range(35)]
    out = await bq.run_quotes(now=NOW, fetch=fetch, sec_fetch=_no_sec, summarize=llm, candidates=cands, pause=0,
                              budget=bq.SecBudget(None))
    assert out["summary"]["picked"] == bq.SEC_TICKERS_PER_DAY == 30
    assert n["llm"] == bq.SUMMARY_DAILY_CAP == 30
    # 같은 날 다시 돌면: 남은 5종목이 먼저 뽑히지만 하루 상한이 차서 LLM 0
    out2 = await bq.run_quotes(now=NOW, fetch=fetch, sec_fetch=_no_sec, summarize=llm, candidates=cands, pause=0,
                               budget=bq.SecBudget(None))
    assert out2["summary"]["llm"] == 0 and n["llm"] == 30
    # 저장된 요약은 머리말과 함께 화면 자료로 나감
    v = await bq.quote_view(cands[0], live_fetch=lambda c: asyncio.sleep(0), now=NOW)
    assert v["summary"]["head"] == bq.SUMMARY_HEAD and v["summary"]["lines"] == ["등록부 상태는 모집 중이다 [1]."]


async def test_summary_same_input_no_call(clean, monkeypatch):
    monkeypatch.setattr(bq, "registry_facts", _reg)
    n = {"llm": 0}

    async def llm(t, system, user):
        n["llm"] += 1
        return {"text": "등록부 상태는 모집 중이다 [1].", "provider": "anthropic", "model": "m"}

    async def fetch(t, period):
        return _raw(n_close=30)

    await bq.run_quotes(now=NOW, fetch=fetch, sec_fetch=_no_sec, summarize=llm, candidates=[A], pause=0, budget=bq.SecBudget(None))
    # 같은 날 · 같은 입력 → 해시 같음 → 호출 0
    from backend.services.db import get_session

    async with get_session() as s:
        row = (await s.execute(select(BiotechQuoteDaily).where(BiotechQuoteDaily.ticker == A))).scalar_one()
        row.summary_checked_at = None
    out = await bq.run_summaries([A], TODAY, sec_fetch=_no_sec, summarize=llm, pause=0, budget=bq.SecBudget(None))
    assert out["same_input"] == 1 and n["llm"] == 1


def test_validate_summary_filter():
    text_ = "\n".join([
        "애널리스트 목표가 평균은 30달러다 [3].",          # 남음 (목표가 + [3])
        "목표가 평균은 30달러다 [1].",                     # 폐기 (목표가인데 [3]·[4] 없음)
        "주가가 오를 것으로 보인다 [3].",                  # 폐기 (예측)
        "상승 여력이 크다 [3].",                           # 폐기 (계산)
        "50일선과 200일선이 교차했다 [1].",                # 폐기 (신호 낱말)
        "Most analysts rate it Buy [3].",                   # 폐기 (등급 낱말)
        "출처 없는 문장이다.",                             # 폐기 (번호 없음)
        "등록부 마지막 갱신은 6월 9일이다 [1].",           # 남음
        "회사는 4분기에 자료를 낸다고 적었다 [2].",        # 남음
        "네 번째 줄은 잘린다 [1].",                       # 3줄 상한
    ])
    kept, dropped = bq.validate_summary(text_, 4)
    assert kept == ["애널리스트 목표가 평균은 30달러다 [3].", "등록부 마지막 갱신은 6월 9일이다 [1].",
                    "회사는 4분기에 자료를 낸다고 적었다 [2]."]
    reasons = [d["reason"] for d in dropped]
    assert reasons.count("forbidden_word") == 4 and "target_without_source" in reasons and "no_or_bad_citation" in reasons


def test_alert_brief_filter_unchanged():
    """경보 요약 필터는 그대로 (목표가 문장 폐기 유지)."""
    from backend.scripts.biotech_llm import FORBIDDEN_RE

    assert FORBIDDEN_RE.search("목표가 평균 30달러")
    assert not bq.QUOTE_FORBIDDEN_RE.search("목표가 평균 30달러")


def test_sources_keep_mismatch_and_registry_facts():
    analyst = {"n_opinions": 10, "dist": {"strongBuy": 3, "buy": 8, "hold": 0, "sell": 0, "strongSell": 0},
               "targets": {"mean": 95.7, "median": 88.0, "high": 150.0, "low": 80.0}, "changes": []}
    src = bq.build_sources(TODAY, _reg("x"), {"filing_date": "2026-11-09", "title": "T",
                                             "lead": "Data on track for Q4 2026. Analysts see upside."}, analyst)
    assert "의견 수 10" in src[2] and "분포 합 11" in src[2]
    assert "상태 RECRUITING" in src[0] and "마지막 갱신 2026-06-09" in src[0]
    assert "upside" not in src[1] and "Q4 2026" in src[1]


async def test_sec_budget_cap():
    b = bq.SecBudget(None)
    for _ in range(bq.SEC_QUOTE_DAILY_REQ):
        assert b.can()
        b.add()
    assert not b.can()
    b2 = bq.SecBudget(None)
    b2.blocked = True
    assert not b2.can()


# ── 10. 점수·순위 불변: 이 모듈은 후보 파일·점수에 쓰지 않는다 ─────────────────

def test_module_does_not_write_scores_or_alerts():
    src = Path(bq.__file__).read_text()
    assert not re.search(r"\.write_text|open\([^)]*['\"]w", src)        # 파일 쓰기 없음 (CSV·JSON 산출 불변)
    for word in ("send_warning", "TelegramNotifier", "radar_v1_3", "score ="):
        assert word not in src


# ── 4절 금지 낱말: 고정 문자열 (서버 모듈 · 응답 머리말) ─────────────────────

SIGNAL = re.compile(r"골든|데드|크로스|교차|정배열|역배열|사십시오|사세요|파세요")


def test_fixed_strings_have_no_signal_or_command_words():
    for s in (bq.OPINION_HEAD, bq.SUMMARY_HEAD, bq.GRADE_NOTE, bq.USE_NOTE):
        assert not SIGNAL.search(s)
    assert "추정 · 보장 아님" in bq.OPINION_HEAD and "추정 · 보장 아님" in bq.SUMMARY_HEAD


# ── 8. 등록부 칸 전달 ───────────────────────────────────────────────

def test_trial_display_passes_registry_dates(monkeypatch):
    from backend.api.routes import biotech as R

    monkeypatch.setattr(R, "_snapshot_by_nct", lambda: {"NCT00000001": {
        "overall_status": "RECRUITING", "primary_completion_date_type": "ESTIMATED",
        "last_update_posted_date": "2026-06-09", "conditions": [], "mesh_terms": [], "interventions": [],
        "primary_outcomes": []}})
    d = R._trial_display("NCT00000001")
    assert d["overall_status"] == "RECRUITING" and d["pcd_type"] == "ESTIMATED" and d["last_update"] == "2026-06-09"


# ── 화면 글자 확인 (tsx · 없으면 건너뜀) ───────────────────────────────

def test_frontend_quote_check_script():
    import shutil
    import subprocess

    fe = Path(__file__).resolve().parents[2] / "frontend"
    if not shutil.which("npx") or not (fe / "node_modules").exists():
        pytest.skip("npx 또는 node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/biotech-quote.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().endswith("ok")
