"""WP95 · 레이더 전문가 채널 입력 주간 복구 (서버 · 런타임 폴더 산출).

단계 (서버 crontab · biotech_h48v3_daily_server.sh 의 주간 모드):
  13d  (화 06:00): 활동가 등록부 55곳 SEC submissions 1회씩 (55회) + 새 13D/13G 신고서 헤더 1회씩 (대상 회사 확인)
       · b98 산출 (docs/plans/biotech/data/h3_seed_events_b98.csv) 과 지난 주 산출 · h65 Form 4 매수 를 합침
       → <RUNTIME>/h3_events_weekly.csv (레이더가 h3_events_*.csv 로 읽음 · target_cik 별 건수)
       · 헤더 = biotech_sec_common.build_client() · 403·429 즉시 중단 · 하루 SEC 장부 "h3_events"
  nlm  (수 06:00): 후보마다 PubMed · Preprint (NLM esearch) 올해·작년 2개 연도 · 초당 3회 이하 · 403·429 즉시 중단
       → <RUNTIME>/h57_pubmed_index_weekly.json · h58_preprint_index_weekly.json (레이더 입력 형식 그대로)
       · 캐시 <RUNTIME>/nlm_cache.json · 결과 0 도 캐시 · 작년 값은 다시 받지 않음 · 올해 값만 매주 갱신

로직 출처: backend/scripts/biotech_h3_events_b98.py (13D/13G 신규 · /A 제외 · 5년 창) ·
          backend/scripts/biotech_h57_pubmed_index.py · biotech_h58_preprint_index.py (검색식 · 회사명 정규화)
b98 와 같은 범위 (활동가 13D/13G + 펀드 Form 4 매수) · 차이: 2024-12 이후 양식 이름 SCHEDULE 13D/13G 도 셈
  (b98 은 SC 13D/13G 만 찾아 2024-12-06 이후 기록이 없었음) · 후보 회사 기준 세기는 쓰지 않음 (수동 13G 잡음 · 2026-10-01 시험 994건 중 915건 13G).
실패해도 주간 잡은 계속 (종료 코드 0) · 텔레그램 warning 1회.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from backend.scripts import _biotech_paths as _P

LOG = logging.getLogger("biotech_radar_inputs_weekly")

NEW_FORMS = {"SC 13D": "13D_new", "SC 13G": "13G_new", "SCHEDULE 13D": "13D_new", "SCHEDULE 13G": "13G_new"}
WINDOW_YEARS = 5
NLM_INTERVAL = 0.34          # 초당 3회 이하
EVENTS_OUT = "h3_events_weekly.csv"
PUBMED_OUT = "h57_pubmed_index_weekly.json"
PREPRINT_OUT = "h58_preprint_index_weekly.json"
NLM_CACHE = "nlm_cache.json"
EVENT_FIELDS = ["event_id", "target_cik", "target_name", "event_type", "event_date", "accession", "institution", "filer_cik"]


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def load_candidates() -> list[dict]:
    """최신 후보 CSV · CIK 있는 행만 (ticker 없는 행도 CIK 로 셈)."""
    p = _P.find_glob("biotech_candidates_2*.csv", subdir="candidates") or _P.find_glob("biotech_candidates_2*.csv")
    if p is None:
        return []
    with p.open() as f:
        return [{"ticker": r.get("ticker", ""), "cik": (r.get("cik") or "").zfill(10), "name": r.get("name", "")}
                for r in csv.DictReader(f) if (r.get("cik") or "").strip()]


def _notify_warning(title: str, body: str) -> None:
    try:
        import asyncio
        from backend.services.notifier import TelegramNotifier
        asyncio.run(TelegramNotifier().send_warning(title=title, body=body))
    except Exception as e:  # noqa: BLE001
        LOG.warning("notifier 실패 · %s", e.__class__.__name__)


# ── 13D / 13G (b98 방식 · 활동가 등록부 기준) ─────────────────────

REGISTRY = "h3_activist_cik_registry_v2.csv"   # docs/plans/biotech/data · 활동가 55곳 (b98 입력 이식)
SEED = "h3_seed_events_b98.csv"                 # docs/plans/biotech/data · b98 산출 (2026-09-14 · 13D/13G 346 + Form 4 984) · 재요청 방지


def load_registry() -> list[dict]:
    p = _P.find(REGISTRY)
    if p is None:
        return []
    with p.open() as f:
        return [{"cik": r["cik"].zfill(10), "institution": r.get("institution", "")} for r in csv.DictReader(f)]


def _read_events(p: Path | None) -> list[dict]:
    if p is None or not p.exists():
        return []
    with p.open() as f:
        return [{k: r.get(k, "") for k in EVENT_FIELDS} for r in csv.DictReader(f)]


def new_13dg_filings(submissions: dict, today: date) -> list[dict]:
    """신고자 (활동가) submissions (recent) → 최근 5년 신규 13D/13G (/A 제외 · 2024-12 이후 SCHEDULE 13D/G 포함)."""
    rec = (submissions.get("filings", {}) or {}).get("recent", {}) or {}
    since = today.replace(year=today.year - WINDOW_YEARS).isoformat()
    return [{"form": f, "date": d, "accession": a}
            for f, d, a in zip(rec.get("form", []), rec.get("filingDate", []), rec.get("accessionNumber", []))
            if f in NEW_FORMS and d >= since]


def subject_from_header(text: str) -> dict:
    """b98 parse_subject_from_header 와 같은 규칙 · SUBJECT COMPANY 블록의 CIK · 이름."""
    import re
    m = re.search(r"SUBJECT COMPANY:(.*?)(?:FILED BY:|</PRE>|$)", text or "", re.DOTALL)
    if not m:
        return {}
    cik_m = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", m.group(1))
    name_m = re.search(r"COMPANY CONFORMED NAME:\s*(.+)", m.group(1))
    return {"cik": cik_m.group(1).zfill(10) if cik_m else "", "name": name_m.group(1).strip() if name_m else ""}


def form4_events() -> list[dict]:
    """h65 Form 4 캐시 (펀드 55곳 · 최근 30일) → F4_buy 행 (b98 산출과 같은 열)."""
    p = _P.find_glob("h28v2_form4_issuer_buys_*.json")
    if p is None:
        return []
    out = []
    for filer, info in json.loads(p.read_text()).items():
        for b in info.get("buys", []):
            if b.get("issuer_cik") and b.get("accession"):
                out.append({"event_id": "", "target_cik": b["issuer_cik"].zfill(10), "target_name": b.get("issuer_name", ""),
                            "event_type": "F4_buy", "event_date": b.get("tx_date", ""), "accession": b["accession"],
                            "institution": "", "filer_cik": filer.zfill(10)})
    return out


def run_13d(get: Callable[[str], Any] | None = None, today: date | None = None, notify=None) -> dict:
    """활동가 55곳 submissions 1회씩 · 새 13D/13G 만 신고서 헤더로 대상 회사 확인 · b98 산출 (씨앗) + 지난 주 산출 + h65 Form 4 합침.

    get(url) → httpx.Response 형태 (status_code · text · json()) · 403 은 SecBlockedError · 429 는 즉시 중단.
    하루 SEC 상한 (SEC_DAILY_CAP) 에 닿으면 헤더 확인을 다음 주로 미룸.
    """
    from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecBlockedError, SecDailyLedger, build_client
    today = today or _kst_today()
    registry = load_registry()
    ledger = SecDailyLedger.load(f"{today:%Y%m%d}")
    out_p = _P.out_flat(EVENTS_OUT)
    events = {}
    for e in _read_events(_P.find(SEED)) + _read_events(out_p if out_p.exists() else None):
        events[(e["event_type"], e["target_cik"], e["accession"], e["filer_cik"])] = e
    known_acc = {e["accession"] for e in events.values() if e["event_type"] != "F4_buy"}
    client = None
    if get is None:
        import time as _t
        from backend.scripts.biotech_sec_common import REQ_INTERVAL
        client = build_client()

        def get(url):  # noqa: E306
            _t.sleep(REQ_INTERVAL)
            r = client.get(url, timeout=25.0)
            if r.status_code == 403:
                raise SecBlockedError("403")
            return r
    requests = headers = added = deferred = deferred_registry = 0
    blocked = None
    try:
        for i, reg in enumerate(registry):
            if ledger.total() >= SEC_DAILY_CAP:   # WP98-3 · 등록부 조회도 하루 상한 안에서만 · 나머지는 미룸
                deferred_registry = len(registry) - i
                LOG.warning("13D 주간 · 하루 SEC 상한 %d 도달 · 등록부 %d곳 조회 미룸", SEC_DAILY_CAP, deferred_registry)
                break
            requests += 1
            ledger.add("h3_events")
            r = get(f"https://data.sec.gov/submissions/CIK{reg['cik']}.json")
            if r.status_code == 429:
                blocked = "SEC HTTP 429"
                break
            if r.status_code != 200:
                continue
            for f in new_13dg_filings(r.json(), today):
                if f["accession"] in known_acc:
                    continue
                if ledger.total() >= SEC_DAILY_CAP:
                    deferred += 1
                    continue
                requests += 1
                headers += 1
                ledger.add("h3_events")
                acc = f["accession"]
                h = get(f"https://www.sec.gov/Archives/edgar/data/{int(reg['cik'])}/{acc.replace('-', '')}/{acc}-index-headers.html")
                if h.status_code == 429:
                    blocked = "SEC HTTP 429"
                    break
                subj = subject_from_header(h.text) if h.status_code == 200 else {}
                if not subj.get("cik"):
                    continue
                e = {"event_id": f"{reg['cik']}_{acc}", "target_cik": subj["cik"], "target_name": subj["name"],
                     "event_type": NEW_FORMS[f["form"]], "event_date": f["date"], "accession": acc,
                     "institution": reg["institution"], "filer_cik": reg["cik"]}
                events[(e["event_type"], e["target_cik"], acc, reg["cik"])] = e
                known_acc.add(acc)
                added += 1
            if blocked:
                break
    except SecBlockedError as e:
        blocked = str(e)
    finally:
        ledger.save()
        if client is not None:
            client.close()
    for e in form4_events():
        events.setdefault((e["event_type"], e["target_cik"], e["accession"], e["filer_cik"]), e)
    since = today.replace(year=today.year - WINDOW_YEARS).isoformat()
    rows = [e for e in events.values() if e["event_type"] == "F4_buy" or e["event_date"] >= since]   # 13D/13G 만 5년 창 (b98 와 같음)
    rows.sort(key=lambda e: (e["event_date"], e["accession"]))
    tmp = out_p.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(out_p)
    if blocked:
        LOG.error("13D 주간 · %s · 즉시 중단 · 받은 것까지 반영", blocked)
        (notify or _notify_warning)("biotech 13D 주간 단계 중단", f"{blocked} · 요청 {requests}")
    LOG.info("13D 주간 · 활동가 %d · SEC 요청 %d (헤더 %d) · 새 13D/13G %d · 상한으로 미룸 헤더 %d · 등록부 %d · 전체 행 %d · %s",
             len(registry), requests, headers, added, deferred, deferred_registry, len(rows), out_p)
    return {"requests": requests, "headers": headers, "added": added, "deferred": deferred, "deferred_registry": deferred_registry,
            "rows": len(rows), "blocked": blocked}


# ── PubMed · Preprint (NLM esearch) ───────────────────────────────

class NlmBlocked(RuntimeError):
    pass


def _query(kind: str, company: str, year: int) -> str:
    from backend.scripts.biotech_h57_pubmed_index import normalize_company
    span = f"{year}/01:{year}/12[EDAT]"
    if kind == "pubmed":
        return f'"{normalize_company(company)}"[AD] AND {span}'
    return f'"{normalize_company(company)}"[AD] AND preprint[SB] AND {span}'


def nlm_count(get: Callable[..., Any], kind: str, company: str, year: int) -> int | None:
    from backend.scripts.biotech_h57_pubmed_index import ESEARCH
    r = get(ESEARCH, params={"db": "pubmed", "term": _query(kind, company, year), "retmode": "json", "retmax": "0"})
    if r.status_code in (403, 429):
        raise NlmBlocked(f"NLM HTTP {r.status_code}")
    if r.status_code != 200:
        return None
    try:
        return int(r.json().get("esearchresult", {}).get("count", 0))
    except Exception:
        return None


def run_nlm(get: Callable[..., Any] | None = None, today: date | None = None, sleep: Callable[[float], None] = time.sleep,
            notify=None) -> dict:
    today = today or _kst_today()
    cy, py = today.year, today.year - 1
    cands = [c for c in load_candidates() if c["name"]]
    cache_p = _P.out_flat(NLM_CACHE)
    cache: dict[str, dict] = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    client = None
    if get is None:
        import httpx
        from backend.scripts.biotech_h57_pubmed_index import UA
        client = httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30.0)
        get = client.get
    requests, blocked, errors = 0, None, 0
    try:
        for c in cands:
            for kind in ("pubmed", "preprint"):
                for yr in (py, cy):
                    key = f"{kind}|{c['cik']}|{yr}"
                    if yr == py and key in cache:          # 작년 값은 다시 받지 않음
                        continue
                    if requests:
                        sleep(NLM_INTERVAL)
                    requests += 1
                    n = nlm_count(get, kind, c["name"], yr)
                    if n is None:
                        errors += 1
                        continue
                    cache[key] = {"count": n, "fetched": today.isoformat(), "company": c["name"]}   # 0 도 캐시
    except NlmBlocked as e:
        blocked = str(e)
    finally:
        cache_p.write_text(json.dumps(cache, ensure_ascii=False))
        if client is not None:
            client.close()
    for kind, name in (("pubmed", PUBMED_OUT), ("preprint", PREPRINT_OUT)):
        idx = {}
        for c in cands:
            counts = {f"y{yr}": cache[f"{kind}|{c['cik']}|{yr}"]["count"] for yr in (py, cy) if f"{kind}|{c['cik']}|{yr}" in cache}
            if counts:
                idx[c["cik"]] = {"company": c["name"], "counts": counts}
        _P.out_flat(name).write_text(json.dumps(idx, ensure_ascii=False))
    if blocked:
        LOG.error("PubMed·Preprint 주간 · %s · 즉시 중단 · 캐시까지만 반영", blocked)
        (notify or _notify_warning)("biotech PubMed·Preprint 주간 단계 중단", f"{blocked} · 요청 {requests}")
    LOG.info("PubMed·Preprint 주간 · 후보 %d · NLM 요청 %d · 오류 %d · 중단 %s · 캐시 %d", len(cands), requests, errors, blocked, len(cache))
    return {"requests": requests, "blocked": blocked, "errors": errors, "cache": len(cache)}


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["13d", "nlm"])
    args = ap.parse_args()
    try:
        res = run_13d() if args.step == "13d" else run_nlm()
    except Exception as e:  # noqa: BLE001 · 주간 잡은 계속
        LOG.error("레이더 입력 주간 단계 실패 · %s · %s", args.step, e.__class__.__name__)
        _notify_warning(f"biotech 레이더 입력 주간 단계 실패 · {args.step}", e.__class__.__name__)
        res = {"error": e.__class__.__name__}
    print(json.dumps({"step": args.step, **res}, ensure_ascii=False))


if __name__ == "__main__":
    main()
