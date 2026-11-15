"""1114-04 · 1114-05 · 상장폐지 · 합병 중인 종목 구분 (순수 판정 · 새 SEC 요청 0).

하는 일
- 제출 단계(biotech_filings)가 이미 받은 submissions 응답으로 회사마다 상태를 정한다 → <RUNTIME>/candidates/listing_status_<날짜>.json (400일 보관)
- 후보 단계가 가장 최근 판정 파일을 읽어 후보 CSV 에 열 4개를 더한다 (status · status_date · status_evidence · status_checked)
- 레이더가 빠질 상태의 행을 점수 계산 앞에서 빼고 radar_excluded_<날짜>.json 에 적는다 (후보 파일에서는 지우지 않음)
- 합병 계약 체결 8-K(항목 1.01 + 체결 문구)를 결과 발표로 세지 않는 판정 (WP39 명부 · 봉인 FR-6c 파일은 고치지 않고 읽는 쪽에서 거름)

상태 값: active · excluded_delisted · merging_seller · merging_fact · merge_done_hold · unchecked
- 순위에서 빼는 상태 = RANK_REMOVED (excluded_delisted · merging_seller · merge_done_hold)
- merging_fact (S-4 계열만) 는 순위에 두고 사실 한 줄만 보인다 · unchecked (판정 없음) 는 순위에 둔다 (안전한 쪽)

환경 변수 BIOTECH_LISTING_FILTER=0 이면 후보 단계의 합병 8-K 거름 · 상한 분리와 레이더의 제외가 모두 꺼진다 (코드 기본값 켬).
양식 이름은 2026-11-15 EDGAR 실제 응답으로 대조했다 (25-NSE · 15-12G · 15-15D · DEFM14A · PREM14A · SC 14D9 · S-4 · S-4/A · 424B3 ·
SC 14D9 의 새 이름 「SCHEDULE 14D-9」는 검색 결과 0건이라 쓰이지 않지만 이름이 바뀔 때를 대비해 함께 둔다 · 15-12B 는 대조하지 못함).
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import html
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from backend.scripts import _biotech_paths as _P

LOG = logging.getLogger("biotech_listing_status")

FORM25 = ("25", "25-NSE")
FORM15 = ("15-12B", "15-12G", "15-15D")          # 정정 (/A) 은 판정에 쓰지 않음
SELLER_FORMS = ("DEFM14A", "PREM14A", "SC 14D9", "SC 14D9/A", "SCHEDULE 14D-9", "SCHEDULE 14D-9/A")
FACT_FORMS = ("S-4", "S-4/A")
FACT_SUPPORT = ("424B3",)                         # S-4 계열이 같은 기간에 있을 때만 함께 보임 · 단독은 아무 판정도 안 함

STATUSES = ("active", "excluded_delisted", "merging_seller", "merging_fact", "merge_done_hold", "unchecked")
RANK_REMOVED = frozenset({"excluded_delisted", "merging_seller", "merge_done_hold"})

DELIST_WINDOW_DAYS = 365
DELIST_NEAR_DAYS = 30                             # Form 25 앞뒤 8-K 2.01 · 3.01 을 보는 거리
MERGE_WINDOW_DAYS = 180
EXPIRED_LOOKBACK_DAYS = 365                       # 무소식 만료를 알아보는 한계 (이보다 오래된 서류는 조용히 지나감)
HOLD_DAYS = 30
STATUS_KEEP_DAYS = 400
STALE_DAYS = 3
HELD_MAX = 20                                     # 후보 80개 상한 밖에 더 붙일 수 있는 제외 행
RANK_CAP = 80

STATUS_NAME = "listing_status"
MEMO_NAME = "listing_memo.json"
EXCLUDED_NAME = "radar_excluded"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


# ── 공통 ─────────────────────────────────────────────────────────────

def filter_enabled() -> bool:
    return (os.environ.get("BIOTECH_LISTING_FILTER") or "1").strip() != "0"


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _items(f: dict) -> set[str]:
    raw = f.get("items") or ""
    if isinstance(raw, list):
        return {str(x).strip() for x in raw}
    return {x.strip() for x in str(raw).split(",") if x.strip()}


def filing_url(cik: str, accession: str, primary: str = "") -> str:
    """sec.gov 원문 주소 · primaryDocument 가 없으면 제출 색인 쪽."""
    c = str(int(cik))
    nodash = accession.replace("-", "")
    if primary:
        return f"{ARCHIVES}/{c}/{nodash}/{primary}"
    return f"{ARCHIVES}/{c}/{nodash}/{accession}-index.htm"


def _form_row(cik: str, f: dict) -> dict:
    return {"form": f["form"], "date": f["filingDate"], "accession": f["accessionNumber"],
            "primary": f.get("primaryDocument") or "",
            "url": filing_url(cik, f["accessionNumber"], f.get("primaryDocument") or "")}


def evidence_string(forms: list[dict]) -> str:
    """후보 CSV 칸 · 양식|날짜|접수번호|본문파일 을 ';' 로 이음."""
    return ";".join("|".join([f["form"], f["date"], f["accession"], f.get("primary") or ""]) for f in forms)


def parse_evidence(s: str, cik: str = "") -> list[dict]:
    out = []
    for part in (s or "").split(";"):
        bits = part.split("|")
        if len(bits) < 3 or not bits[2]:
            continue
        row = {"form": bits[0], "date": bits[1], "accession": bits[2], "primary": bits[3] if len(bits) > 3 else ""}
        if cik:
            row["url"] = filing_url(cik, row["accession"], row["primary"])
        out.append(row)
    return out


# ── 판정 ─────────────────────────────────────────────────────────────

def _ticker_listed(rec: dict) -> bool:
    """후보 종목 코드가 SEC 종목 코드 목록에 남아 있는가 (후보 코드가 없으면 목록이 비었는지만 본다)."""
    secs = {str(t).upper() for t in rec.get("sec_tickers") or []}
    tk = (rec.get("ticker") or "").upper()
    return (tk in secs) if tk else bool(secs)


def _delisting(cik: str, rec: dict, fs: list[dict], today: date) -> dict | None:
    lo = today - timedelta(days=DELIST_WINDOW_DAYS)
    f25s = [f for f in fs if f["form"] in FORM25 and (_date(f["filingDate"]) or date.min) >= lo]
    if not f25s:
        return None
    f25 = max(f25s, key=lambda f: f["filingDate"])
    d25 = date.fromisoformat(f25["filingDate"])
    signals, evid = [], [f25]
    if not (rec.get("sec_tickers") or []):
        signals.append("tickers_empty")
    near_201 = [f for f in fs if f["form"] == "8-K" and "2.01" in _items(f)
                and abs(((_date(f["filingDate"]) or date.max) - d25).days) <= DELIST_NEAR_DAYS]
    near_301 = [f for f in fs if f["form"] == "8-K" and "3.01" in _items(f)
                and abs(((_date(f["filingDate"]) or date.max) - d25).days) <= DELIST_NEAR_DAYS]
    if near_201 or near_301:
        signals.append("item_201" if near_201 else "item_301")
        evid.extend(near_201 or near_301)
    f15 = [f for f in fs if f["form"] in FORM15 and (_date(f["filingDate"]) or date.min) > d25]
    if f15:
        signals.append("form15")
        evid.extend(f15[:1])
    if not signals:
        return None
    # 오탐 방어 (사용자 결정 11/14 ㉡): Form 25 + 8-K 3.01 하나만 겹치고 종목 코드가 SEC 목록에 남으면 빼지 않고 watch 로만 기록
    if signals == ["item_301"] and _ticker_listed(rec):
        return {"watch": True, "since": f25["filingDate"], "forms": evid, "signals": signals}
    return {"watch": False, "since": f25["filingDate"], "forms": evid, "signals": signals}


def _rename_after(rec: dict, memo: dict | None, anchor: date) -> bool:
    """서류 제출일 뒤에 SEC 이름이나 종목 코드가 바뀌었는가."""
    for fn in rec.get("former_names") or []:
        to = _date(fn.get("to") or "")
        if to and to >= anchor:
            return True
    if memo:
        first_name = (memo.get("sec_name") or "").strip().lower()
        if first_name and first_name != (rec.get("sec_name") or "").strip().lower():
            return True
        first_tk = {str(t).upper() for t in memo.get("sec_tickers") or []}
        cur_tk = {str(t).upper() for t in rec.get("sec_tickers") or []}
        if first_tk and cur_tk and first_tk != cur_tk:
            return True
    return False


def _new_code_confirmed(rec: dict, memo: dict | None) -> bool:
    """후보 파일의 종목 코드가 이미 새 코드이다 (처음 본 코드 목록에 없고 지금 SEC 목록에 있다)."""
    tk = (rec.get("ticker") or "").upper()
    if not tk or not memo:
        return False
    first_tk = {str(t).upper() for t in memo.get("sec_tickers") or []}
    hold_tk = (memo.get("hold_ticker") or "").upper()
    cur = {str(t).upper() for t in rec.get("sec_tickers") or []}
    return tk in cur and tk not in first_tk and tk != hold_tk


def _family(fs: list[dict], names: tuple[str, ...], today: date, support: tuple[str, ...] = ()) -> tuple[list[dict], list[dict]]:
    """(창 안 서류, 창 밖 365일 안 서류) · support 양식은 주 서류가 창 안에 있을 때만 창 안에 더한다."""
    win = today - timedelta(days=MERGE_WINDOW_DAYS)
    far = today - timedelta(days=EXPIRED_LOOKBACK_DAYS)
    main_in = [f for f in fs if f["form"] in names and (_date(f["filingDate"]) or date.min) >= win]
    main_out = [f for f in fs if f["form"] in names and far <= (_date(f["filingDate"]) or date.min) < win]
    if support and main_in:
        main_in = main_in + [f for f in fs if f["form"] in support and (_date(f["filingDate"]) or date.min) >= win]
    return main_in, main_out


def _after(fs: list[dict], anchor: date, item: str) -> dict | None:
    hits = [f for f in fs if f["form"] == "8-K" and item in _items(f) and (_date(f["filingDate"]) or date.min) > anchor]
    return min(hits, key=lambda f: f["filingDate"]) if hits else None


def judge(cik: str, rec: dict, today: date, memo: dict | None = None) -> dict:
    """한 회사의 상태 · rec = {ticker, sec_tickers, sec_name, former_names, filings[]} (submissions 원본 한 회사분)."""
    fs = [f for f in rec.get("filings") or [] if f.get("form") and f.get("filingDate") and f.get("accessionNumber")]
    out = {"status": "active", "since": "", "forms": [], "sec_tickers": list(rec.get("sec_tickers") or []),
           "watch": [], "facts": [], "expired": False, "signals": []}

    d = _delisting(cik, rec, fs, today)
    if d and not d["watch"]:
        out.update(status="excluded_delisted", since=d["since"], forms=[_form_row(cik, f) for f in d["forms"]], signals=d["signals"])
        return out
    if d and d["watch"]:
        out["watch"].append({"kind": "form25_item301_ticker_kept", "since": d["since"],
                             "forms": [_form_row(cik, f) for f in d["forms"]]})

    # 종결 뒤 30일 (기억 파일에 남은 날짜 · 제출 목록에서 서류가 밀려나도 흔들리지 않음)
    hold_until = _date((memo or {}).get("hold_until") or "")
    if hold_until and today <= hold_until and (memo or {}).get("done_date") and not _new_code_confirmed(rec, memo):
        out.update(status="merge_done_hold", since=memo["done_date"], done_date=memo["done_date"], hold_until=hold_until.isoformat(),
                   hold_ticker=memo.get("hold_ticker", rec.get("ticker", "")), forms=[])
        return out

    for kind, names, support in (("seller", SELLER_FORMS, ()), ("fact", FACT_FORMS, FACT_SUPPORT)):
        docs, old_docs = _family(fs, names, today, support)
        if not docs:
            if old_docs:
                anchor = max(_date(f["filingDate"]) for f in old_docs)
                if not (_after(fs, anchor, "2.01") or _after(fs, anchor, "1.02")):
                    out["expired"] = True
            continue
        anchor = max(_date(f["filingDate"]) for f in docs)
        if _after(fs, anchor, "1.02"):          # 해지
            return out
        done = _after(fs, anchor, "2.01")        # 종결
        if done:
            if _rename_after(rec, memo, anchor) and not _new_code_confirmed(rec, memo):
                dd = date.fromisoformat(done["filingDate"])
                until = dd + timedelta(days=HOLD_DAYS)
                if today <= until:
                    out.update(status="merge_done_hold", since=done["filingDate"], done_date=done["filingDate"],
                               hold_until=until.isoformat(), hold_ticker=rec.get("ticker", ""),
                               forms=[_form_row(cik, f) for f in docs[:1] + [done]])
            return out
        newest = sorted(docs, key=lambda f: f["filingDate"])
        out.update(status="merging_seller" if kind == "seller" else "merging_fact", since=newest[0]["filingDate"],
                   forms=[_form_row(cik, f) for f in newest])
        return out
    return out


# ── 판정 파일 · 기억 파일 ────────────────────────────────────────────

def _cand_dir() -> Path:
    return _P.out_dir("candidates")


def status_path(day: date) -> Path:
    return _cand_dir() / f"{STATUS_NAME}_{day:%Y%m%d}.json"


def memo_path() -> Path:
    return _cand_dir() / MEMO_NAME


def load_memo() -> dict:
    p = memo_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("rows") or {}
    except (ValueError, OSError):
        LOG.warning("listing_memo.json 읽기 실패 · 기억 없이 판정")
        return {}


def update_memo(memo: dict, results: dict, raw: dict, today: date) -> list[str]:
    """기억 파일을 제자리에서 고치고 기록할 줄(무소식 만료로 순위에 돌아온 회사)을 돌려준다."""
    logs: list[str] = []
    for cik, r in results.items():
        prev = memo.get(cik) or {}
        rec = raw.get(cik) or {}
        e = {
            "first_seen": prev.get("first_seen") or today.isoformat(),
            "sec_name": prev.get("sec_name") or rec.get("sec_name") or "",
            "sec_tickers": prev.get("sec_tickers") or list(rec.get("sec_tickers") or []),
            "status": r["status"], "since": r.get("since", ""), "last_checked": today.isoformat(),
        }
        if r["status"] == "merge_done_hold":
            e.update(done_date=r.get("done_date", ""), hold_until=r.get("hold_until", ""), hold_ticker=r.get("hold_ticker", ""))
        elif prev.get("hold_until") and _date(prev["hold_until"]) and today <= _date(prev["hold_until"]):
            e.update(done_date=prev.get("done_date", ""), hold_until=prev["hold_until"], hold_ticker=prev.get("hold_ticker", ""))
        if r.get("expired") and prev.get("status") in ("merging_seller", "merging_fact") and r["status"] == "active":
            logs.append(f"합병 서류 180일 지나 끝 조건 없음 · 순위로 되돌림 · CIK {cik} · 이전 상태 {prev['status']}")
        memo[cik] = e
    return logs


def save_memo(memo: dict, today: date) -> None:
    memo_path().write_text(json.dumps({"updated": today.isoformat(), "rows": memo}, ensure_ascii=False, indent=1))


def write_status_file(day: date, rows: dict, extra: dict | None = None) -> Path:
    p = status_path(day)
    counts: dict[str, int] = {}
    for r in rows.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    p.write_text(json.dumps({"date": day.isoformat(), "counts": counts, **(extra or {}), "rows": rows}, ensure_ascii=False, indent=1))
    for f in p.parent.glob(f"{STATUS_NAME}_*.json"):
        try:
            d = datetime.strptime(f.stem.rsplit("_", 1)[1], "%Y%m%d").date()
        except (ValueError, IndexError):
            continue
        if (day - d).days > STATUS_KEEP_DAYS:
            f.unlink()
    return p


def build_status_rows(raw: dict, memo: dict, today: date) -> tuple[dict, list[str]]:
    """raw = submissions 원본의 companies_raw · 새 요청 없음. 반환 (CIK → 판정 행, 기록할 줄)."""
    rows = {}
    for cik, rec in raw.items():
        r = judge(cik, rec, today, memo.get(cik))
        rows[cik] = {"ticker": rec.get("ticker", ""), **r}
    logs = update_memo(memo, rows, raw, today)
    return rows, logs


def run_status(raw: dict, today: date) -> dict:
    """제출 단계가 부르는 한 줄 진입점 · 판정 파일 + 기억 파일을 쓴다. 실패해도 제출 단계는 계속 (예외는 위로 올리지 않음)."""
    try:
        memo = load_memo()
        rows, logs = build_status_rows(raw, memo, today)
        write_status_file(today, rows)
        save_memo(memo, today)
        for line in logs:
            LOG.warning(line)
        counts: dict[str, int] = {}
        for r in rows.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        watch = sum(1 for r in rows.values() if r["watch"])
        LOG.info("listing_status · 판정 %d · %s · watch %d", len(rows), counts, watch)
        return {"ok": True, "counts": counts, "watch": watch}
    except Exception as e:  # noqa: BLE001 · 판정 실패가 제출 목록 저장을 막으면 안 됨
        LOG.error("listing_status 실패 · %s: %s", e.__class__.__name__, e)
        return {"ok": False, "error": e.__class__.__name__}


# ── 후보 단계 ────────────────────────────────────────────────────────

def load_status_rows(run_day: date) -> tuple[dict, dict]:
    """가장 최근 판정 파일 (3일 넘으면 못 쓴 것으로 봄) → (CIK → 행, 정보)."""
    files = sorted(_cand_dir().glob(f"{STATUS_NAME}_????????.json"))
    if not files:
        return {}, {"usable": False, "reason": "missing", "file": "", "age_days": None}
    p = files[-1]
    try:
        j = json.loads(p.read_text())
        d = _date(j.get("date") or "")
    except (ValueError, OSError):
        return {}, {"usable": False, "reason": "broken", "file": p.name, "age_days": None}
    if d is None:
        return {}, {"usable": False, "reason": "broken", "file": p.name, "age_days": None}
    age = (run_day - d).days
    if age > STALE_DAYS:
        return {}, {"usable": False, "reason": "stale", "file": p.name, "age_days": age}
    return j.get("rows") or {}, {"usable": True, "reason": "", "file": p.name, "age_days": age}


UNCHECKED = {"status": "unchecked", "status_date": "", "status_evidence": "", "status_checked": "N"}
STATUS_COLUMNS = ["status", "status_date", "status_evidence", "status_checked"]


def status_columns(cand: dict, rows: dict, info: dict) -> dict:
    cik = str(cand.get("cik") or "").zfill(10)
    r = rows.get(cik) if info.get("usable") else None
    if not r:
        return dict(UNCHECKED)
    return {"status": r["status"], "status_date": r.get("since", ""), "status_evidence": evidence_string(r.get("forms") or []),
            "status_checked": "Y"}


def warn_once(info: dict, day: date, notify: Callable[[str, str], None] | None = None) -> bool:
    """판정 파일이 없거나 오래됐으면 텔레그램 warning 한 번 (하루 한 번 · 표지 파일)."""
    if info.get("usable"):
        return False
    marker = _P.out_dir("logs") / f"listing_status_warned_{day:%Y%m%d}"
    if marker.exists():
        return False
    marker.write_text(info.get("reason", ""))
    reason = {"missing": "판정 파일이 아직 없습니다 (첫 실행 전이면 정상입니다)", "stale": f"판정 파일이 {info.get('age_days')}일 지났습니다",
              "broken": "판정 파일을 읽지 못했습니다"}.get(info.get("reason", ""), "판정 파일을 쓸 수 없습니다")
    if os.environ.get("BIOTECH_NOTIFY_OFF", "").strip() == "1" and notify is None:
        return True
    try:
        from backend.services import alert_text as at
        title, body = at.biotech_message("warning", "상장 상태 판정 파일 확인 필요", [
            at.esc(reason),
            "이 상태에서는 종목을 순위에서 빼지 않고 이전 방식대로 보여 줍니다.",
        ], next_spec="07:00")
        if notify is not None:
            notify(title, body)
        else:
            import asyncio
            from backend.services.notifier import TelegramNotifier
            asyncio.run(TelegramNotifier().send_warning(category="biotech", title=title, body=body))
    except Exception as e:  # noqa: BLE001
        LOG.warning("notifier 실패 · %s", e.__class__.__name__)
    return True


def row_status(row: dict) -> str:
    return (row.get("status") or "unchecked").strip() or "unchecked"


def cap_candidates(filtered: list[dict], enabled: bool, cap: int = RANK_CAP, held_max: int = HELD_MAX) -> list[dict]:
    """후보 80개 상한 · 켜져 있으면 순위에서 빠질 행은 상한 밖에 최대 20개 더 둔다 (원래 정렬 순서 유지)."""
    if not enabled:
        return filtered[:cap]
    ranked = [c for c in filtered if row_status(c) not in RANK_REMOVED][:cap]
    held = [c for c in filtered if row_status(c) in RANK_REMOVED][:held_max]
    keep = {id(c) for c in ranked} | {id(c) for c in held}
    return [c for c in filtered if id(c) in keep]


def split_removed(rows: list[dict], enabled: bool) -> tuple[list[dict], list[dict]]:
    """레이더가 점수 계산 앞에서 쓰는 분리 · 꺼져 있으면 아무것도 빼지 않는다."""
    if not enabled:
        return list(rows), []
    kept = [r for r in rows if row_status(r) not in RANK_REMOVED]
    removed = [r for r in rows if row_status(r) in RANK_REMOVED]
    return kept, removed


REASON = {
    "excluded_delisted": "상장폐지 서류 기준",
    "merging_seller": "합병 서류 기준 (팔리는 쪽 양식)",
    "merge_done_hold": "합병 종결 뒤 이름 또는 종목 코드가 바뀐 것으로 보여 30일 동안 확인 중",
}


def excluded_json(removed: list[dict], day: date, enabled: bool) -> dict:
    out = []
    for r in removed:
        cik = str(r.get("cik") or "").zfill(10)
        ev = parse_evidence(r.get("status_evidence") or "", cik if r.get("cik") else "")
        out.append({"ticker": r.get("ticker", ""), "name": r.get("name", ""), "cik": cik, "status": row_status(r),
                    "status_date": r.get("status_date", ""), "reason": REASON.get(row_status(r), ""), "evidence": ev})
    return {"date": day.isoformat(), "filter_on": enabled, "rows": out}


# ── 합병 계약 체결 8-K (결과 발표로 세지 않음) ───────────────────────

MERGER_WORD_RE = re.compile(r"Agreement and Plan of (?:Merger|Reorganization)|Merger Agreement|Merger Sub")
SIGN_RE = re.compile(r"(?:entered into|entry into|have entered into|executed).{0,250}?"
                     r"(?:Agreement and Plan of (?:Merger|Reorganization)|Merger Agreement)")
PREV_RE = re.compile(r"[Aa]s previously (?:disclosed|announced)")
SIGN_SCAN_CHARS = 30000
EXCLUDE_NAME = "h39_merger_8k_exclude.json"


def clean_text(body: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body or "")))


def is_merger_announcement(items, body: str) -> bool:
    """항목 1.01 있고 2.02 없고 · 합병 낱말이 있고 · 앞 30000자 안에 체결 문구가 있고 · 「이미 발표」 문구가 바로 앞에 없을 때 참.

    「Exchange Ratio」 는 단독 근거가 아니다 (워런트 · 주주권리계획 문구 오탐 방지).
    """
    its = {x.strip() for x in (items if isinstance(items, list) else str(items or "").split(","))}
    if "1.01" not in its or "2.02" in its:
        return False
    t = clean_text(body)
    if not MERGER_WORD_RE.search(t):
        return False
    m = SIGN_RE.search(t[:SIGN_SCAN_CHARS])
    if not m:
        return False
    return not PREV_RE.search(t[max(0, m.start() - 60):m.start()])


def is_merger_event(event: dict, exclude: set[str] | frozenset[str] = frozenset()) -> bool:
    """읽는 쪽 거름 · 표지가 참이거나 접수번호가 거름 목록에 있을 때만 참 (표지 없음 = 판정 안 됨 = 거르지 않음)."""
    return event.get("merger_announcement") is True or (event.get("accession") or "") in exclude
