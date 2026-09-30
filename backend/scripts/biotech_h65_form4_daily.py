"""WP65 · Form 4 증분 수집 (일일 파이프 · 최근 30일 · 55 CIK).

WP28-2 는 전량 수집 (55 CIK · Form 4 최근 60건) · 이건 초회 백필.
WP65 는 일일 증분: 각 filer 의 submissions.json 최신 accession · 이미 캐시 있는지 확인 후 신규만 append.

**출력**:
- 캐시 갱신: `backend/data/h28v2_form4_issuer_buys_{sha}.json` (덧붙임)
- rumor daily 리포트에 표 4 병기 · radar 순위표에 "임원·대주주 매수" 꼬리표

**하단 문구** (표 4):
- "잠정 확인 → **유보 강등** · WP63-3 견고성 (d) 13D 중복 제외 CI 하한 < 0 · 60일 전향 재평가 (2026-11-15)"
- 소액 실전 규칙 적용
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha
from backend.scripts.biotech_h28v2_form4_channel import (
    load_fund_ciks, sec_get, fetch_form4_accessions, fetch_form4_xml, parse_form4,
)
from backend.scripts.biotech_sec_common import SecDailyLedger, build_client

import csv
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


from backend.scripts import _biotech_paths as _P

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h65_form4_daily")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def sec_client(on_request):
    """WP88-2 · 공용 build_client (단일 헤더 상수) + 요청마다 장부에 세는 hook · 시간 제한은 예전과 같은 30초."""
    return build_client(event_hooks={"request": [on_request]}, timeout=30.0)


PRICE_BACKFILL_MAX = 10   # 하루 가격 보충 신고서 수 상한 (SEC 요청 증가 제한)


def backfill_prices(cache: dict, cutoff: str, fetch_xml) -> int:
    """가격 키가 없는 최근 매수 → 신고서 XML 을 다시 읽어 (tx_date, shares) 로 맞춰 가격 채움 · 못 찾으면 None 기록 (재요청 없음)."""
    todo: dict[tuple[str, str], list[dict]] = {}
    for filer, info in cache.items():
        for b in info.get("buys", []):
            if "price" not in b and b.get("tx_date", "") >= cutoff and b.get("accession"):
                todo.setdefault((filer, b["accession"]), []).append(b)
    done = 0
    for (filer, acc), buys in list(todo.items())[:PRICE_BACKFILL_MAX]:
        try:
            xml = fetch_xml(filer, acc)
        except Exception:
            continue
        parsed = parse_form4(xml) if xml else []
        for b in buys:
            hit = next((p for p in parsed if p["tx_date"] == b.get("tx_date") and abs(p["shares"] - float(b.get("shares", 0))) < 0.5), None)
            b["price"] = hit["price"] if hit else None
        done += 1
    return done


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if _P.find(f"h3_events_{sha}.csv") is None:
        fb = _P.data_sha_auto("h3_targets_v2_*.csv")
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    fund_ciks = load_fund_ciks()
    LOG.info("filers (WP28-2 55 CIK): %d", len(fund_ciks))
    if not fund_ciks:
        # WP78 · 2026-09-21~28 서버에서 입력 파일 부재로 0 filer "성공" 처리되던 결함 · 이제 실패로 드러냄 (파이프는 skip 허용)
        LOG.error("filer 목록 0 · 입력 파일 부재 · Form 4 단계 실패")
        raise SystemExit(2)

    cache_read = _P.find(f"h28v2_form4_issuer_buys_{sha}.json") or _P.find_glob("h28v2_form4_issuer_buys_*.json")
    cache = json.loads(cache_read.read_text()) if cache_read is not None and cache_read.exists() else {}
    # 산출 위치는 flat (RUNTIME 최상위 or backend/data)
    cache_path = _P.out_flat(f"h28v2_form4_issuer_buys_{sha}.json")

    # 최근 30일 컷오프
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    new_buys = 0
    price_fills = 0
    # WP87-2 · 하루 SEC 요청 공용 장부 · 이 단계의 모든 요청을 보내기 직전에 센다 (form4 · price_backfill 구분)
    ledger = SecDailyLedger.load()
    stage = {"cat": "form4"}

    def _count(_request):
        ledger.add(stage["cat"])

    try:
        with sec_client(_count) as client:
            for i, filer_cik in enumerate(fund_ciks, 1):
                try:
                    accs = fetch_form4_accessions(client, filer_cik)
                except Exception:
                    continue
                # 30일 이내 accession 만
                recent = [a for a in accs if a.get("date", "") >= cutoff]
                if not recent:
                    continue
                # 기존 accession 세트
                existing = set()
                for b in cache.get(filer_cik, {}).get("buys", []):
                    if b.get("accession"):
                        existing.add(b["accession"])
                fresh_recent = [a for a in recent if a["accession"] not in existing]
                if not fresh_recent:
                    continue
                LOG.info("[%d/%d] filer %s: +%d fresh accessions (30d)", i, len(fund_ciks), filer_cik, len(fresh_recent))
                for a in fresh_recent[:20]:  # 하루당 filer 최대 20건
                    try:
                        xml = fetch_form4_xml(client, filer_cik, a["accession"])
                    except Exception:
                        continue
                    if xml is None:
                        continue
                    for b in parse_form4(xml):
                        b["filing_date"] = a["date"]
                        b["filer_cik"] = filer_cik
                        b["accession"] = a["accession"]
                        if filer_cik not in cache:
                            cache[filer_cik] = {"n_accs": 0, "n_buys": 0, "buys": []}
                        cache[filer_cik]["buys"].append(b)
                        cache[filer_cik]["n_buys"] = len(cache[filer_cik]["buys"])
                        new_buys += 1
            # WP87 · 가격 보충 · 예전 캐시 (가격 필드 없음) 의 최근 30일 매수 · 신고서 1건당 1회 · 한 번에 최대 10건
            stage["cat"] = "price_backfill"
            price_fills = backfill_prices(cache, cutoff, lambda f, acc: fetch_form4_xml(client, f, acc))
    finally:
        ledger.save()
        LOG.info("SEC 요청 · form4 %d · 가격 보충 %d · 오늘 합계 %d", ledger.counts.get("form4", 0),
                 ledger.counts.get("price_backfill", 0), ledger.total())

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    LOG.info("증분 · 신규 buys: +%d · 전체 filers cached: %d · 가격 보충 신고서 %d건", new_buys, len(cache), price_fills)

    # 표 4 · 최근 20 거래일 F4 매수 (rumor daily 확장용)
    # 정정 (2026-09-14): 제출자 유형 (전문 펀드/임원·이사/기타) + 매수 금액 근사 열 추가
    cutoff_20d = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")  # 20 거래일 ≈ 30 달력일

    # 제출자 유형 판정 · h41_filer_classification 활용
    filer_class_path = _P.find("h41_filer_classification.json")
    filer_class = json.loads(filer_class_path.read_text()) if filer_class_path is not None and filer_class_path.exists() else {}

    def _filer_type(filer_cik: str) -> str:
        info = filer_class.get(filer_cik, {})
        bucket = info.get("bucket", "")
        name = info.get("name", "")
        et = info.get("entityType", "").lower()
        if bucket == "fund":
            return "전문 펀드"
        if bucket == "individual" or "individual" in et:
            return "임원·이사"
        if bucket == "strategic_corporate":
            return "기타 (전략적 기업)"
        return "기타"

    # 발행사 티커·가격 매핑 (매수일 종가 조회용)
    from backend.scripts.biotech_h63_f4_backtest import load_cik_ticker
    from backend.scripts.biotech_h3_backtest import load_prices
    cik2tk = load_cik_ticker(sha)
    # WP69-3g: h3_prices_merged 없으면 빈 dict (미산정)
    _p_prices = _P.find(f"h3_prices_merged_{sha}.csv") or _P.find_glob("h3_prices_merged_*.csv")
    prices = load_prices(_p_prices) if _p_prices is not None else {}

    def _price_on(ticker: str, date_str: str) -> float | None:
        sp = prices.get(ticker, {})
        if not sp or not date_str:
            return None
        keys = sorted(sp.keys())
        for k in keys:
            if k >= date_str:
                return sp[k]
        return None

    table4 = []
    for filer_cik, info in cache.items():
        for b in info.get("buys", []):
            tx_date = b.get("tx_date", "")
            if tx_date >= cutoff_20d:
                elapsed_days = (datetime.now(timezone.utc).date() - datetime.strptime(tx_date, "%Y-%m-%d").date()).days if tx_date else 0
                issuer_cik = (b.get("issuer_cik", "") or "").zfill(10)
                shares = float(b.get("shares", 0) or 0)
                # 매수 금액 근사 = 주식수 × 매수일 종가
                tk = cik2tk.get(issuer_cik, "")
                price = _price_on(tk, tx_date) if tk else None
                amount_usd = shares * price if (price and shares) else None
                px = b.get("price")   # WP87 · 신고서 기재 주당 가격 (없으면 None → 화면 "금액 미기재")
                table4.append({
                    "price_per_share": px,
                    "amount_usd_reported": round(shares * px) if (px and shares) else None,
                    "filer_name": filer_class.get(filer_cik, {}).get("name", ""),
                    "filing_date": b.get("filing_date", ""),
                    "tx_date": tx_date,
                    "elapsed_days": elapsed_days,
                    "issuer_cik": issuer_cik,
                    "issuer_name": b.get("issuer_name", ""),
                    "issuer_ticker": tk,   # WP85 · 화면 티커 표시 (없으면 빈 값)
                    "filer_cik": filer_cik,
                    "filer_type": _filer_type(filer_cik),
                    "shares": int(shares) if shares else 0,
                    "price_on_tx": round(price, 4) if price else None,
                    "amount_usd_approx": round(amount_usd) if amount_usd else None,
                    "accession": b.get("accession", ""),
                })
    table4.sort(key=lambda x: x["tx_date"], reverse=True)
    table4 = table4[:30]  # 최근 30건

    out_csv = _P.out_flat(f"h65_form4_daily_table_{sha}.csv")
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["filing_date", "tx_date", "elapsed_days", "issuer_cik", "issuer_name",
                    "filer_cik", "filer_type", "shares", "price_on_tx", "amount_usd_approx", "accession", "issuer_ticker",
                    "filer_name", "price_per_share", "amount_usd_reported"])
        for row in table4:
            w.writerow([row["filing_date"], row["tx_date"], row["elapsed_days"],
                        row["issuer_cik"], row["issuer_name"], row["filer_cik"],
                        row.get("filer_type", ""), row["shares"], row.get("price_on_tx", ""),
                        row.get("amount_usd_approx", ""), row["accession"], row.get("issuer_ticker", ""),
                        row.get("filer_name", ""), row.get("price_per_share") if row.get("price_per_share") is not None else "",
                        row.get("amount_usd_reported") if row.get("amount_usd_reported") is not None else ""])

    # 순위표 꼬리표용 issuer_cik 세트
    tagged_ciks = {row["issuer_cik"] for row in table4}
    tag_out = _P.out_flat(f"h65_f4_tag_ciks_{sha}.json")
    tag_out.write_text(json.dumps(sorted(tagged_ciks), ensure_ascii=False, indent=2))

    print(json.dumps({
        "git_sha": sha,
        "new_buys_added": new_buys,
        "total_filers_cached": len(cache),
        "table4_rows": len(table4),
        "table4_csv": str(out_csv),
        "tagged_issuer_ciks": len(tagged_ciks),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
