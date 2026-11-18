"""1114-06 · 후보 종목의 가장 최근 분기·연간 보고서 본문에서 「계속기업 의문」 문구 유무를 사실로 읽는 단계.

계획: docs/plans/biotech/1114-06-going-concern-plan.md (승인 11/17 · 판정 규칙은 설계 · 실제 문장 표본으로 조정 예정).
- 대상: 제출 목록(submissions)에서 양식이 정확히 10-K · 10-Q 인 행 중 제출일이 가장 늦은 1건. 20-F 는 표본 확인 전까지 요청 없이 「확인 못 함」.
- 요청: 본문 파일(primaryDocument) 1건 · 헤더 = build_client 단일 상수 · 장부 범주 "going_concern" · 보내기 직전에 장부에 더함.
  하루 최대 15건 · 요청 1건마다 「장부 + 1 + 그날 남길 몫 ≤ 300」 · 403 · 429 · 401 즉시 중단.
- 저장: <RUNTIME>/filings/going_concern.json (본문 전체는 저장하지 않음 · 인용 최대 3개 · 각 300자 이하).
- 판정은 순수 규칙(LLM 없음). 점수 · 순위는 바꾸지 않는다. 화면은 사실 표시만.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import html
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_listing_status import filing_url
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecBlockedError, SecDailyLedger

LOG = logging.getLogger("biotech_going_concern")

RULE_VERSION = "gc-3"   # 11/18 판단 동사 부정(「does not believe that … exists」) → 부정 · 「있음」 행을 먼저 다시 받음
LEDGER_CAT = "going_concern"
STORE_NAME = "going_concern.json"
DAILY_MAX = 15
TARGET_FORMS = ("10-K", "10-Q")
FOREIGN_FORMS = ("20-F",)                      # 표본 확인 전 · 요청 없이 「확인 못 함」
READ_FORMS = TARGET_FORMS + FOREIGN_FORMS
STALE_DAYS = {"10-Q": 135, "10-K": 400, "20-F": 400}   # 임의 값 · 표본으로 조정 (계획 1절)
UPDATE_STOP_DAYS = 7                           # 이 단계가 이만큼 못 돌았으면 「갱신 멈춤」
MIN_CHARS = 50_000                             # 임의 값 · 표본으로 조정
WINDOW = 300                                   # 일치 위치 앞뒤 창
QUOTE_MAX = 300
MAX_QUOTES = 3
MAX_TRIES = 3                                  # 일시 오류 · 그 뒤 주 1회만
RETRY_WEEK_DAYS = 7
KEEP_DAYS = 90                                 # 후보에서 빠진 회사의 저장값 보관
READ_TIMEOUT = 60.0                            # 큰 10-K 용 · 공용 함수 기본(25초)은 그대로 (계획 10절 ③)
QUOTE_RESERVE = 90                             # 화~토 08:45 보도자료 몫 (biotech_quotes 자체 상한)
SHARES_EXTRA = 10                              # 월요일 주식수 단계 몫 = 후보 수 + 약 10

# 상태
PRESENT, ALLEVIATED, PAST_ONLY = "present", "alleviated", "past_only"
NOT_FOUND, UNCLEAR, UNKNOWN = "not_found", "unclear", "unknown"
# 확인 못 함 까닭
R_NOT_RECEIVED, R_GONE, R_NO_FIN, R_SHORT = "not_received", "gone", "no_financials", "short"
R_NO_TARGET, R_FOREIGN = "no_target", "foreign_unchecked"

# 창 분류
W_IGNORE, W_NEG, W_HYP, W_ALLEV, W_PAST, W_CONF, W_UNCLEAR = "ignore", "neg", "hyp", "alleviated", "past", "confirmed", "unclear"

_BAD = re.compile(r"[\x00-\x1f]|[\ud800-\udfff]")
_I = re.I


def _r(p: str) -> "re.Pattern[str]":
    return re.compile(p, _I)


_INLINE_TAG = _r(r"(?<=[A-Za-z])(?:</?(?:span|font|b|i|u|em|strong|a|sup|sub)\b[^>]*>)+(?=[A-Za-z])")
_SUBSTANTIAL = _r(r"substantial doubt")
_GOING = _r(r"going concern")
_ABBR = re.compile(r"(?:(?i:\b(?:inc|corp|co|ltd|dr|mr|ms|no|vs|st|u\.s|e\.g|i\.e|etc))|\b[A-Z])$")
_BOUNDARY = re.compile(r"[.;:]\s+(?=[A-Z(\"'])")
_MODAL_RAISE = _r(r"\b(?:could|may|might|would|can)\b(?:\s+\w+){0,3}\s+(?:raise|raises|cast|casts|create|creates)\s+(?:a\s+|further\s+|significant\s+|serious\s+)*$")
_COND_RAISE = _r(r"\b(?:if|unless)\b(?:\s+\w+){0,5}\s+(?:raise|raises|cast|casts|create|creates)\s+(?:a\s+|further\s+)*$")
_NEG_JUDGE = _r(r"(?:\bnot\b|n't\b)\s+(?:\w+\s+)?(?:believe[sd]?|conclude[sd]?|determine[sd]?|think|consider|expect)\s+(?:that\s+)?(?:there\s+(?:is|are|exists?)\s+)?(?:a\s+|any\s+)?$")   # 11/18 서버 표본 「does not believe that substantial doubt exists」
_NEG_BEFORE = _r(r"(?:\bno\s+|\bwithout\s+(?:a\s+)?|\bnot\s+(?:\w+\s+){0,2}?(?:raise|raises|cast|casts|create|creates)\s+(?:a\s+)?)$")
_POLICY = _r(r"\bwhether\b|\bevaluat(?:e|es|ing)\b")
_CONF_VERB = _r(r"(?:\braise[sd]?|\braising|\brise to|\bcast(?:s|ing)?|\bcreat(?:e|es|ed|ing)|\bindicat\w+|\bthere is|\bthere exists?"
                r"|\bexists?)\s+(?:a\s+|significant\s+|serious\s+|further\s+)*$")
_CONF_AFTER = _r(r"^\s*(?:exists?|remains?|existed)\b")
_RAISED_PAST = _r(r"\braised\s+(?:a\s+)?$")
_RAISE_PRESENT = _r(r"\b(?:raises?|raising)\s+(?:a\s+)?substantial doubt")
_RAISE_ANY = _r(r"\b(?:raise[sd]?|raising)\s+(?:a\s+)?substantial doubt")
_ALLEV = _r(r"\balleviat\w*")
_ALLEV_BLOCK = _r(r"(?:\bnot\s+(?:\w+\s+){0,2}$|\bnot been\s+$|n't\s+(?:\w+\s+){0,2}$"
                  r"|\b(?:intended|plans?|expected|designed|attempt\w*|seek\w*|aim\w*|intends?)\s+(?:\w+\s+){0,2}to\s+$)")
_NO_LONGER = _r(r"\bno\s+longer\s+(?:\w+\s+){0,3}$")             # 11/17 표본: 「no longer substantial doubt」 → 지난 기간
_THERE_WAS = _r(r"\bthere\s+was\s+(?:a\s+)?$")                       # 「there was」 는 이전 기간 표지가 같은 창에 있을 때만 지난 기간 (Fable 1114-06-03 막음 1)
_NEG_WAS = _r(r"(?:\bnot\b|n't\b|\bno\b)(?:\s+\w+){0,4}\s+there\s+was\s+(?:a\s+)?$")
_PRIOR = _r(r"\bprior (?:year|period|fiscal year|reporting period)\b|\bprevious (?:year|period)\b|\bpreviously\b")
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_ASOF = _r(rf"\bas of ({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
_MONTH_NO = {m: i for i, m in enumerate(_MONTHS.split("|"), 1)}
_FIN_SHEET = _r(r"\bbalance sheets?\b|\bstatements? of financial position\b")
_FIN_AUDIT = _r(r"report of independent registered public accounting firm")
_FIN_NOTES = _r(r"\bnotes to (?:the |our )?(?:condensed |unaudited |consolidated |interim )*financial statements\b")


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


# ── 본문 정규화 · 창 분류 (순수 함수) ───────────────────────────────────────

def plain_text(raw: str) -> str:
    """HTML → 글자 · 낱말 한가운데 태그는 붙이고 · 줄바꿈 하이픈 이음 · 곡선 따옴표 · going-concern → going concern (대소문자는 그대로)."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)                    # 줄바꿈으로 갈라진 낱말
    t = _INLINE_TAG.sub("", t)                                      # 낱말 한가운데 태그
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ").replace("­", "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"(?i)going[-‐-―]\s*concern", "going concern", t)
    return re.sub(r"\s+", " ", _BAD.sub(" ", t)).strip()


def _sentence_tail(text: str, s: int) -> str:
    """일치 위치 s 앞쪽 같은 문장의 글 (최대 260자 · 약어 마침표에서는 끊지 않음)."""
    lo = max(0, s - 260)
    seg = text[lo:s]
    cut = 0
    for m in _BOUNDARY.finditer(seg):
        if not _ABBR.search(seg[:m.start()]):
            cut = m.end()
    return seg[cut:]


def _clause_tail(sent: str) -> str:
    """같은 문장에서 마지막 쉼표 뒤 (substantial doubt 를 직접 꾸미는 자리)."""
    return sent.rsplit(",", 1)[-1]


def _prior_dates(win: str, filing: date | None) -> bool:
    """창 안의 「as of <월> <일>, <연도>」 가운데 제출일보다 120일 넘게 앞선 날짜가 있으면 이전 기간."""
    if filing is None:
        return False
    for m in _ASOF.finditer(win):
        try:
            d = date(int(m.group(3)), _MONTH_NO[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            continue
        if (filing - d).days > 120:
            return True
    return False


def _effective_alleviation(win: str) -> bool:
    for m in _ALLEV.finditer(win):
        if not _ALLEV_BLOCK.search(win[max(0, m.start() - 40):m.start()]):
            return True
    return False


def _blocked_alleviation(win: str) -> bool:
    return any(_ALLEV_BLOCK.search(win[max(0, m.start() - 40):m.start()]) for m in _ALLEV.finditer(win))


def classify_window(text: str, s: int, e: int, filing: date | None = None) -> str:
    """`substantial doubt` 한 곳(s:e) 앞뒤 300자 창의 분류 · 위에서 아래로 첫 일치 (계획 3절).

    text 는 plain_text() 결과 (대소문자 그대로 · 문장 경계는 대문자로 찾음 · 나머지 규칙은 대소문자 무시)."""
    win = text[max(0, s - WINDOW):e + WINDOW]
    sent = _sentence_tail(text, s)
    clause = _clause_tail(sent)
    pair = bool(_GOING.search(win))
    if _POLICY.search(sent):                                          # 회계 정책 설명 · 맨 위
        return W_IGNORE
    if pair and _NO_LONGER.search(clause):                            # 「no longer」 는 부정·가정보다 먼저 (11/17 표본)
        return W_PAST
    if _NEG_JUDGE.search(clause):                                     # 「does not believe that」 · 「did not conclude that」 → 부정 (gc-3)
        return W_NEG
    if _NEG_WAS.search(clause):                                       # 「do not believe there was」 → 부정
        return W_NEG
    if pair and _THERE_WAS.search(clause) and (_PRIOR.search(win) or _prior_dates(win, filing)):
        return W_PAST
    if _NEG_BEFORE.search(clause):
        return W_NEG
    if _MODAL_RAISE.search(clause) or _COND_RAISE.search(clause):
        return W_HYP
    if not pair:
        return W_UNCLEAR
    if _effective_alleviation(win) and _RAISE_ANY.search(win):
        return W_ALLEV
    verb = bool(_CONF_VERB.search(clause)) or bool(_CONF_AFTER.search(text[e:e + 40]))
    prior = bool(_PRIOR.search(win)) or _prior_dates(win, filing)
    if prior and _RAISED_PAST.search(clause) and not _RAISE_PRESENT.search(win):
        return W_PAST
    if verb or _blocked_alleviation(win):
        return W_CONF
    return W_UNCLEAR


def classify_text(norm: str, filing: date | None = None) -> dict:
    """plain_text() 결과 → 창 분류 모음과 최종 상태 (계획 3절 우선순위).

    최종: 확정 > 해소 > 과거 기간 > (가정 · 부정만) > 문구 없음 · 사람 확인은 다른 분류가 하나도 없을 때만."""
    wins: list[tuple[str, str]] = []
    for m in _SUBSTANTIAL.finditer(norm):
        kind = classify_window(norm, m.start(), m.end(), filing)
        q = norm[max(0, m.start() - 150):m.end() + 150][:QUOTE_MAX]
        wins.append((kind, q))
    kinds = {k for k, _ in wins}
    if W_CONF in kinds:
        state = PRESENT
    elif W_ALLEV in kinds:
        state = ALLEVIATED
    elif W_PAST in kinds:
        state = PAST_ONLY
    elif kinds & {W_HYP, W_NEG, W_IGNORE}:
        state = NOT_FOUND
    elif W_UNCLEAR in kinds:
        state = UNCLEAR
    else:
        state = NOT_FOUND
    hyp_only = state == NOT_FOUND and W_HYP in kinds
    quote_kinds = {PRESENT: W_CONF, ALLEVIATED: W_ALLEV, PAST_ONLY: W_PAST, UNCLEAR: W_UNCLEAR}.get(state)
    quotes = [q for k, q in wins if k == quote_kinds][:MAX_QUOTES] if quote_kinds else []
    return {"state": state, "hypothetical_only": hyp_only, "quotes": quotes, "windows": len(wins), "details": wins}


def financials_marker(norm: str, form: str) -> bool:
    """재무제표 표지 · 목차 줄에만 있는 글은 인정하지 않는다 (두 번 이상 나와야 본문에도 있다고 봄 · 임시 규칙 · 표본으로 조정)."""
    sheet = len(_FIN_SHEET.findall(norm)) >= 2
    if form == "10-K":
        head = len(_FIN_AUDIT.findall(norm)) >= 2
    else:
        head = len(_FIN_NOTES.findall(norm)) >= 2
    return sheet and head


def judge_report(raw: str, form: str, filing: date | None = None) -> dict:
    """본문(HTML) → 상태 · 까닭 · 표지 · 인용. 본문 전체는 돌려주지 않는다."""
    norm = plain_text(raw)
    if len(norm) < MIN_CHARS:
        return {"state": UNKNOWN, "reason": R_SHORT, "flags": {"hypothetical_only": False, "financials_marker": False}, "quotes": [],
                "chars": len(norm)}
    fin = financials_marker(norm, form)
    c = classify_text(norm, filing)
    out = {"state": c["state"], "reason": "", "chars": len(norm), "quotes": c["quotes"],
           "flags": {"hypothetical_only": c["hypothetical_only"], "financials_marker": fin}}
    if c["state"] == NOT_FOUND and not fin:
        out["state"], out["reason"] = UNKNOWN, R_NO_FIN
    return out


# ── 대상 보고서 고르기 ───────────────────────────────────────────────────

def pick_report(filings: list[dict]) -> dict | None:
    """양식이 정확히 10-K · 10-Q · 20-F 인 행 중 제출일이 가장 늦은 1건 (같으면 접수 시각이 늦은 쪽). /A · 10-KT · 6-K · 40-F 는 제외."""
    rows = [f for f in filings if f.get("form") in READ_FORMS and f.get("filingDate") and f.get("accessionNumber")]
    if not rows:
        return None
    return max(rows, key=lambda f: (f["filingDate"], f.get("acceptanceDateTime") or "", f["accessionNumber"]))


# ── 저장 ───────────────────────────────────────────────────────────────

def store_path() -> Path:
    return _P.out_dir("filings") / STORE_NAME


def load_store() -> dict:
    p = store_path()
    if not p.exists():
        return {"meta": {}, "rows": {}}
    try:
        j = json.loads(p.read_text())
        if isinstance(j.get("rows"), dict):
            return {"meta": j.get("meta") or {}, "rows": j["rows"]}
    except (ValueError, OSError):
        LOG.warning("계속기업 파일 읽기 실패 · %s", p)
    return {"meta": {}, "rows": {}}


def save_store(store: dict, today: date) -> None:
    p = store_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": today.isoformat(), "rule_version": RULE_VERSION, "meta": store["meta"],
                               "rows": dict(sorted(store["rows"].items()))}, ensure_ascii=False, indent=1))
    tmp.replace(p)


def _quota_reserve(today: date, ledger: SecDailyLedger, n_companies: int) -> int:
    """그날 남길 몫 (계획 2절) · 화~토 08:45 보도자료(이미 돌았으면 0) · 월 주식수(장부에 아직 없을 때) · 일 0."""
    wd = today.weekday()
    if 1 <= wd <= 5:
        # 1114-06 ㉠ (11/18) · 08:45 보도자료 잡이 그날 이미 돌았으면(장부에 quote_8k 가 있음) 더 남기지 않음
        return 0 if ledger.counts.get("quote_8k", 0) > 0 else QUOTE_RESERVE
    if wd == 0 and not ledger.counts.get("mcap_shares", 0):
        return n_companies + SHARES_EXTRA
    return 0


def _gate(row: dict, acc: str, today: date) -> bool:
    """같은 접수번호로 지난 시도가 실패했으면 다시 보낼 때인지 · 3회까지 하루 뒤 · 그 뒤 주 1회 · 410 은 안 보냄."""
    if row.get("tries_accession") != acc or not row.get("tries"):
        return True
    if row.get("gone"):
        return False
    tried = row.get("tried_on") or ""
    if int(row["tries"]) < MAX_TRIES:
        return tried < today.isoformat()
    return bool(tried) and (today - date.fromisoformat(tried)).days >= RETRY_WEEK_DAYS


def needs_request(row: dict | None, latest: dict, today: date) -> str | None:
    """요청이 필요한 까닭 (first · new · rule · retry) · 없으면 None (같은 접수번호 · 같은 규칙 판이면 요청 0)."""
    acc = latest["accessionNumber"]
    if row is None or not row.get("read") or row.get("accession") != acc:
        if not _gate(row or {}, acc, today):
            return None
        if row and row.get("tries_accession") == acc and row.get("tries"):
            return "retry"
        return "first" if (row is None or not row.get("accession")) else "new"
    if row.get("rule_version") != RULE_VERSION:
        return "rule" if _gate(row, acc, today) else None
    return None


def run_daily(raw: dict[str, dict], today: date, get_text: Callable[[str], dict] | None, ledger: SecDailyLedger,
              order: list[str] | None = None, skip: bool = False, notify: Callable[[str, str], None] | None = None) -> dict:
    """submissions 원본(CIK → 회사 · filings) → 새 단계. 예외는 호출 쪽 try 로도 막는다 (계획 4절).

    skip=True (다른 단계가 403 · 429 로 멈춤) 이면 요청 0 · 저장값만 갱신하고 끝."""
    store = load_store()
    rows: dict[str, dict] = store["rows"]
    meta = store["meta"]
    rank = {cik: i for i, cik in enumerate(order or [])}
    work: list[tuple[int, int, str, dict]] = []
    kinds_order = {"new": 0, "first": 0, "rule": 1, "retry": 2}
    counts = {"companies": len(raw), "with_target": 0}
    for cik, c in raw.items():
        latest = pick_report(c.get("filings") or [])
        row = rows.get(cik)
        if row is not None:
            row["last_seen_on"] = today.isoformat()
        if latest is None:
            rows[cik] = {**(row or {}), "state": UNKNOWN, "reason": R_NO_TARGET, "form": "", "filing_date": "", "accession": "", "url": "",
                         "quotes": [], "flags": {"hypothetical_only": False, "financials_marker": False}, "rule_version": RULE_VERSION,
                         "checked_on": today.isoformat(), "latest_accession": "", "last_seen_on": today.isoformat(), "read": False}
            continue
        url = filing_url(cik, latest["accessionNumber"], latest.get("primaryDocument") or "")
        latest_info = {"latest_accession": latest["accessionNumber"], "latest_form": latest["form"], "latest_filed": latest["filingDate"]}
        if latest["form"] in FOREIGN_FORMS:                            # 요청 없이 「확인 못 함」
            rows[cik] = {"state": UNKNOWN, "reason": R_FOREIGN, "form": latest["form"], "filing_date": latest["filingDate"],
                         "accession": latest["accessionNumber"], "url": url, "quotes": [],
                         "flags": {"hypothetical_only": False, "financials_marker": False}, "rule_version": RULE_VERSION,
                         "checked_on": today.isoformat(), "last_seen_on": today.isoformat(), "read": False, **latest_info}
            continue
        counts["with_target"] += 1
        if row is None:
            row = rows[cik] = {"state": UNKNOWN, "reason": R_NOT_RECEIVED, "form": "", "filing_date": "", "accession": "", "url": "",
                               "quotes": [], "flags": {"hypothetical_only": False, "financials_marker": False}, "rule_version": RULE_VERSION,
                               "last_seen_on": today.isoformat(), "read": False, "tries": 0}
        row.update(latest_info)
        why = needs_request(row, latest, today)
        if why:
            # 규칙 판이 바뀌면 지금 「있음」 행을 맨 먼저 다시 받는다 (틀린 「있음」이 화면에 오래 남지 않게 · gc-3)
            first = 0 if (why == "rule" and row.get("state") == PRESENT) else 1
            work.append((first, rank.get(cik, 10**6), kinds_order[why], cik, latest))
    work.sort(key=lambda w: (w[0], w[1], w[2], w[3]))
    sent = received = capped = 0
    blocked = None
    gone = 0
    reserve = _quota_reserve(today, ledger, len(raw))
    if get_text is not None and not skip:
        for i, (_f, _r, _k, cik, latest) in enumerate(work):
            if sent >= DAILY_MAX:
                break
            if ledger.total() + 1 + reserve > SEC_DAILY_CAP:          # 요청 1건마다 · 그날 남길 몫까지 본다
                capped = len(work) - i
                break
            if not latest.get("primaryDocument"):
                continue
            row = rows[cik]
            ledger.add(LEDGER_CAT)                                      # 보내기 직전에 셈 · 예외로 끝나도 장부에 남음
            ledger.save()
            sent += 1
            acc = latest["accessionNumber"]
            url = filing_url(cik, acc, latest["primaryDocument"])
            try:
                r = get_text(url)
                status, text = r.get("status"), r.get("text")
            except SecBlockedError as e:
                blocked = str(e)
                break
            except (httpx.HTTPError, TimeoutError, OSError) as e:
                status, text = -1, None
                LOG.warning("going_concern · CIK %s · 일시 오류 %s", cik, e.__class__.__name__)
            if status in (401, 403, 429):
                blocked = f"SEC HTTP {status}"
                break
            tries = (int(row.get("tries") or 0) + 1) if row.get("tries_accession") == acc else 1
            base = {"tries": tries, "tries_accession": acc, "tried_on": today.isoformat(), "http": status}
            if status == 200 and text:
                j = judge_report(text, latest["form"], date.fromisoformat(latest["filingDate"]))
                rows[cik] = {**row, **base, "state": j["state"], "reason": j["reason"], "form": latest["form"],
                             "filing_date": latest["filingDate"], "accession": acc, "url": url, "flags": j["flags"],
                             "quotes": j["quotes"], "chars": j["chars"], "rule_version": RULE_VERSION, "checked_on": today.isoformat(),
                             "read": True, "tries": 0, "gone": False}
                received += 1
                continue
            LOG.warning("going_concern · CIK %s · HTTP %s · 시도 %d", cik, status, tries)
            if status == 410:
                gone += 1
            upd = {**row, **base, "gone": status == 410}
            if not row.get("accession"):                                # 옛 값이 없으면 확인 못 함 표시
                upd.update(state=UNKNOWN, reason=R_GONE if status == 410 else R_NOT_RECEIVED, form=latest["form"],
                           filing_date=latest["filingDate"], url=url, quotes=[])
            rows[cik] = upd
    elif skip:
        LOG.warning("going_concern · 앞 단계가 SEC 접근 거부로 멈춰 이번에는 요청 0")
    left = max(0, len(work) - sent) if get_text is not None and not skip else len(work)
    # 알림 조건 (계획 4절 · 교훈 #10)
    msgs: list[str] = []
    if blocked:
        LOG.error("%s · going_concern 즉시 중단 (보낸 요청 %d)", blocked, sent)
        msgs.append(f"SEC 접근 거부 · {blocked}")
    if gone:
        msgs.append(f"보고서 본문이 영구히 없어짐(HTTP 410) {gone}건")
    if sent > 0:
        meta["zero_streak"] = 0 if received > 0 else int(meta.get("zero_streak") or 0) + 1
        if meta["zero_streak"] == 3 and not blocked:
            msgs.append("3일 연속 요청은 갔으나 받은 보고서가 0건")
    if not blocked and not skip:
        meta["last_run_on"] = today.isoformat()
    meta.update({"last_blocked": blocked or meta.get("last_blocked") or "", "last_sent": sent, "last_received": received})
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    pruned = [k for k, v in rows.items() if (v.get("last_seen_on") or "9999") < cutoff]
    for k in pruned:
        del rows[k]
    save_store(store, today)
    states: dict[str, int] = {}
    for v in rows.values():
        states[v.get("state", "")] = states.get(v.get("state", ""), 0) + 1
    LOG.info("going_concern · 대상 %d · 요청 %d · 수신 %d · 미룸 %d · 상한으로 멈춤 %d · 남긴 몫 %d · 중단 %s · 상태 %s",
             counts["with_target"], sent, received, left, capped, reserve, blocked, states)
    if msgs and notify is not None:
        try:
            notify("going_concern", " · ".join(msgs))
        except Exception as e:  # 알림 실패는 단계를 막지 않음
            LOG.warning("notifier 실패 · %s", e.__class__.__name__)
    return {"companies": counts["companies"], "targets": counts["with_target"], "to_request": len(work), "sent": sent,
            "received": received, "deferred": left, "capped": capped, "reserve": reserve, "blocked": blocked, "states": states,
            "pruned": len(pruned)}


def notify_warning(step: str, detail: str) -> None:
    """텔레그램 warning 1회 (코드 포함 · 단계는 계속)."""
    import asyncio

    from backend.services import alert_text as at
    from backend.services.notifier import TelegramNotifier

    title, body = at.biotech_message("warning", f"계속기업 문구 확인 단계 알림 · {step}", [f"내용: {at.esc(detail)}"],
                                     next_spec="daily 07:00")
    asyncio.run(TelegramNotifier().send_warning(category="biotech", title=title, body=body))
