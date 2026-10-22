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


def test_meta_exists_csv_deleted_stops_and_not_recreated(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    f6.run(date(2026, 10, 16))
    f6.out_path().unlink()
    res = f6.run(date(2026, 10, 17))["prices"]
    assert res["status"] == "stopped" and "다시 만들지 않음" in res["reason"]
    assert not f6.out_path().exists()


@pytest.mark.parametrize("missing_xbi", [True, False])
def test_xbi_gap_counts_as_missing(tmp_path, monkeypatch, missing_xbi):
    hist = {("AAA", "2025-10-08"): 1.0, ("AAA", "2025-10-09"): 2.0, ("XBI", "2025-10-08"): 3.0}
    if not missing_xbi:
        hist[("XBI", "2025-10-09")] = 4.0
    _setup(tmp_path, monkeypatch, rows=(ROW_A,), hist=hist)
    assert f6.run(date(2026, 10, 16))["prices"]["missing"] == (1 if missing_xbi else 0)


# ─── P4-2 · 집계 · 사분위 · 칸 판정 ───

def _ev(direction="긍정", stage="2상", mcap="300M-1B", d="2026-05-01", x=0.01, source="WP39 사전 커밋 태그"):
    return {"accession": f"{direction}{stage}{d}{x}", "ticker": "T", "date": d, "direction": direction, "stage": stage,
            "mcap": mcap, "source": source, "excess": x}


def test_quantile_design_example():
    xs = [-0.10, -0.04, 0.00, 0.02, 0.06, 0.30]       # 설계 3.1절 68~72행
    got = [f6.quantile(xs, p) for p in (0, 0.25, 0.5, 0.75, 1)]
    assert got == pytest.approx([-0.10, -0.03, 0.01, 0.05, 0.30])


def test_quantile_matches_numpy_on_random_arrays():
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(20261015)
    for n in (1, 2, 3, 19, 20, 21, 68, 101):
        xs = rng.normal(0, 0.2, n).tolist()
        for p in (0, 0.25, 0.5, 0.75, 1):
            assert f6.quantile(xs, p) == pytest.approx(float(np.percentile(xs, p * 100)), abs=1e-12)


def test_excess_return_hand_calc():
    # 종목 10 → 12 (+20%) · XBI 100 → 105 (+5%) → 초과 +15%
    r = {"price_base": "10", "price_reaction": "12", "xbi_base": "100", "xbi_reaction": "105"}
    assert f6.excess_return(r) == pytest.approx(0.15)
    assert f6.excess_return({**r, "xbi_reaction": ""}) is None


def test_residual_cell_hidden_even_with_20():
    es = [_ev(stage="단계 미확인", x=i / 100) for i in range(20)]
    cells = {c["label"]: c for c in f6.build_cells(es, date(2026, 10, 16))["cells"]}
    assert cells["긍정 · 단계 미확인"]["n"] == 20 and cells["긍정 · 단계 미확인"]["status"] == "잔여"
    assert cells["긍정"]["status"] == "표시" and cells["전체"]["status"] == "표시"   # 거친 칸에는 들어감
    assert "긍정 · 단계 미확인" not in f6.build_cells(es, date(2026, 10, 16))["display_rows"]


def test_no_mcap_counts_in_coarse_cells_only():
    es = [_ev(mcap=f6.NO_MCAP, x=i / 100) for i in range(20)]
    cells = {c["label"]: c for c in f6.build_cells(es, date(2026, 10, 16))["cells"]}
    assert cells["긍정 · 2상"]["status"] == "표시"                      # 시총을 쓰지 않는 칸
    assert cells["긍정 · 2상 · 시총 없음"]["status"] == "잔여"


@pytest.mark.parametrize("n,status", [(19, "표본 부족"), (20, "표시")])
def test_min_n_boundary(n, status):
    es = [_ev(x=i / 100) for i in range(n)]
    c = {c["label"]: c for c in f6.build_cells(es, date(2026, 10, 16))["cells"]}["긍정 · 2상"]
    assert c["status"] == status and c["n"] == n
    assert ("median" in c) == (status == "표시")


def test_missing_price_not_in_n():
    es = [_ev(x=i / 100) for i in range(20)] + [_ev(x=None)]
    res = f6.build_cells(es, date(2026, 10, 16))
    c = {c["label"]: c for c in res["cells"]}["긍정 · 2상"]
    assert c["n"] == 20 and c["missing_price"] == 1 and res["missing_price"] == 1


def test_24_month_window_edges():
    asof = date(2026, 10, 16)
    es = [_ev(d="2024-10-16"), _ev(d="2024-10-15"), _ev(d="2026-10-16"), _ev(d="2026-10-17")]
    res = f6.build_cells(es, asof)
    assert res["window"] == {"from": "2024-10-16", "to": "2026-10-16", "months": 24}
    assert res["events_in_window"] == 2
    assert f6.months_before(date(2026, 3, 31), 24) == date(2024, 3, 31)
    assert f6.months_before(date(2026, 2, 28), 24) == date(2024, 2, 28)


def test_granularity_order():
    es = [_ev(), _ev(direction="부정", stage="3상", mcap="1B-5B")]
    levels = [c["level"] for c in f6.build_cells(es, date(2026, 10, 16))["cells"]]
    assert levels == sorted(levels, key=f6.LEVELS.index)
    assert levels[0] == "전체" and levels[-1] == "방향 × 단계 × 시총"


def test_today_rows_are_overall_and_positive_on_sealed_sample():
    """봉인 표본 68행의 방향 · 단계 분포 그대로 (가격은 임의 값) · 오늘 표시 행 = 전체 · 긍정 (설계 부록 B)."""
    rows = f6.sealed_sample()
    fake = [{**r, "price_base": "10", "price_reaction": str(10 + i % 7), "xbi_base": "100", "xbi_reaction": "101"}
            for i, r in enumerate(rows)]
    events = [f6.to_event(r, {}) for r in fake]
    res = f6.build_cells(events, date(2026, 10, 16))
    assert res["display_rows"] == ["전체", "긍정"]
    n = {c["label"]: c["n"] for c in res["cells"]}
    assert (n["전체"], n["긍정"], n["혼재"], n["부정"], n["긍정 · 단계 미확인"]) == (68, 43, 19, 6, 20)


def test_mcap_at_announcement_uses_latest_end_on_or_before():
    pts = [{"end": "2025-06-30", "shares": 100}, {"end": "2025-12-31", "shares": 200}, {"end": "2026-03-31", "shares": 300}]
    assert f6.shares_at(pts, "2026-01-15") == 200
    assert f6.shares_at(pts, "2025-01-01") is None
    r = {"accession": "A", "ticker": "T", "accept_et": "2026-01-15T07:00:00", "direction": "positive", "stage": "2상",
         "price_base": "2", "price_reaction": "2", "xbi_base": "1", "xbi_reaction": "1"}
    assert f6.to_event(r, {"T": [{"end": "2025-12-31", "shares": 100_000_000}]})["mcap"] == "50M-300M"   # 2억
    assert f6.to_event(r, {})["mcap"] == f6.NO_MCAP


def test_monthly_cells_first_judgment_then_skip_then_day1(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = f6.run(date(2026, 10, 16))
    assert res["cells"]["status"] == "computed"                       # 그 달 파일 없음 → 첫 판정
    assert json.loads(f6.cells_path(date(2026, 10, 16)).read_text())["reason"].startswith("첫 판정")
    assert f6.run(date(2026, 10, 17))["cells"]["status"] == "skipped"  # 다른 날 건너뜀
    assert f6.run(date(2026, 11, 1))["cells"]["status"] == "computed"  # 1일 재판정
    assert json.loads(f6.cells_path(date(2026, 11, 1)).read_text())["reason"] == "1일 재판정"


def test_cells_stop_when_fixed_price_file_changed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    f6.run(date(2026, 10, 16))
    f6.out_path().write_text(f6.out_path().read_text() + "x\n")
    res = f6.run(date(2026, 11, 1))
    assert res["cells"]["status"] == "stopped" and "고정 가격" in res["cells"]["reason"]
