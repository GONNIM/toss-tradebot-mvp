"""표본 무결성 검증 · SEC EDGAR EFTS 1차 기록 조회 (B22).

각 표본 티커에 대해:
  (a) Form 25 (상장폐지 신고) · 우선순위 1
  (b) 8-K item 2.01 (인수 완료) · Form 25 부재 시 대체
  (c) Chapter 11 관련 filing · 파산

조회 방식: SEC EDGAR EFTS 전문검색 API
  https://efts.sec.gov/LATEST/search-index?q=<query>&forms=<form>&dateRange=custom&startdt=&enddt=

무결성 규칙:
- 티커·이벤트일 ±180일 창 안에서 첫 매치를 확정
- 매치 부재 시 후보 accession 없음 · 미검증 표기
- 사용자 지시 사전 정정: PRQR 제거 · KZR → ACQUIRED 2026-05-11 (Aurinia)

산출: `backend/data/biotech_coverage_samples_v2_{git_sha}.csv`
컬럼: ticker · event_type · event_date · edgar_accession · edgar_form_type · 비고

절대 금지: 결제·구독. API 키 불필요.
실행: ./backend/venv/bin/python backend/scripts/biotech_samples_verify.py
"""
from __future__ import annotations

from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING  # noqa: E402 · WP23

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_verify")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
REQ_INTERVAL = 0.5  # SEC rate limit safety (약 6-7 req/s · 정책 10 req/s 이내)


@dataclass
class Sample:
    ticker: str
    event_type: str   # ACQUIRED / DELISTED / BANKRUPT
    event_date: str   # YYYY-MM-DD (사용자 최초 기재 · 이후 정정 가능)
    event_desc: str
    # 검증 후 채워짐
    edgar_accession: str = ""
    edgar_form_type: str = ""
    edgar_file_date: str = ""
    edgar_company: str = ""
    verified: bool = False
    note: str = ""


# 사용자 지시 정정 반영
SAMPLES: list[Sample] = [
    Sample("HZNP", "ACQUIRED", "2023-10-06", "Horizon Therapeutics → Amgen"),
    Sample("SGEN", "ACQUIRED", "2023-12-14", "Seagen → Pfizer"),
    Sample("GBT",  "ACQUIRED", "2022-10-05", "Global Blood Therapeutics → Pfizer"),
    Sample("ARNA", "ACQUIRED", "2022-03-11", "Arena Pharmaceuticals → Pfizer"),
    Sample("ALXN", "ACQUIRED", "2021-07-21", "Alexion Pharmaceuticals → AstraZeneca"),
    Sample("TRIL", "ACQUIRED", "2021-11-17", "Trillium Therapeutics → Pfizer"),
    Sample("AKUS", "ACQUIRED", "2022-12-22", "Akouos → Eli Lilly"),
    Sample("MYOV", "ACQUIRED", "2023-03-13", "Myovant Sciences → Sumitomo"),
    Sample("DCPH", "ACQUIRED", "2024-06-06", "Deciphera Pharmaceuticals → Ono"),
    Sample("PRVL", "ACQUIRED", "2021-01-22", "Prevail Therapeutics → Eli Lilly"),
    Sample("XLRN", "ACQUIRED", "2021-11-08", "Acceleron Pharma → Merck"),
    Sample("AVEO", "ACQUIRED", "2023-08-04", "AVEO Pharmaceuticals → LG Chem"),
    Sample("KDMN", "ACQUIRED", "2022-09-21", "Kadmon Holdings → Sanofi"),
    Sample("CNCE", "ACQUIRED", "2023-03-06", "Concert Pharmaceuticals → Sun Pharma"),
    Sample("TALS", "ACQUIRED", "2023-11-06", "Talaris → Tourmaline merger"),
    Sample("SYRS", "BANKRUPT", "2024-11-11", "Syros Pharmaceuticals bankruptcy"),
    Sample("VBIV", "DELISTED", "2024-06-11", "VBI Vaccines Nasdaq 상장폐지"),
    Sample("HGEN", "BANKRUPT", "2023-02-27", "Humanigen Chapter 11"),
    # KZR 정정 (사용자 지시): DELISTED 2024-04-01 → ACQUIRED 2026-05-11 (Aurinia)
    Sample("KZR",  "ACQUIRED", "2026-05-11", "Kezar Life Sciences → Aurinia (Fable 정정)"),
    # PRQR 제거 (사용자 지시) · 대체 종목은 별도 EDGAR Form 25 검색 결과로 append
]

# 대체 후보군: 사용자 지시로 EDGAR Form 25 검색으로 발견한 실제 폐지·인수 사례
# (하드코딩 우려 회피: 이 목록은 별도 세션에서 EDGAR Form 25 스캔 결과로 대체 예정)
# 이번 세션에선 EFTS Form 25 검색을 코드로 실행해 후보 추출한다 (아래 find_replacement 함수).


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


def edgar_search(
    client: httpx.Client,
    query: str,
    forms: str,
    start: str,
    end: str,
) -> list[dict]:
    """EDGAR EFTS 검색 · 결과 hits 반환."""
    params = {
        "q": query,
        "dateRange": "custom",
        "startdt": start,
        "enddt": end,
        "forms": forms,
    }
    time.sleep(REQ_INTERVAL)
    try:
        r = client.get(EFTS_BASE, params=params, timeout=20.0)
        if r.status_code != 200:
            LOG.warning("EFTS HTTP %d · q=%s forms=%s", r.status_code, query, forms)
            return []
        data = r.json()
        return data.get("hits", {}).get("hits", [])
    except Exception as e:
        LOG.warning("EFTS ERR %s: %s", type(e).__name__, e)
        return []


def verify_sample(client: httpx.Client, s: Sample) -> None:
    """단일 표본 검증 · Form 25 우선 · 없으면 8-K · 없으면 Ch 11 관련."""
    ev = datetime.strptime(s.event_date, "%Y-%m-%d")
    # 검색 창: 이벤트 ±180일 (M&A 발표 → 완료 몇 개월 · Form 25 는 완료 후 며칠~몇 주)
    start = (ev - timedelta(days=180)).strftime("%Y-%m-%d")
    end = (ev + timedelta(days=180)).strftime("%Y-%m-%d")

    # ticker 를 큰따옴표로 감싸 정확 매치 유도
    q_ticker = f'"{s.ticker}"'
    # 회사명 첫 단어 (fallback · Sample.event_desc 에서 추출)
    company_first = s.event_desc.split()[0] if s.event_desc else s.ticker
    q_company = f'"{company_first}"'

    LOG.info("검증 [%s] type=%s date=%s", s.ticker, s.event_type, s.event_date)

    # 1) Form 25 우선 (상장폐지·deregistration)
    hits = edgar_search(client, q_ticker, "25", start, end)
    if not hits:
        hits = edgar_search(client, q_company, "25", start, end)
    if hits:
        first = hits[0]["_source"]
        s.edgar_accession = first.get("adsh", "")
        s.edgar_form_type = first.get("form", "25")
        s.edgar_file_date = first.get("file_date", "")
        s.edgar_company = (first.get("display_names") or [""])[0]
        s.verified = True
        s.note = "Form 25 확인"
        return

    # 2) 8-K (인수 완료 item 2.01 등)
    if s.event_type == "ACQUIRED":
        hits = edgar_search(client, q_ticker, "8-K", start, end)
        if not hits:
            hits = edgar_search(client, q_company, "8-K", start, end)
        if hits:
            # 이벤트일 ±30일 우선
            target = ev
            best = None
            best_delta = None
            for h in hits[:20]:
                src = h.get("_source", {})
                fd = src.get("file_date", "")
                try:
                    d = datetime.strptime(fd, "%Y-%m-%d")
                except ValueError:
                    continue
                delta = abs((d - target).days)
                if best_delta is None or delta < best_delta:
                    best = src
                    best_delta = delta
            if best is not None:
                s.edgar_accession = best.get("adsh", "")
                s.edgar_form_type = best.get("form", "8-K")
                s.edgar_file_date = best.get("file_date", "")
                s.edgar_company = (best.get("display_names") or [""])[0]
                s.verified = True
                s.note = f"8-K 최근접 (Δ{best_delta}d)"
                return

    # 3) Chapter 11 관련 (파산)
    if s.event_type == "BANKRUPT":
        hits = edgar_search(client, f'{q_ticker} bankruptcy', "8-K", start, end)
        if not hits:
            hits = edgar_search(client, f'{q_company} "Chapter 11"', "8-K", start, end)
        if hits:
            first = hits[0]["_source"]
            s.edgar_accession = first.get("adsh", "")
            s.edgar_form_type = first.get("form", "8-K")
            s.edgar_file_date = first.get("file_date", "")
            s.edgar_company = (first.get("display_names") or [""])[0]
            s.verified = True
            s.note = "Ch 11 관련 8-K"
            return

    # 미검증
    s.note = "1차 기록 미확보 · 표본 제외"


def find_replacement(client: httpx.Client, exclude_tickers: set[str]) -> Sample | None:
    """EDGAR Form 25 검색으로 2021~2026 바이오 폐지·인수 대체 후보 1건 찾기.

    전략:
      - Form 25 · dateRange 2021-01-01~2026-08-31
      - 결과에서 SIC 2834/2836 회사 우선 필터 (display_names / assignee_cik 없어 heuristic)
      - 회사명에 pharma/therapeutics/biosciences 등 바이오 키워드 매칭
      - exclude_tickers 회피
    """
    LOG.info("EDGAR Form 25 대체 후보 검색")
    keywords = ["therapeutics", "pharma", "biosciences", "bio", "genetics"]
    for kw in keywords:
        hits = edgar_search(client, f'"{kw}"', "25", "2021-01-01", "2026-08-31")
        for h in hits[:40]:
            src = h.get("_source", {})
            company = (src.get("display_names") or [""])[0]
            fd = src.get("file_date", "")
            adsh = src.get("adsh", "")
            if not company or not fd or not adsh:
                continue
            # 회사명에서 ticker 추출 시도: "Company Name (TICKER)" 패턴
            import re
            m = re.search(r"\(([A-Z]{2,5})\)", company)
            if not m:
                continue
            tkr = m.group(1)
            if tkr in exclude_tickers:
                continue
            # 바이오 키워드 포함 확인
            low = company.lower()
            if not any(k in low for k in ["therap", "pharma", "biosci", "bio", "genet"]):
                continue
            return Sample(
                ticker=tkr,
                event_type="ACQUIRED",  # Form 25 는 폐지 신고이지만 M&A 후 이어짐이 흔함
                event_date=fd,
                event_desc=f"{company} (EDGAR Form 25 검색 대체)",
                edgar_accession=adsh,
                edgar_form_type="25",
                edgar_file_date=fd,
                edgar_company=company,
                verified=True,
                note="B22 대체 종목 · Form 25 검색",
            )
    return None


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    git_sha = _git_sha()

    with httpx.Client(headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}) as client:
        for s in SAMPLES:
            verify_sample(client, s)

        # 미검증 종목 수 + PRQR 자리(1건) 만큼 대체 확보 · 총 20 verified 목표
        unverified_count = sum(1 for s in SAMPLES if not s.verified)
        needed = 1 + unverified_count  # PRQR 자리 1건 고정 + 미검증 자리 각각
        exclude = {s.ticker for s in SAMPLES} | {"PRQR"}
        replacements: list[Sample] = []
        attempts = 0
        while len(replacements) < needed and attempts < 20:
            repl = find_replacement(client, exclude)
            attempts += 1
            if repl is None:
                LOG.warning("대체 후보 소진 · attempt %d", attempts)
                break
            if repl.ticker in exclude:
                continue
            replacements.append(repl)
            exclude.add(repl.ticker)
            LOG.info("대체 종목 확보 (%d/%d): %s (%s)",
                     len(replacements), needed, repl.ticker, repl.edgar_company)
        SAMPLES.extend(replacements)

    # CSV 산출
    out_path = DATA_DIR / f"biotech_coverage_samples_v2_{git_sha}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ticker", "event_type", "event_date",
                "edgar_accession", "edgar_form_type", "edgar_file_date",
                "edgar_company", "verified", "note", "event_desc",
            ],
        )
        w.writeheader()
        for s in SAMPLES:
            w.writerow({
                "ticker": s.ticker,
                "event_type": s.event_type,
                "event_date": s.event_date,
                "edgar_accession": s.edgar_accession,
                "edgar_form_type": s.edgar_form_type,
                "edgar_file_date": s.edgar_file_date,
                "edgar_company": s.edgar_company,
                "verified": s.verified,
                "note": s.note,
                "event_desc": s.event_desc,
            })

    n = len(SAMPLES)
    verified = sum(1 for s in SAMPLES if s.verified)
    print("\n== Biotech Sample Verification v2 (B22) ==")
    print(f"git_sha:             {git_sha}")
    print(f"total_samples:       {n}")
    print(f"verified (accession 확보): {verified}")
    print(f"unverified:          {n - verified}")
    print(f"csv:                 {out_path}")
    print("\n표본별 검증:")
    for s in SAMPLES:
        flag = "✓" if s.verified else "✗"
        print(f"  {flag} {s.ticker:6s} {s.event_type:9s} {s.event_date}  "
              f"acc={s.edgar_accession or '-':22s} form={s.edgar_form_type or '-':6s} "
              f"filed={s.edgar_file_date or '-':10s} note={s.note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
