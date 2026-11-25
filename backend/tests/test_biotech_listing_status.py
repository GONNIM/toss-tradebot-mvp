"""1114-04 · 1114-05 · 상장폐지·합병 종목 거르기 (순수 판정 · 외부 요청 0).

가짜 종목 코드만 쓴다: TBXA = 상장폐지 모양 · FLXA = 역합병 모양 · HWLA = 역합병 모양.
양식 이름은 11/15 EDGAR 실제 응답으로 대조했다 (25-NSE · 15-12G · 15-15D · DEFM14A · PREM14A · SC 14D9 · S-4 · S-4/A · 424B3).
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_h48v3_candidates as cand
from backend.scripts import biotech_h46v3_radar as radar
from backend.scripts import biotech_listing_status as ls

TODAY = date(2026, 11, 15)
ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).parent / "fixtures"


def _d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _f(form: str, days_ago: int, items: str = "", acc: str | None = None) -> dict:
    acc = acc or f"0000000001-26-{abs(hash((form, days_ago, items))) % 900000 + 100000}"
    return {"form": form, "filingDate": _d(days_ago), "acceptanceDateTime": "", "accessionNumber": acc,
            "items": items, "primaryDocument": "x.htm"}


def _rec(filings, ticker="TBXA", sec_tickers=("TBXA",), sec_name="Alpha Bio Inc", former=()):
    return {"ticker": ticker, "sec_tickers": list(sec_tickers), "sec_name": sec_name,
            "former_names": list(former), "filings": list(filings)}


def _judge(rec, memo=None, today=TODAY):
    return ls.judge("0000000001", rec, today, memo)


# ── 3.1 상장폐지 ───────────────────────────────────────────────────

def test_1_delisted_form25_form15_item201_no_tickers():
    r = _judge(_rec([_f("25-NSE", 50), _f("15-12G", 40), _f("8-K", 52, "2.01,9.01")], sec_tickers=()))
    assert r["status"] == "excluded_delisted"
    assert {x["form"] for x in r["forms"]} >= {"25-NSE", "15-12G"}


def test_2_form25_alone_stays_active():
    assert _judge(_rec([_f("25", 50)]))["status"] == "active"


def test_3_warrant_only_delisting_is_watch_not_excluded():
    r = _judge(_rec([_f("25", 50), _f("8-K", 49, "3.01")], sec_tickers=("TBXA",)))
    assert r["status"] == "active" and r["watch"]


def test_3b_form25_item301_but_ticker_gone_is_excluded():
    r = _judge(_rec([_f("25", 50), _f("8-K", 49, "3.01")], sec_tickers=()))
    assert r["status"] == "excluded_delisted"


def test_4_exchange_transfer_25_stays_active():
    assert _judge(_rec([_f("25", 30)], sec_tickers=("TBXA",)))["status"] == "active"


def test_5_old_form25_outside_365_days_is_active():
    r = _judge(_rec([_f("25", 800), _f("15-12G", 790), _f("8-K", 801, "2.01")], sec_tickers=()))
    assert r["status"] == "active"


def test_form15_before_form25_does_not_count():
    assert _judge(_rec([_f("15-12B", 70), _f("25", 50)]))["status"] == "active"


def test_item201_far_from_form25_does_not_count():
    assert _judge(_rec([_f("25", 50), _f("8-K", 120, "2.01")]))["status"] == "active"


# ── 3.2 · 3.3 합병 ─────────────────────────────────────────────────

def test_6_s4_only_is_fact_not_excluded():
    r = _judge(_rec([_f("S-4", 10), _f("8-K", 200, "2.01")]))
    assert r["status"] == "merging_fact" and ls.RANK_REMOVED.isdisjoint({r["status"]})


def test_6b_s4_then_completion_without_rename_is_active():
    assert _judge(_rec([_f("S-4", 40), _f("8-K", 10, "2.01")]))["status"] == "active"


def test_7_424b3_alone_is_active_without_mark():
    r = _judge(_rec([_f("424B3", 10)]))
    assert r["status"] == "active" and not r["forms"]


def test_8_424b3_with_s4_same_period_is_fact():
    r = _judge(_rec([_f("S-4", 40), _f("424B3", 10)]))
    assert r["status"] == "merging_fact" and {x["form"] for x in r["forms"]} == {"S-4", "424B3"}


def test_9_defm14a_only_is_seller():
    assert _judge(_rec([_f("DEFM14A", 60)]))["status"] == "merging_seller"


@pytest.mark.parametrize("form", ["PREM14A", "SC 14D9", "SC 14D9/A", "SCHEDULE 14D-9"])
def test_seller_forms(form):
    assert _judge(_rec([_f(form, 20)]))["status"] == "merging_seller"


def test_10_termination_8k_102_returns_active():
    assert _judge(_rec([_f("DEFM14A", 60), _f("8-K", 20, "1.02,9.01")]))["status"] == "active"


def test_11_completion_with_new_ticker_is_hold_then_active():
    memo = {"first_seen": _d(90), "sec_name": "Alpha Bio Inc", "sec_tickers": ["TBXA"]}
    fs = [_f("DEFM14A", 60), _f("8-K", 10, "2.01")]
    old = _judge(_rec(fs, ticker="TBXA", sec_tickers=("NEWC",), sec_name="Newco Inc"), memo)
    assert old["status"] == "merge_done_hold" and old["hold_until"] == (TODAY + timedelta(days=20)).isoformat()
    new = _judge(_rec(fs, ticker="NEWC", sec_tickers=("NEWC",), sec_name="Newco Inc"), memo)
    assert new["status"] == "active"


def test_11b_rename_seen_through_former_names_without_memo():
    fs = [_f("S-4", 60), _f("8-K", 10, "2.01")]
    former = [{"name": "Alpha Bio Inc", "from": "2015-01-01T00:00:00.000Z", "to": _d(9) + "T00:00:00.000Z"}]
    r = _judge(_rec(fs, ticker="TBXA", sec_tickers=("NEWC",), sec_name="Newco Inc", former=former))
    assert r["status"] == "merge_done_hold"


def test_12_completion_plus_form25_no_tickers_is_excluded():
    fs = [_f("DEFM14A", 60), _f("8-K", 10, "2.01"), _f("25", 9)]
    assert _judge(_rec(fs, sec_tickers=()))["status"] == "excluded_delisted"


def test_13_no_end_condition_after_180_days_returns_to_rank_with_expired_flag():
    r = _judge(_rec([_f("DEFM14A", 200)]))
    assert r["status"] == "active" and r["expired"] is True
    assert _judge(_rec([_f("DEFM14A", 100)]))["expired"] is False


def test_hold_expires_after_30_days_and_memo_keeps_it_when_filings_are_gone():
    # 19: 제출 목록에 서류가 없어도 기억 파일의 hold_until 이 남아 있으면 상태가 그대로
    memo = {"status": "merge_done_hold", "hold_until": (TODAY + timedelta(days=5)).isoformat(), "done_date": _d(25),
            "hold_ticker": "TBXA", "sec_name": "Alpha Bio Inc", "sec_tickers": ["TBXA"]}
    assert _judge(_rec([], ticker="TBXA", sec_tickers=("NEWC",)), memo)["status"] == "merge_done_hold"
    memo["hold_until"] = (TODAY - timedelta(days=1)).isoformat()
    assert _judge(_rec([], ticker="TBXA", sec_tickers=("NEWC",)), memo)["status"] == "active"


def test_priority_delisted_over_merging():
    fs = [_f("DEFM14A", 60), _f("25", 20), _f("15-12B", 10)]
    assert _judge(_rec(fs, sec_tickers=()))["status"] == "excluded_delisted"


# ── 판정 파일 · 기억 파일 ──────────────────────────────────────────

def test_17_new_candidate_without_status_is_unchecked(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    (tmp_path / "candidates").mkdir()
    ls.write_status_file(TODAY - timedelta(days=1), {"0000000009": {"status": "excluded_delisted", "forms": []}})
    rows, info = ls.load_status_rows(TODAY)
    out = ls.status_columns({"cik": "0000000001"}, rows, info)
    assert out == {"status": "unchecked", "status_date": "", "status_evidence": "", "status_checked": "N"}
    out9 = ls.status_columns({"cik": "0000000009"}, rows, info)
    assert out9["status"] == "excluded_delisted" and out9["status_checked"] == "Y"


def test_18_stale_status_file_changes_nothing_and_warns_once(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    (tmp_path / "candidates").mkdir()
    ls.write_status_file(TODAY - timedelta(days=4), {"0000000009": {"status": "excluded_delisted", "forms": []}})
    rows, info = ls.load_status_rows(TODAY)
    assert info["usable"] is False and info["reason"] == "stale" and rows == {}
    out = ls.status_columns({"cik": "0000000009"}, rows, info)
    assert out["status"] == "unchecked" and out["status_checked"] == "N"
    sent = []
    assert ls.warn_once(info, TODAY, notify=lambda t, b: sent.append((t, b))) is True
    assert ls.warn_once(info, TODAY, notify=lambda t, b: sent.append((t, b))) is False
    assert len(sent) == 1


def test_status_file_missing_is_unusable(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    (tmp_path / "candidates").mkdir()
    rows, info = ls.load_status_rows(TODAY)
    assert rows == {} and info["usable"] is False and info["reason"] == "missing"


def test_status_files_kept_400_days(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    (tmp_path / "candidates").mkdir()
    ls.write_status_file(TODAY - timedelta(days=401), {})
    ls.write_status_file(TODAY - timedelta(days=399), {})
    ls.write_status_file(TODAY, {})
    names = sorted(p.name for p in (tmp_path / "candidates").glob("listing_status_*.json"))
    assert len(names) == 2 and "listing_status_20261115.json" in names


def test_memo_keeps_first_seen_and_hold(tmp_path):
    memo = {}
    res = {"0000000001": {"status": "merge_done_hold", "since": _d(10), "done_date": _d(10),
                          "hold_until": _d(-20), "hold_ticker": "TBXA", "forms": []}}
    raw = {"0000000001": _rec([], sec_tickers=("NEWC",), sec_name="Newco")}
    logs = ls.update_memo(memo, res, raw, TODAY)
    e = memo["0000000001"]
    assert e["first_seen"] == TODAY.isoformat() and e["sec_name"] == "Newco" and e["hold_until"] == _d(-20)
    ls.update_memo(memo, res, {"0000000001": _rec([], sec_tickers=("ZZZ",), sec_name="Other")}, TODAY + timedelta(days=1))
    assert memo["0000000001"]["sec_name"] == "Newco"        # 처음 본 이름은 바뀌지 않음
    assert logs == []


def test_memo_logs_expired_return_to_rank():
    memo = {"0000000001": {"status": "merging_seller", "first_seen": _d(200)}}
    res = {"0000000001": {"status": "active", "expired": True, "forms": []}}
    logs = ls.update_memo(memo, res, {"0000000001": _rec([])}, TODAY)
    assert logs and "0000000001" in logs[0]


def test_evidence_roundtrip_and_url():
    forms = [{"form": "S-4", "date": "2026-11-04", "accession": "0001193125-26-123456", "primary": "d1.htm"},
             {"form": "SC 14D9", "date": "2026-11-05", "accession": "0001193125-26-123999", "primary": ""}]
    s = ls.evidence_string(forms)
    back = ls.parse_evidence(s, "0001680581")
    assert [b["form"] for b in back] == ["S-4", "SC 14D9"]
    assert back[0]["url"] == "https://www.sec.gov/Archives/edgar/data/1680581/000119312526123456/d1.htm"
    assert back[1]["url"].endswith("0001193125-26-123999-index.htm")
    assert ls.parse_evidence("") == [] and ls.parse_evidence("broken") == []


def test_filing_url_is_sec_gov():
    u = ls.filing_url("0001680581", "0001193125-26-123456", "d1.htm")
    assert u == "https://www.sec.gov/Archives/edgar/data/1680581/000119312526123456/d1.htm"
    u2 = ls.filing_url("0001680581", "0001193125-26-123456", "")
    assert u2 == "https://www.sec.gov/Archives/edgar/data/1680581/000119312526123456/0001193125-26-123456-index.htm"


# ── 4 합병 계약 체결 8-K ───────────────────────────────────────────

MERGER_8K = ("Item 1.01 Entry into a Material Definitive Agreement. On August 17, 2026, Flxa Therapeutics, Inc. entered into an "
             "Agreement and Plan of Merger with Merger Sub and Private Co, Inc. The pipeline has pivotal trial topline data.")


def test_14_merger_signing_8k_is_filtered():
    assert ls.is_merger_announcement("1.01,3.02,7.01,9.01", MERGER_8K) is True


def test_15_clinical_8k_is_kept():
    assert ls.is_merger_announcement("7.01", "The company announced topline results from its pivotal Phase 3 trial.") is False


def test_16_license_agreement_8k_is_kept():
    body = "Item 1.01 Entry into a Material Definitive Agreement. The company entered into a License Agreement. topline"
    assert ls.is_merger_announcement("1.01,7.01", body) is False


def test_24_exchange_ratio_only_is_kept():
    body = "Item 1.01 The Rights Agreement ... Exchange Ratio of warrants ... topline data"
    assert ls.is_merger_announcement("1.01,8.01", body) is False


def test_25_item_202_together_is_kept():
    assert ls.is_merger_announcement("1.01,2.02,9.01", MERGER_8K) is False


def test_previously_disclosed_merger_is_kept():
    body = "As previously disclosed, the Company entered into an Agreement and Plan of Merger with Alpha."
    assert ls.is_merger_announcement("1.01", body) is False


def test_html_and_entities_are_cleaned():
    body = "<p>Item&#160;1.01</p><p>The Company  entered\n into an <b>Agreement and Plan of Merger</b> with Merger Sub.</p>"
    assert ls.is_merger_announcement("1.01", body) is True


def test_signing_phrase_with_inc_period_inside_company_name():
    body = "The Company entered into an agreement to acquire Modis Therapeutics, Inc., pursuant to an Agreement and Plan of Merger."
    assert ls.is_merger_announcement("1.01", body) is True


def test_event_filter_uses_mark_and_exclude_list():
    ex = {"0000000001-26-000007"}
    assert ls.is_merger_event({"accession": "0000000001-26-000001", "merger_announcement": True}, ex) is True
    assert ls.is_merger_event({"accession": "0000000001-26-000007"}, ex) is True
    assert ls.is_merger_event({"accession": "0000000001-26-000002", "merger_announcement": False}, ex) is False
    # 26: 표지 없는 보충 이벤트는 「판정 안 됨」 · 거르지 않음
    assert ls.is_merger_event({"accession": "0000000001-26-000003"}, ex) is False


def _real_cache() -> Path | None:
    for p in (os.environ.get("H39_CACHE_DIR"), str(ROOT / "backend" / "data" / "h39_readout_cache")):
        if p and Path(p).is_dir() and any(Path(p).iterdir()):
            return Path(p)
    return None


def test_fixture_74_accessions_has_exact_count():
    acc = [x.strip() for x in (FIX / "biotech_merger_8k_filtered_74.txt").read_text().split() if x.strip()]
    assert len(acc) == 74 and len(set(acc)) == 74


@pytest.mark.skipif(_real_cache() is None, reason="h39_readout_cache 본문 캐시가 이 폴더에 없음 (H39_CACHE_DIR 로 지정 가능)")
def test_wp39_roster_filter_result_equals_fixed_74():
    cache = _real_cache()
    events = json.loads((ROOT / "docs" / "plans" / "biotech" / "data" / "h39_readouts_checkpoint.json").read_text())["events"]
    got = set()
    for e in events:
        p = cache / f"{e['accession']}.txt"
        if p.exists() and ls.is_merger_announcement(e.get("items") or "", p.read_text(errors="ignore")):
            got.add(e["accession"])
    want = {x.strip() for x in (FIX / "biotech_merger_8k_filtered_74.txt").read_text().split() if x.strip()}
    assert got == want


def test_wp39_sealed_roster_not_modified():
    import hashlib
    p = ROOT / "docs" / "plans" / "biotech" / "data" / "h39_readouts_checkpoint.json"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == "7de3afdea1a101090a88bc8804d824be0da84f228065bd8965c7d8bc96496a62"


# ── 후보 단계 ──────────────────────────────────────────────────────

def test_source_a_drops_merger_events(tmp_path, monkeypatch):
    base = {"events": [
        {"cik": "0000000001", "accession": "x-1", "d_day": "2099-01-01", "direction": "positive"},
        {"cik": "0000000002", "accession": "x-2", "d_day": "2099-01-01"}]}
    inc = {"events": [
        {"cik": "0000000003", "accession": "x-3", "d_day": "2099-01-01", "merger_announcement": True},
        {"cik": "0000000004", "accession": "x-4", "d_day": "2099-01-01", "merger_announcement": False},
        {"cik": "0000000005", "accession": "x-5", "d_day": "2099-01-01"}]}
    (tmp_path / "h39_readouts_checkpoint.json").write_text(json.dumps(base))
    (tmp_path / "h39_readouts_increment.json").write_text(json.dumps(inc))
    (tmp_path / "h39_merger_8k_exclude.json").write_text(json.dumps({"accessions": ["x-2"]}))
    monkeypatch.setattr(cand, "_find", lambda name: (tmp_path / name) if (tmp_path / name).exists() else None)
    monkeypatch.setattr(cand, "FALLBACK_DIR", tmp_path)      # 1112-08 · 보충 파일은 docs 본 · RUNTIME 본 두 곳을 직접 읽음
    monkeypatch.setattr(cand, "RUNTIME_DIR", None)
    monkeypatch.delenv("BIOTECH_LISTING_FILTER", raising=False)
    assert [o["cik"] for o in cand.source_a_readout("sha")] == ["0000000001", "0000000004", "0000000005"]
    monkeypatch.setenv("BIOTECH_LISTING_FILTER", "0")
    assert len(cand.source_a_readout("sha")) == 5


def _c(tk, status="active", n=1):
    return {"ticker": tk, "cik": tk, "sources": ["a"] * n, "status": status}


def test_20_removed_rows_do_not_push_out_rank_candidates():
    rows = [_c(f"R{i}") for i in range(85)] + [_c(f"X{i}", "excluded_delisted") for i in range(25)] + [_c("M1", "merging_fact")]
    final = ls.cap_candidates(rows, enabled=True)
    ranked = [c for c in final if c["status"] not in ls.RANK_REMOVED]
    held = [c for c in final if c["status"] in ls.RANK_REMOVED]
    assert len(ranked) == 80 and len(held) == 20
    assert [c["ticker"] for c in ranked][:3] == ["R0", "R1", "R2"]
    off = ls.cap_candidates(rows, enabled=False)
    assert len(off) == 80 and off == rows[:80]


def test_21_old_csv_without_status_columns_reads_as_unchecked():
    row = {"ticker": "AAA", "cik": "0000000001"}
    assert ls.row_status(row) == "unchecked"
    kept, removed = ls.split_removed([row], enabled=True)
    assert kept == [row] and removed == []


def test_27_status_columns_survive_time_state_step():
    """h50 (2단계) 는 입력 행을 dict(c) 로 복사하고 열만 더한 뒤 첫 행 열 이름으로 다시 쓴다 → 상태 열이 따라온다."""
    text = (ROOT / "backend" / "scripts" / "biotech_h50_ct_upcoming.py").read_text()
    assert "row = dict(c)" in text and "fields = list(rows_out[0].keys())" in text
    # 후보 CSV 가 상태 열을 쓰고 · 제외 행도 CSV 에 남는다 (순위 밖은 레이더에서)
    cols = ls.STATUS_COLUMNS
    assert cols == ["status", "status_date", "status_evidence", "status_checked"]


def test_split_removed_and_radar_output(tmp_path, monkeypatch):
    rows = [{"ticker": "AAA", "cik": "1", "name": "A", "status": "active"},
            {"ticker": "TBXA", "cik": "2", "name": "T", "status": "excluded_delisted", "status_date": "2026-09-23",
             "status_evidence": "25-NSE|2026-09-23|0000000002-26-000001|x.htm"},
            {"ticker": "HOLD", "cik": "3", "name": "H", "status": "merge_done_hold"},
            {"ticker": "SELL", "cik": "4", "name": "S", "status": "merging_seller"},
            {"ticker": "FACT", "cik": "5", "name": "F", "status": "merging_fact"},
            {"ticker": "NEW", "cik": "6", "name": "N", "status": "unchecked", "status_checked": "N"}]
    kept, removed = ls.split_removed(rows, enabled=True)
    assert [r["ticker"] for r in kept] == ["AAA", "FACT", "NEW"]
    assert [r["ticker"] for r in removed] == ["TBXA", "HOLD", "SELL"]
    kept_off, removed_off = ls.split_removed(rows, enabled=False)
    assert len(kept_off) == 6 and removed_off == []
    j = ls.excluded_json(removed, TODAY, enabled=True)
    assert [x["ticker"] for x in j["rows"]] == ["TBXA", "HOLD", "SELL"]
    assert j["rows"][0]["evidence"][0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/2/")


def test_filter_env_default_on(monkeypatch):
    monkeypatch.delenv("BIOTECH_LISTING_FILTER", raising=False)
    assert ls.filter_enabled() is True
    monkeypatch.setenv("BIOTECH_LISTING_FILTER", "0")
    assert ls.filter_enabled() is False
    monkeypatch.setenv("BIOTECH_LISTING_FILTER", "1")
    assert ls.filter_enabled() is True


# ── 제출 목록 단계 ─────────────────────────────────────────────────

def test_filings_step_writes_status_file_and_caps_leave_unchecked(tmp_path, monkeypatch):
    from backend.scripts import biotech_filings as bf
    from backend.scripts.biotech_sec_common import SecDailyLedger
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    cols = {k: [] for k in bf.KEEP_FIELDS}
    for form, fd, acc, accn, items in [("25-NSE", _d(50), "", "0000000001-26-000001", ""),
                                       ("15-12G", _d(40), "", "0000000001-26-000002", ""),
                                       ("8-K", _d(52), "", "0000000001-26-000003", "2.01")]:
        for k, v in zip(bf.KEEP_FIELDS, (form, fd, acc, accn, items, "d.htm")):
            cols[k].append(v)
    resp = {"tickers": [], "name": "Gone Bio", "formerNames": [{"name": "Old Bio", "from": "2010-01-01T00:00:00.000Z", "to": "2020-01-01T00:00:00.000Z"}],
            "filings": {"recent": cols, "files": []}}
    ledger = SecDailyLedger(tmp_path / "led.json", "20261115", {"x": bf.SEC_DAILY_CAP - 1})   # 1건만 더 보낼 수 있음
    cands = [{"cik": "1", "ticker": "TBXA", "name": "Gone"}, {"cik": "2", "ticker": "LATE", "name": "Late"}]
    meta = bf.run_submissions(TODAY, get=lambda url: {"status": 200, "json": resp}, ledger=ledger, cands=cands,
                              get_text=lambda url: {"status": 404, "text": ""})
    assert meta["capped"] == 1
    j = json.loads((tmp_path / "candidates" / "listing_status_20261115.json").read_text())
    assert j["rows"]["0000000001"]["status"] == "excluded_delisted"
    assert "0000000002" not in j["rows"]                       # 건너뛴 종목 = 판정 없음 = 후보 단계에서 unchecked
    raw = json.loads((tmp_path / "filings" / "submissions_20261115.json").read_text())["companies_raw"]["0000000001"]
    assert raw["sec_name"] == "Gone Bio" and raw["former_names"][0]["name"] == "Old Bio"
    memo = json.loads((tmp_path / "candidates" / "listing_memo.json").read_text())
    assert memo["rows"]["0000000001"]["status"] == "excluded_delisted"


def test_radar_keeps_scoring_code_untouched():
    """28: 점수 계산 줄은 이번 변경에서 바뀌지 않는다 (명부 직접 읽기 · 부정 건수 입력 그대로)."""
    text = (ROOT / "backend" / "scripts" / "biotech_h46v3_radar.py").read_text()
    for needle in ('neg_by_cik[c] += 1', 'score = 0.25 * (exp + crowd + near + un) + tag_bonus - 0.10 * risk',
                   'risk += min(0.5, neg_n / 5.0)'):
        assert needle in text


# ── 증분 스크립트 표지 ────────────────────────────────────────────

def test_increment_marks_merger_on_new_events_and_mark_merger_backfills(tmp_path):
    import httpx
    from backend.scripts import biotech_readout_increment as ri

    d = {"events": [
        {"cik": "0000000001", "accession": "0000000001-26-000001", "items": "7.01"},                 # 1.01 없음 → 본문 없이 거짓
        {"cik": "0000000001", "accession": "0000000001-26-000002", "items": "1.01,7.01"},            # 합병 체결
        {"cik": "0000000001", "accession": "0000000001-26-000003", "items": "1.01,8.01"},            # 라이선스
        {"cik": "0000000001", "accession": "0000000001-26-000004", "items": "1.01,8.01"},            # 받기 실패
        {"cik": "0000000001", "accession": "0000000001-26-000005", "items": "1.01", "merger_announcement": False},   # 이미 표지 있음
    ]}
    bodies = {"000000000126000002": MERGER_8K, "000000000126000003": "Item 1.01 License Agreement topline."}
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        for k, v in bodies.items():
            if k in str(req.url):
                return httpx.Response(200, text=v)
        return httpx.Response(500, text="")

    saved = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        led = ri.SecDailyLedger(tmp_path / "l.json", "20261115")
        st = ri.mark_merger(ri.make_getter(c, led, 300, sleep=lambda s: None), d, lambda: saved.append(1))
    flags = [e.get("merger_announcement") for e in d["events"]]
    assert flags == [False, True, False, None, False]                    # 받지 못한 건 표지 없음 = 판정 안 됨
    assert st["no_101"] == 1 and st["fetched"] == 2 and st["marked_true"] == 1 and len(st["failed"]) == 1
    assert len(seen) == 3 and saved == [1] and led.counts["readout_increment"] == 3


def test_increment_new_event_carries_mark(tmp_path):
    import httpx
    from backend.scripts import biotech_readout_increment as ri

    def handler(req: httpx.Request):
        if "efts" in str(req.url):
            return httpx.Response(200, json={"hits": {"total": {"value": 1}, "hits": [
                {"_source": {"adsh": "0000000001-26-000009", "items": "1.01,7.01", "file_date": "2026-10-20"}}]}})
        return httpx.Response(200, text="ACCEPTANCE-DATETIME>20261020070000\n" + MERGER_8K)
    d = ri.load_out(tmp_path / "o.json", "a", "b")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        led = ri.SecDailyLedger(tmp_path / "l.json", "20261115")
        ri.run(ri.make_getter(c, led, 300, sleep=lambda s: None),
               {"processed_ciks": ["0000000001"], "events": []}, d, "a", "b", lambda: None)
    assert d["events"][0]["merger_announcement"] is True
