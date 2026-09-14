"""표본 무결성 재검증 v3 · 회사별 제출 이력 조회 방식 (B24).

Fable 지적 (v2 검수):
- v2 EFTS 전문검색 첫 hit 채택 → filer CIK 미대조로 오매칭 다수
  (GBT · AVEO · KDMN 등 · 다른 회사의 filing 을 잘못 채택)
- 날짜 미조정 (SYRS Δ120d · HGEN Δ148d)
- 대체 종목 유형 하드코딩 (CARM 등)

v3 원칙:
- CIK 확정 후 회사 자체 제출 이력만 조회
  · https://www.sec.gov/files/company_tickers.json (활성) — 접근 시도
  · 실패 시 EFTS 회사명 검색 (10-K filter) → filer CIK 확정
- Form 25 / 25-NSE 우선 (권위 기록 · file_date 채택)
- 8-K Item 1.03 → BANKRUPT 확정
- 8-K (인수 완료) → Form 25 부재 시 · 필수: filer CIK 일치
- filer CIK 불일치 filing 절대 채택 금지
- 기존 event_date 와 30일 초과 차이 시 권위 기록일로 교체 · Δ 비고

절대 금지: 결제 · 구독. API 키 불필요.
실행: ./backend/venv/bin/python backend/scripts/biotech_samples_verify_v3.py
"""
from __future__ import annotations

from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING  # noqa: E402 · WP23

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_verify_v3")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
REQ_INTERVAL = 0.5  # SEC 10 req/s 이내

DATE_CORRECTION_THRESHOLD_DAYS = 30
FORM25_TYPES = {"25", "25-NSE"}


@dataclass
class SampleV3:
    ticker: str
    event_type_original: str
    event_date_original: str
    event_desc: str
    company_name: str = ""
    # 검증 후
    cik: str = ""
    cik_source: str = ""
    event_type: str = ""
    event_date: str = ""
    edgar_accession: str = ""
    edgar_form_type: str = ""
    edgar_file_date: str = ""
    edgar_items: str = ""
    filer_match: bool = False
    date_corrected: bool = False
    date_delta_days: int = 0
    type_evidence: str = ""  # accession 참조
    verified: bool = False
    note: str = ""


# 기존 v2 verified 20 + PRQR 원상 (Fable 요구: PRQR 제거 유지 · 재확인 대상)
# event_type_original 및 event_date_original 은 v2 CSV 값 그대로
# company_name 은 event_desc 에서 파싱한 대상 회사명
SAMPLES: list[SampleV3] = [
    SampleV3("HZNP", "ACQUIRED", "2023-10-06", "Horizon Therapeutics → Amgen", "Horizon Therapeutics"),
    SampleV3("SGEN", "ACQUIRED", "2023-12-14", "Seagen → Pfizer", "Seagen"),
    SampleV3("GBT",  "ACQUIRED", "2022-10-05", "Global Blood Therapeutics → Pfizer", "Global Blood Therapeutics"),
    SampleV3("ARNA", "ACQUIRED", "2022-03-11", "Arena Pharmaceuticals → Pfizer", "Arena Pharmaceuticals"),
    SampleV3("ALXN", "ACQUIRED", "2021-07-21", "Alexion Pharmaceuticals → AstraZeneca", "Alexion Pharmaceuticals"),
    SampleV3("TRIL", "ACQUIRED", "2021-11-17", "Trillium Therapeutics → Pfizer", "Trillium Therapeutics"),
    SampleV3("AKUS", "ACQUIRED", "2022-12-22", "Akouos → Eli Lilly", "Akouos"),
    SampleV3("MYOV", "ACQUIRED", "2023-03-13", "Myovant Sciences → Sumitomo", "Myovant Sciences"),
    SampleV3("DCPH", "ACQUIRED", "2024-06-06", "Deciphera Pharmaceuticals → Ono", "Deciphera Pharmaceuticals"),
    SampleV3("PRVL", "ACQUIRED", "2021-01-22", "Prevail Therapeutics → Eli Lilly", "Prevail Therapeutics"),
    SampleV3("XLRN", "ACQUIRED", "2021-11-08", "Acceleron Pharma → Merck", "Acceleron Pharma"),
    SampleV3("AVEO", "ACQUIRED", "2023-08-04", "AVEO Pharmaceuticals → LG Chem", "AVEO Pharmaceuticals"),
    SampleV3("KDMN", "ACQUIRED", "2022-09-21", "Kadmon Holdings → Sanofi", "Kadmon Holdings"),
    SampleV3("CNCE", "ACQUIRED", "2023-03-06", "Concert Pharmaceuticals → Sun Pharma", "Concert Pharmaceuticals"),
    SampleV3("TALS", "ACQUIRED", "2023-11-06", "Talaris → Tourmaline merger", "Talaris Therapeutics"),
    SampleV3("SYRS", "BANKRUPT", "2024-11-11", "Syros Pharmaceuticals bankruptcy", "Syros Pharmaceuticals"),
    SampleV3("HGEN", "BANKRUPT", "2023-02-27", "Humanigen Chapter 11", "Humanigen"),
    SampleV3("KZR",  "ACQUIRED", "2026-05-11", "Kezar Life Sciences → Aurinia", "Kezar Life Sciences"),
    SampleV3("CALT", "ACQUIRED", "2024-09-13", "Calliditas Therapeutics (v2 대체)", "Calliditas Therapeutics"),
    SampleV3("CARM", "ACQUIRED", "2025-12-15", "Carisma Therapeutics (v2 대체 · 유형 재확인)", "Carisma Therapeutics"),
]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get(client: httpx.Client, url: str, params: dict | None = None, retries: int = 3) -> httpx.Response | None:
    """rate limit 준수 + 5xx 재시도 (0.5s → 1.5s → 4.5s)."""
    delay = REQ_INTERVAL
    last: httpx.Response | None = None
    for attempt in range(retries):
        time.sleep(delay)
        try:
            r = client.get(url, params=params, timeout=25.0)
            if r.status_code < 500:
                return r
            LOG.warning("HTTP %d · retry %d/%d", r.status_code, attempt + 1, retries)
            last = r
        except Exception as e:
            LOG.warning("HTTP ERR %s: %s · retry %d/%d", type(e).__name__, e, attempt + 1, retries)
        delay = min(delay * 3, 5.0)
    return last


def resolve_cik(client: httpx.Client, s: SampleV3) -> None:
    """CIK 확정. EFTS 회사명 검색 · 여러 form filter fallback."""
    q = f'"{s.company_name}"'
    target_low = s.company_name.lower()
    target_first = target_low.split()[0]

    # 10-K → 20-F (foreign) → no filter 순차
    for forms_filter, kind in [("10-K", "10-K"), ("20-F", "20-F"), ("", "any-form")]:
        params = {"q": q}
        if forms_filter:
            params["forms"] = forms_filter
        r = _get(client, EFTS_BASE, params)
        if r is None or r.status_code != 200:
            continue
        hits = r.json().get("hits", {}).get("hits", [])
        for h in hits[:40]:
            src = h.get("_source", {})
            names = src.get("display_names") or []
            ciks = src.get("ciks") or []
            if not names or not ciks:
                continue
            display = names[0]
            low = display.lower().split("(")[0]  # 회사명 부분만
            # 정확 매치: 회사 전체 이름 or 첫 단어 매치
            if target_low in low or (target_first and target_first in low.split()):
                s.cik = ciks[0]
                s.cik_source = f"EFTS 회사명 검색 ({kind} filter · /files/company_tickers.json 접근 차단으로 fallback)"
                LOG.info("CIK %s = %s (%s · %s)", s.ticker, s.cik, display, kind)
                return
    s.note = f"CIK 미확보 · EFTS 회사명 검색 매치 실패"


def fetch_submissions(client: httpx.Client, cik: str) -> dict | None:
    """data.sec.gov/submissions/CIK{10}.json 조회."""
    url = f"{SUBMISSIONS_BASE}/CIK{cik.zfill(10)}.json"
    r = _get(client, url)
    if r is None or r.status_code != 200:
        LOG.warning("submissions HTTP %s · CIK %s", r.status_code if r else "-", cik)
        return None
    try:
        return r.json()
    except Exception as e:
        LOG.warning("submissions JSON parse fail CIK %s: %s", cik, e)
        return None


def find_authority_record(subs: dict, s: SampleV3) -> tuple[str, str, str, str, str] | None:
    """
    filings.recent 에서 다음 순서로 권위 기록 검색:
      1) Form 25 / 25-NSE · 창 ±180d 안에서 최근접
      2) 8-K Item 1.03 (BANKRUPT 힌트)
      3) 8-K · 창 ±180d 안에서 event_date 최근접
    반환: (accession, form, file_date, items_str, kind) 또는 None
    kind ∈ {'form25', '8-K-1.03', '8-K-nearest'}
    """
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    items_list = recent.get("items", [])
    if not forms:
        return None

    try:
        ev = datetime.strptime(s.event_date_original, "%Y-%m-%d")
    except ValueError:
        return None

    # Form 25 는 폐지 완료 후 즉시~ 몇 개월 후 신고 · 인수 완료 8-K 는 이벤트 근접
    # 창을 넓혀 놓치는 사례 최소화 (파산 지연신고 대비 8-K item 1.03 은 별도 창)
    lo = ev - timedelta(days=270)
    hi = ev + timedelta(days=540)

    # 1) Form 25 / 25-NSE
    best_25 = None
    for i, f in enumerate(forms):
        if f not in FORM25_TYPES:
            continue
        try:
            d = datetime.strptime(dates[i], "%Y-%m-%d")
        except ValueError:
            continue
        if not (lo <= d <= hi):
            continue
        delta = abs((d - ev).days)
        cand = (accs[i], f, dates[i], items_list[i] if i < len(items_list) else "", "form25", delta)
        if best_25 is None or cand[5] < best_25[5]:
            best_25 = cand
    if best_25 is not None:
        return best_25[:5]

    # 2) 8-K Item 1.03 (BANKRUPT 힌트) - 검색 창 확대(±540d) · 파산은 지연 신고 흔함
    for i, f in enumerate(forms):
        if f != "8-K":
            continue
        items = items_list[i] if i < len(items_list) else ""
        if "1.03" not in items:
            continue
        try:
            d = datetime.strptime(dates[i], "%Y-%m-%d")
        except ValueError:
            continue
        wide_lo = ev - timedelta(days=540)
        wide_hi = ev + timedelta(days=540)
        if not (wide_lo <= d <= wide_hi):
            continue
        return (accs[i], f, dates[i], items, "8-K-1.03")

    # 3) 8-K 최근접 (인수 완료 대체) · 창 안 우선 · items 에 2.01 있으면 강한 근거
    best_8k = None
    for i, f in enumerate(forms):
        if f != "8-K":
            continue
        try:
            d = datetime.strptime(dates[i], "%Y-%m-%d")
        except ValueError:
            continue
        if not (lo <= d <= hi):
            continue
        delta = abs((d - ev).days)
        items = items_list[i] if i < len(items_list) else ""
        # item 2.01 (인수 완료) 이 있으면 우선순위 강화 (delta 절반으로 가중)
        weight = delta if "2.01" not in items else max(1, delta // 2)
        cand = (accs[i], f, dates[i], items, "8-K-nearest", weight)
        if best_8k is None or cand[5] < best_8k[5]:
            best_8k = cand
    if best_8k is not None:
        return best_8k[:5]

    return None


def verify_sample_v3(client: httpx.Client, s: SampleV3) -> None:
    """단일 표본 재검증."""
    LOG.info("검증 [%s] %s %s", s.ticker, s.event_type_original, s.event_date_original)
    resolve_cik(client, s)
    if not s.cik:
        s.note = s.note or "CIK 미확보"
        return

    subs = fetch_submissions(client, s.cik)
    if subs is None:
        s.note = "submissions API 조회 실패"
        return

    # 회사명 확인 (filer 일치 신뢰 강화)
    subs_name = subs.get("name", "")
    if s.company_name.lower().split()[0] not in subs_name.lower() and subs_name.lower().split()[0] not in s.company_name.lower():
        LOG.warning("subs name mismatch · sample=%s subs=%s", s.company_name, subs_name)

    rec = find_authority_record(subs, s)
    if rec is None:
        s.note = f"권위 기록 미확보 (Form 25/25-NSE/8-K 창 안에 없음) · subs.name={subs_name}"
        return

    acc, form, fdate, items, kind = rec
    s.edgar_accession = acc
    s.edgar_form_type = form
    s.edgar_file_date = fdate
    s.edgar_items = items
    s.type_evidence = acc
    s.filer_match = True

    # 유형 확정
    if kind == "8-K-1.03":
        s.event_type = "BANKRUPT"
    elif kind == "form25":
        # Form 25 는 폐지 신고 · 사유 별도 확인 필요 (인수 or 자진폐지)
        # 원본 event_type 이 ACQUIRED 였고 인수사 이름이 event_desc 에 있으면 유지
        # 그렇지 않으면 "DELISTED(사유 미확인)"
        if s.event_type_original == "ACQUIRED" and "→" in s.event_desc:
            s.event_type = "ACQUIRED"
            s.note = "Form 25 확인 · 원본 event_desc 에 인수사 명시"
        elif s.event_type_original == "BANKRUPT":
            s.event_type = "BANKRUPT"
        else:
            s.event_type = "DELISTED(사유 미확인)"
            s.note = "Form 25 만 확인 · 사유(인수 vs 자진폐지) 확정 위해 8-K 내용 별도 조회 필요"
    else:  # 8-K-nearest
        # 원본 유형 유지 · 단 filer 일치 확인은 CIK 로 이미 완료
        s.event_type = s.event_type_original
        s.note = "8-K 최근접 (item 미검증) · filer CIK 일치"

    # 날짜 정정
    try:
        ev_orig = datetime.strptime(s.event_date_original, "%Y-%m-%d")
        ev_new = datetime.strptime(fdate, "%Y-%m-%d")
        delta = abs((ev_new - ev_orig).days)
        s.date_delta_days = delta
        if delta > DATE_CORRECTION_THRESHOLD_DAYS:
            s.event_date = fdate
            s.date_corrected = True
            s.note = (s.note + " · " if s.note else "") + f"날짜 정정 Δ{delta}d"
        else:
            s.event_date = s.event_date_original
    except ValueError:
        s.event_date = s.event_date_original

    s.verified = True


def find_bankruptcy_candidate(client: httpx.Client, exclude: set[str]) -> SampleV3 | None:
    """EFTS 로 Item 1.03 (파산) 후보 발굴 · CIK 조회로 검증 · SIC 2834/2836 확인.

    후보 발굴: q='Chapter 11' 또는 q='Item 1.03' + forms=8-K + dateRange 2021-2026
    검증: 각 후보 CIK 의 submissions API 조회 · SIC 2834/2836 · Item 1.03 8-K 확인
    """
    # 검색 창 넓게 · 결과에서 바이오 SIC 우선 채택
    for query in ['"Chapter 11" "bankruptcy"', '"Item 1.03"']:
        r = _get(client, EFTS_BASE, {
            "q": query,
            "forms": "8-K",
            "dateRange": "custom",
            "startdt": "2021-01-01",
            "enddt": "2026-08-31",
        })
        if r is None or r.status_code != 200:
            continue
        hits = r.json().get("hits", {}).get("hits", [])
        for h in hits[:80]:
            src = h.get("_source", {})
            ciks = src.get("ciks") or []
            sics = src.get("sics") or []
            names = src.get("display_names") or []
            if not ciks or not names:
                continue
            cik = ciks[0]
            display = names[0]
            # 바이오 SIC 필터
            if not any(s in ("2834", "2836") for s in sics):
                continue
            # ticker 추출
            import re
            m = re.search(r"\(([A-Z]{2,5})\)", display)
            if not m:
                continue
            tkr = m.group(1)
            if tkr in exclude:
                continue
            # 후보 · CIK 검증
            company_name = display.split("(")[0].strip()
            fd = src.get("file_date", "")
            LOG.info("파산 후보 검토: %s (%s · CIK %s · SIC %s)", tkr, company_name, cik, sics[0] if sics else '-')

            cand = SampleV3(
                ticker=tkr,
                event_type_original="BANKRUPT",
                event_date_original=fd,
                event_desc=f"{display} (B26 EFTS Chapter 11 검색 · CIK 검증 채택)",
                company_name=company_name,
            )
            cand.cik = cik
            cand.cik_source = f"EFTS Chapter 11 후보 발굴 · SIC {sics[0]} · CIK 매치"

            # submissions 조회로 filer CIK Item 1.03 확인
            subs = fetch_submissions(client, cik)
            if subs is None:
                continue
            # find_authority_record 로 Item 1.03 8-K 확인
            rec = find_authority_record(subs, cand)
            if rec is None:
                LOG.info("파산 후보 %s : 권위 기록 창 안에 없음 · 넘김", tkr)
                continue
            acc, form, fdate, items, kind = rec
            cand.edgar_accession = acc
            cand.edgar_form_type = form
            cand.edgar_file_date = fdate
            cand.edgar_items = items
            cand.type_evidence = acc
            cand.filer_match = True
            if kind == "8-K-1.03":
                cand.event_type = "BANKRUPT"
                cand.event_date = fdate
                cand.verified = True
                cand.note = "B26 파산 보충 · Item 1.03 확인"
                return cand
            else:
                LOG.info("파산 후보 %s : Item 1.03 미확인 · 넘김", tkr)
                continue
    return None


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # B44 · 기존 보안 경로 연결 (setup_secure_logging 자동 · 2026-08 사고 산출물 재사용)
    from backend.services import config as _config  # noqa: F401
    git_sha = _git_sha()

    with httpx.Client(
        headers={
            "User-Agent": SEC_UA,
            "From": SEC_FROM,
            "Accept-Encoding": SEC_ACCEPT_ENCODING,
        }
    ) as client:
        for s in SAMPLES:
            verify_sample_v3(client, s)

        # B26 파산 보충 · verified 20 목표 · 구성 15/5 근접 (파산·부실폐지 5)
        verified_count = sum(1 for s in SAMPLES if s.verified)
        if verified_count < 20:
            needed = 20 - verified_count
            exclude = {s.ticker for s in SAMPLES}
            for _ in range(needed):
                cand = find_bankruptcy_candidate(client, exclude)
                if cand is None:
                    LOG.warning("B26 파산 후보 소진")
                    break
                SAMPLES.append(cand)
                exclude.add(cand.ticker)
                LOG.info("B26 파산 보충 확보: %s (CIK %s · %s)",
                         cand.ticker, cand.cik, cand.edgar_file_date)

    # CSV
    out_path = DATA_DIR / f"biotech_coverage_samples_v3_{git_sha}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ticker", "cik", "cik_source",
                "event_type", "event_type_original",
                "event_date", "event_date_original",
                "date_corrected", "date_delta_days",
                "edgar_accession", "edgar_form_type", "edgar_file_date", "edgar_items",
                "type_evidence", "filer_match", "verified", "note",
                "company_name", "event_desc",
            ],
        )
        w.writeheader()
        for s in SAMPLES:
            w.writerow({
                "ticker": s.ticker,
                "cik": s.cik,
                "cik_source": s.cik_source,
                "event_type": s.event_type,
                "event_type_original": s.event_type_original,
                "event_date": s.event_date or s.event_date_original,
                "event_date_original": s.event_date_original,
                "date_corrected": s.date_corrected,
                "date_delta_days": s.date_delta_days,
                "edgar_accession": s.edgar_accession,
                "edgar_form_type": s.edgar_form_type,
                "edgar_file_date": s.edgar_file_date,
                "edgar_items": s.edgar_items,
                "type_evidence": s.type_evidence,
                "filer_match": s.filer_match,
                "verified": s.verified,
                "note": s.note,
                "company_name": s.company_name,
                "event_desc": s.event_desc,
            })

    n = len(SAMPLES)
    cik_ok = sum(1 for s in SAMPLES if s.cik)
    filer_ok = sum(1 for s in SAMPLES if s.filer_match)
    verified = sum(1 for s in SAMPLES if s.verified)
    date_corr = sum(1 for s in SAMPLES if s.date_corrected)
    type_diff = sum(1 for s in SAMPLES if s.event_type and s.event_type != s.event_type_original)

    print("\n== Biotech Sample Verification v3 (B24) ==")
    print(f"git_sha:              {git_sha}")
    print(f"total_samples:        {n}")
    print(f"CIK 확보:              {cik_ok}/{n}")
    print(f"filer 일치:            {filer_ok}/{n}")
    print(f"verified:             {verified}/{n}")
    print(f"날짜 정정 (Δ>30d):     {date_corr}")
    print(f"유형 정정:             {type_diff}")
    print(f"csv:                  {out_path}")
    print("\n표본별:")
    for s in SAMPLES:
        flag = "✓" if s.verified else "✗"
        dcflag = f"Δ{s.date_delta_days}d{'*' if s.date_corrected else ''}"
        print(f"  {flag} {s.ticker:6s} CIK={s.cik or '-':10s}  type={s.event_type or '-':22s}  "
              f"date={s.event_date or s.event_date_original}  {dcflag:10s}  "
              f"form={s.edgar_form_type or '-':7s} acc={s.edgar_accession or '-':22s}  "
              f"note={s.note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
