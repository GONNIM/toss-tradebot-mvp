"""1114-06 · 계속기업 의문 문구 단계 시험 · 가짜 회사와 직접 쓴 문장만 쓴다 (실제 보고서 문장 표본은 아직 없음)."""
from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest

from backend.api.routes import biotech as api
from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_filings as bf
from backend.scripts import biotech_going_concern as gc
from backend.scripts import biotech_going_concern_sample as smp
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SEC_ACCEPT_ENCODING, SEC_FROM, SEC_UA, SecBlockedError, SecDailyLedger, build_client

FILING = date(2026, 11, 6)
FILL_WORD = "Alpha company reports routine operations and clinical activity across several programs. "
NOTE = ("Notes to Condensed Financial Statements. Condensed Balance Sheets. ")
AUDIT = ("Report of Independent Registered Public Accounting Firm. Balance Sheets. ")


def body(sentences: str, form: str = "10-Q", fin: bool = True, size: int = 52_000) -> str:
    """50,000자 넘는 가짜 본문 · 재무제표 표지는 두 번씩 (목차 + 본문)."""
    marks = (NOTE if form == "10-Q" else AUDIT) * 2 if fin else ""
    pad = FILL_WORD * (size // len(FILL_WORD) + 1)
    return f"<html><body><p>{marks}</p><p>{pad}</p><p>{sentences}</p><p>{pad[:2000]}</p></body></html>"


def state_of(sentences: str, form: str = "10-Q", fin: bool = True) -> dict:
    return gc.judge_report(body(sentences, form, fin), form, FILING)


def cls(sentences: str, filing: date | None = FILING) -> dict:
    return gc.classify_text(gc.plain_text(sentences), filing)


# ── 판정 규칙 (6절 1~7 · 25 · 26 · 30~33 · 39 · 40) ─────────────────────────

def test_01_note_sentence_is_present():
    s = "These conditions raise substantial doubt about the Company's ability to continue as a going concern."
    r = state_of(s)
    assert r["state"] == gc.PRESENT and r["quotes"] and len(r["quotes"][0]) <= 300


def test_02_auditor_emphasis_paragraph_is_present():
    s = ("The accompanying financial statements have been prepared assuming that the Company will continue as a going concern. "
         "As discussed in Note 1, the Company has suffered recurring losses that raise substantial doubt about its ability to continue as a going concern.")
    assert state_of(s, "10-K")["state"] == gc.PRESENT


def test_03_hypothetical_only_is_not_found_with_flag():
    s = ("A failure to obtain funding could raise substantial doubt about our ability to continue as a going concern. "
         "Delays may cast substantial doubt on our going concern status. "
         "If we fail to raise capital, our auditors could raise substantial doubt about our going concern assumption.")
    r = state_of(s, "10-K")
    assert r["state"] == gc.NOT_FOUND and r["flags"]["hypothetical_only"] is True and r["flags"]["financials_marker"] is True


def test_04_alleviated():
    s = ("Conditions raised substantial doubt about the Company's ability to continue as a going concern. "
         "Management's plans alleviate the substantial doubt about the going concern assumption.")
    assert state_of(s)["state"] == gc.ALLEVIATED


def test_05_negative_forms_not_found():
    for s in ("These conditions do not raise substantial doubt about our ability to continue as a going concern.",
              "Management concluded there is no substantial doubt about the entity's going concern."):
        r = state_of(s)
        assert r["state"] == gc.NOT_FOUND and r["flags"]["hypothetical_only"] is False, s


def test_06_and_40_policy_sentences_are_ignored():
    s6 = "Management evaluates each period whether conditions exist that raise substantial doubt."
    s40 = ("Management evaluates whether there are conditions that raise substantial doubt about the entity's ability to continue as a going concern.")
    for s in (s6, s40):
        assert cls(s)["state"] == gc.NOT_FOUND and cls(s)["quotes"] == [], s
    # 정책 문장이 앞에 있어도 다음 문장의 확정 문구는 정책으로 오인하지 않는다
    both = s40 + " The Company's losses raise substantial doubt about its ability to continue as a going concern."
    assert cls(both)["state"] == gc.PRESENT


def test_07_format_variants():
    variants = [
        "These conditions raise substantial doubt about our ability to continue as a going‑concern.",
        "These conditions raise substantial doubt about our ability to continue as a going-concern.",
        "These conditions raise substantial&nbsp;doubt about our ability to continue as a going&nbsp;concern.",
        "These conditions raise <span>substan</span><span>tial</span> doubt about our ability to continue as a going concern.",
        "These conditions raise substantial\n   doubt about our ability to continue as a\n going concern.",
        "These conditions raise sub-\nstantial doubt about our ability to continue as a going concern.",
        "The Company’s recurring losses raise substantial doubt about its ability to continue as a GOING CONCERN.",
    ]
    for v in variants:
        assert cls(v)["state"] == gc.PRESENT, v


def test_08_short_or_no_financials_is_unknown():
    r = gc.judge_report("<p>raise substantial doubt going concern</p>", "10-Q", FILING)
    assert r["state"] == gc.UNKNOWN and r["reason"] == gc.R_SHORT
    r = state_of("Nothing relevant is written here.", fin=False)
    assert r["state"] == gc.UNKNOWN and r["reason"] == gc.R_NO_FIN
    # 문구가 있으면 재무제표 표지가 없어도 「있음」은 사실로 낸다
    assert state_of("These conditions raise substantial doubt about our going concern.", fin=False)["state"] == gc.PRESENT


def test_25_26_confirmed_wins_over_nearby_modal():
    a = "We do not have sufficient cash to fund operations, which raises substantial doubt about our ability to continue as a going concern."
    b = "Additional funding may not be available, and our losses raise substantial doubt about our ability to continue as a going concern."
    c = "Additional funding may not be available and our losses raise substantial doubt about our ability to continue as a going concern."
    assert cls(a)["state"] == gc.PRESENT and cls(b)["state"] == gc.PRESENT and cls(c)["state"] == gc.PRESENT


def test_30_substantial_doubt_without_going_concern_is_unclear():
    r = cls("Our results raise substantial doubt about the viability of the program.")
    assert r["state"] == gc.UNCLEAR
    # 가정 문장이 하나라도 있으면 사람 확인은 내지 않는다
    r2 = cls("This may raise substantial doubt about viability. Separately, results raise substantial doubt about the program.")
    assert r2["state"] == gc.NOT_FOUND


def test_31_32_past_period_only_and_with_current():
    past = "As of December 31, 2025 conditions raised substantial doubt about the Company's ability to continue as a going concern."
    assert cls(past)["state"] == gc.PAST_ONLY
    current = "As of September 30, 2026, the Company's losses raise substantial doubt about its ability to continue as a going concern."
    far = " " + ("filler text without the key words. " * 40)
    assert cls(past + far + current)["state"] == gc.PRESENT


def test_33_abbreviation_periods_do_not_break_classification():
    s = ("Alpha Bio, Inc. and its U.S. subsidiary state that management evaluates, in the U.S. markets, nothing. "
         "Alpha Bio, Inc. recurring losses raise substantial doubt about the Company's ability to continue as a going concern.")
    assert cls(s)["state"] == gc.PRESENT
    # 앞 문장의 평가 설명이 약어 마침표 때문에 뒤 문장으로 번지지 않는다
    s2 = "The Co. evaluates whether it applies. Alpha Corp. losses raise substantial doubt about going concern."
    assert cls(s2)["state"] == gc.PRESENT


def test_39_negated_or_intended_alleviation_is_present():
    cond = "Conditions raise substantial doubt about the Company's ability to continue as a going concern. "
    for tail in ("Our plans do not alleviate the substantial doubt.",
                 "The substantial doubt has not been alleviated.",
                 "Management has plans intended to alleviate the substantial doubt."):
        assert cls(cond + tail)["state"] == gc.PRESENT, tail


def test_34_toc_only_financial_marker_is_not_enough():
    toc_only = "<p>Balance Sheets 10. Report of Independent Registered Public Accounting Firm 9.</p>" + "<p>" + FILL_WORD * 700 + "</p>"
    r = gc.judge_report(toc_only, "10-K", FILING)
    assert r["state"] == gc.UNKNOWN and r["reason"] == gc.R_NO_FIN


def test_36_same_filing_date_picks_later_acceptance():
    fs = [{"form": "10-Q", "filingDate": "2026-11-06", "acceptanceDateTime": "2026-11-06T10:00:00.000Z", "accessionNumber": "A-1", "primaryDocument": "a.htm"},
          {"form": "10-Q", "filingDate": "2026-11-06", "acceptanceDateTime": "2026-11-06T21:00:00.000Z", "accessionNumber": "A-2", "primaryDocument": "b.htm"},
          {"form": "10-K", "filingDate": "2026-03-01", "acceptanceDateTime": "", "accessionNumber": "A-0", "primaryDocument": "k.htm"}]
    assert gc.pick_report(fs)["accessionNumber"] == "A-2"


def test_12_excluded_forms_have_no_target():
    fs = [{"form": f, "filingDate": "2026-11-01", "acceptanceDateTime": "", "accessionNumber": f"A-{i}", "primaryDocument": "x.htm"}
          for i, f in enumerate(("40-F", "6-K", "10-K/A", "10-KT", "10-Q/A"))]
    assert gc.pick_report(fs) is None


# ── 단계 실행 (6절 9~18 · 28 · 29 · 37) ───────────────────────────────────

TODAY_SUN = date(2026, 11, 15)    # 일요일 · 남길 몫 0
TODAY_TUE = date(2026, 11, 17)
TODAY_MON = date(2026, 11, 16)


def filing(form="10-Q", fd="2026-11-06", accn="0000000001-26-000010", doc="q.htm", acc_dt="2026-11-06T21:00:00.000Z"):
    return {"form": form, "filingDate": fd, "acceptanceDateTime": acc_dt, "accessionNumber": accn, "items": "", "primaryDocument": doc}


def mk_raw(n=1, **kw):
    return {str(i).zfill(10): {"ticker": f"T{i}", "name": "Fake", "filings": [filing(accn=f"0000000001-26-{i:06d}", **kw)]} for i in range(1, n + 1)}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    return tmp_path


def ledger_for(rt, day=TODAY_SUN, **counts):
    (rt / "sec_usage").mkdir(exist_ok=True)
    return SecDailyLedger(rt / "sec_usage" / f"sec_usage_{day:%Y%m%d}.json", f"{day:%Y%m%d}", counts)


def ok_text(sentence="Nothing here."):
    return lambda url: {"status": 200, "text": body(sentence)}


def test_09_status_codes_are_kept_apart(rt):
    outcomes = {404: gc.R_NOT_RECEIVED, 500: gc.R_NOT_RECEIVED, 410: gc.R_GONE}
    for code, reason in outcomes.items():
        led = ledger_for(rt)
        (rt / "filings").mkdir(exist_ok=True)
        sp = rt / "filings" / "going_concern.json"
        sp.unlink(missing_ok=True)
        res = gc.run_daily(mk_raw(), TODAY_SUN, lambda u, c=code: {"status": c, "text": None}, led)
        row = json.loads(sp.read_text())["rows"]["0000000001"]
        assert row["state"] == gc.UNKNOWN and row["reason"] == reason and row["http"] == code, code
        assert res["blocked"] is None
    # 거부 코드는 즉시 중단 · 이 단계 뒤 요청 없음
    for code in (401, 429):
        sp = rt / "filings" / "going_concern.json"
        sp.unlink(missing_ok=True)
        sent = []
        res = gc.run_daily(mk_raw(3), TODAY_SUN, lambda u, c=code: sent.append(u) or {"status": c, "text": None}, ledger_for(rt))
        assert len(sent) == 1 and res["blocked"] == f"SEC HTTP {code}"


def test_09b_403_raises_blocked_and_stops(rt):
    sent = []

    def get(u):
        sent.append(u)
        raise SecBlockedError("403 · test")

    res = gc.run_daily(mk_raw(3), TODAY_SUN, get, ledger_for(rt))
    assert len(sent) == 1 and "403" in res["blocked"]
    assert "last_run_on" not in json.loads((rt / "filings" / "going_concern.json").read_text())["meta"]


def test_10_same_accession_same_rule_sends_nothing(rt):
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("Nothing here.")}   # noqa: E731
    gc.run_daily(mk_raw(), TODAY_SUN, get, ledger_for(rt))
    assert len(sent) == 1
    before = (rt / "filings" / "going_concern.json").read_text()
    res = gc.run_daily(mk_raw(), date(2026, 11, 16), get, ledger_for(rt, date(2026, 11, 16)))
    assert len(sent) == 1 and res["sent"] == 0
    strip = lambda rows: {k: {a: b for a, b in v.items() if a != "last_seen_on"} for k, v in rows.items()}   # noqa: E731
    assert strip(json.loads(before)["rows"]) == strip(json.loads((rt / "filings" / "going_concern.json").read_text())["rows"])


def test_11_new_accession_one_request_and_overwrite(rt):
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("These conditions raise substantial doubt about our going concern.")}   # noqa: E731
    gc.run_daily(mk_raw(), TODAY_SUN, get, ledger_for(rt))
    raw2 = {"0000000001": {"ticker": "T1", "filings": [filing(accn="0000000001-26-999999", fd="2026-11-12", doc="new.htm")]}}
    get2 = lambda u: sent.append(u) or {"status": 200, "text": body("Nothing here.")}   # noqa: E731
    res = gc.run_daily(raw2, date(2026, 11, 16), get2, ledger_for(rt, date(2026, 11, 16)))
    row = json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]["0000000001"]
    assert res["sent"] == 1 and len(sent) == 2 and sent[1].endswith("/new.htm")
    assert row["accession"] == "0000000001-26-999999" and row["state"] == gc.NOT_FOUND and row["filing_date"] == "2026-11-12"


def test_12b_20f_makes_no_request(rt):
    raw = {"0000000001": {"ticker": "F1", "filings": [filing(form="20-F", doc="f.htm", fd="2026-04-01")]}}
    sent = []
    res = gc.run_daily(raw, TODAY_SUN, lambda u: sent.append(u) or {"status": 200, "text": "x"}, ledger_for(rt))
    row = json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]["0000000001"]
    assert sent == [] and res["sent"] == 0 and row["state"] == gc.UNKNOWN and row["reason"] == gc.R_FOREIGN and row["form"] == "20-F"


def test_12_no_target_row(rt):
    raw = {"0000000001": {"ticker": "N1", "filings": [filing(form="6-K")]}}
    gc.run_daily(raw, TODAY_SUN, ok_text(), ledger_for(rt))
    row = json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]["0000000001"]
    assert row["state"] == gc.UNKNOWN and row["reason"] == gc.R_NO_TARGET


def test_13_daily_max_15_and_rest_next_day(rt):
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("Nothing here.")}   # noqa: E731
    res = gc.run_daily(mk_raw(20), TODAY_SUN, get, ledger_for(rt))
    assert res["sent"] == 15 and res["deferred"] == 5
    res2 = gc.run_daily(mk_raw(20), date(2026, 11, 16), get, ledger_for(rt, date(2026, 11, 16), form4=0, mcap_shares=1))
    assert res2["sent"] == 5 and len(sent) == 20


def test_13_reserve_by_weekday(rt):
    # 화 · 후보 약 80개 기준 시작 212 → 212 + 1 + 90 = 303 > 300 → 0건
    led = ledger_for(rt, TODAY_TUE, h3_events=58, form4=63, filings_submissions=81, readout_text=10)
    assert led.total() == 212
    res = gc.run_daily(mk_raw(5), TODAY_TUE, ok_text(), led)
    assert res["sent"] == 0 and res["reserve"] == 90
    # 후보 38 기준 시작 170 → 15건 모두 (170 + 15 + 90 = 275)
    led2 = ledger_for(rt, TODAY_TUE, h3_events=58, form4=63, filings_submissions=38, readout_text=11)
    assert led2.total() == 170
    (rt / "filings" / "going_concern.json").unlink(missing_ok=True)
    res2 = gc.run_daily(mk_raw(20), TODAY_TUE, ok_text(), led2)
    assert res2["sent"] == 15
    # 화 · 보도자료 잡이 이미 돌았으면(장부에 quote_8k) 더 남기지 않음 (1114-06 ㉠ 11/18)
    led3 = ledger_for(rt, TODAY_TUE, form4=63, quote_8k=60)
    assert gc._quota_reserve(TODAY_TUE, led3, 80) == 0
    # 월 · 주식수가 장부에 없으면 후보 수 + 약 10 · 있으면 0 · 일 0
    assert gc._quota_reserve(TODAY_MON, ledger_for(rt, TODAY_MON, form4=1), 80) == 90
    assert gc._quota_reserve(TODAY_MON, ledger_for(rt, TODAY_MON, mcap_shares=91), 80) == 0
    assert gc._quota_reserve(TODAY_SUN, ledger_for(rt), 80) == 0


def test_13_cap_checked_per_request_not_only_at_start(rt):
    led = ledger_for(rt, TODAY_SUN, form4=SEC_DAILY_CAP - 3)           # 일요일 몫 0 → 3건까지
    sent = []
    res = gc.run_daily(mk_raw(10), TODAY_SUN, lambda u: sent.append(u) or {"status": 200, "text": body("x")}, led)
    assert res["sent"] == 3 and len(sent) == 3 and res["capped"] == 7 and led.total() == SEC_DAILY_CAP


def test_14_ledger_counted_before_request_even_on_exception(rt):
    led = ledger_for(rt)

    def get(u):
        raise httpx.ReadTimeout("slow")

    gc.run_daily(mk_raw(2), TODAY_SUN, get, led)
    assert led.counts[gc.LEDGER_CAT] == 2
    saved = json.loads((rt / "sec_usage" / "sec_usage_20261115.json").read_text())
    assert saved["counts"][gc.LEDGER_CAT] == 2


def test_15_header_constants_are_build_client_constants():
    c = build_client()
    try:
        assert (c.headers["User-Agent"], c.headers["From"], c.headers["Accept-Encoding"]) == (SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING)
    finally:
        c.close()
    src = open(gc.__file__, encoding="utf-8").read()
    assert "User-Agent" not in src and "Accept-Encoding" not in src and "httpx.Client(" not in src


def test_16_store_has_no_full_text_or_credentials(rt):
    sentinel = "SENTINEL-FULL-TEXT-MARKER"
    txt = body(f"{sentinel} " + "These conditions raise substantial doubt about our going concern. " * 3)
    gc.run_daily(mk_raw(), TODAY_SUN, lambda u: {"status": 200, "text": txt}, ledger_for(rt))
    raw = (rt / "filings" / "going_concern.json").read_text()
    j = json.loads(raw)
    row = j["rows"]["0000000001"]
    assert len(raw) < 5_000 and all(len(q) <= 300 for q in row["quotes"]) and len(row["quotes"]) <= 3
    assert raw.count(FILL_WORD.strip()) < 10          # 본문 전체가 아니라 인용 몇 줄뿐
    for bad in ("eyJ", "sk-", "AKIA", "password", "Bearer", "suauncle"):
        assert bad not in raw


def test_17_three_temporary_errors_then_weekly_retry(rt):
    sent = []
    get = lambda u: sent.append(u) or {"status": 503, "text": None}   # noqa: E731
    days = [date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 17)]
    for d in days:
        gc.run_daily(mk_raw(), d, get, ledger_for(rt, d, filings_submissions=1))
        gc.run_daily(mk_raw(), d, get, ledger_for(rt, d, filings_submissions=1, going_concern=1))    # 같은 날 두 번째는 안 보냄
    assert len(sent) == 3
    row = json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]["0000000001"]
    assert row["tries"] == 3 and row["reason"] == gc.R_NOT_RECEIVED
    for d in (date(2026, 11, 18), date(2026, 11, 23)):                # 6일째까지 안 보냄 · 7일째 1회
        gc.run_daily(mk_raw(), d, get, ledger_for(rt, d))
    assert len(sent) == 3
    gc.run_daily(mk_raw(), date(2026, 11, 24), get, ledger_for(rt, date(2026, 11, 24)))
    assert len(sent) == 4


def test_18_rule_version_change_refetches_within_daily_max(rt, monkeypatch):
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("Nothing here.")}   # noqa: E731
    gc.run_daily(mk_raw(20), TODAY_SUN, get, ledger_for(rt))
    gc.run_daily(mk_raw(20), date(2026, 11, 16), get, ledger_for(rt, date(2026, 11, 16), mcap_shares=1))
    assert len(sent) == 20
    monkeypatch.setattr(gc, "RULE_VERSION", gc.RULE_VERSION + "-next")
    n0 = len(sent)
    res = gc.run_daily(mk_raw(20), date(2026, 11, 22), get, ledger_for(rt, date(2026, 11, 22)))
    assert res["sent"] == 15 and len(sent) - n0 == 15 and res["deferred"] == 5       # 한 번에 몰지 않음


def test_37_timeout_is_temporary_error_and_uses_longer_limit(rt):
    def get(u):
        raise httpx.ReadTimeout("slow")

    res = gc.run_daily(mk_raw(), TODAY_SUN, get, ledger_for(rt))
    row = json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]["0000000001"]
    assert res["sent"] == 1 and row["reason"] == gc.R_NOT_RECEIVED and row["http"] == -1
    assert gc.READ_TIMEOUT > 25.0


def test_sec_get_text_default_timeout_unchanged():
    import inspect

    from backend.scripts import biotech_sec_common as sc
    assert inspect.signature(sc.sec_get_text).parameters["timeout"].default == 25.0
    seen = {}

    class C:
        def get(self, url, timeout):
            seen["t"] = timeout
            return type("R", (), {"status_code": 404, "text": ""})()

    import time as _t
    orig = _t.sleep
    _t.sleep = lambda s: None
    try:
        sc.sec_get_text(C(), "u")
        assert seen["t"] == 25.0
        sc.sec_get_text(C(), "u", timeout=60.0)
        assert seen["t"] == 60.0
    finally:
        _t.sleep = orig


def test_alert_messages(rt):
    msgs = []
    gc.run_daily(mk_raw(2), TODAY_SUN, lambda u: {"status": 429, "text": None}, ledger_for(rt), notify=lambda s, d: msgs.append(d))
    assert len(msgs) == 1 and "429" in msgs[0]
    msgs.clear()
    gc.run_daily(mk_raw(1), date(2026, 11, 16), lambda u: {"status": 410, "text": None}, ledger_for(rt, date(2026, 11, 16), mcap_shares=1),
                 notify=lambda s, d: msgs.append(d))
    assert len(msgs) == 1 and "410" in msgs[0]
    # 3일 연속 요청은 갔는데 수신 0건
    msgs.clear()
    (rt / "filings" / "going_concern.json").unlink()
    zero = []
    for i, d in enumerate((date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 17))):
        raw = mk_raw(1)
        raw["0000000001"]["filings"][0]["accessionNumber"] = f"0000000001-26-00010{i}"      # 날마다 새 접수번호
        gc.run_daily(raw, d, lambda u: {"status": 503, "text": None}, ledger_for(rt, d, mcap_shares=1, quote_8k=90), notify=lambda s, dd: zero.append(dd))
    assert sum("3일 연속" in z for z in zero) == 1


def test_prune_rows_not_seen_for_90_days(rt):
    gc.run_daily(mk_raw(2), TODAY_SUN, ok_text(), ledger_for(rt))
    only1 = {k: v for k, v in mk_raw(2).items() if k == "0000000001"}
    gc.run_daily(only1, date(2026, 11, 16), ok_text(), ledger_for(rt, date(2026, 11, 16), mcap_shares=1))
    assert set(json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]) == {"0000000001", "0000000002"}
    res = gc.run_daily(only1, date(2027, 2, 20), ok_text(), ledger_for(rt, date(2027, 2, 20)))
    assert res["pruned"] == 1
    assert set(json.loads((rt / "filings" / "going_concern.json").read_text())["rows"]) == {"0000000001"}


# ── 제출 목록 단계 안의 격리 (6절 24 · 27 · 28 · 29) ───────────────────────

def _resp(form="10-Q"):
    cols = {k: [] for k in bf.KEEP_FIELDS}
    for k, v in zip(bf.KEEP_FIELDS, (form, "2026-11-06", "2026-11-06T21:00:00.000Z", "0000000001-26-000010", "", "q.htm")):
        cols[k].append(v)
    return {"tickers": ["AAA"], "name": "Fake Bio", "filings": {"recent": cols, "files": []}}


def _run(rt, monkeypatch, gc_run=None, get_text=None):
    called = []
    if gc_run is not None:
        monkeypatch.setattr(gc, "run_daily", gc_run)
    led = SecDailyLedger(rt / "led.json", "20261115", {})
    meta = bf.run_submissions(TODAY_SUN, get=lambda u: {"status": 200, "json": _resp()}, ledger=led,
                              cands=[{"cik": "1", "ticker": "AAA", "name": "Fake"}],
                              get_text=get_text or (lambda u: {"status": 404, "text": ""}))
    return meta, called


def test_27_exception_in_step_still_writes_files_and_runs_listing(rt, monkeypatch):
    listing_called = []
    real = bf._listing.run_status
    monkeypatch.setattr(bf._listing, "run_status", lambda raw, today: listing_called.append(1) or real(raw, today))

    def boom(*a, **k):
        raise RuntimeError("boom")

    meta, _ = _run(rt, monkeypatch, gc_run=boom)
    assert meta["going_concern"] == {"error": "RuntimeError"} and listing_called == [1]
    assert (rt / "filings" / "submissions_20261115.json").exists() and (rt / "filings" / "filings_derived_20261115.json").exists()


def test_29_sec_blocked_inside_step_does_not_escape(rt, monkeypatch):
    def blocked(*a, **k):
        raise SecBlockedError("403 · inner")

    meta, _ = _run(rt, monkeypatch, gc_run=blocked)
    assert meta["going_concern"] == {"error": "SecBlockedError"}
    assert (rt / "filings" / "submissions_20261115.json").exists()


def test_28_blocked_flags_make_zero_requests(rt, monkeypatch):
    seen = []
    real = gc.run_daily

    def spy(raw, today, get_text, ledger, **k):
        seen.append(k["skip"])
        return real(raw, today, get_text, ledger, **k)

    # submissions 단계가 429 로 멈춘 경우
    monkeypatch.setattr(gc, "run_daily", spy)
    led = SecDailyLedger(rt / "led.json", "20261115", {})
    sent = []
    meta = bf.run_submissions(TODAY_SUN, get=lambda u: {"status": 429, "json": None}, ledger=led,
                              cands=[{"cik": "1", "ticker": "AAA", "name": "Fake"}], get_text=lambda u: sent.append(u) or {"status": 200, "text": body("x")})
    assert seen == [True] and sent == [] and meta["going_concern"]["sent"] == 0


@pytest.mark.parametrize("which", ["atm", "readout"])
def test_28b_atm_or_readout_blocked_skips_step(rt, monkeypatch, which):
    seen = []
    real = gc.run_daily
    monkeypatch.setattr(gc, "run_daily", lambda raw, today, get_text, ledger, **k: seen.append(k["skip"]) or real(raw, today, get_text, ledger, **k))
    monkeypatch.setattr(bf._atm, "judge_new", lambda *a, **k: {"new": 0, "sent": 0, "blocked": "x" if which == "atm" else None, "capped": 0, "positive": 0})
    monkeypatch.setattr(bf._readout, "run_daily", lambda *a, **k: {"new": 0, "sent": 0, "received": 0, "deferred": 0, "expired": 0,
                                                                     "blocked": "x" if which == "readout" else None, "capped": 0})
    _run(rt, monkeypatch)
    assert seen == [True]


def test_24_no_new_scheduler_job_and_pipeline_has_no_new_step():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    assert "going_concern" not in (root / "backend" / "scheduler" / "cron.py").read_text()
    assert "going_concern" not in (root / "backend" / "scripts" / "biotech_h48v3_daily_server.sh").read_text()


# ── API (6절 19 · 20 · 21 · 35) ───────────────────────────────────────────

CSV_COLS = "ticker,name,cik,score,time_state,why_easy,mcap,expert,crowd,near,unnoticed,risk,tag_bonus,status,status_evidence,status_checked"


def _csv(rt):
    d = rt / "candidates"
    d.mkdir(exist_ok=True)
    (d / "radar_v1_3_20261115.csv").write_text(
        CSV_COLS + "\nAAA,Fake A,0000000001,0.9,A,x,,0.1,0.1,0.1,0.1,0.1,0,active,,Y\nBBB,Fake B,2,0.8,B,x,,0.1,0.1,0.1,0.1,0.1,0,active,,Y\n")


def _radar(rt, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR_RUNTIME", rt)
    api._FILE_CACHE.clear()
    return asyncio.run(api.get_radar_json(_admin="x"))


def _store(rt, rows, last_run="2026-11-15"):
    (rt / "filings").mkdir(exist_ok=True)
    (rt / "filings" / "going_concern.json").write_text(json.dumps({"meta": {"last_run_on": last_run}, "rows": rows}))


def test_19_api_null_when_file_missing_or_broken_or_cik_absent(rt, monkeypatch):
    _csv(rt)
    r = _radar(rt, monkeypatch)
    assert [x.going_concern for x in r.rows] == [None, None]
    (rt / "filings").mkdir(exist_ok=True)
    (rt / "filings" / "going_concern.json").write_text("{broken")
    assert [x.going_concern for x in _radar(rt, monkeypatch).rows] == [None, None]
    _store(rt, {"0000000009": {"state": "present"}})
    assert [x.going_concern for x in _radar(rt, monkeypatch).rows] == [None, None]
    _store(rt, {"0000000001": "not a dict"})
    assert [x.going_concern for x in _radar(rt, monkeypatch).rows] == [None, None]


def test_20_21_api_old_fields_and_score_rank_unchanged(rt, monkeypatch):
    _csv(rt)
    before = _radar(rt, monkeypatch)
    _store(rt, {"0000000001": {"state": "present", "form": "10-Q", "filing_date": "2026-11-06", "url": "https://www.sec.gov/Archives/edgar/data/1/x/q.htm",
                               "accession": "A", "latest_accession": "A"}})
    after = _radar(rt, monkeypatch)
    assert [(x.rank, x.score, x.ticker, x.state) for x in before.rows] == [(x.rank, x.score, x.ticker, x.state) for x in after.rows]
    d0 = before.rows[0].model_dump(exclude={"going_concern"})
    d1 = after.rows[0].model_dump(exclude={"going_concern"})
    assert d0 == d1
    g = after.rows[0].going_concern
    assert g.state == "present" and g.form == "10-Q" and g.filed == "2026-11-06" and g.previous_report is False
    assert after.rows[1].going_concern is None


def test_21_scoring_code_does_not_read_going_concern():
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    for name in ("biotech_h46v3_radar.py", "biotech_h48v3_candidates.py", "biotech_listing_status.py"):
        assert "going_concern" not in (scripts / name).read_text(), name


def test_35_stale_by_form_and_previous_report_and_updates_stopped():
    def g(form, filed, today, last_run="2026-11-15", acc="A", latest="A"):
        store = {"meta": {"last_run_on": last_run}, "rows": {"0000000001": {"state": "not_found", "form": form, "filing_date": filed,
                                                                           "accession": acc, "latest_accession": latest}}}
        return api._going_concern_for(store, "1", today)

    from datetime import datetime
    base = date(2026, 11, 15)

    def at(d):
        return datetime(d.year, d.month, d.day)

    from datetime import timedelta
    assert g("10-Q", (base - timedelta(days=135)).isoformat(), at(base)).stale is False
    assert g("10-Q", (base - timedelta(days=136)).isoformat(), at(base)).stale is True
    assert g("10-K", (base - timedelta(days=400)).isoformat(), at(base)).stale is False
    assert g("10-K", (base - timedelta(days=401)).isoformat(), at(base)).stale is True
    assert g("20-F", (base - timedelta(days=401)).isoformat(), at(base)).stale is True
    assert g("10-Q", "2026-11-06", at(base), acc="A", latest="B").previous_report is True
    # 이 단계가 7일 넘게 못 돌았으면 「갱신 멈춤」이 「오래된 보고서」를 대신한다
    s = g("10-Q", (base - timedelta(days=200)).isoformat(), at(date(2026, 11, 23)), last_run="2026-11-15")
    assert s.updates_stopped is True and s.stale is False
    assert g("10-Q", "2026-11-06", at(date(2026, 11, 22)), last_run="2026-11-15").updates_stopped is False


# ── 표본 받기 스크립트 (㉧① · 실제 요청 없음) ──────────────────────────────

def _srcs(n):
    return mk_raw(n)


def test_sample_refuses_without_server_total_or_when_over_cap(rt):
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("x")}   # noqa: E731
    with pytest.raises(SystemExit):
        smp.run_sample(_srcs(5), TODAY_SUN, get, None)                       # 서버 장부를 모르면 실행 안 함
    with pytest.raises(SystemExit):
        smp.run_sample(_srcs(5), TODAY_SUN, get, SEC_DAILY_CAP - 4)          # 서버 + 로컬 + 예정 5 > 300
    with pytest.raises(SystemExit):
        smp.run_sample(_srcs(5), TODAY_SUN, get, 0, limit=31)
    assert sent == []


def test_sample_over_cap_needs_reason_and_known_server_total(rt):
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("x")}   # noqa: E731
    with pytest.raises(SystemExit):                                          # 서버 장부를 모르면 사유가 있어도 안 함
        smp.run_sample(_srcs(2), TODAY_SUN, get, None, over_cap_reason="test")
    assert sent == []
    res = smp.run_sample(_srcs(2), TODAY_SUN, get, SEC_DAILY_CAP + 81, over_cap_reason="사용자 1회 예외")
    assert res["sent"] == 2 and "사용자 승인 예외" in res["gate"]


def test_sample_runs_within_gate_and_saves_sentences_only(rt):
    sent = []
    sentence = "These conditions raise substantial doubt about our ability to continue as a going concern."
    get = lambda u: sent.append(u) or {"status": 200, "text": body(sentence)}   # noqa: E731
    out = rt / "filings" / "samples.json"
    res = smp.run_sample(_srcs(4), TODAY_SUN, get, 100, out=out, local_total=50)
    assert len(sent) == 4 and res["sent"] == 4 and "= 154" in res["gate"]
    raw = out.read_text()
    j = json.loads(raw)
    row = next(iter(j["rows"].values()))
    assert row["rule_state"] == gc.PRESENT and row["windows"][0]["kind"] == gc.W_CONF
    assert raw.count(FILL_WORD.strip()) < 40 and len(raw) < 20_000
    led = json.loads((rt / "sec_usage" / "sec_usage_20261115.json").read_text())
    assert led["counts"][smp.LEDGER_CAT] == 4


def test_sample_max_30_and_20f_included_without_judging(rt):
    raw = mk_raw(40)
    for i in (1, 2, 3, 4):
        raw[str(i).zfill(10)]["filings"] = [filing(form="20-F", accn=f"0000000001-26-9000{i}", doc="f.htm")]
    t = smp.pick_targets(raw, 30)
    assert len(t) == 30 and sum(x["form"] == "20-F" for x in t) == 3
    sent = []
    get = lambda u: sent.append(u) or {"status": 200, "text": body("Management notes a material uncertainty related to going concern.", "10-K")}   # noqa: E731
    res = smp.run_sample(raw, TODAY_SUN, get, 0, out=rt / "s.json", local_total=0)
    assert res["sent"] == 30
    rows = json.loads((rt / "s.json").read_text())["rows"]
    foreign = [r for r in rows.values() if r["form"] == "20-F"]
    assert len(foreign) == 3 and all(r["rule_state"] == "not_judged_20f" and r["snippets"] for r in foreign)


def test_sample_stops_on_block(rt):
    sent = []

    def get(u):
        sent.append(u)
        raise SecBlockedError("403 · x")

    res = smp.run_sample(_srcs(5), TODAY_SUN, get, 0, out=rt / "s.json", local_total=0)
    assert len(sent) == 1 and "403" in res["blocked"]


def test_sample_1117_no_longer_and_there_was_are_past_only():
    """11/17 표본 30건에서 「찾지 못함(가정만)」으로 잘못 나온 모양 (가짜 문장)."""
    txt = ("As previously disclosed, management concluded that existing resources may not have been sufficient for one year and that "
           "there was substantial doubt as to the Company's ability to continue as a going concern. On August 1 the Company raised funds. "
           "As a result, management has concluded that there is no longer substantial doubt about the Company's ability to continue as a going concern.")
    r = gc.classify_text(gc.plain_text(txt), date(2026, 11, 10))
    assert r["state"] == gc.PAST_ONLY


def test_there_was_without_prior_marker_is_not_past_only():
    """Fable 1114-06-03 막음 1 · 이번 기간 확정 문장을 「지난 기간」으로 내지 않음 (가짜 문장)."""
    for txt in ("Management concluded that there was substantial doubt about the Company's ability to continue as a going concern "
                "within one year after the date these financial statements were issued.",
                "As of September 30, 2026, there was substantial doubt about the Company's ability to continue as a going concern."):
        assert gc.classify_text(gc.plain_text(txt), date(2026, 11, 10))["state"] != gc.PAST_ONLY


def test_negated_there_was_is_not_past_only():
    txt = "We do not believe there was substantial doubt about our ability to continue as a going concern in the prior period."
    assert gc.classify_text(gc.plain_text(txt), date(2026, 11, 10))["state"] != gc.PAST_ONLY


def test_36_not_requested_yet_is_not_yet_and_failed_stays_not_received():
    """1114-06 ㉠ (11/18) · 한 번도 요청하지 않은 행 = not_yet · 받기에 실패한 행(tries ≥ 1) 은 그대로 not_received."""
    def g(row):
        return api._going_concern_for({"meta": {"last_run_on": "2026-11-18"}, "rows": {"0000000001": row}}, "1")
    assert g({"state": "unknown", "reason": "not_received", "tries": 0}).reason == "not_yet"
    assert g({"state": "unknown", "reason": "not_received"}).reason == "not_yet"
    assert g({"state": "unknown", "reason": "not_received", "tries": 1}).reason == "not_received"
    assert g({"state": "unknown", "reason": "gone", "tries": 0}).reason == "gone"
    assert g({"state": "not_found", "reason": "", "tries": 0}).reason == ""


def test_37_order_radar_first_then_candidates(tmp_path):
    """1114-06 ㉡ (11/18) · 순위표 행 순서가 먼저 · 겹치면 한 번만 · 순위표에 없는 후보는 뒤에 후보 파일 순서."""
    p = tmp_path / "radar_v1_3_20261118.csv"
    p.write_text("ticker,name,cik\nBBB,b,2\nCCC,c,3\nXXX,x,\n")
    cands = [{"cik": "1", "ticker": "AAA", "name": "a"}, {"cik": "2", "ticker": "BBB", "name": "b"}, {"cik": "4", "ticker": "DDD", "name": "d"}]
    assert bf.gc_order(cands, p) == ["0000000002", "0000000003", "0000000001", "0000000004"]
    assert bf.gc_order(cands, tmp_path / "none.csv") == ["0000000001", "0000000002", "0000000004"]


def test_38_radar_order_changes_which_15_are_sent(rt):
    """순위표 뒤쪽 회사가 후보 파일 앞에 있어도 순위표 위쪽부터 보낸다."""
    raw = mk_raw(20)
    ciks = sorted(raw)
    order = list(reversed(ciks))
    sent = []
    gc.run_daily(raw, TODAY_SUN, lambda u: sent.append(u) or {"status": 200, "text": body("Nothing here.")}, ledger_for(rt), order=order)
    assert len(sent) == 15 and all(str(int(c)) in sent[0] or True for c in order[:1])
    assert any(str(int(order[0])) in u for u in sent[:1])


def test_39_going_concern_only_needs_todays_submissions(rt, monkeypatch):
    """수동 실행 · 오늘 submissions 파일이 없으면 요청 0 으로 멈춤 · 있으면 계속기업 단계만."""
    with pytest.raises(SystemExit):
        bf.run_going_concern_only(TODAY_TUE, get_text=lambda u: pytest.fail("요청하면 안 됨"), ledger=ledger_for(rt, TODAY_TUE))
    (rt / "filings").mkdir(exist_ok=True)
    (rt / "filings" / f"submissions_{TODAY_TUE:%Y%m%d}.json").write_text(json.dumps({"companies_raw": mk_raw(3)}))
    monkeypatch.setattr(bf, "load_candidates", lambda: [])
    sent = []
    res = bf.run_going_concern_only(TODAY_TUE, get_text=lambda u: sent.append(u) or {"status": 200, "text": body("Nothing here.")},
                                    ledger=ledger_for(rt, TODAY_TUE, quote_8k=65))
    assert res["sent"] == 3 and len(sent) == 3 and res["reserve"] == 0
