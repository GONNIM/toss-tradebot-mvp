"""1112-07 · 결과 발표 명부 보충 (WP39 명부는 그대로 · 별도 파일에 새 사건만 덧붙임).

까닭: WP39 명부 (docs/plans/biotech/data/h39_readouts_checkpoint.json) 는 2026-09-01 에서 멈춘 고정 파일이다
(해시 고정 시험 · 「WP39 명부·코드 수정 금지」). 후보 출처 (a) 「최근 90일 결과 발표」 가 이 파일만 읽어
11/07 부터 후보가 줄고 12/02 07:00 KST 에 0 이 된다 (1112-06 조사 · Fable 2026-11-12-1112-06-01).

하는 일:
- 대상 회사 = WP39 명부의 processed_ciks (같은 회사 범위 · 서버에도 있는 파일)
- EFTS forms=8-K · 기간 --since ~ --until · 회사마다 1회 이상 (100건 단위 쪽 넘김)
- 항목 2.02 · 7.01 · 8.01 이 있는 8-K 만 본문 1건 (`{accession}.txt`) · WP39 규칙 (KW_RE · 방향 · 접수 시각) 을 import 해 그대로 씀
- WP39 명부에 이미 있는 접수번호는 건너뜀 · 결과는 h39_readouts_increment.json (기간 · 처리 회사 · 사건 · 집계)
- 같은 기간으로 다시 돌리면 처리한 회사는 건너뜀 (이어 받기)

지킬 것:
- 헤더 = biotech_sec_common.build_client 단일 상수 · 요청마다 장부 범주 "readout_increment" 에 보내기 직전 셈
- 하루 상한 SEC_DAILY_CAP (장부 합계 기준) 에 닿으면 저장하고 멈춤 (종료 코드 3 · 다음 날 같은 명령으로 이어 받음)
- 403 · 429 즉시 중단 (종료 코드 2) · 재시도 없음
- WP39 명부 · 그 코드는 고치지 않음 (함수만 import)

1112-08 · 서버 주간 작업 (--weekly · 시스템 crontab 매일 22:00 KST) 과 오래됨 점검 (--check-stale · 07:00 파이프 · 요청 0):
- 기간은 순수 함수 plan_period 가 정한다 (앞 기간 끝남 + 앞 until 에서 7일 지남 → 새 기간 · 덜 끝남 → 이어 받기 · 아니면 할 일 없음)
- 기간을 열 때와 실행을 시작할 때 complete=False 로 먼저 저장 · 끝까지 받았을 때만 True (막음 ①)
- 실행마다 last_run_at 을 쓴다 (할 일이 없어도) · 오래됨 판단은 이 칸으로 한다 (막음 ②)
- 이미 본 접수번호 = WP39 명부 + docs 본 + RUNTIME 본 사건 + 검색어 없던 본문 접수번호 (파일에 저장 · 최근 두 기간만 · 막음 ③)
- 장부는 요청마다 다시 읽어 더해 저장 · 보내기 직전 합계 + 1 > 상한이면 멈춤 · 실행 중 KST 날짜가 바뀌면 멈춤
- 겹쳐 실행 금지 (파일 잠금) · 403/429 이틀 연속이면 자동 실행 멈춤 (--clear-halt 로 다시 켬)
- docs 본 (docs/plans/biotech/data/h39_readouts_increment.json) 은 고정 · 서버는 RUNTIME 본에만 쓴다

사용 (로컬 · 저장소 맨 위에서): backend/venv/bin/python -m backend.scripts.biotech_readout_increment --since 2026-09-02 --until 2026-11-12
  (-I 를 붙이면 현재 폴더가 import 경로에서 빠져 backend 를 못 찾는다)
- 200 이 아닌 응답 · 전송 예외는 그 회사를 처리 목록에 넣지 않고 failures 에 적는다 (다음 실행에서 다시 받음) · 저장은 늘 함
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import fcntl
import json
import logging
import sys
import time
from collections import Counter

import httpx
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_listing_status import is_merger_announcement
from backend.scripts.biotech_h39_readouts import (
    KW_RE, classify_direction, extract_matched_keywords, parse_accept_dt, d_day_from_accept,
)
from backend.scripts.biotech_sec_common import (
    REQ_INTERVAL, SEC_DAILY_CAP, SecBlockedError, SecDailyLedger, build_client,
)

LOG = logging.getLogger("biotech_readout_increment")

EFTS = "https://efts.sec.gov/LATEST/search-index"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
WANTED_ITEMS = ("2.02", "7.01", "8.01")
LEDGER_CAT = "readout_increment"
OUT_NAME = "h39_readouts_increment.json"
BASE_NAME = "h39_readouts_checkpoint.json"
MAX_BODY = 5_000_000
WEEKLY_LEDGER_CAT = LEDGER_CAT
NEW_PERIOD_DAYS = 7          # 앞 until 에서 이만큼 지나면 새 기간
OVERLAP_DAYS = 3             # 새 기간 since = 앞 until − 3일 (겹침)
STALE_UNTIL_DAYS = 9         # --check-stale · until 이 이보다 오래되면 알림
STALE_RUN_DAYS = 3           # --check-stale · last_run_at 이 이보다 오래되면 알림
OPEN_ALERT_DAYS = 7          # 기간을 연 뒤 이만큼 지나도 덜 끝나면 알림
KEEP_NO_KW_PERIODS = 2       # 검색어 없던 본문 접수번호 보관 기간 수
PERSISTENT_FAIL_RUNS = 3     # 이 횟수 이상 실패한 회사 = 계속 오류
LOCK_NAME = ".readout_weekly.lock"
EXIT_OK, EXIT_BLOCKED, EXIT_CAP, EXIT_FAILURES, EXIT_HALTED, EXIT_BROKEN = 0, 2, 3, 4, 5, 6


class CapReached(RuntimeError):
    pass


class DayRolled(CapReached):
    """실행 중 KST 날짜가 바뀜 · 장부 날짜가 어긋나므로 멈춤 (종료 3 · 다음 날 이어 받음)."""


def out_path() -> Path:
    """서버 (RUNTIME) 면 RUNTIME 아래 · 로컬이면 docs/plans/biotech/data (커밋 이식 · 9/20 α 와 같은 길)."""
    return (_P.RUNTIME_DIR / OUT_NAME) if _P.RUNTIME_DIR is not None else (_P.DATA_DIR_DOCS / OUT_NAME)


def load_base() -> dict:
    p = _P.find(BASE_NAME)
    if p is None:
        raise FileNotFoundError(BASE_NAME)
    return json.loads(p.read_text())


def _fresh(since: str, until: str) -> dict:
    return {"since": since, "until": until, "processed_ciks": [], "events": [], "complete": False,
            "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0}}


def period_key(since: str, until: str) -> str:
    return f"{since}~{until}"


def _rollover(d: dict, since: str, until: str) -> dict:
    """기간이 바뀜 · 사건 · 기간별 통계 · 알림 기록은 남기고 처리 회사 · 실패 · 통계만 새로 시작 (complete 는 False · 막음 ①)."""
    if d.get("since") and (d.get("stats") or {}).get("efts_calls"):      # 받은 적 없는 기간 (docs 본 기준 빈 시작) 은 적지 않음
        d.setdefault("period_stats", {})[period_key(d["since"], d.get("until", ""))] = d.get("stats") or {}
    d.update({"since": since, "until": until, "processed_ciks": [], "complete": False, "failures": [],
              "fail_counts": {}, "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0}})
    d.pop("closed_incomplete", None)
    d.pop("abandoned_ciks", None)
    return d


def load_out(path: Path, since: str, until: str) -> dict:
    """같은 기간이면 이어 받기 · 기간이 바뀌면 _rollover."""
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("since") == since and d.get("until") == until:
            return d
        return _rollover(d, since, until)
    return _fresh(since, until)


def save_out(path: Path, d: dict) -> None:
    d["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    tmp.replace(path)


def make_getter(client, ledger: SecDailyLedger, cap: int, sleep: Callable[[float], None] = time.sleep,
                today_fn: Callable[[], str] | None = None):
    """보내기 직전 장부를 다시 읽고 합계 + 1 > 상한이면 CapReached · 이번 요청 1건만 더해 저장 (다른 잡이 더한 수를 덮지 않음) · 403/429 면 SecBlockedError.

    today_fn 이 주어지면 (서버 실행) 장부 날짜와 KST 오늘이 다를 때 DayRolled. get.status_counts 에 응답 상태를 센다.
    """
    from backend.services.biotech_quotes import save_ledger_merged

    status_counts: Counter = Counter()

    def get(url: str, params: dict | None = None):
        if today_fn is not None and today_fn() != ledger.day:
            raise DayRolled(f"KST 날짜가 {ledger.day} 에서 {today_fn()} 로 바뀜")
        fresh = SecDailyLedger.load(day=ledger.day, base=ledger.path.parent)
        if fresh.total() + 1 > cap:
            ledger.counts = fresh.counts
            raise CapReached(f"장부 합계 {fresh.total()} + 1 > 상한 {cap}")
        save_ledger_merged(ledger, 1, LEDGER_CAT)
        sleep(REQ_INTERVAL)
        r = client.get(url, params=params)
        status_counts[r.status_code] += 1
        if r.status_code in (403, 429):
            raise SecBlockedError(f"SEC HTTP {r.status_code} · {url[:60]}")
        return r
    get.status_counts = status_counts
    return get


class FetchFailed(RuntimeError):
    pass


def efts_8k(get, cik10: str, since: str, until: str) -> list[dict]:
    hits, page_from = [], 0
    while True:
        r = get(EFTS, {"forms": "8-K", "dateRange": "custom", "startdt": since, "enddt": until,
                       "ciks": cik10, "from": page_from, "size": 100})
        if r.status_code != 200:
            raise FetchFailed(f"EFTS HTTP {r.status_code}")
        j = r.json()
        hh = j.get("hits", {}).get("hits", [])
        if not hh:
            break
        hits.extend(hh)
        total = j.get("hits", {}).get("total", {}).get("value", 0)
        page_from += len(hh)
        if page_from >= total or len(hh) < 100:
            break
    return hits


def known_accessions(base: dict, d: dict, extra_known=()) -> set:
    """이미 본 접수번호 (막음 ③) = WP39 명부 + docs 본 (extra_known) + RUNTIME 본 사건 + 검색어 없던 본문 (파일에 저장한 최근 두 기간)."""
    known = {e.get("accession") for e in base.get("events", [])} | {e.get("accession") for e in d["events"]}
    known |= {a for a in extra_known if a}
    for accs in (d.get("no_kw_accessions") or {}).values():
        known |= set(accs)
    known.discard(None)
    known.discard("")
    return known


def _prune_no_kw(d: dict) -> None:
    nk = d.get("no_kw_accessions") or {}
    for k in sorted(nk)[:-KEEP_NO_KW_PERIODS] if len(nk) > KEEP_NO_KW_PERIODS else []:
        del nk[k]


def sec_ticker_map(path: Path | None) -> dict:
    """SEC 회사 명부 (sec_company_tickers.json · 요청 0) → {cik10: 티커} · 한 CIK 의 여러 티커 중 첫 항목."""
    out: dict = {}
    if path is None or not path.exists():
        return out
    try:
        for _, e in json.loads(path.read_text()).items():
            cik = str(e.get("cik_str", "")).zfill(10)
            tk = str(e.get("ticker", "")).upper()
            if tk and cik not in out:
                out[cik] = tk
    except Exception as e:  # 명부가 깨져도 보충은 계속 (티커는 후보 단계가 CIK 로 채움)
        LOG.warning("SEC 회사 명부 읽기 실패 · 티커 비움 · %s", e.__class__.__name__)
    return out


def run(get, base: dict, d: dict, since: str, until: str, save: Callable[[], None],
        extra_known=(), sec_tickers: dict | None = None) -> dict:
    cik2tk = dict(sec_tickers or {})
    for e in base.get("events", []):
        if e.get("ticker"):
            cik2tk[e["cik"]] = e["ticker"]            # WP39 명부 티커가 우선
    known = known_accessions(base, d, extra_known)
    key = period_key(since, until)
    no_kw = d.setdefault("no_kw_accessions", {}).setdefault(key, [])
    no_kw_set = set(no_kw)
    processed = set(d["processed_ciks"])
    st = d["stats"]
    targets = sorted(base.get("processed_ciks", []))
    d["complete"] = False                    # 막음 ① · 끝까지 받았을 때만 아래에서 True
    d["failures"] = []                       # 이번 실행의 실패만 (다음 실행에서 다시 받음)
    fail_counts = d.setdefault("fail_counts", {})
    try:
        for i, cik in enumerate(targets, 1):
            if cik in processed:
                continue
            st["efts_calls"] += 1
            n_fail = len(d["failures"])
            try:
                ok = _one_company(get, cik, since, until, known, cik2tk, d, st, no_kw_set)
            except (FetchFailed, httpx.TransportError) as e:
                d["failures"].append({"cik": cik, "accession": "", "status": str(e)[:80]})
                ok = False
            if ok:
                processed.add(cik)
                d["processed_ciks"] = sorted(processed)
                fail_counts.pop(cik, None)
            elif len(d["failures"]) > n_fail:
                fail_counts[cik] = fail_counts.get(cik, 0) + 1
            if i % 10 == 0:
                save()
                LOG.info("진행 %d/%d · 사건 %d · 본문 %d · 실패 %d", i, len(targets), len(d["events"]), st["bodies"], len(d["failures"]))
    finally:
        d["no_kw_accessions"][key] = sorted(no_kw_set)
        _prune_no_kw(d)
        d.setdefault("period_stats", {})[key] = dict(st)
    d["complete"] = len(processed) >= len(targets) and not d["failures"]
    return d


def _one_company(get, cik, since, until, known, cik2tk, d, st, no_kw: set | None = None) -> bool:
    ok = True
    for h in efts_8k(get, cik, since, until):
            src = h.get("_source", {})
            acc = src.get("adsh", "")
            items = src.get("items", "") or ""
            if not acc or acc in known:
                continue
            if items and not any(it in items for it in WANTED_ITEMS):
                continue
            url = f"{ARCHIVES}/{int(cik)}/{acc.replace('-', '')}/{acc}.txt"
            try:
                r = get(url)
            except httpx.TransportError as e:
                d["failures"].append({"cik": cik, "accession": acc, "status": type(e).__name__})
                ok = False
                continue
            st["bodies"] += 1
            if r.status_code != 200:
                d["failures"].append({"cik": cik, "accession": acc, "status": f"HTTP {r.status_code}"})
                ok = False
                continue
            body = r.text[:MAX_BODY]
            known.add(acc)
            if not KW_RE.search(body):
                if no_kw is not None:
                    no_kw.add(acc)                     # 막음 ③ · 겹친 기간에서 다시 받지 않음
                continue
            st["kw_match"] += 1
            accept = parse_accept_dt(body)
            d_day, session = d_day_from_accept(accept) if accept else ("", "unknown")
            d["events"].append({
                "cik": cik, "ticker": cik2tk.get(cik, ""), "accession": acc,
                "file_date": src.get("file_date", ""), "accept_datetime_et": accept or "",
                "session_bucket": session, "d_day": d_day, "items": items,
                "direction": classify_direction(body),
                "matched_keywords": "|".join(extract_matched_keywords(body)),
                "merger_announcement": is_merger_announcement(items, body),   # 1114-05 · 합병 계약 체결 8-K 표지 (후보 단계가 이 표지로 거름)
            })
    return ok


def mark_merger(get, d: dict, save: Callable[[], None]) -> dict:
    """1114-05 · 표지(merger_announcement)가 없는 이벤트에 표지를 붙인다.

    항목에 1.01 이 없거나 2.02 가 같이 있으면 본문 없이 거짓 (규칙 앞 두 조건). 그 밖에 1.01 이 있으면 본문 1건을 받아 판정한다 (장부 범주 readout_increment).
    받지 못한 이벤트는 표지를 비워 둔다 = 판정 안 됨 = 거르지 않음 (거짓이 아님).
    """
    st = {"no_101": 0, "fetched": 0, "marked_true": 0, "failed": []}
    try:
        for e in d["events"]:
            if "merger_announcement" in e:
                continue
            raw_items = e.get("items") or ""
            its = {str(x).strip() for x in (raw_items if isinstance(raw_items, list) else str(raw_items).split(","))}   # EFTS 는 목록 · 이미 저장된 값은 문자열일 수도 있음
            if "1.01" not in its or "2.02" in its:       # 규칙의 앞 두 조건 (1.01 없음 · 2.02 동반) 은 본문 없이 거짓
                e["merger_announcement"] = False
                st["no_101"] += 1
                continue
            acc, cik = e["accession"], e["cik"]
            try:
                r = get(f"{ARCHIVES}/{int(cik)}/{acc.replace('-', '')}/{acc}.txt")
            except httpx.TransportError as ex:
                st["failed"].append({"accession": acc, "status": type(ex).__name__})
                continue
            if r.status_code != 200:
                st["failed"].append({"accession": acc, "status": f"HTTP {r.status_code}"})
                continue
            st["fetched"] += 1
            e["merger_announcement"] = is_merger_announcement(raw_items, r.text[:MAX_BODY])
            st["marked_true"] += int(e["merger_announcement"])
    finally:
        save()               # 상한 · 차단으로 멈춰도 지금까지 붙인 표지는 남김
    return st


# ─ 1112-08 · 서버 주간 작업 ──────────────────────────────────────────────────────

KST = timezone(timedelta(hours=9))


def et_yesterday(now: datetime) -> date:
    """미국 동부 기준 어제 (SEC 접수일 기준 · EFTS 는 접수일로 끊음)."""
    try:
        from zoneinfo import ZoneInfo
        et = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # 시간대 자료가 없으면 고정 -5시간 (22:00 KST 에는 UTC 날짜와 같은 날)
        et = now.astimezone(timezone(timedelta(hours=-5)))
    return et.date() - timedelta(days=1)


def kst_date(now: datetime) -> date:
    return now.astimezone(KST).date()


def plan_period(prev_since: str, prev_until: str, prev_complete: bool, yesterday_et: date) -> dict:
    """기간 순수 함수 (계획 3-1).

    - 앞 기간이 덜 끝났으면 같은 기간 이어 받기 (resume)
    - 끝났고 (미국 동부 어제 − 앞 until) ≥ 7일이면 새 기간 (since = 앞 until − 3일 · until = 미국 동부 어제)
    - 아니면 할 일 없음 (idle)
    """
    prev_u = date.fromisoformat(prev_until)
    if not prev_complete:
        return {"action": "resume", "since": prev_since, "until": prev_until}
    if (yesterday_et - prev_u).days >= NEW_PERIOD_DAYS:
        return {"action": "new", "since": (prev_u - timedelta(days=OVERLAP_DAYS)).isoformat(), "until": yesterday_et.isoformat()}
    return {"action": "idle", "since": prev_since, "until": prev_until}


# 알림 원인 코드 (텔레그램 warning · 같은 원인은 하루 1번 · 매수 · 매도 권유 문장 없음)
CAUSE_TEXT = {
    "http_403": "SEC 가 접근을 막았습니다 (403)",
    "http_429": "SEC 가 요청이 너무 많다고 답했습니다 (429)",
    "http_410": "SEC 가 해당 주소를 더 이상 제공하지 않는다고 답했습니다 (410)",
    "http_401": "SEC 가 인증 오류로 답했습니다 (401)",
    "halted": "403 또는 429 가 이틀 연속이라 결과 발표 보충을 자동으로 멈췄습니다 (사람이 다시 켜야 합니다)",
    "errors_2d": "SEC 서버 오류 또는 전송 오류가 이틀 연속 났습니다",
    "stale_open": "결과 발표 보충 기간이 열린 지 7일이 넘었는데 아직 끝나지 않았습니다",
    "stale_until": "결과 발표 보충의 마지막 날짜가 9일 넘게 갱신되지 않았습니다",
    "stale_run": "결과 발표 보충 작업이 3일 넘게 실행 기록을 남기지 않았습니다",
    "file_broken": "결과 발표 보충 파일을 읽지 못해 이번 실행을 건너뛰었습니다",
}


def default_notify(cause: str, lines: list[str]) -> None:
    """텔레그램 warning 1회 (biotech_going_concern.notify_warning 과 같은 방식 · 틀은 alert_text.biotech_message)."""
    import asyncio

    from backend.services import alert_text as at
    from backend.services.notifier import TelegramNotifier

    title, body = at.biotech_message("warning", f"결과 발표 보충 알림 · {cause}", [at.esc(x) for x in lines],
                                     next_spec="22:00")
    asyncio.run(TelegramNotifier().send_warning(category="biotech", title=title, body=body, dedupe_id=f"readout-weekly:{cause}"))


def send_alert_once(d: dict, cause: str, today: date, notify: Callable[[str, list[str]], None], detail: str = "") -> bool:
    """같은 원인은 KST 하루에 한 번만 보낸다 (기록은 d["alerts_sent"] · 파일에 저장). 보냈으면 True."""
    sent = d.setdefault("alerts_sent", {})
    if sent.get(cause) == today.isoformat():
        return False
    lines = [f"원인: {CAUSE_TEXT.get(cause, cause)} [{cause}]"]
    if detail:
        lines.append(f"내용: {detail}")
    lines.append("자료 수집 상태 알림이며 종목 판단과는 관계가 없습니다.")
    try:
        notify(cause, lines)
    except Exception as e:  # 알림 실패가 수집을 막지 않음
        LOG.warning("알림 실패 · %s · %s", cause, e.__class__.__name__)
        return False
    sent[cause] = today.isoformat()
    return True


def _record_day(d: dict, field: str, today: date) -> bool:
    """오늘을 기록하고 어제도 있었으면 True (이틀 연속)."""
    days = sorted(set(d.get(field, [])) | {today.isoformat()})
    d[field] = days[-14:]
    return (today - timedelta(days=1)).isoformat() in days


class WeeklyLock:
    """같은 스크립트 겹쳐 실행 금지 (파일 잠금 · 못 잡으면 acquired=False)."""

    def __init__(self, path: Path):
        self.path, self.fh, self.acquired = path, None, False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
        except OSError:
            self.acquired = False
        return self

    def __exit__(self, *exc):
        if self.fh is not None:
            if self.acquired:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def _read_docs(docs_path: Path | None) -> dict:
    if docs_path is None or not docs_path.exists():
        return {}
    try:
        return json.loads(docs_path.read_text())
    except Exception:
        return {}


def _load_state(path: Path, docs_path: Path | None) -> dict:
    """RUNTIME 본이 있으면 그것 · 없으면 docs 본의 기간 (첫 서버 실행 · 11/12 기준) 에서 사건 없이 시작 (끝난 기간으로 본다)."""
    if path.exists():
        return json.loads(path.read_text())
    dd = _read_docs(docs_path)
    d = _fresh(dd.get("since", ""), dd.get("until", ""))
    d["complete"] = True
    return d


def weekly_run(now: datetime, path: Path, docs_path: Path | None, base: dict, ledger: SecDailyLedger,
               make_get: Callable[[], Callable], notify: Callable[[str, list[str]], None],
               sec_tickers: dict | None = None, cap: int = SEC_DAILY_CAP, clear_halt: bool = False) -> int:
    """매일 22:00 실행 한 번 · 종료 코드 0 정상 · 2 차단 · 3 상한/날짜 넘김 · 4 일부 실패 · 5 멈춤 상태 · 6 파일 깨짐."""
    today = kst_date(now)
    try:
        d = _load_state(path, docs_path)
    except Exception as e:
        LOG.error("RUNTIME 본 읽기 실패 · 덮어쓰지 않고 건너뜀 · %s", e.__class__.__name__)
        send_alert_once({}, "file_broken", today, notify, e.__class__.__name__)
        return EXIT_BROKEN
    d["last_run_at"] = now.astimezone(KST).isoformat(timespec="seconds")      # 막음 ② · 할 일이 없어도 쓴다
    if clear_halt:
        d.pop("halted", None)
        d["block_days"] = []
        LOG.info("자동 멈춤을 풀었습니다 (사람이 다시 켬)")
    if d.get("halted"):
        send_alert_once(d, "halted", today, notify, f"멈춘 날 {d['halted']}")
        save_out(path, d)
        LOG.warning("자동 실행 멈춤 상태 · 요청 0 · --clear-halt 로 다시 켬")
        return EXIT_HALTED
    if not d.get("until"):
        save_out(path, d)
        LOG.error("기준 기간이 없습니다 (docs 본 · RUNTIME 본 모두 없음) · 요청 0")
        return EXIT_BROKEN
    plan = plan_period(d["since"], d["until"], bool(d.get("complete", False)), et_yesterday(now))
    if plan["action"] == "idle":
        save_out(path, d)
        LOG.info("할 일 없음 · 기간 %s~%s 끝남 · 마지막 실행 기록만 남김", plan["since"], plan["until"])
        return EXIT_OK
    if plan["action"] == "new":
        _rollover(d, plan["since"], plan["until"])
        d["opened_at"] = today.isoformat()
    d["complete"] = False                      # 막음 ① · 시작 때 먼저 저장 · 끝까지 받았을 때만 run 이 True
    d.setdefault("opened_at", today.isoformat())
    save_out(path, d)
    since, until = d["since"], d["until"]
    if ledger.total() + 1 > cap:
        LOG.warning("하루 상한 · 장부 합계 %d + 1 > %d · 요청 0 · 내일 이어 받음", ledger.total(), cap)
        return EXIT_CAP
    get = make_get()
    code = EXIT_OK
    try:
        run(get, base, d, since, until, lambda: save_out(path, d),
            extra_known=[e.get("accession") for e in _read_docs(docs_path).get("events", [])], sec_tickers=sec_tickers)
    except CapReached as e:
        LOG.warning("하루 상한 또는 날짜 넘김 · %s · 저장 후 멈춤 (다음 날 이어 받음)", e)
        code = EXIT_CAP
    except SecBlockedError as e:
        LOG.error("즉시 중단 · %s · 저장 후 멈춤", e)
        code = EXIT_BLOCKED
    finally:
        save_out(path, d)                      # 예상 못 한 오류로 멈춰도 지금까지 받은 것은 남김
    sc = getattr(get, "status_counts", Counter())
    for status in (403, 429, 410, 401):
        if sc.get(status):
            send_alert_once(d, f"http_{status}", today, notify, f"HTTP {status} · {sc[status]}번")
    if sc.get(403) or sc.get(429):
        if _record_day(d, "block_days", today):            # 이틀 연속 403 · 429 → 자동 실행 멈춤
            d["halted"] = today.isoformat()
            send_alert_once(d, "halted", today, notify, f"멈춘 날 {d['halted']}")
    server_err = any(k >= 500 and v for k, v in sc.items()) or any(
        "HTTP 5" in f.get("status", "") or "Error" in f.get("status", "") or "Timeout" in f.get("status", "")
        for f in d.get("failures", []))
    if server_err and _record_day(d, "err_days", today):
        send_alert_once(d, "errors_2d", today, notify, f"실패 {len(d.get('failures', []))}건")
    total, done = len(base.get("processed_ciks", [])), len(d.get("processed_ciks", []))
    opened = date.fromisoformat(d["opened_at"])
    if not d.get("complete") and (today - opened).days >= OPEN_ALERT_DAYS:
        persistent = {c for c, n in d.get("fail_counts", {}).items() if n >= PERSISTENT_FAIL_RUNS}
        remaining = set(base.get("processed_ciks", [])) - set(d.get("processed_ciks", []))
        if remaining and remaining <= persistent and code == EXIT_OK:
            d.update({"complete": True, "closed_incomplete": True, "abandoned_ciks": sorted(remaining)})   # 계획 3-9
            detail = f"처리 {done}/{total} · 계속 오류 회사 {len(remaining)}곳을 빼고 기간을 닫았습니다"
        else:
            why = {EXIT_CAP: "하루 상한으로 멈춤", EXIT_BLOCKED: "SEC 차단"}.get(code, f"실패 {len(d.get('failures', []))}건")
            detail = f"처리 {done}/{total} · 까닭 {why}"
        send_alert_once(d, "stale_open", today, notify, detail)
    save_out(path, d)
    LOG.info("요약 · 기간 %s~%s · 처리 %d/%d · 사건 %d · 본문 %d · 장부 %s=%d (합계 %d) · 끝남 %s · 실패 %d",
             since, until, done, total, len(d["events"]), d["stats"]["bodies"], LEDGER_CAT,
             ledger.counts.get(LEDGER_CAT, 0), ledger.total(), d.get("complete", False), len(d.get("failures", [])))
    if code == EXIT_OK and d.get("failures"):
        code = EXIT_FAILURES
    return code


def check_stale(now: datetime, path: Path, docs_path: Path | None, notify: Callable[[str, list[str]], None]) -> int:
    """요청 0 · until 이 9일 넘게 옛것이거나 마지막 실행 기록이 3일 넘게 멈췄으면 알림 (원인별 하루 1번).

    RUNTIME 본이 아직 없으면 지금 시각을 첫 확인 시각으로 적은 본을 만들어 둔다 (22:00 줄이 한 번도 안 돌아도 3일 뒤 알림이 나가게).
    """
    today = kst_date(now)
    try:
        d = _load_state(path, docs_path)
    except Exception as e:
        send_alert_once({}, "file_broken", today, notify, e.__class__.__name__)
        return EXIT_BROKEN
    if not path.exists():
        d["first_seen_at"] = now.astimezone(KST).isoformat(timespec="seconds")
    until = d.get("until", "")
    last = d.get("last_run_at") or d.get("first_seen_at") or ""
    hit = []
    if until and (today - date.fromisoformat(until)).days > STALE_UNTIL_DAYS:
        send_alert_once(d, "stale_until", today, notify, f"마지막 날짜 {until}")
        hit.append("until")
    if last:
        last_d = datetime.fromisoformat(last).astimezone(KST).date()
        if (today - last_d).days > STALE_RUN_DAYS:
            send_alert_once(d, "stale_run", today, notify, f"마지막 실행 기록 {last_d.isoformat()}")
            hit.append("run")
    if d.get("until"):
        save_out(path, d)
    LOG.info("오래됨 점검 · until %s · 마지막 실행 %s · 알림 %s", until or "-", last or "-", ",".join(hit) or "없음")
    return EXIT_OK


def weekly_main(a) -> int:
    runtime = _P.RUNTIME_DIR
    if runtime is None:
        LOG.error("BIOTECH_RUNTIME_DIR 가 없습니다 · 서버 전용 모드라 docs 본을 건드리지 않도록 멈춥니다")
        return EXIT_HALTED
    path = runtime / OUT_NAME
    docs_path = _P.DATA_DIR_DOCS / OUT_NAME
    now = datetime.now(timezone.utc)
    if a.check_stale:
        return check_stale(now, path, docs_path, default_notify)
    with WeeklyLock(runtime / LOCK_NAME) as lock:
        if not lock.acquired:
            LOG.warning("다른 보충 작업이 실행 중 · 이번 실행은 건너뜀")
            return EXIT_OK
        base = load_base()
        ledger = SecDailyLedger.load()
        sec_p = _P.find("sec_company_tickers.json")
        with build_client(timeout=30.0) as client:
            return weekly_run(now, path, docs_path, base, ledger,
                              lambda: make_getter(client, ledger, a.cap, today_fn=_P.today_kst_str),
                              default_notify, sec_tickers=sec_ticker_map(sec_p), cap=a.cap, clear_halt=a.clear_halt)


def main(argv: list[str] | None = None) -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--weekly", action="store_true", help="1112-08 · 서버 매일 22:00 · 기간을 스스로 정해 이어 받음 (RUNTIME 본에만 씀)")
    ap.add_argument("--check-stale", action="store_true", help="1112-08 · 요청 0 · 오래됨 점검 (07:00 파이프)")
    ap.add_argument("--clear-halt", action="store_true", help="1112-08 · 이틀 연속 403/429 로 멈춘 자동 실행을 사람이 다시 켬")
    ap.add_argument("--cap", type=int, default=SEC_DAILY_CAP)
    ap.add_argument("--mark-merger", action="store_true",
                    help="1114-05 · 새 사건 받기 대신 · 이미 있는 이벤트에 합병 계약 체결 표지를 붙임 (1.01 이 든 이벤트만 본문 1건)")
    a = ap.parse_args(argv)
    if a.weekly or a.check_stale:
        return weekly_main(a)
    if not (a.since and a.until):
        ap.error("--since · --until 이 필요합니다 (--weekly · --check-stale 이 아니면)")
    base = load_base()
    path = out_path()
    if a.mark_merger:
        d = json.loads(path.read_text())
        ledger = SecDailyLedger.load()
        try:
            with build_client(timeout=30.0) as client:
                st = mark_merger(make_getter(client, ledger, a.cap), d, lambda: save_out(path, d))
        except CapReached as e:
            LOG.warning("하루 상한 · %s · 지금까지 붙인 표지만 저장", e)
            return 3
        except SecBlockedError as e:
            LOG.error("즉시 중단 · %s · 지금까지 붙인 표지만 저장", e)
            return 2
        LOG.info("표지 · 1.01 없음 %d · 본문 받음 %d · 체결 표지 참 %d · 실패 %d · 장부 합계 %d",
                 st["no_101"], st["fetched"], st["marked_true"], len(st["failed"]), ledger.total())
        return 4 if st["failed"] else 0
    d = load_out(path, a.since, a.until)
    ledger = SecDailyLedger.load()
    code = 0
    with build_client(timeout=30.0) as client:
        get = make_getter(client, ledger, a.cap)
        try:
            run(get, base, d, a.since, a.until, lambda: save_out(path, d))
        except CapReached as e:
            LOG.warning("하루 상한 · %s · 저장 후 멈춤 (다음 날 같은 명령으로 이어 받음)", e)
            code = 3
        except SecBlockedError as e:
            LOG.error("즉시 중단 · %s · 저장 후 멈춤", e)
            code = 2
        finally:
            save_out(path, d)
    LOG.info("요약 · 기간 %s~%s · 처리 회사 %d/%d · 사건 %d · 본문 %d · 장부 %s=%d (합계 %d) · 끝남 %s",
             a.since, a.until, len(d["processed_ciks"]), len(base.get("processed_ciks", [])),
             len(d["events"]), d["stats"]["bodies"], LEDGER_CAT, ledger.counts.get(LEDGER_CAT, 0),
             ledger.total(), d.get("complete", False))
    if d.get("failures"):
        LOG.warning("실패 %d 건 · 다음 실행에서 다시 받음 · %s", len(d["failures"]), d["failures"][:5])
        code = code or 4
    return code


if __name__ == "__main__":
    sys.exit(main())
