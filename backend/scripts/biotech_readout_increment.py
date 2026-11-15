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

사용 (로컬 · 저장소 맨 위에서): backend/venv/bin/python -m backend.scripts.biotech_readout_increment --since 2026-09-02 --until 2026-11-12
  (-I 를 붙이면 현재 폴더가 import 경로에서 빠져 backend 를 못 찾는다)
- 200 이 아닌 응답 · 전송 예외는 그 회사를 처리 목록에 넣지 않고 failures 에 적는다 (다음 실행에서 다시 받음) · 저장은 늘 함
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import json
import logging
import sys
import time

import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from backend.scripts import _biotech_paths as _P
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


class CapReached(RuntimeError):
    pass


def out_path() -> Path:
    """서버 (RUNTIME) 면 RUNTIME 아래 · 로컬이면 docs/plans/biotech/data (커밋 이식 · 9/20 α 와 같은 길)."""
    return (_P.RUNTIME_DIR / OUT_NAME) if _P.RUNTIME_DIR is not None else (_P.DATA_DIR_DOCS / OUT_NAME)


def load_base() -> dict:
    p = _P.find(BASE_NAME)
    if p is None:
        raise FileNotFoundError(BASE_NAME)
    return json.loads(p.read_text())


def load_out(path: Path, since: str, until: str) -> dict:
    if path.exists():
        d = json.loads(path.read_text())
        if d.get("since") == since and d.get("until") == until:
            return d
        if d.get("events"):
            # 기간이 바뀌면 앞 사건은 남기고 처리 회사만 새로 시작
            d.update({"since": since, "until": until, "processed_ciks": []})
            return d
    return {"since": since, "until": until, "processed_ciks": [], "events": [],
            "stats": {"efts_calls": 0, "bodies": 0, "kw_match": 0}}


def save_out(path: Path, d: dict) -> None:
    d["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    tmp.replace(path)


def make_getter(client, ledger: SecDailyLedger, cap: int, sleep: Callable[[float], None] = time.sleep):
    """보내기 직전 장부 셈 · 상한이면 CapReached · 403/429 면 SecBlockedError."""
    def get(url: str, params: dict | None = None):
        if ledger.total() >= cap:
            raise CapReached(f"장부 합계 {ledger.total()} ≥ 상한 {cap}")
        ledger.add(LEDGER_CAT)
        ledger.save()
        sleep(REQ_INTERVAL)
        r = client.get(url, params=params)
        if r.status_code in (403, 429):
            raise SecBlockedError(f"SEC HTTP {r.status_code} · {url[:60]}")
        return r
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


def run(get, base: dict, d: dict, since: str, until: str, save: Callable[[], None]) -> dict:
    cik2tk = {}
    for e in base.get("events", []):
        if e.get("ticker"):
            cik2tk[e["cik"]] = e["ticker"]
    known = {e.get("accession") for e in base.get("events", [])} | {e.get("accession") for e in d["events"]}
    processed = set(d["processed_ciks"])
    st = d["stats"]
    targets = sorted(base.get("processed_ciks", []))
    d["failures"] = []                       # 이번 실행의 실패만 (다음 실행에서 다시 받음)
    for i, cik in enumerate(targets, 1):
        if cik in processed:
            continue
        st["efts_calls"] += 1
        try:
            ok = _one_company(get, cik, since, until, known, cik2tk, d, st)
        except (FetchFailed, httpx.TransportError) as e:
            d["failures"].append({"cik": cik, "accession": "", "status": str(e)[:80]})
            ok = False
        if ok:
            processed.add(cik)
            d["processed_ciks"] = sorted(processed)
        if i % 10 == 0:
            save()
            LOG.info("진행 %d/%d · 사건 %d · 본문 %d · 실패 %d", i, len(targets), len(d["events"]), st["bodies"], len(d["failures"]))
    d["complete"] = len(processed) >= len(targets) and not d["failures"]
    return d


def _one_company(get, cik, since, until, known, cik2tk, d, st) -> bool:
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
            })
    return ok


def main(argv: list[str] | None = None) -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--cap", type=int, default=SEC_DAILY_CAP)
    a = ap.parse_args(argv)
    base = load_base()
    path = out_path()
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
