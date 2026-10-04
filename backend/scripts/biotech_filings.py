"""P3a ② · ③ · 후보 회사 SEC 제출 목록 (submissions) 일일 단계 · companyfacts 재무 추출 · 자금 여력 파생 (PRD v0.5 FR-5 · FR-6a).

② submissions 일일 (07:00 파이프 · 후보 종목당 1건 · 장부 "filings_submissions")
  - 헤더 = biotech_sec_common.build_client() 단일 상수 · 403 · 429 즉시 중단 · 하루 300 장부에 닿으면 남은 종목은 건너뜀
  - 원본: <RUNTIME>/filings/submissions_<YYYYMMDD>.json (최근 3년 + 여유 · 필드 6개) · 7일 보관
  - 파생: <RUNTIME>/filings/filings_derived_<YYYYMMDD>.json · 외국 발행사 (20-F · 6-K) · S-3 유효 (제출 후 3년)
    · 최근 12개월 S-3 · 424B5 · S-1 목록 · 최근 8-K 접수 시각 (UTC · 미국 동부) · ATM = "미확인" (표지 규칙 검수 전)
③ companyfacts 재무 (주간 · 요청 0 추가) · 월요일 시총 주식수 단계가 이미 받는 companyfacts 응답에서 추출
  - <RUNTIME>/finance/companyfacts_<YYYYMMDD>.json · 현금 · 영업현금흐름 (start · end · form · filed) · 차입금 4 · Liabilities
  - 최근 12개월 영업현금흐름 = 직전 연간 + 올해 누적 − 전년 같은 기간 누적 (FR-5 · 분기 차감 안 함)
  - 남은 개월 수 = 현금 ÷ (12개월 소모 ÷ 12) · 분기 말 기준과 오늘 기준 (경과 개월 보정) · 분기 말 뒤 424B5 가 있으면 "증자 반영 전"
  - 파생: <RUNTIME>/finance/runway_<YYYYMMDD>.json (일일 submissions 단계 끝에 최신 재무 파일로 다시 계산 · 요청 0)

표시 · 점수 · 후보 판정에는 쓰지 않는다 (화면은 P3b).

실행:
    python -m backend.scripts.biotech_filings submissions    # 일일 07:00 파이프 단계
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecBlockedError, SecDailyLedger, build_client, sec_get

LOG = logging.getLogger("biotech_filings")
ET = ZoneInfo("America/New_York")

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
LEDGER_CAT = "filings_submissions"
KEEP_FIELDS = ("form", "filingDate", "acceptanceDateTime", "accessionNumber", "items", "primaryDocument")
FOREIGN_FORMS = ("20-F", "6-K")                 # PRD 6절 · 외국 발행사 표시
ANNUAL_FORMS = ("10-K", "20-F")                 # 가장 최근 연간 보고서 양식으로 현재 외국 발행사인지 판정
SHELF_FORMS = ("S-3", "S-3ASR")                 # 일괄 신고 원본 (정정 S-3/A 는 3년 기산에 쓰지 않음)
OFFERING_FORMS = ("S-3", "S-3ASR", "S-3/A", "424B5", "S-1", "S-1/A")   # 최근 12개월 증자 관련 목록
RAISE_FORMS = ("424B5",)                        # 분기 말 뒤 "증자 반영 전" 판정 (8-K 는 사유가 많아 쓰지 않음)
SHELF_YEARS = 3
RAW_DAYS = SHELF_YEARS * 366 + 30               # 원본에 남기는 기간 (S-3 3년 판정 + 여유)
RAW_KEEP_DAYS = 7                               # 원본 파일 보관 일수
DERIVED_KEEP_DAYS = 400                         # 파생 파일 보관 일수
ATM_UNKNOWN = "미확인"                          # PRD FR-6a · 표지 규칙 Fable 검수 전

# ── 공통 ─────────────────────────────────────────────────────────────


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def load_candidates() -> list[dict]:
    """후보 (cik · ticker · name) · 티커가 빈 행도 CIK 로 받는다 (INCY 같은 행)."""
    p = _P.find_glob("biotech_candidates_2*.csv", subdir="candidates") or _P.find_glob("biotech_candidates_2*.csv")
    if p is None:
        return []
    with p.open() as f:
        rows = [{"cik": (r.get("cik") or "").strip(), "ticker": (r.get("ticker") or "").strip(), "name": r.get("name") or ""}
                for r in csv.DictReader(f)]
    return [r for r in rows if r["cik"]]


def to_et(acceptance_utc: str) -> str | None:
    """SEC submissions acceptanceDateTime (UTC · 'Z') → 미국 동부 시각 ISO (초 단위 · 시간대 없음)."""
    if not acceptance_utc:
        return None
    t = datetime.fromisoformat(acceptance_utc.replace("Z", "+00:00"))
    return t.astimezone(ET).replace(tzinfo=None).isoformat(timespec="seconds")


def _add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:            # 2/29
        return d.replace(year=d.year + n, day=28)


def _prune(folder: Path, prefix: str, today: date, keep_days: int) -> int:
    n = 0
    for f in folder.glob(f"{prefix}_*.json"):
        try:
            d = datetime.strptime(f.stem[len(prefix) + 1:], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - d).days > keep_days:
            f.unlink()
            n += 1
    return n

# ── ② submissions ────────────────────────────────────────────────────


def parse_recent(j: dict) -> list[dict]:
    """filings.recent 의 열 배열 → 행 (필드 6개)."""
    rec = ((j or {}).get("filings") or {}).get("recent") or {}
    cols = {k: rec.get(k) or [] for k in KEEP_FIELDS}
    n = len(cols["accessionNumber"])
    return [{k: (cols[k][i] if i < len(cols[k]) else "") for k in KEEP_FIELDS} for i in range(n)]


def derive(filings: list[dict], today: date, older_pages: bool) -> dict:
    """한 회사의 제출 목록 → 파생 값.

    older_pages: submissions 응답에 'files' (recent 밖 과거 목록) 가 있으면 True.
    S-3 유효 = 원본 S-3 · S-3ASR 제출일 + 3년 > 오늘. recent 가 3년을 덮지 못하고 그 안에 S-3 이 없으면 None (미확인).
    """
    fs = sorted((f for f in filings if f.get("filingDate")), key=lambda f: (f["filingDate"], f.get("acceptanceDateTime", "")),
                reverse=True)
    oldest = fs[-1]["filingDate"] if fs else None
    foreign = [f for f in fs if f["form"] in FOREIGN_FORMS]
    year_ago = (today - timedelta(days=365)).isoformat()
    # 외국 발행사 = 가장 최근 연간 보고서가 20-F 이거나 최근 12개월에 6-K 가 있음
    # (예전에 20-F 를 내다 10-K 로 바꾼 회사는 국내 제출사 · 2026-10-04 실행 ENTX 마지막 20-F 2021-11-10)
    last_annual = next((f for f in fs if f["form"] in ANNUAL_FORMS), None)
    is_foreign = bool((last_annual and last_annual["form"] == "20-F")
                      or any(f["form"] == "6-K" and f["filingDate"] >= year_ago for f in fs))
    shelf = next((f for f in fs if f["form"] in SHELF_FORMS
                  and _add_years(date.fromisoformat(f["filingDate"]), SHELF_YEARS) > today), None)
    three_years_ago = _add_years(today, -SHELF_YEARS).isoformat()
    if shelf:
        s3 = {"effective": True, "form": shelf["form"], "filingDate": shelf["filingDate"],
              "accessionNumber": shelf["accessionNumber"],
              "expires": _add_years(date.fromisoformat(shelf["filingDate"]), SHELF_YEARS).isoformat()}
    elif not older_pages or (oldest is not None and oldest <= three_years_ago):
        s3 = {"effective": False}
    else:
        s3 = {"effective": None, "reason": f"제출 목록이 {oldest} 부터라 3년을 덮지 못함 · 미확인"}
    offerings = [{k: f[k] for k in ("form", "filingDate", "accessionNumber", "primaryDocument")}
                 for f in fs if f["form"] in OFFERING_FORMS and f["filingDate"] >= year_ago]
    eightk = sorted((f for f in fs if f["form"] == "8-K" and f.get("acceptanceDateTime")),
                    key=lambda f: f["acceptanceDateTime"], reverse=True)
    last_8k = None
    if eightk:
        k = eightk[0]
        last_8k = {"acceptanceDateTime": k["acceptanceDateTime"], "acceptance_et": to_et(k["acceptanceDateTime"]),
                   "filingDate": k["filingDate"], "accessionNumber": k["accessionNumber"], "items": k.get("items", "")}
    return {
        "foreign_issuer": is_foreign,
        "last_annual_form": last_annual["form"] if last_annual else None,
        "foreign_forms": sorted({f["form"] for f in foreign}),
        "foreign_last": foreign[0]["filingDate"] if foreign else None,
        "s3": s3,
        "offerings_12m": offerings,
        "last_8k": last_8k,
        "atm": ATM_UNKNOWN,
        "recent_from": oldest,
        "recent_n": len(fs),
        "older_pages": older_pages,
    }


def run_submissions(today: date | None = None, get: Callable[[str], dict] | None = None,
                    ledger: SecDailyLedger | None = None, cands: list[dict] | None = None) -> dict:
    today = today or _kst_today()
    cands = cands if cands is not None else load_candidates()
    ledger = ledger or SecDailyLedger.load(f"{today:%Y%m%d}")
    client = None
    if get is None:
        client = build_client()                        # biotech_sec_common 단일 헤더 상수
        get = lambda url: sec_get(client, url)         # noqa: E731
    raw, derived = {}, {}
    sent, blocked, capped = 0, None, 0
    lo = (today - timedelta(days=RAW_DAYS)).isoformat()
    try:
        for c in sorted(cands, key=lambda r: r["cik"]):
            if ledger.total() >= SEC_DAILY_CAP:
                capped += 1
                continue
            cik = str(int(c["cik"])).zfill(10)
            ledger.add(LEDGER_CAT)                     # 보내기 직전에 셈 · 예외로 끝나도 장부에 남김
            ledger.save()
            sent += 1
            try:
                r = get(SUBMISSIONS_URL.format(cik=cik))
            except SecBlockedError as e:
                blocked = str(e)
                break
            if r.get("status") == 429:
                blocked = "SEC HTTP 429"
                break
            j = r.get("json")
            if r.get("status") != 200 or not j:
                LOG.warning("submissions · CIK %s · HTTP %s · 건너뜀", cik, r.get("status"))
                continue
            rows = parse_recent(j)
            older = bool((j.get("filings") or {}).get("files"))
            raw[cik] = {"ticker": c["ticker"], "name": c["name"], "sec_tickers": j.get("tickers") or [],
                        "older_pages": older, "filings": [f for f in rows if f["filingDate"] >= lo]}
            derived[cik] = {"ticker": c["ticker"] or ((j.get("tickers") or [""])[0]), "ticker_in_candidates": c["ticker"],
                            **derive(rows, today, older)}
    finally:
        if client is not None:
            client.close()
    if blocked:
        LOG.error("%s · submissions 즉시 중단 (보낸 요청 %d)", blocked, sent)
    if capped:
        LOG.warning("submissions · 하루 SEC 상한 %d 도달 · %d 종목 건너뜀", SEC_DAILY_CAP, capped)
    fdir = _P.out_dir("filings")
    meta = {"date": today.isoformat(), "requests": sent, "blocked": blocked, "capped": capped, "companies": len(derived)}
    (fdir / f"submissions_{today:%Y%m%d}.json").write_text(json.dumps({**meta, "companies_raw": raw}, ensure_ascii=False))
    (fdir / f"filings_derived_{today:%Y%m%d}.json").write_text(
        json.dumps({**meta, "rows": derived}, ensure_ascii=False, indent=1))
    pr = _prune(fdir, "submissions", today, RAW_KEEP_DAYS) + _prune(fdir, "filings_derived", today, DERIVED_KEEP_DAYS)
    rw = write_runway(today, derived)
    LOG.info("submissions · 요청 %d · 회사 %d · 외국 발행사 %d · S-3 유효 %d · 미확인 %d · 12개월 증자 공시 보유 %d · 지운 파일 %d · 자금 여력 %s",
             sent, len(derived), sum(1 for d in derived.values() if d["foreign_issuer"]),
             sum(1 for d in derived.values() if d["s3"]["effective"] is True),
             sum(1 for d in derived.values() if d["s3"]["effective"] is None),
             sum(1 for d in derived.values() if d["offerings_12m"]), pr, rw)
    return meta

# ── ③ companyfacts 재무 ─────────────────────────────────────────────

CASH_TAG = "CashAndCashEquivalentsAtCarryingValue"
OCF_TAG = "NetCashProvidedByUsedInOperatingActivities"
DEBT_TAGS = ("LongTermDebt", "LongTermDebtNoncurrent", "DebtCurrent", "ConvertibleNotesPayable")   # PRD FR-6a
LIAB_TAG = "Liabilities"
REPORT_FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
PT_FIELDS = ("start", "end", "val", "form", "filed", "accn")
MONTH_DAYS = 365.25 / 12


def _pts(ug: dict, tag: str) -> list[dict]:
    """USD 값 · 보고 양식만 · 같은 (start, end) 는 가장 늦게 제출된 값 하나 (정정 · 비교 기간 재기재)."""
    node = ug.get(tag)
    if not node:
        return []
    best: dict[tuple, dict] = {}
    for p in (node.get("units") or {}).get("USD", []):
        if p.get("form") not in REPORT_FORMS or p.get("val") is None:
            continue
        k = (p.get("start"), p["end"])
        if k not in best or (p.get("filed", ""), p.get("accn", "")) > (best[k].get("filed", ""), best[k].get("accn", "")):
            best[k] = p
    return list(best.values())


def _pick(p: dict | None) -> dict | None:
    return {k: p.get(k) for k in PT_FIELDS if k in p} if p else None


def _latest(pts: list[dict]) -> dict | None:
    return max(pts, key=lambda p: (p["end"], p.get("filed", ""))) if pts else None


def _days(p: dict) -> int:
    return (date.fromisoformat(p["end"]) - date.fromisoformat(p["start"])).days


def _months(p: dict) -> int | None:
    """기간 길이 → 3 · 6 · 9 · 12 개월 (그 밖은 None)."""
    d = _days(p)
    for m, (lo, hi) in {3: (80, 100), 6: (170, 190), 9: (260, 285), 12: (350, 380)}.items():
        if lo <= d <= hi:
            return m
    return None


def _near(a: str, b: date, tol: int = 7) -> bool:
    return abs((date.fromisoformat(a) - b).days) <= tol


def ttm_ocf(pts: list[dict]) -> dict:
    """최근 12개월 영업현금흐름 = 직전 연간 + 올해 누적 − 전년 같은 기간 누적 (PRD v0.5 FR-5).

    가장 최근 기간이 연간 (10-K) 이면 그 값이 12개월 합이다. 세 값 중 하나라도 없으면 계산하지 않는다.
    """
    dur = [p for p in pts if p.get("start") and _months(p)]
    if not dur:
        return {"ttm": None, "reason": "XBRL 영업현금흐름 항목 없음"}
    end = max(p["end"] for p in dur)
    at_end = sorted((p for p in dur if p["end"] == end), key=_days, reverse=True)
    if _months(at_end[0]) == 12:
        a = at_end[0]
        return {"ttm": a["val"], "end": end, "method": "annual", "annual": _pick(a), "ytd": None, "prior_ytd": None}
    for ytd in at_end:
        s, e = date.fromisoformat(ytd["start"]), date.fromisoformat(ytd["end"])
        annual = next((p for p in dur if _months(p) == 12 and _near(p["end"], s - timedelta(days=1))), None)
        prior = next((p for p in dur if _months(p) == _months(ytd) and _near(p["end"], _add_years(e, -1))
                      and _near(p["start"], _add_years(s, -1))), None)
        if annual and prior:
            return {"ttm": annual["val"] + ytd["val"] - prior["val"], "end": end, "method": "annual+ytd-prior_ytd",
                    "annual": _pick(annual), "ytd": _pick(ytd), "prior_ytd": _pick(prior)}
    return {"ttm": None, "end": end, "reason": "영업현금흐름 기간 불일치", "ytd": _pick(at_end[0])}


def extract_finance(facts: dict) -> dict:
    """companyfacts 응답 → 저장할 재무 값 (요청 없음 · 순수 함수)."""
    allf = (facts or {}).get("facts") or {}
    ug = allf.get("us-gaap")
    if not ug:
        return {"reason": "XBRL us-gaap 없음 (외국 발행사 20-F 등)", "taxonomies": sorted(allf)}
    ocf = _pts(ug, OCF_TAG)
    return {
        "cash": _pick(_latest(_pts(ug, CASH_TAG))),
        "ocf_latest": _pick(_latest([p for p in ocf if p.get("start")])),
        "ocf_ttm": ttm_ocf(ocf),
        "debt": {t: _pick(_latest(_pts(ug, t))) for t in DEBT_TAGS},
        "liabilities": _pick(_latest(_pts(ug, LIAB_TAG))),
    }


def runway(fin: dict, filings: dict | None, today: date) -> dict:
    """남은 개월 수 (분기 말 기준 · 오늘 기준) · 분기 말 뒤 424B5 가 있으면 오늘 기준 대신 "증자 반영 전"."""
    if filings and filings.get("foreign_issuer") and not fin.get("cash"):
        return {"months_qe": None, "months_today": None, "label": "계산 불가", "reason": "외국 발행사 (20-F · 6-K)"}
    if fin.get("reason"):
        return {"months_qe": None, "months_today": None, "label": "계산 불가", "reason": fin["reason"]}
    cash, t = fin.get("cash"), fin.get("ocf_ttm") or {}
    if not cash:
        return {"months_qe": None, "months_today": None, "label": "계산 불가", "reason": "XBRL 현금성 자산 항목 없음"}
    if t.get("ttm") is None:
        return {"months_qe": None, "months_today": None, "label": "계산 불가", "reason": t.get("reason", "영업현금흐름 없음"),
                "cash": cash["val"], "qe": cash["end"]}
    base = {"cash": cash["val"], "qe": cash["end"], "ocf_ttm": t["ttm"], "ocf_end": t.get("end"),
            "period_match": t.get("end") == cash["end"]}
    if t["ttm"] >= 0:
        return {**base, "months_qe": None, "months_today": None, "label": "현금 소모 없음"}
    months_qe = cash["val"] / (-t["ttm"] / 12)
    elapsed = (today - date.fromisoformat(cash["end"])).days / MONTH_DAYS
    raises = [o for o in (filings or {}).get("offerings_12m", []) if o["form"] in RAISE_FORMS and o["filingDate"] > cash["end"]]
    out = {**base, "months_qe": round(months_qe, 2), "elapsed_months": round(elapsed, 2)}
    if raises:
        return {**out, "months_today": None, "label": "증자 반영 전", "raises_after_qe": raises}
    return {**out, "months_today": round(months_qe - elapsed, 2), "label": "그 사이 증자가 없다고 가정"}


def finance_path(today: date) -> Path:
    return _P.out_dir("finance") / f"companyfacts_{today:%Y%m%d}.json"


def save_finance(rows: dict[str, dict], today: date) -> Path:
    """월요일 시총 주식수 단계가 받은 companyfacts 에서 뽑은 재무 값 저장 (ticker → 값)."""
    p = finance_path(today)
    p.write_text(json.dumps({"date": today.isoformat(), "rows": rows}, ensure_ascii=False, indent=1))
    _prune(p.parent, "companyfacts", today, DERIVED_KEEP_DAYS)
    return p


def write_runway(today: date, derived: dict[str, dict]) -> str:
    """최신 재무 파일 + 오늘 파생 제출 목록 → runway_<날짜>.json (요청 0)."""
    hits = sorted(_P.out_dir("finance").glob("companyfacts_*.json"))
    if not hits:
        return "재무 파일 없음 (월요일 주간 단계 전)"
    fin = json.loads(hits[-1].read_text())
    by_ticker = {d["ticker"]: d for d in derived.values() if d.get("ticker")}
    rows = {tk: {"cik": v.get("cik"), **runway(v, by_ticker.get(tk), today)} for tk, v in fin.get("rows", {}).items()}
    out = _P.out_dir("finance") / f"runway_{today:%Y%m%d}.json"
    out.write_text(json.dumps({"date": today.isoformat(), "finance_asof": fin.get("date"), "rows": rows},
                              ensure_ascii=False, indent=1))
    _prune(out.parent, "runway", today, DERIVED_KEEP_DAYS)
    return f"{len(rows)}종목 · 재무 {fin.get('date')}"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["submissions"])
    ap.parse_args()
    print(json.dumps(run_submissions(), ensure_ascii=False))


if __name__ == "__main__":
    main()
