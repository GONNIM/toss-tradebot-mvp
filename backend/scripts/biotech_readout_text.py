"""P4-4 · 새 8-K 본문 단계 (봉인 설계 fr6c_design_v1.md 2.2절 · 8절 · 11절 2).

submissions 단계가 찾은 후보 회사의 새 8-K 마다 본문 1건을 받아 WP39 검색어 · 방향 규칙으로 "후보 방향" 을 붙인다.
- 요청: 8-K 제출 전체 텍스트 1건 (`{accession}.txt` · EX-99 보도자료 포함) · WP39 가 규칙을 적용한 입력과 같다
  (`biotech_h39_readouts.fetch_txt_cached`). 헤더 = biotech_sec_common.build_client 단일 상수 · 장부 범주 "readout_text".
- 하루 상한 10 · 남은 8-K 는 다음 날로 미룸 · 접수 시각이 가장 늦은 것부터 · 접수 뒤 30일이 지나도록 못 받으면
  "본문 미수신" 으로 남기고 더 요청하지 않음 (설계 8절 117행) · 403 · 429 즉시 중단 · 하루 300 상한에 닿으면 멈춤.
- 규칙: `biotech_h39_readouts` 의 KW_RE · classify_direction · extract_matched_keywords 를 그대로 import (사전 변경 없음).
  WP39 와 같이 항목 2.02 · 7.01 · 8.01 이 없는 8-K 는 검색어 대상이 아니다 (태그만 "항목 대상 아님" · 본문은 받음).
- 확정은 사용자다 (FR-6b 카드 · /api/v1/biotech/fr6c/confirm). 이 단계는 후보 방향만 저장한다.
저장: <RUNTIME>/fr6c/readout_text.json (접수번호 → 상태 · 후보 방향 · 검색어 · 인용).
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_atm_cover import plain
from backend.scripts.biotech_h39_readouts import KW_RE, classify_direction, extract_matched_keywords
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecBlockedError, SecDailyLedger

LOG = logging.getLogger("biotech_readout_text")

LEDGER_CAT = "readout_text"
DAILY_MAX = 10
EXPIRE_DAYS = 30
START_ET = "2026-10-22"            # 전향 표본 시작 (P4-4 배포일 · 미국 동부 접수일 기준 · 설계 2.2절 33행)
WP39_ITEMS = ("2.02", "7.01", "8.01")
MAX_CHARS = 5_000_000              # WP39 fetch_txt_cached 와 같은 크기 제한
QUOTE = 60
TXT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{accn}.txt"
RECEIVED, NOT_RECEIVED, ERROR = "수신", "본문 미수신", "오류"
NO_ITEM, NO_KW = "항목 대상 아님", "검색어 없음"


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def store_path() -> Path:
    return _P.out_dir("fr6c") / "readout_text.json"


def load_store() -> dict[str, dict]:
    p = store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("rows", {})
    except (ValueError, OSError):
        LOG.warning("8-K 본문 파일 읽기 실패 · %s", p)
        return {}


def save_store(rows: dict[str, dict], today: date) -> None:
    store_path().write_text(json.dumps({"updated": today.isoformat(), "rule": {"keywords": KW_RE.pattern, "items": WP39_ITEMS},
                                        "rows": dict(sorted(rows.items()))}, ensure_ascii=False, indent=1))


def txt_url(cik: str, accn: str) -> str:
    return TXT_URL.format(cik=int(cik), nodash=accn.replace("-", ""), accn=accn)


def new_8ks(raw: dict[str, dict], to_et: Callable[[str], str | None]) -> list[dict]:
    """submissions 원본 (CIK → 회사 · filings) → 전향 시작일 이후 8-K (접수 시각 늦은 순)."""
    out = []
    for cik, c in raw.items():
        for f in c.get("filings") or []:
            if f.get("form") != "8-K" or not f.get("acceptanceDateTime"):
                continue
            et = to_et(f["acceptanceDateTime"]) or ""
            if et[:10] >= START_ET:
                out.append({"cik": cik, "ticker": c.get("ticker") or "", "accessionNumber": f["accessionNumber"],
                            "accept_et": et, "items": f.get("items") or "", "filingDate": f.get("filingDate") or ""})
    return sorted(out, key=lambda x: (x["accept_et"], x["accessionNumber"]), reverse=True)


def tag(text: str, items: str) -> dict:
    """WP39 규칙 그대로 · 원문 전체 (최대 5MB) 에 검색어 · 방향 · 인용은 글자만 뽑은 본문에서."""
    body = text[:MAX_CHARS]
    has_item = (not items) or any(it in items for it in WP39_ITEMS)   # WP39: items 가 비면 거르지 않음
    kw = extract_matched_keywords(body)
    if not has_item:
        cand = NO_ITEM
    elif not KW_RE.search(body):
        cand = NO_KW
    else:
        cand = classify_direction(body)
    flat = plain(body[:400_000])
    m = KW_RE.search(flat)
    return {"candidate_direction": cand, "keywords": kw, "has_ex99": bool(re.search(r"<TYPE>EX-99", body, re.I)),
            "quote": flat[max(0, m.start() - QUOTE):m.end() + QUOTE] if m else None}


def run_daily(raw: dict[str, dict], today: date, get_text: Callable[[str], dict] | None, ledger: SecDailyLedger,
              to_et: Callable[[str], str | None]) -> dict:
    """새 8-K 본문 · 하루 상한 10 · 최신 우선 · 30일 지나면 본문 미수신."""
    store = load_store()
    pending = [k for k in new_8ks(raw, to_et) if k["accessionNumber"] not in store
               or store[k["accessionNumber"]].get("status") == ERROR]
    expired = 0
    lo = (today - timedelta(days=EXPIRE_DAYS)).isoformat()
    todo = []
    for k in pending:
        if k["accept_et"][:10] < lo:
            store[k["accessionNumber"]] = {**k, "status": NOT_RECEIVED, "marked_on": today.isoformat()}
            expired += 1
        else:
            todo.append(k)
    sent, blocked, capped, received = 0, None, 0, 0
    if get_text is not None:
        for k in todo:
            if sent >= DAILY_MAX:
                break
            if ledger.total() >= SEC_DAILY_CAP:
                capped = len(todo) - sent
                break
            ledger.add(LEDGER_CAT)                # 보내기 직전에 셈
            ledger.save()
            sent += 1
            try:
                r = get_text(txt_url(k["cik"], k["accessionNumber"]))
            except SecBlockedError as e:
                blocked = str(e)
                break
            if r.get("status") == 429:
                blocked = "SEC HTTP 429"
                break
            if r.get("status") != 200 or not r.get("text"):
                store[k["accessionNumber"]] = {**k, "status": ERROR, "http": r.get("status"), "tried_on": today.isoformat()}
                continue
            store[k["accessionNumber"]] = {**k, "status": RECEIVED, **tag(r["text"], k["items"]),
                                           "fetched_on": today.isoformat()}
            received += 1
    if blocked:
        LOG.error("%s · 8-K 본문 즉시 중단 (보낸 요청 %d)", blocked, sent)
    if todo or expired:
        save_store(store, today)
    left = max(0, len(todo) - sent)
    LOG.info("8-K 본문 · 새 8-K %d · 요청 %d · 수신 %d · 미룸 %d · 본문 미수신 처리 %d · 중단 %s",
             len(pending), sent, received, left, expired, blocked)
    return {"new": len(pending), "sent": sent, "received": received, "deferred": left, "expired": expired,
            "blocked": blocked, "capped": capped}
