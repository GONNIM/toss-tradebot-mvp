"""1114-04 · 1114-05 · 화면용 API (/radar.json) · 사실 한 줄 · 뺀 종목 목록 · 확인 못 함 표시."""
from __future__ import annotations

import asyncio
import json

from backend.api.routes import biotech as b

HEAD = ("ticker,name,mcap,time_state,score,expert,crowd,near,unnoticed,risk,tag_bonus,why_easy,"
        "cik,status,status_date,status_evidence,status_checked\n")


def _setup(tmp_path, monkeypatch):
    c = tmp_path / "candidates"
    c.mkdir()
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", tmp_path)
    b._FILE_CACHE.clear()
    return c


def test_api_radar_json_carries_fact_line_excluded_and_unknown(tmp_path, monkeypatch):
    c = _setup(tmp_path, monkeypatch)
    (c / "radar_v1_3_20261116.csv").write_text(
        HEAD
        + "FLXA,Flxa Therapeutics,unknown,C,0.5,0.5,0,0,0.5,0,0,복합 관측,0000000005,merging_fact,2026-11-04,"
          "S-4|2026-11-04|0001193125-26-123456|d1.htm,Y\n"
        + "NEWA,New Co,unknown,C,0.4,0.5,0,0,0.5,0,0,복합 관측,0000000006,unchecked,,,N\n"
        + "ACTV,Active Co,unknown,C,0.3,0.5,0,0,0.5,0,0,복합 관측,0000000007,active,,,Y\n")
    (c / "radar_excluded_20261116.json").write_text(json.dumps({"date": "2026-11-16", "filter_on": True, "rows": [
        {"ticker": "TBXA", "name": "Tbxa Bio", "cik": "0000000002", "status": "excluded_delisted", "status_date": "2026-09-23",
         "reason": "상장폐지 서류 기준",
         "evidence": [{"form": "25-NSE", "date": "2026-09-23", "accession": "a", "primary": "",
                       "url": "https://www.sec.gov/Archives/edgar/data/2/a/a-index.htm"}]},
        {"ticker": "SELL", "name": "Sell Bio", "cik": "0000000003", "status": "merging_seller", "status_date": "2026-10-01",
         "reason": "합병 서류 기준 (팔리는 쪽 양식)", "evidence": []},
        {"ticker": "HOLD", "name": "Hold Bio", "cik": "0000000004", "status": "merge_done_hold", "status_date": "2026-11-01",
         "reason": "x", "evidence": []}]}))
    j = asyncio.run(b.get_radar_json(_admin="x"))
    by = {r.ticker: r for r in j.rows}
    assert by["FLXA"].fact_line == "합병 관련 서류: S-4 · 2026-11-04"
    assert by["FLXA"].fact_url == "https://www.sec.gov/Archives/edgar/data/5/000119312526123456/d1.htm"
    assert by["FLXA"].status_known is True and by["NEWA"].status_known is False and by["ACTV"].fact_line == ""
    assert [x.ticker for x in j.excluded] == ["TBXA"] and j.excluded[0].forms[0].url.startswith("https://www.sec.gov/")
    assert [x.ticker for x in j.merging] == ["SELL", "HOLD"]


def test_api_old_csv_without_status_columns_is_quiet(tmp_path, monkeypatch):
    c = _setup(tmp_path, monkeypatch)
    (c / "radar_v1_3_20261116.csv").write_text(
        "ticker,name,mcap,time_state,score,expert,crowd,near,unnoticed,risk,tag_bonus,why_easy\n"
        "AAA,A,unknown,C,0.5,0.5,0,0,0.5,0,0,복합 관측\n")
    j = asyncio.run(b.get_radar_json(_admin="x"))
    assert j.rows[0].status_known is True and j.excluded == [] and j.merging == []


def test_api_broken_excluded_file_gives_empty_lists(tmp_path, monkeypatch):
    c = _setup(tmp_path, monkeypatch)
    (c / "radar_v1_3_20261116.csv").write_text(
        "ticker,name,mcap,time_state,score,expert,crowd,near,unnoticed,risk,tag_bonus,why_easy\n"
        "AAA,A,unknown,C,0.5,0.5,0,0,0.5,0,0,복합 관측\n")
    (c / "radar_excluded_20261116.json").write_text("{broken")
    j = asyncio.run(b.get_radar_json(_admin="x"))
    assert j.excluded == [] and j.merging == [] and len(j.rows) == 1
