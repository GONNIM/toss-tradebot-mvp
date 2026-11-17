"""1114-06 ㉧① · 계속기업 판정 규칙 표본 받기 (로컬 전용 · 최대 30건 · 표본 문장만 저장 · 본문 전체는 저장하지 않음).

실행 조건 (biotech_atm_cover.ledger_gate 와 같은 방식 · 요일 대신 실측):
  서버 장부 오늘 합계(--server-total · 사용자가 서버 장부를 읽어 넣음) + 로컬 장부 오늘 합계 + 예정 건수 ≤ 300 일 때만 실행한다.
  --server-total 이 없으면 실행하지 않는다 (필수 인자). 로컬 장부를 읽지 못해도 실행하지 않는다.
요청: 본문 파일 1건씩 · 헤더 = build_client 단일 상수 · 장부 범주 "going_concern_sample"(로컬 장부) · 보내기 직전에 더함 · 403 · 429 · 401 즉시 중단.
저장: <RUNTIME 또는 backend/data/biotech>/filings/going_concern_samples.json · 회사마다 현재 규칙의 판정 + 창별 분류 + 표본 문장(300자 이하).
  20-F 는 판정하지 않고 「going concern」 · 「material uncertainty」 앞뒤 문장만 모은다 (IFRS 문구 확인용).
규칙을 이 결과로 조정하는 일은 따로 맡긴다 (이 스크립트는 규칙을 바꾸지 않는다).

실행 (사용자가 서버 장부를 확인한 뒤 · 로컬):
    python -m backend.scripts.biotech_going_concern_sample --server-total <서버 장부 오늘 합계> [--submissions <submissions_YYYYMMDD.json>]
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import httpx

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_going_concern as gc
from backend.scripts.biotech_atm_cover import ledger_gate, read_local_ledger_total
from backend.scripts.biotech_listing_status import filing_url
from backend.scripts.biotech_sec_common import SecBlockedError, SecDailyLedger, build_client, sec_get_text

LOG = logging.getLogger("biotech_going_concern_sample")

MAX_SAMPLES = 30
FOREIGN_WANTED = 3                      # IFRS 확인용 20-F 최소 건수 (있으면)
LEDGER_CAT = "going_concern_sample"
OUT_NAME = "going_concern_samples.json"
_IFRS = re.compile(r"going concern|material uncertaint\w*", re.I)
SNIP = 150


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def pick_targets(raw: dict[str, dict], limit: int) -> list[dict]:
    """submissions 원본 → 표본 대상 · 20-F 최대 3 먼저 · 나머지는 10-K · 10-Q 를 CIK 순으로 고르게 건너뛰며 (한쪽에 쏠리지 않게)."""
    foreign, domestic = [], []
    for cik, c in sorted(raw.items()):
        r = gc.pick_report(c.get("filings") or [])
        if not r or not r.get("primaryDocument"):
            continue
        item = {"cik": cik, "form": r["form"], "filingDate": r["filingDate"], "accession": r["accessionNumber"],
                "primary": r["primaryDocument"]}
        (foreign if r["form"] in gc.FOREIGN_FORMS else domestic).append(item)
    f = foreign[:min(FOREIGN_WANTED, limit)]
    need = limit - len(f)
    if need <= 0 or not domestic:
        return f[:limit]
    step = max(1, len(domestic) // need)
    return (f + domestic[::step][:need])[:limit]


def sample_of(text: str, form: str, filing: date) -> dict:
    """본문 → 표본 요약 (본문 전체는 돌려주지 않음)."""
    norm = gc.plain_text(text)
    if form in gc.FOREIGN_FORMS:
        snips = []
        for m in _IFRS.finditer(norm):
            snips.append(norm[max(0, m.start() - SNIP):m.end() + SNIP][:gc.QUOTE_MAX])
            if len(snips) >= 6:
                break
        return {"rule_state": "not_judged_20f", "chars": len(norm), "snippets": snips}
    j = gc.judge_report(text, form, filing)
    c = gc.classify_text(norm, filing)
    return {"rule_state": j["state"], "reason": j["reason"], "flags": j["flags"], "chars": j["chars"],
            "windows": [{"kind": k, "quote": q[:gc.QUOTE_MAX]} for k, q in c["details"][:8]]}


def run_sample(raw: dict[str, dict], today: date, get_text: Callable[[str], dict], server_total: int | None,
               out: Path | None = None, limit: int = MAX_SAMPLES, ledger: SecDailyLedger | None = None,
               local_total: int | None = None) -> dict:
    """게이트 통과 시에만 요청 · 못 통과하면 요청 0 으로 SystemExit."""
    if limit > MAX_SAMPLES:
        raise SystemExit(f"표본 상한 {MAX_SAMPLES}건 초과 요청 {limit} · 실행하지 않음")
    day = f"{today:%Y%m%d}"
    targets = pick_targets(raw, limit)
    local = read_local_ledger_total(day) if local_total is None else local_total
    ok, why = ledger_gate(server_total, local, len(targets))
    LOG.info("SEC 장부 조건 · %s", why)
    if not ok:
        raise SystemExit(f"SEC 장부 조건 불충족 · {why}")
    ledger = ledger or SecDailyLedger.load(day)
    rows, sent, blocked = {}, 0, None
    for t in targets:
        ledger.add(LEDGER_CAT)                                   # 보내기 직전에 셈
        ledger.save()
        sent += 1
        url = filing_url(t["cik"], t["accession"], t["primary"])
        try:
            r = get_text(url)
        except SecBlockedError as e:
            blocked = str(e)
            break
        except (httpx.HTTPError, TimeoutError, OSError) as e:
            rows[t["accession"]] = {**t, "error": e.__class__.__name__}
            continue
        if r.get("status") in (401, 403, 429):
            blocked = f"SEC HTTP {r.get('status')}"
            break
        if r.get("status") != 200 or not r.get("text"):
            rows[t["accession"]] = {**t, "http": r.get("status")}
            continue
        rows[t["accession"]] = {**t, "url": url, **sample_of(r["text"], t["form"], date.fromisoformat(t["filingDate"]))}
    if blocked:
        LOG.error("%s · 표본 받기 즉시 중단 (보낸 요청 %d)", blocked, sent)
    out = out or (_P.out_dir("filings") / OUT_NAME)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"date": today.isoformat(), "rule_version": gc.RULE_VERSION, "gate": why, "sent": sent, "blocked": blocked,
                               "rows": rows}, ensure_ascii=False, indent=1))
    return {"sent": sent, "blocked": blocked, "saved": len(rows), "gate": why, "out": str(out)}


def _latest_local_submissions() -> Path | None:
    return _P.find_glob("submissions_2*.json", subdir="filings")


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-total", type=int, required=True, help="서버 장부 오늘 합계 (사용자가 서버 장부를 읽어 넣음)")
    ap.add_argument("--submissions", default=None, help="로컬 submissions_<날짜>.json (기본: 최신)")
    ap.add_argument("--limit", type=int, default=MAX_SAMPLES)
    a = ap.parse_args()
    p = Path(a.submissions) if a.submissions else _latest_local_submissions()
    if p is None or not p.exists():
        raise SystemExit("로컬 submissions 파일이 없습니다 · 실행하지 않음")
    raw = json.loads(p.read_text()).get("companies_raw") or {}
    with build_client() as client:
        res = run_sample(raw, _kst_today(), lambda u: sec_get_text(client, u, timeout=gc.READ_TIMEOUT), a.server_total, limit=a.limit)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
