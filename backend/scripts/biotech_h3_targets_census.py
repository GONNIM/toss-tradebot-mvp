"""H3 종목 단위 census + CIK 등록명 대조표 + 바이오 자격 필터 (B49·B50·B51).

산출:
1) `backend/data/h3_activist_cik_registry_{git_sha}.csv`  (B49-1)
   컬럼: institution · cik · registrant_name · 비고
2) `backend/data/h3_targets_{git_sha}.csv`  (B49-2 + B50)
   컬럼: ticker · target_cik · target_name · sic · sic_biotech
         · institutions · sc13d_new · sc13g_new · form4_all · total_events
         · first_event_date · listing_status · form25_accession · form25_date

이벤트 정의 (B51 고정 · 2026-09-02):
- 신규 SC 13D · 신규 SC 13G · Form 4 (all · transaction code 필터는 별건)
- 13D/A · 13G/A · Form 4/A 는 census 집계에 포함하지만 신호(이벤트)에서 제외
- ⚠ Form 4 transaction code P 필터는 XML 본문 파싱 필요 · 이번 세션 스코프 밖 · 후속

원칙 (B47 독립 운영):
- biotech 독립 이름공간 · 기존 activist 코드 수정 금지
- setup_secure_logging 재사용 (backend.services.config import)

실행:
    python -m backend.scripts.biotech_h3_targets_census
"""
from __future__ import annotations

from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING  # noqa: E402 · WP23

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_h3_targets")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
REQ_INTERVAL = 0.5

DATE_START = "2021-09-01"
DATE_END = "2026-09-01"
FORM_25 = {"25", "25-NSE"}
BIOTECH_SICS = {"2834", "2836"}

# B49 재사용 · biotech_h3_filing_census.py 의 INSTITUTIONS 정의 동일
from backend.scripts.biotech_h3_filing_census import INSTITUTIONS, load_seed_activists, resolve_cik


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
    delay = REQ_INTERVAL
    for attempt in range(retries):
        time.sleep(delay)
        try:
            r = client.get(url, params=params, timeout=25.0)
            if r.status_code < 500:
                return r
        except Exception as e:
            LOG.warning("HTTP ERR %s: %s (retry %d)", type(e).__name__, e, attempt + 1)
        delay = min(delay * 3, 5.0)
    return None


def fetch_submissions(client: httpx.Client, cik: str) -> dict | None:
    url = f"{SUBMISSIONS_BASE}/CIK{cik.zfill(10)}.json"
    r = _get(client, url)
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


def collect_events_per_institution(client: httpx.Client, inst) -> list[dict]:
    """기관 name 기준 EFTS 검색 · 각 filing 의 (target_cik, form, date, accession) 수집.

    B52 수정 (2026-09-02): EFTS `forms=` 다중 파라미터 (comma-separated) 사용 시
    응답에서 신규 filing 이 누락되는 이상 동작 확인. 각 form 을 개별 검색으로 분리.
    hit._source.ciks 에서 fund CIK 아닌 것 = target.
    dedupe: (accession, target_cik) 키로 중복 배제 (여러 검색어에서 중복 등장).
    """
    fund_ciks = {c["cik"].lstrip("0") for c in inst.ciks}
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for q in inst.search_queries:
        # 각 form 을 개별 검색 (다중 파라미터 이상 동작 회피)
        for single_form in ["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "4", "4/A"]:
            for from_offset in range(0, 1000, 100):
                r = _get(client, EFTS_BASE, {
                    "q": q,
                    "forms": single_form,
                    "dateRange": "custom",
                    "startdt": DATE_START,
                    "enddt": DATE_END,
                    "from": from_offset,
                })
                if r is None or r.status_code != 200:
                    break
                try:
                    data = r.json()
                except Exception:
                    break
                hits = data.get("hits", {}).get("hits", [])
                if not hits:
                    break
                for h in hits:
                    src = h.get("_source", {})
                    ciks_in_hit = src.get("ciks") or []
                    form = src.get("form", "")
                    if form != single_form:
                        continue
                    file_date = src.get("file_date", "")
                    accession = src.get("adsh", "")
                    if not ciks_in_hit:
                        continue
                    # SEC EDGAR 관례: ciks[0] = subject/issuer · ciks[1]+ = filer 계열
                    # SC 13D/G · Form 4 는 subject 1건이 원칙 → ciks[0] 만 target 으로
                    target = ciks_in_hit[0]
                    if target.lstrip("0") in fund_ciks:
                        # fund 자신이 subject? 이상 · 스킵 (self-filing)
                        continue
                    key = (accession, target)
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append({
                        "institution": inst.name,
                        "target_cik": target,
                        "form": form,
                        "file_date": file_date,
                        "accession": accession,
                    })
                if len(hits) < 100:
                    break
    return events


def recover_ticker_from_form25(client: httpx.Client, cik: str, acc: str) -> tuple[str, str]:
    """25-NSE primary document 에서 ticker 파싱 시도.
    반환: (ticker, source_note)
    """
    if not acc:
        return "", "no accession"
    acc_no_dash = acc.replace("-", "")
    # 25-NSE index.json 조회로 primary document 찾기
    idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dash}/{acc}-index.json"
    r = _get(client, idx_url)
    if r is None or r.status_code != 200:
        return "", f"index.json HTTP {r.status_code if r else '-'}"
    try:
        idx = r.json()
    except Exception:
        return "", "index.json parse fail"
    items = idx.get("directory", {}).get("item", [])
    primary_doc = None
    for it in items:
        nm = it.get("name", "")
        if nm.endswith(".xml"):
            primary_doc = nm
            break
    if not primary_doc:
        # fallback: 첫 non-index 항목
        for it in items:
            nm = it.get("name", "")
            if nm and not nm.startswith("0000") and not nm.endswith("-index.json"):
                primary_doc = nm
                break
    if not primary_doc:
        return "", "no primary doc in index"
    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_no_dash}/{primary_doc}"
    r2 = _get(client, doc_url)
    if r2 is None or r2.status_code != 200:
        return "", f"doc HTTP {r2.status_code if r2 else '-'}"
    text = r2.text
    # 티커 파싱 · Form 25 XML 에는 <issuerTradingSymbol> 또는 유사 태그
    import re
    # 다양한 XML 태그 시도
    for pattern in [
        r"<issuerTradingSymbol[^>]*>([^<]+)</issuerTradingSymbol>",
        r"<tradingSymbol[^>]*>([^<]+)</tradingSymbol>",
        r"<issuerSymbol[^>]*>([^<]+)</issuerSymbol>",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip(), f"form25 XML tag ({pattern[:30]}...)"
    # HTML 25-NSE 표에서 심볼 추출 (텍스트 기반 · 폴백)
    # 일반적으로 "Common Stock ... TICKER" 패턴
    m = re.search(r"([A-Z]{1,5})\s*</td>", text[:20000])
    if m:
        return m.group(1), "form25 HTML text fallback"
    return "", "form25 unparsed"


def recover_ticker_from_10x(client: httpx.Client, subs: dict) -> tuple[str, str]:
    """10-K/10-Q 표지에서 ticker 파싱 · submissions.filings.recent 에서 최근 10-K/10-Q 조회."""
    cik = subs.get("cik", "").lstrip("0")
    if not cik:
        return "", "no cik"
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accs = recent.get("accessionNumber", [])
    for i, f in enumerate(forms):
        if f in ("10-K", "10-Q"):
            acc = accs[i] if i < len(accs) else ""
            if not acc:
                continue
            t, note = recover_ticker_from_form25(client, cik, acc)  # 동일 파서 재사용
            if t:
                return t, f"10x ({f}) " + note
    return "", "no 10-K/10-Q found"


def check_target_listing(client: httpx.Client, cik: str, recover_ticker: bool = True) -> dict:
    """target 상장 상태 + SIC + name + tickers · Form 25 accession/date.
    B53: DELISTED 종목은 tickers 공백 시 25-NSE + 10-K/10-Q 파싱 순차 시도.
    """
    subs = fetch_submissions(client, cik)
    if subs is None:
        return {"status": "SUBMISSIONS_UNAVAILABLE", "name": "", "sic": "", "tickers": [],
                "form25_acc": "", "form25_date": "", "ticker_source": ""}
    name = subs.get("name", "")
    sic = subs.get("sic", "")
    tickers = subs.get("tickers", [])
    ticker_source = "submissions.tickers" if tickers else ""
    recent = subs.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])

    form25_acc = ""
    form25_date = ""
    for i, f in enumerate(forms):
        if f in FORM_25:
            form25_acc = accs[i] if i < len(accs) else ""
            form25_date = dates[i] if i < len(dates) else ""
            break

    if form25_acc:
        status = "DELISTED"
    elif dates:
        try:
            last = datetime.strptime(dates[0], "%Y-%m-%d")
            days = (datetime.now() - last).days
            status = "INACTIVE_FILER" if days > 365 * 2 else "ACTIVE"
        except ValueError:
            status = "UNKNOWN"
    else:
        status = "UNKNOWN"

    # B53 · 티커 복구
    recovered_ticker = ""
    if recover_ticker and status == "DELISTED" and not tickers:
        recovered_ticker, ts = recover_ticker_from_form25(client, cik.zfill(10), form25_acc)
        if recovered_ticker:
            ticker_source = ts
        else:
            recovered_ticker, ts = recover_ticker_from_10x(client, subs)
            if recovered_ticker:
                ticker_source = ts
            else:
                ticker_source = "미복구 · " + ts

    tickers_final = tickers if tickers else ([recovered_ticker] if recovered_ticker else [])

    return {
        "status": status,
        "name": name,
        "sic": sic,
        "tickers": tickers_final,
        "form25_acc": form25_acc,
        "form25_date": form25_date,
        "ticker_source": ticker_source,
    }


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from backend.services import config as _config  # noqa: F401 · B44 보안 경로

    git_sha = _git_sha()
    seed = load_seed_activists()

    with httpx.Client(
        headers={"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}
    ) as client:
        # ─ B49-1 · CIK 등록명 대조표 ─
        for inst in INSTITUTIONS:
            resolve_cik(client, inst, seed)

        registry_rows: list[dict] = []
        for inst in INSTITUTIONS:
            for c in inst.ciks:
                subs = fetch_submissions(client, c["cik"])
                reg_name = subs.get("name", "") if subs else ""
                registry_rows.append({
                    "institution": inst.name,
                    "cik": c["cik"],
                    "registrant_name": reg_name,
                    "note": c["source"],
                })
        registry_path = DATA_DIR / f"h3_activist_cik_registry_{git_sha}.csv"
        with open(registry_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["institution", "cik", "registrant_name", "note"])
            w.writeheader()
            w.writerows(registry_rows)
        LOG.info("registry saved: %s (%d rows)", registry_path, len(registry_rows))

        # ─ B49-2 · 종목 단위 census ─
        # 1) 기관별 이벤트 전수 수집
        all_events: list[dict] = []
        for inst in INSTITUTIONS:
            LOG.info("[%s] 이벤트 수집", inst.name)
            events = collect_events_per_institution(client, inst)
            LOG.info("[%s] %d events", inst.name, len(events))
            all_events.extend(events)

        # 2) target 별 aggregate
        by_target: dict[str, dict] = {}
        for e in all_events:
            t = e["target_cik"]
            if t not in by_target:
                by_target[t] = {
                    "target_cik": t,
                    "institutions": set(),
                    "sc13d_new": 0,
                    "sc13g_new": 0,
                    "form4_all": 0,
                    "form_amendment_count": 0,
                    "form_other_count": 0,
                    "first_event_date": "",
                    "accession_first_event": "",
                }
            b = by_target[t]
            b["institutions"].add(e["institution"])
            form = e["form"]
            # B51 이벤트 정의: 신규 SC 13D · 신규 SC 13G · Form 4 (매수 필터는 후속)
            is_event = False
            if form == "SC 13D":
                b["sc13d_new"] += 1
                is_event = True
            elif form == "SC 13G":
                b["sc13g_new"] += 1
                is_event = True
            elif form == "4":
                b["form4_all"] += 1
                is_event = True
            elif form.endswith("/A"):
                b["form_amendment_count"] += 1
            else:
                b["form_other_count"] += 1
            # first_event_date 갱신 (이벤트만 대상)
            if is_event and e["file_date"]:
                if not b["first_event_date"] or e["file_date"] < b["first_event_date"]:
                    b["first_event_date"] = e["file_date"]
                    b["accession_first_event"] = e["accession"]

        LOG.info("unique targets: %d · 상장 상태 확인 + 티커 복구 시작", len(by_target))
        # 3) target 각각 상태·SIC·ticker (B53 티커 복구)
        for i, (cik, b) in enumerate(by_target.items(), 1):
            if i % 50 == 0:
                LOG.info("listing+ticker recovery %d/%d", i, len(by_target))
            info = check_target_listing(client, cik, recover_ticker=True)
            b["target_name"] = info["name"]
            b["sic"] = info["sic"]
            b["sic_biotech"] = info["sic"] in BIOTECH_SICS
            b["ticker"] = info["tickers"][0] if info["tickers"] else ""
            b["ticker_source"] = info["ticker_source"]
            b["listing_status"] = info["status"]
            b["form25_accession"] = info["form25_acc"]
            b["form25_date"] = info["form25_date"]

        # 4) CSV 저장 (v2 · P0 수정 반영)
        targets_path = DATA_DIR / f"h3_targets_v2_{git_sha}.csv"
        with open(targets_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ticker", "ticker_source", "target_cik", "target_name", "sic", "sic_biotech",
                "institutions", "sc13d_new", "sc13g_new", "form4_all",
                "form_amendment_count", "form_other_count",
                "total_events",
                "first_event_date", "accession_first_event",
                "listing_status", "form25_accession", "form25_date",
            ])
            w.writeheader()
            for b in by_target.values():
                total_events = b["sc13d_new"] + b["sc13g_new"] + b["form4_all"]
                w.writerow({
                    "ticker": b.get("ticker", ""),
                    "ticker_source": b.get("ticker_source", ""),
                    "target_cik": b["target_cik"],
                    "target_name": b.get("target_name", ""),
                    "sic": b.get("sic", ""),
                    "sic_biotech": b.get("sic_biotech", False),
                    "institutions": ";".join(sorted(b["institutions"])),
                    "sc13d_new": b["sc13d_new"],
                    "sc13g_new": b["sc13g_new"],
                    "form4_all": b["form4_all"],
                    "form_amendment_count": b["form_amendment_count"],
                    "form_other_count": b["form_other_count"],
                    "total_events": total_events,
                    "first_event_date": b["first_event_date"],
                    "accession_first_event": b["accession_first_event"],
                    "listing_status": b.get("listing_status", ""),
                    "form25_accession": b.get("form25_accession", ""),
                    "form25_date": b.get("form25_date", ""),
                })
        LOG.info("targets saved: %s (%d rows)", targets_path, len(by_target))

        # summary
        total = len(by_target)
        biotech_qualified = sum(1 for b in by_target.values() if b["sic_biotech"])
        biotech_delisted = sum(1 for b in by_target.values() if b["sic_biotech"] and b["listing_status"] == "DELISTED")
        biotech_active = sum(1 for b in by_target.values() if b["sic_biotech"] and b["listing_status"] == "ACTIVE")
        non_bio_excluded = total - biotech_qualified
        with_ticker = sum(1 for b in by_target.values() if b["ticker"])

        import math
        eodhd_days = math.ceil(biotech_delisted / 20) if biotech_delisted else 0

        print("\n== B49·B50 종목 단위 census ==")
        print(f"git_sha:                     {git_sha}")
        print(f"registry_rows (CIK):         {len(registry_rows)}")
        print(f"total_unique_targets:        {total}")
        print(f"targets_with_ticker:         {with_ticker}")
        print(f"biotech_qualified (SIC 2834/2836): {biotech_qualified}")
        print(f"non_biotech_excluded:        {non_bio_excluded}")
        print(f"biotech_delisted:            {biotech_delisted}")
        print(f"biotech_active:              {biotech_active}")
        print(f"eodhd_split_days (biotech delisted only): ceil({biotech_delisted}/20) = {eodhd_days}")
        print(f"registry_csv:                {registry_path}")
        print(f"targets_csv:                 {targets_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
