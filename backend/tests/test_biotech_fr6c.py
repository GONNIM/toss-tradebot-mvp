"""FR-6c · P4-1 가격 고정 (봉인 해시 · 반응일 재계산 · 가격 없음 · 한 번만 쓰기)."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date

import pytest

from backend.scripts import biotech_fr6c as f6

HEAD = ("accession,cik,ticker,accept_et,direction,direction_source,session,base_date,reaction_date,stage,stage_src,"
        "aact_nct,aact_phase,aact_pcd,aact_snapshot_date,price_base,price_reaction,xbi_base,xbi_reaction")
ROW_A = "A1,0000000001,AAA,2025-10-08T16:33:30,negative,WP39 사전 커밋 태그,after_close,2025-10-08,2025-10-09,단계 미확인,미확인,,,,2026-10-04,,,,"
ROW_B = "B1,0000000002,BBB,2026-07-08T07:00:00,positive,WP39 사전 커밋 태그,pre_open,2026-07-07,2026-07-08,2상,AACT,,,,2026-10-04,,,,"


def _setup(tmp_path, monkeypatch, rows=(ROW_A, ROW_B), hist=None):
    sample = tmp_path / "sample.csv"
    sample.write_text("\n".join((HEAD, *rows)) + "\n")
    design = tmp_path / "design.md"
    design.write_text("design\n")
    monkeypatch.setattr(f6._P, "RUNTIME_DIR", tmp_path / "rt")
    monkeypatch.setattr(f6, "FR6C_SAMPLE", sample)
    monkeypatch.setattr(f6, "FR6C_SAMPLE_SHA256", hashlib.sha256(sample.read_bytes()).hexdigest())
    monkeypatch.setattr(f6, "FR6C_DESIGN", design)
    monkeypatch.setattr(f6, "FR6C_DESIGN_SHA256", hashlib.sha256(design.read_bytes()).hexdigest())
    monkeypatch.setattr(f6, "load_usage", lambda m: {"hourly": {"2026-10-08T07": {"WP75": 1, "WP75-backfill-fr6c": 5}}})
    hist = hist if hist is not None else {
        ("AAA", "2025-10-08"): 8.9, ("AAA", "2025-10-09"): 8.54, ("XBI", "2025-10-08"): 105.44, ("XBI", "2025-10-09"): 106.52,
        ("BBB", "2026-07-07"): 10.0, ("XBI", "2026-07-07"): 160.0, ("XBI", "2026-07-08"): 161.0,   # BBB 반응가 없음
    }
    p = f6._P.out_dir("prices") / "iex_daily_history.csv"
    with p.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "date", "close"])
        for (tk, d), c in sorted(hist.items()):
            w.writerow([tk, d, c])
    return sample


def test_sample_hash_mismatch_stops_and_writes_nothing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(f6, "FR6C_SAMPLE_SHA256", "0" * 64)
    res = f6.run(date(2026, 10, 16))
    assert res["prices"]["status"] == "stopped" and "표본" in res["prices"]["reason"]
    assert not f6.out_path().exists() and not f6.meta_path().exists()


def test_design_hash_mismatch_stops(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(f6, "FR6C_DESIGN_SHA256", "1" * 64)
    assert f6.run(date(2026, 10, 16))["prices"]["status"] == "stopped"
    assert not f6.out_path().exists()


def test_reaction_day_recalc_matches_sealed_rows(tmp_path, monkeypatch):
    rows = f6.sealed_sample(_setup(tmp_path, monkeypatch), f6.FR6C_SAMPLE_SHA256)
    f6.check_reaction_days(rows)                     # 일치 · 예외 없음


def test_reaction_day_mismatch_stops(tmp_path, monkeypatch):
    bad = ROW_A.replace("after_close,2025-10-08,2025-10-09", "after_close,2025-10-07,2025-10-09")
    _setup(tmp_path, monkeypatch, rows=(bad, ROW_B))
    res = f6.run(date(2026, 10, 16))
    assert res["prices"] == {"status": "stopped", "reason": "반응일 재계산 불일치 1건"}
    assert not f6.out_path().exists()


def test_real_sealed_sample_reaction_days_match():
    """저장소 봉인 목록 68행 전부 · reaction() 재계산 일치 · 해시도 봉인값."""
    rows = f6.sealed_sample()
    assert len(rows) == 68
    f6.check_reaction_days(rows)


def test_missing_price_marked_and_counted(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = f6.run(date(2026, 10, 16))["prices"]
    assert res["status"] == "created" and res["rows"] == 2 and res["missing"] == 1
    out = list(csv.DictReader(f6.out_path().open()))
    a, b = out
    assert (a["price_base"], a["price_reaction"], a["xbi_base"], a["xbi_reaction"]) == ("8.9", "8.54", "105.44", "106.52")
    assert b["price_reaction"] == "" and b["price_source"] == "가격 없음"
    meta = json.loads(f6.meta_path().read_text())
    assert meta["missing"] == {"count": 1, "accessions": ["B1"]}
    assert meta["sample"]["sha256"] == f6.FR6C_SAMPLE_SHA256 and meta["design"]["sha256"] == f6.FR6C_DESIGN_SHA256
    assert meta["sha256"] == hashlib.sha256(f6.out_path().read_bytes()).hexdigest()
    assert meta["backfill_dates"] == {"WP75-backfill-fr6c": ["2026-10-08"]}


def test_price_source_rule():
    starts = {"AAA": "2025-09-23", "FBRX": "2026-06-29"}
    assert f6.price_source("AAA", "2025-10-08", starts) == f6.SRC_BACKFILL          # 06-26 전 = 백필만 가능
    assert f6.price_source("AAA", "2026-07-08", starts) == f6.SRC_BACKFILL          # 백필 종목 · 10-06 이하 = 덮어씀
    assert f6.price_source("AAA", "2026-10-07", starts) == f6.SRC_IEX
    assert f6.price_source("FBRX", "2026-07-08", starts) == f6.SRC_IEX              # 백필 안 된 종목
    assert f6.price_source("FBRX", "2026-07-08", starts, {"FBRX": "2026-06-29"}) == f6.SRC_BACKFILL


def test_written_once_never_rewritten(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    first = f6.run(date(2026, 10, 16))["prices"]["sha256"]
    f6.out_path().write_text(f6.out_path().read_text())   # 내용 그대로
    p = f6._P.out_dir("prices") / "iex_daily_history.csv"
    p.write_text("ticker,date,close\n")                    # 가격 기록이 바뀌어도
    again = f6.run(date(2026, 10, 17))["prices"]
    assert again == {"status": "fixed", "sha256": first}


@pytest.mark.parametrize("missing_xbi", [True, False])
def test_xbi_gap_counts_as_missing(tmp_path, monkeypatch, missing_xbi):
    hist = {("AAA", "2025-10-08"): 1.0, ("AAA", "2025-10-09"): 2.0, ("XBI", "2025-10-08"): 3.0}
    if not missing_xbi:
        hist[("XBI", "2025-10-09")] = 4.0
    _setup(tmp_path, monkeypatch, rows=(ROW_A,), hist=hist)
    assert f6.run(date(2026, 10, 16))["prices"]["missing"] == (1 if missing_xbi else 0)
