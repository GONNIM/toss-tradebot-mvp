"""WP77-1 · 급등 브리핑 수집 (경보 종목만 · 하루 최대 5종목) + WP77-2 자동 요약 호출.

경보 기준 = /api/v1/biotech/kpi.json 과 같음 (h_radar_params v1.5 alerts_definition):
    apewisdom 평소 대비 배수 ≥ 5  OR  reddit RSS 매치 ≥ 3
판정·점수·후보 선정은 바꾸지 않는다 · 이 스크립트는 사실 수집·표시용 파일만 만든다.

패널 항목 (모두 수집 자료 필드 · 지어내는 문장 없음):
  (a) 언급량: 어제 n → 오늘 m · 평소 대비 배수 · 최근 30일 일별 숫자 (st_baseline JSON)
  (b) 커뮤니티: 최근 24시간 매치 레딧 글 제목·링크 최대 5 (confirm reddit_posts · 제목만 · 본문 인용 없음)
  (c) 회사 공시: SEC submissions 최근 5거래일 8-K · 항목 코드 · 문서 설명 · EX-99.1 보도자료 제목 (<title>)
  (d) Form 4 최근 20거래일 (h65 표 · 기존 자료)
  (e) 일정: candidates v3 state_note 의 종료 예정일 D-n · 없으면 "예정 일정 없음"

SEC: biotech_sec_common 선언 헤더 상수 · 403 즉시 중단 (이후 SEC 요청 없음) · 429 도 중단
산출: <RUNTIME>/briefs/alert_brief_<YYYYMMDD>.json · 요약 캐시 summary_<TICKER>_<YYYYMMDD>.json
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import html
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_sec_common import REQ_INTERVAL, SecBlockedError, build_client

LOG = logging.getLogger("biotech_h77_alert_brief")

ALERT_MULT = 5.0        # kpi.json 과 같은 기준
ALERT_RSS = 3
MAX_TICKERS = 5         # 하루 최대 5종목
BUSINESS_DAYS_8K = 5    # 최근 5거래일 (주말 제외 · 휴장일 미반영)
FORM4_DAYS = 20
PANEL_NOTE = "아래는 수집된 사실의 나열입니다. 진위는 확인되지 않았습니다."
_GENERIC_TITLE_RE = re.compile(r"^(ex[-\s]?99\.?1?|exhibit 99\.?1?|press release|document|untitled)?$", re.IGNORECASE)


def _latest(subdir: str, pattern: str) -> Path | None:
    return _P.find_glob(pattern, subdir=subdir) or _P.find_glob(pattern)


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pick_alerts(confirm_rows: list[dict]) -> list[dict]:
    """경보 종목 · 배수·매치 큰 순 · 최대 5."""
    hits = []
    for r in confirm_rows:
        mult = 0.0 if r.get("st_baseline_mult") in ("", "collecting", None) else _f(r.get("st_baseline_mult"))
        rss = int(_f(r.get("reddit_rss_matches")))
        if mult >= ALERT_MULT or rss >= ALERT_RSS:
            hits.append((mult, rss, r))
    hits.sort(key=lambda x: (-x[0], -x[1], x[2].get("ticker", "")))
    return [h[2] for h in hits[:MAX_TICKERS]]


def mention_history(ticker: str, days: int = 30) -> list[dict]:
    base = (_P.RUNTIME_DIR / "st_baseline") if _P.RUNTIME_DIR else (_P.DATA_DIR / "biotech" / "st_baseline")
    out = []
    for p in sorted(base.glob(f"{ticker}_*.json"))[-days:]:
        try:
            d = json.loads(p.read_text())
            out.append({"date": d.get("date", ""), "apewisdom_24h": int(_f(d.get("apewisdom_24h"))),
                        "reddit_matches": int(_f(d.get("reddit_matches")))})
        except Exception:
            continue
    return out


def recent_posts(row: dict, now: datetime) -> list[dict]:
    """최근 24시간 매치 글 (reddit_posts · 시각 있음) · 이 열이 없는 옛 confirm 은 reddit_posts_fallback 사용."""
    try:
        posts = json.loads(row.get("reddit_posts") or "[]")
    except Exception:
        posts = []
    out = []
    for p in posts:
        try:
            upd = datetime.fromisoformat((p.get("updated") or "").replace("Z", "+00:00"))
        except ValueError:
            continue  # 시각 없는 글은 24시간 판정 불가 → 제외
        if now - upd <= timedelta(hours=24):
            out.append({"title": p.get("title", ""), "link": p.get("link", ""), "updated": p.get("updated", "")})
    return out[:5]


def reddit_block(row: dict, now: datetime) -> tuple[list[dict], bool]:
    """(글 목록, 24시간 확인 여부) · reddit_posts 열 없으면 reddit_samples 제목·링크 (시각 없음 → 24시간 미확인)."""
    if "reddit_posts" in row:
        return recent_posts(row, now), True
    try:
        samples = json.loads(row.get("reddit_samples") or "[]")
    except Exception:
        samples = []
    return [{"title": p.get("title", ""), "link": p.get("link", ""), "updated": ""} for p in samples][:5], False


def business_days_back(today: date, n: int) -> date:
    d = today
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _sec_text(client, url: str, counter: dict) -> str | None:
    time.sleep(REQ_INTERVAL)
    counter["sec_requests"] += 1
    r = client.get(url, timeout=25.0)
    if r.status_code in (403, 429):
        raise SecBlockedError(f"SEC HTTP {r.status_code} · 즉시 중단")
    return r.text if r.status_code == 200 else None


def sec_8k(client, cik: str, since: date, counter: dict) -> list[dict]:
    """최근 8-K · 항목 코드 · 주 문서 설명 · EX-99.1 제목."""
    cik10 = str(int(cik)).zfill(10)
    txt = _sec_text(client, f"https://data.sec.gov/submissions/CIK{cik10}.json", counter)
    if not txt:
        return []
    rec = json.loads(txt).get("filings", {}).get("recent", {})
    out = []
    for i, form in enumerate(rec.get("form", [])):
        if form != "8-K":
            continue
        fdate = rec["filingDate"][i]
        if fdate < since.isoformat():
            continue
        acc = rec["accessionNumber"][i]
        item = {"filing_date": fdate, "items": rec.get("items", [""] * (i + 1))[i],
                "description": rec.get("primaryDocDescription", [""] * (i + 1))[i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index.htm",
                "ex99_1_title": ""}
        idx = _sec_text(client, item["url"], counter)
        m = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?EX-99\.1(?:(?!</tr>).)*?</tr>", idx or "", re.S | re.I)
        if m:
            href = re.search(r'href="([^"]+)"', m.group(0))
            if href:
                doc = _sec_text(client, "https://www.sec.gov" + href.group(1).replace("/ix?doc=", ""), counter)
                t = re.search(r"<title>(.*?)</title>", doc or "", re.S | re.I)
                title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip() if t else ""
                item["ex99_1_title"] = "" if _GENERIC_TITLE_RE.match(title) else title[:200]
        out.append(item)
    return out


def form4_summary(cik: str) -> dict:
    p = _latest("", "h65_form4_daily_table_*.csv")
    if not p:
        return {"available": False}
    rows = [r for r in csv.DictReader(p.open()) if (r.get("issuer_cik") or "").lstrip("0") == str(cik).lstrip("0")]
    return {"available": True, "n": len(rows), "rows": rows[:5]}


def schedule_note(cand: dict | None) -> str:
    note = (cand or {}).get("state_note_v50") or (cand or {}).get("state_note") or ""
    m = re.search(r"D-(\d+)\s*\((\d{4}-\d{2}-\d{2})", note)
    return f"임상 종료 예정일 {m.group(2)} (D-{m.group(1)})" if m else "예정 일정 없음"


def sources_for(b: dict) -> list[str]:
    """요약 입력 = 패널 자료만 · 번호 붙일 출처 목록."""
    src = []
    h = b["mentions"]["history"]
    if h:
        src.append(f"언급량 (apewisdom 24시간): 어제 {b['mentions']['yesterday']} → 오늘 {b['mentions']['today']} · "
                   f"평소 대비 배수 {b['mentions']['mult']} · 레딧 RSS 매치 오늘 {b['mentions']['reddit_today']}건")
    for p in b["reddit"]:
        src.append(f"레딧 글 제목{'' if b.get('reddit_time_checked', True) else ' (게시 시각 미확인)'}: {p['title']}")
    for f in b["sec_8k"]:
        src.append(f"SEC 8-K ({f['filing_date']}) 항목 {f['items'] or '-'} · {f['description'] or ''} · "
                   f"보도자료 제목: {f['ex99_1_title'] or '없음'}")
    f4 = b["form4"]
    src.append(f"Form 4 최근 {FORM4_DAYS}거래일 신고 {f4.get('n', 0)}건" if f4.get("available") else "Form 4 자료 없음")
    src.append(f"일정: {b['schedule']}")
    return src


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from backend.scripts import biotech_llm

    t0 = time.time()
    today = _P.today_kst_str()
    now = datetime.now(timezone.utc)
    conf_p = _latest("community_daily", "community_confirm_*.csv")
    cand_p = _latest("candidates", "biotech_candidates_v3_*.csv")
    base_p = _latest("candidates", "biotech_candidates_2*.csv")
    if not conf_p:
        LOG.warning("confirm CSV 없음 · 브리핑 생략")
        return
    confirm = list(csv.DictReader(conf_p.open()))
    cands = {r["ticker"]: r for r in csv.DictReader(cand_p.open())} if cand_p else {}
    ciks = {r["ticker"]: r.get("cik", "") for r in csv.DictReader(base_p.open())} if base_p else {}
    alerts = pick_alerts(confirm)
    counter = {"sec_requests": 0, "zai_calls": 0}
    since = business_days_back(date.fromisoformat(f"{today[:4]}-{today[4:6]}-{today[6:]}"), BUSINESS_DAYS_8K)
    out_dir = _P.out_dir("briefs")
    briefs = []
    sec_blocked = False
    client = build_client()
    for r in alerts:
        tk = r["ticker"]
        hist = mention_history(tk)
        b: dict[str, Any] = {
            "ticker": tk, "name": r.get("name", ""), "note": PANEL_NOTE,
            "mentions": {
                "yesterday": hist[-2]["apewisdom_24h"] if len(hist) >= 2 else None,
                "today": hist[-1]["apewisdom_24h"] if hist else None,
                "mult": r.get("st_baseline_mult", ""),
                "reddit_today": int(_f(r.get("reddit_rss_matches"))),
                "history": hist,
            },
            "reddit": [],
            "sec_8k": [], "sec_status": "ok",
            "form4": form4_summary(ciks.get(tk, "")) if ciks.get(tk) else {"available": False},
            "schedule": schedule_note(cands.get(tk)),
        }
        b["reddit"], b["reddit_time_checked"] = reddit_block(r, now)
        if sec_blocked:
            b["sec_status"] = "blocked_earlier"
        elif not ciks.get(tk):
            b["sec_status"] = "no_cik"
        else:
            try:
                b["sec_8k"] = sec_8k(client, ciks[tk], since, counter)
            except SecBlockedError as e:
                LOG.error("SEC 차단 · %s · 이후 SEC 요청 중단", e)
                sec_blocked = True
                b["sec_status"] = "blocked"
        b["sources"] = sources_for(b)
        # WP77-2 · 종목·날짜별 1회 · 캐시
        cache = out_dir / f"summary_{tk}_{today}.json"
        if cache.exists():
            b["summary"] = json.loads(cache.read_text())
        else:
            counter["zai_calls"] += 1
            b["summary"] = biotech_llm.summarize(tk, b["sources"])
            cache.write_text(json.dumps(b["summary"], ensure_ascii=False, indent=2))
        briefs.append(b)
    client.close()
    out = {"date": today, "generated_utc": now.isoformat(), "since_8k": since.isoformat(), "briefs": briefs,
           "counts": {**counter, "tickers": len(briefs), "elapsed_sec": round(time.time() - t0, 1)}}
    path = out_dir / f"alert_brief_{today}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"path": str(path), **out["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
