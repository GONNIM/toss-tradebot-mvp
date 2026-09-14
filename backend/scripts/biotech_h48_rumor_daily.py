"""WP48-0 · 첫 소문 보고서 (apewisdom ∩ 바이오 우주 · 상위 10).

용도:
- apewisdom 전체 상위 (all-stocks · 3페이지 · rank ~300)
- 바이오 우주: h3_targets_v2 SIC 2834/2836 ∪ biotech_ticker_set ∪ Tiingo US Stock (부분)
- 교집합 → 상위 10 · 언급 수 · 24h 변화 · 순위
- 각 종목: CT.gov 완료 예정일 (최근 60일 안) · 최근 8-K 여부 (submissions.recent)
- 산출: docs/plans/biotech/rumor-daily/2026-09-14.md (사용자 지시 날짜 준수)

원칙:
- 선언 UA (SEC 지정 헤더 재사용) · 간격 준수
- 본문 저장 금지 · 제목·수치·링크만
- 개인정보 저장 금지 (사용자명 · 답글 내용 등)
- 특정 게시글을 추천 근거로 쓰지 않음
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING, REQ_INTERVAL

import csv
import json
import logging
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h48_rumor_daily")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"

APEWISDOM = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{page}"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
SUBMISSIONS = "https://data.sec.gov/submissions"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_biotech_universe(sha: str) -> tuple[set[str], dict[str, dict]]:
    """biotech ticker set + h3_targets_v2 sic bio · ticker → {cik, name} 매핑."""
    universe: set[str] = set()
    meta: dict[str, dict] = {}
    p = DATA_DIR / f"biotech_ticker_set_{sha}.csv"
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                t = (r.get("ticker") or "").strip()
                n = (r.get("name") or "").strip()
                if t and t != "-":
                    universe.add(t)
                    meta.setdefault(t, {"name": n, "cik": ""})
    p2 = DATA_DIR / f"h3_targets_v2_{sha}.csv"
    if p2.exists():
        with p2.open() as f:
            for r in csv.DictReader(f):
                if r.get("sic_biotech") != "True":
                    continue
                t = (r.get("ticker") or "").strip()
                n = (r.get("target_name") or "").strip()
                cik = (r.get("target_cik") or "").zfill(10)
                if t:
                    universe.add(t)
                    meta.setdefault(t, {"name": n, "cik": cik})
                    if not meta[t].get("cik"):
                        meta[t]["cik"] = cik
    return universe, meta


def fetch_apewisdom(client: httpx.Client, pages: int = 3) -> list[dict]:
    out = []
    for p in range(1, pages + 1):
        try:
            r = client.get(APEWISDOM.format(page=p), timeout=30.0)
            r.raise_for_status()
            for e in r.json().get("results", []):
                out.append(e)
        except Exception as e:
            LOG.warning("apewisdom page %d fail: %s", p, e)
            break
        time.sleep(1.0)
    return out


def fetch_ctgov_upcoming(client: httpx.Client, sponsor_name: str, days_ahead: int = 60) -> list[dict]:
    """스폰서명으로 CT.gov 검색 · 완료 예정일 (primaryCompletionDate) 최근/향후."""
    if not sponsor_name:
        return []
    try:
        r = client.get(CTGOV, params={
            "query.term": sponsor_name,
            "query.leadSponsor": sponsor_name,
            "pageSize": 20,
            "format": "json",
            "fields": "protocolSection.identificationModule.nctId,protocolSection.statusModule.overallStatus,protocolSection.statusModule.primaryCompletionDateStruct,protocolSection.designModule.phases,protocolSection.identificationModule.briefTitle",
        }, timeout=30.0)
        if r.status_code != 200:
            return []
        studies = r.json().get("studies", [])
        today = datetime.now(timezone.utc).date()
        upcoming = []
        for st in studies:
            ps = st.get("protocolSection", {})
            status = ps.get("statusModule", {}).get("overallStatus", "")
            if status not in ("RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED"):
                continue
            date_str = ps.get("statusModule", {}).get("primaryCompletionDateStruct", {}).get("date", "")
            if not date_str:
                continue
            try:
                d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            delta = (d - today).days
            if -30 <= delta <= days_ahead:
                nct = ps.get("identificationModule", {}).get("nctId", "")
                phases = "|".join(ps.get("designModule", {}).get("phases", []))
                upcoming.append({"nct": nct, "date": date_str[:10], "delta_days": delta, "phases": phases, "status": status})
        upcoming.sort(key=lambda x: abs(x["delta_days"]))
        return upcoming[:3]
    except Exception as e:
        LOG.debug("ct.gov fail %s: %s", sponsor_name, e)
        return []


def fetch_recent_8k(client: httpx.Client, cik10: str) -> tuple[bool, str]:
    if not cik10 or cik10 == "0000000000":
        return (False, "no_cik")
    try:
        time.sleep(REQ_INTERVAL)
        r = client.get(f"{SUBMISSIONS}/CIK{cik10}.json", timeout=30.0)
        if r.status_code != 200:
            return (False, f"http_{r.status_code}")
        recent = r.json().get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        today = datetime.now(timezone.utc).date()
        for i, f in enumerate(forms[:30]):
            if f != "8-K":
                continue
            try:
                d = datetime.strptime(dates[i], "%Y-%m-%d").date()
            except Exception:
                continue
            if (today - d).days <= 14:
                return (True, dates[i])
        return (False, "no_recent_14d")
    except Exception:
        return (False, "err")


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    LOG.info("git_sha=%s", sha)

    universe, meta = load_biotech_universe(sha)
    LOG.info("biotech universe: %d tickers · meta rows: %d", len(universe), len(meta))

    ua_ape = {"User-Agent": "TossTradebot-BiotechRadar biotech-radar@sung2011103.dev", "Accept": "application/json"}
    ua_sec = {"User-Agent": SEC_UA, "From": SEC_FROM, "Accept-Encoding": SEC_ACCEPT_ENCODING}

    with httpx.Client(headers=ua_ape) as c1:
        ape = fetch_apewisdom(c1, pages=3)
    LOG.info("apewisdom entries: %d", len(ape))

    # 바이오 우주 교집합
    hits = []
    for e in ape:
        tk = (e.get("ticker") or "").upper()
        if tk not in universe:
            continue
        def _i(v):
            try:
                return int(v)
            except Exception:
                return 0
        mc = _i(e.get("mentions"))
        mp = _i(e.get("mentions_24h_ago"))
        change_pct = round(100 * (mc - mp) / max(1, mp), 1) if mp else None
        hits.append({
            "rank": _i(e.get("rank")),
            "ticker": tk,
            "name": (e.get("name") or "").strip() or meta.get(tk, {}).get("name", ""),
            "mentions_24h": mc,
            "mentions_24h_ago": mp,
            "change_pct": change_pct,
            "upvotes": _i(e.get("upvotes")),
        })
    hits.sort(key=lambda x: x["rank"])
    top10 = hits[:10]
    LOG.info("biotech hits: %d · top10: %s", len(hits), [(h["ticker"], h["rank"]) for h in top10])

    # 각 종목의 CT.gov 예정 · 최근 8-K
    with httpx.Client(headers=ua_sec) as c_sec:
        with httpx.Client(headers={"User-Agent": ua_ape["User-Agent"]}) as c_ct:
            for h in top10:
                nm = h["name"] or meta.get(h["ticker"], {}).get("name", "")
                cik = meta.get(h["ticker"], {}).get("cik", "")
                h["ctgov_upcoming"] = fetch_ctgov_upcoming(c_ct, nm)
                time.sleep(0.5)
                has_8k, note = fetch_recent_8k(c_sec, cik)
                h["recent_8k_14d"] = has_8k
                h["recent_8k_note"] = note

    # 저장
    out_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "rumor-daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path = out_dir / f"{today}.md"

    lines = [
        f"# 소문 감시 일일 보고서 · {today} (WP48-0 · 첫 보고 · UTC)",
        "",
        "> ⚠️ **토론방 소문은 진위 미검증 · 참고용** · 매수 신호 아님 · 소액 실전 규칙 적용",
        "",
        f"- 소스: apewisdom (레딧 종합 top ~300) ∩ 바이오 우주 ({len(universe)} 티커)",
        f"- 바이오 매치: **{len(hits)}종목** · 상위 10 표시",
        "",
        "## 상위 10 (오늘 언급)",
        "",
        "| # | 티커 | 회사 | 오늘 언급 | 24h 전 | 변화% | CT.gov 예정 (최근/향후 30~60일) | 최근 8-K (14일) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h in top10:
        ct_summary = ""
        if h.get("ctgov_upcoming"):
            first = h["ctgov_upcoming"][0]
            ct_summary = f"{first['nct']} · {first['date']} (D{first['delta_days']:+d}) · {first['phases'] or 'n/a'}"
        recent_note = "✅ " + h["recent_8k_note"] if h.get("recent_8k_14d") else "—"
        lines.append(
            f"| {h['rank']} | **{h['ticker']}** | {h['name'][:40]} | {h['mentions_24h']} | {h['mentions_24h_ago']} | {h['change_pct']:+.1f}% | {ct_summary or '—'} | {recent_note} |"
        )
    lines += [
        "",
        "## 급등 경보 (평소 대비 5배 이상)",
        "",
    ]
    surge = [h for h in top10 if h["change_pct"] and h["change_pct"] >= 400]
    if surge:
        for h in surge:
            lines.append(f"- **{h['ticker']}** · {h['change_pct']:+.1f}% ({h['mentions_24h_ago']} → {h['mentions_24h']})")
    else:
        lines.append("- 없음 (5배 이상 급등 없음)")

    lines += [
        "",
        "## 하단 고정",
        "",
        "- 토론방 소문은 진위 미검증 · 소액 실전 규칙 적용",
        "- 특정 게시글을 추천 근거로 쓰지 않음",
        "- 본 보고서는 능동 순찰 결과 · 사용자 조회 아님",
        "",
        "---",
        "",
        f"- git_sha: `{sha}`",
        f"- 생성 시각 UTC: {datetime.now(timezone.utc).isoformat()}",
    ]
    md_path.write_text("\n".join(lines))
    LOG.info("saved: %s", md_path)
    print(f"REPORT: {md_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
