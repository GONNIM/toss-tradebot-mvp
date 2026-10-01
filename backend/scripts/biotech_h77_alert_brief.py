"""WP77-1 · 급등 브리핑 수집 (경보 종목만 · 하루 최대 5종목) + WP77-2 자동 요약 호출.

경보 기준 = backend/scripts/biotech_alert_rule.py judge() (kpi.json 과 공용 · WP78 alerts_definition_wp78)
판정·점수·후보 선정은 바꾸지 않는다 · 이 스크립트는 사실 수집·표시용 파일만 만든다.

패널 항목 (모두 수집 자료 필드 · 지어내는 문장 없음):
  (a) 언급량: 어제 n → 오늘 m · 평소 대비 배수 · 최근 30일 일별 숫자 (st_baseline JSON)
  (b) 커뮤니티: 최근 24시간 매치 레딧 글 제목·링크 최대 5 (confirm reddit_posts · 제목만 · 본문 인용 없음)
  (c) 회사 공시: SEC submissions 최근 5거래일 8-K · 항목 코드 · 문서 설명 · EX-99.1 보도자료 제목 (<title>)
      WP88 · 항목 8.01 또는 7.01 + 9.01 인 8-K 는 보도자료 제목·첫 문단 (최대 400자 · 진위 미검증) 도 읽음
      하루 SEC 요청 상한 SEC_DAILY_CAP (공용 장부 합산) 에 닿으면 보도자료 읽기만 건너뛰고 daily.log 에 남김
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
from backend.scripts.biotech_alert_rule import judge
from backend.scripts.biotech_llm import FORBIDDEN_RE
from backend.scripts.biotech_sec_common import REQ_INTERVAL, SEC_DAILY_CAP, SecBlockedError, SecDailyLedger, build_client

LOG = logging.getLogger("biotech_h77_alert_brief")

MAX_TICKERS = 5         # 하루 최대 5종목
BUSINESS_DAYS_8K = 5    # 최근 5거래일 (주말 제외 · 휴장일 미반영)
FORM4_DAYS = 20
PANEL_NOTE = "아래는 수집된 사실의 나열입니다. 진위는 확인되지 않았습니다."
_GENERIC_TITLE_RE = re.compile(r"^(ex[-\s]?99\.?1?|exhibit 99\.?1?|press release|document|untitled)?$", re.IGNORECASE)
LEAD_MAX = 400          # WP88 · 보도자료 첫 문단 최대 글자 수 (전문 저장 금지)
TITLE_MAX = 80          # WP88 · 본문에서 제목으로 볼 대문자 줄 최대 길이
BOLD_TITLE_MAX = 200    # WP92 · 굵은 글씨 제목 최대 길이 (IOVA 2026-09-29 제목 86자)
# 날짜·지명 머리말 · 예: "BOSTON, Sept. 29, 2026 /PRNewswire/ --" · "SAN DIEGO, Calif., Sept. 29, 2026 (GLOBE NEWSWIRE) --"
_DATELINE_RE = re.compile(
    r"^[A-Z][A-Za-z .,'&-]{1,60},\s*(?:[A-Z][a-z]{2,9}\.?\s+\d{1,2},\s*\d{4})\s*"
    r"(?:/[^/]{1,40}/|\([^)]{1,40}\))?\s*(?:--|—|–|-)\s*")
_FLS_RE = re.compile(r"forward[-\s]looking\s+statements?", re.IGNORECASE)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")


def _latest(subdir: str, pattern: str) -> Path | None:
    return _P.find_glob(pattern, subdir=subdir) or _P.find_glob(pattern)


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def pick_alerts(confirm_rows: list[dict]) -> list[dict]:
    """경보 종목 (공용 규칙 biotech_alert_rule.judge) · 배수·매치 큰 순 · 최대 5."""
    hits = []
    for r in confirm_rows:
        ok, _why = judge(r)
        if ok:
            mult = 0.0 if r.get("st_baseline_mult") in ("", "collecting", None) else _f(r.get("st_baseline_mult"))
            hits.append((mult, int(_f(r.get("reddit_rss_matches"))), r))
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


def _sec_text(client, url: str, counter: dict, category: str = "brief") -> str | None:
    time.sleep(REQ_INTERVAL)
    counter["sec_requests"] += 1
    if counter.get("ledger") is not None:   # WP87-2 · 하루 SEC 요청 공용 장부 (brief · exhibit)
        counter["ledger"].add(category)
    r = client.get(url, timeout=25.0)
    if r.status_code in (403, 429):
        raise SecBlockedError(f"SEC HTTP {r.status_code} · 즉시 중단")
    return r.text if r.status_code == 200 else None


def exhibit_target(items: str) -> bool:
    """WP88 · 보도자료 본문을 읽을 8-K · 항목 9.01 (첨부) 과 8.01 (기타 중요 사건) 또는 7.01 (공정 공시)."""
    codes = set(re.findall(r"\d+\.\d+", items or ""))
    return "9.01" in codes and bool(codes & {"8.01", "7.01"})


def _text_blocks(doc: str) -> list[str]:
    """HTML → 문단 목록 (태그 제거 · 공백 정리 · 빈 문단 제외).

    WP92 · 원문 줄바꿈은 문단 경계가 아님 (EDGAR 보도자료는 한 <P> 안을 여러 줄로 씀 · IOVA 2026-09-29 에서 첫 문단이 잘림)
    """
    doc = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", doc, flags=re.S | re.I)
    doc = re.sub(r"</?(p|div|br|tr|h[1-6]|li|table)\b[^>]*>", "\x00", doc, flags=re.I)
    doc = re.sub(r"<[^>]+>", " ", doc)
    out = []
    for blk in html.unescape(doc).replace("\xa0", " ").split("\x00"):
        blk = re.sub(r"\s+", " ", blk).strip()
        if blk:
            out.append(blk)
    return out


def exhibit_title(doc: str) -> str:
    """① <title> (일반 이름이면 버림) → ② 첫 굵은 글씨 또는 첫 문단이 전부 대문자·80자 이하 → ③ "" (화면에서 "제목 없음")."""
    t = re.search(r"<title>(.*?)</title>", doc or "", re.S | re.I)
    title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip() if t else ""
    if title and not _GENERIC_TITLE_RE.match(title):
        return title[:200]
    # WP92 · 굵은 글씨를 차례로 보고 일반 이름 ("Exhibit 99.1") · 날짜·지명 머리말은 건너뜀 · 길이 200자까지
    for bm in re.finditer(r"<(b|strong)\b[^>]*>(.*?)</\1>", doc or "", re.S | re.I):
        bt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", bm.group(2))).replace("\xa0", " ")).strip()
        if not bt or _GENERIC_TITLE_RE.match(bt) or _DATELINE_RE.match(bt + " "):
            continue
        if len(bt) <= BOLD_TITLE_MAX and len(bt.split()) >= 3:
            return bt
    for blk in _text_blocks(doc or "")[:5]:
        if len(blk) <= TITLE_MAX and blk == blk.upper() and re.search(r"[A-Z]{3}", blk) and not _GENERIC_TITLE_RE.match(blk):
            return blk
    return ""


def cut_lead(text: str, limit: int = LEAD_MAX) -> str:
    """최대 limit 자 · 넘으면 limit 안의 마지막 문장 경계에서 자르고 "…" (경계가 없으면 글자 수로 자름)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", head)]
    return (head[: ends[-1]] if ends else head).rstrip() + "…"


def exhibit_lead(doc: str, title: str = "") -> str:
    """첫 문단 · 전망성 진술 구간 이후 버림 · 날짜·지명 머리말 제거 · 40자 미만·제목 줄은 건너뜀 · 최대 400자.

    WP92 · 날짜·지명 머리말로 시작하는 문단이 있으면 그 문단을 먼저 씀 (부제목을 첫 문단으로 잡던 결함)
    """
    blocks = _text_blocks(doc or "")
    for blk in blocks:
        if _FLS_RE.search(blk) and len(blk) < 120:
            break
        if _DATELINE_RE.match(blk):
            lead = _DATELINE_RE.sub("", blk).strip()
            if len(lead) >= 40:
                return cut_lead(lead)
    for blk in blocks:
        if _FLS_RE.search(blk) and len(blk) < 120:      # "Forward-Looking Statements" 제목 줄 → 이후 전부 버림
            break
        if blk == title or len(blk) < 40 or blk == blk.upper():
            continue
        fls = _FLS_RE.search(blk)
        lead = _DATELINE_RE.sub("", blk[: fls.start()] if fls and fls.start() > 0 else blk).strip()
        if len(lead) >= 40:
            return cut_lead(lead)
    return ""


def safe_lead_for_llm(lead: str) -> str:
    """z.ai 입력 전 금지어 검사 · 문장마다 FORBIDDEN_RE · 걸린 문장은 뺌 · 다 걸리면 ""."""
    return " ".join(s for s in _SENT_SPLIT_RE.split(lead or "") if s.strip() and not FORBIDDEN_RE.search(s)).strip()


def sec_8k(client, cik: str, since: date, counter: dict) -> list[dict]:
    """최근 8-K · 항목 코드 · 주 문서 설명 · EX-99.1 제목 · (WP88) 대상 항목이면 첫 문단."""
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
                "ex99_1_title": "", "ex99_1_lead": "", "ex99_1_url": "", "ex99_1_status": "none"}
        idx = _sec_text(client, item["url"], counter)
        target = exhibit_target(item["items"])
        m = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?EX-99\.1(?:(?!</tr>).)*?</tr>", idx or "", re.S | re.I)
        if not m and target:   # WP88 · EX-99.1 이 없으면 첫 EX-99 첨부 1회 시도
            m = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?EX-99(?:(?!</tr>).)*?</tr>", idx or "", re.S | re.I)
        href = re.search(r'href="([^"]+)"', m.group(0)) if m else None
        if href:
            ledger = counter.get("ledger")
            if ledger is not None and ledger.total() >= SEC_DAILY_CAP:
                item["ex99_1_status"] = "daily_cap"
                counter["exhibit_skipped"] = counter.get("exhibit_skipped", 0) + 1
                LOG.warning("SEC 하루 상한 %d회 도달 (오늘 %d회) · 보도자료 읽기 건너뜀 · 8-K %s", SEC_DAILY_CAP, ledger.total(), acc)
            else:
                doc_url = "https://www.sec.gov" + href.group(1).replace("/ix?doc=", "")
                doc = _sec_text(client, doc_url, counter, "exhibit")
                item["ex99_1_url"] = doc_url
                item["ex99_1_status"] = "ok" if doc else "none"
                item["ex99_1_title"] = exhibit_title(doc or "") if target else _plain_title(doc or "")
                if target:
                    item["ex99_1_lead"] = exhibit_lead(doc or "", item["ex99_1_title"])
        out.append(item)
    return out


def _plain_title(doc: str) -> str:
    """대상 항목이 아닌 8-K · 예전과 같이 <title> 만 (일반 이름이면 버림)."""
    t = re.search(r"<title>(.*?)</title>", doc, re.S | re.I)
    title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip() if t else ""
    return "" if _GENERIC_TITLE_RE.match(title) else title[:200]


def form4_summary(cik: str) -> dict:
    p = _latest("", "h65_form4_daily_table_*.csv")
    if not p:
        return {"available": False}
    rows = [r for r in csv.DictReader(p.open()) if (r.get("issuer_cik") or "").lstrip("0") == str(cik).lstrip("0")]
    return {"available": True, "n": len(rows), "rows": rows[:5]}


def schedule_note(cand: dict | None, today: date | None = None) -> str:
    """WP87 · D-n 은 실행일 (KST) 기준으로 다시 계산 (노트의 D-n 은 주간 AACT 잡 날짜 기준)."""
    note = (cand or {}).get("state_note_v50") or (cand or {}).get("state_note") or ""
    m = re.search(r"D-(\d+)\s*\((\d{4}-\d{2}-\d{2})", note)
    if not m:
        return "예정 일정 없음"
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    days = (date.fromisoformat(m.group(2)) - today).days
    return f"임상 종료 예정일 {m.group(2)} ({'D-' + str(days) if days >= 0 else 'D+' + str(-days)})"


def sources_for(b: dict) -> list[str]:
    """요약 입력 = 패널 자료만 · 번호 붙일 출처 목록."""
    src = []
    h = b["mentions"]["history"]
    if h:
        mult = b["mentions"]["mult"]
        mult_txt = "수집 중 (7일 미만)" if mult in ("collecting", "", None) else f"{mult}배"
        src.append(f"apewisdom (커뮤니티 언급 집계 사이트) 24시간 언급 수: 어제 {b['mentions']['yesterday']} → 오늘 {b['mentions']['today']} · "
                   f"apewisdom 평소 대비 {mult_txt}")
        src.append(f"레딧 RSS 제목 매치 오늘 {b['mentions']['reddit_today']}건")
    for p in b["reddit"]:
        src.append(f"레딧 글 제목{'' if b.get('reddit_time_checked', True) else ' (게시 시각 미확인)'}: {p['title']}")
    for f in b["sec_8k"]:
        src.append(f"SEC 8-K ({f['filing_date']}) 항목 {f['items'] or '-'} · {f['description'] or ''} · "
                   f"보도자료 제목: {f['ex99_1_title'] or '없음'}")
        lead = safe_lead_for_llm(f.get("ex99_1_lead", ""))   # WP88 · 금지어 문장 제외 · 다 걸리면 출처에서 뺌
        if lead:
            src.append(f"SEC 8-K 보도자료 첫 문단 ({f['filing_date']} · 원문 · 진위 미검증): {lead}")
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
    ledger = SecDailyLedger.load(today)
    counter["ledger"] = ledger
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
                "mean": _f(r.get("st_baseline_mean")) if r.get("st_baseline_mean") not in (None, "") else None,  # WP86
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
    counter.pop("ledger")
    ledger.save()
    LOG.info("SEC 요청 · 브리핑 %d · 보도자료 %d · 오늘 합계 %d/%d · 상한으로 건너뛴 보도자료 %d건", ledger.counts.get("brief", 0),
             ledger.counts.get("exhibit", 0), ledger.total(), SEC_DAILY_CAP, counter.get("exhibit_skipped", 0))
    out = {"date": today, "generated_utc": now.isoformat(), "since_8k": since.isoformat(), "briefs": briefs,
           "counts": {**counter, "tickers": len(briefs), "elapsed_sec": round(time.time() - t0, 1)}}
    path = out_dir / f"alert_brief_{today}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    # WP86 관측 · 매일 한 줄 (2주 확인용)
    LOG.info("경보 %d건 · z.ai 호출 %d/%d", len(briefs), counter["zai_calls"], MAX_TICKERS)
    print(json.dumps({"path": str(path), **out["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
