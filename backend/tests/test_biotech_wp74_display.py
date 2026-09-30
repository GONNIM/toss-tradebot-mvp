"""WP74 · 시총 배지 (표시 계층 전용) · 신선도 규칙."""
from __future__ import annotations

from datetime import date, timedelta

from backend.api.routes import biotech as b


def _write(tmp_path, rows):
    p = tmp_path / "mcap_display_inputs_test.csv"
    p.write_text("ticker,cik,shares,shares_asof,close,close_date,source\n" + "\n".join(rows) + "\n")
    return tmp_path


def test_mcap_display_freshness(tmp_path, monkeypatch):
    today = date.today()
    fresh = (today - timedelta(days=30)).isoformat()
    old_sh = (today - timedelta(days=400)).isoformat()
    old_px = (today - timedelta(days=90)).isoformat()
    d = _write(tmp_path, [
        f"AAA,1,10000000,{fresh},50,{fresh},t",      # 5억 달러 → 300M-1B
        f"BBB,2,10000000,{old_sh},50,{fresh},t",     # 주식수 12개월 초과 → 배지 없음
        f"CCC,3,10000000,{fresh},50,{old_px},t",     # 종가 60일 초과 → 배지 없음
        f"DDD,4,1000000000,{fresh},10,{fresh},t",    # 100억 → 5B+
    ])
    monkeypatch.setattr(b, "DATA_DIR_DOCS", d)
    monkeypatch.setattr(b, "DATA_DIR", tmp_path / "none")
    b._MCAP_CACHE.update({"mtime": None, "rows": {}})
    assert b._mcap_display("AAA") == ("300M-1B", fresh)
    assert b._mcap_display("BBB") == ("", "")
    assert b._mcap_display("CCC") == ("", "")
    assert b._mcap_display("DDD")[0] == "5B+"
    assert b._mcap_display("ZZZ") == ("", "")
    assert b._mcap_display("AAA", "1B-5B") == ("1B-5B", "")      # CSV 실제 값 우선


def test_note_fields_parse_and_fallback(monkeypatch):
    monkeypatch.setattr(b, "_today_kst", lambda: date(2026, 9, 27))
    f = b._note_fields("CT.gov (AACT 2026-09-27) NCT06868264 완료 예정 D-3 (2026-09-30 · PHASE3)")
    assert f == {"nct_id": "NCT06868264", "days_to": 3, "event_date": "2026-09-30", "phase": "PHASE3"}
    assert b._note_fields("FDA AdCom 2026-10-01")  == {}       # 형식 불일치 → 화면은 원문 표시


def test_rumor_rows_have_display_fields():
    # 표1 과 A 전체 행은 카드 펼침용 필드 (stage · baseline_n) 를 가진다 (기본값 허용)
    r = b.RumorRow(table="A", ticker="X", name="n", mcap_bucket="", days_hint="D-1", detail="d")
    assert r.stage == "" and r.baseline_n is None and r.days_to is None
    k = b.BiotechKpi(generated="t", candidates_total=0, news_a_ready=0, insider_buy_20d=0, alerts=0)
    assert k.alert_tickers == []


def test_wp79_dictionary_categories(tmp_path, monkeypatch):
    """검수 v1 · 미용 신설 · 미등재 = '기타 (원문)' · 참가 조건 3건은 v2 (WP80) 에서 '건강인·약동학' 으로 이동."""
    import json as _json
    snap = {"matches": [
        {"nct_id": f"NCT0000000{i}", "conditions": [c], "mesh_terms": []}
        for i, c in enumerate(["Hepatic Impairment", "Hepatic Impairment (HI)", "Renal Impairments", "Wrinkle", "Pigmentation", "Some Unlisted Thing"])
    ]}
    (tmp_path / "ctgov_snapshot.json").write_text(_json.dumps(snap))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    cats = [b._trial_display(f"NCT0000000{i}")["category"] for i in range(6)]
    assert cats[:3] == ["건강인·약동학", "건강인·약동학", "건강인·약동학"]   # v1 '기타' → v2 이동
    assert cats[3:5] == ["미용", "미용"]
    assert cats[5] == "기타 (Some Unlisted Thing)"


def test_wp79_card_text_renders_new_categories():
    """프론트 cardText() 가 '미용' · '기타' 분류를 문장 앞에 렌더 (tsx 로 실행 · 없으면 건너뜀)."""
    import shutil
    import subprocess
    from pathlib import Path
    import pytest
    fe = Path(__file__).resolve().parents[2] / "frontend"
    if not shutil.which("npx") or not (fe / "node_modules").exists():
        pytest.skip("npx/node_modules 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/biotech-display.check.ts"], cwd=fe, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-500:]



def test_wp80_dictionary_v2_categories(tmp_path, monkeypatch):
    """사전 v2 · 신설 분류 3개 · 전암 병변 = 암 · 참가 조건 = 건강인·약동학."""
    import json as _json
    terms = ["Healthy Volunteers", "Chronic Pain", "Hearing Loss", "Uterine Cervical Dysplasia", "Hepatic Impairment"]
    snap = {"matches": [{"nct_id": f"NCT1000000{i}", "conditions": [t], "mesh_terms": []} for i, t in enumerate(terms)]}
    (tmp_path / "ctgov_snapshot.json").write_text(_json.dumps(snap))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    cats = [b._trial_display(f"NCT1000000{i}")["category"] for i in range(len(terms))]
    assert cats == ["건강인·약동학", "통증", "청각·이비인후", "암", "건강인·약동학"]



def test_wp82_ignore_category_skipped_and_never_shown(tmp_path, monkeypatch):
    """'무시' 용어는 건너뛰고 다음 용어 · 모두 '무시' 면 '기타 (첫 원문)' · 화면 값에 '무시' 없음."""
    import csv as _csv
    import json as _json
    ign = [r["term"] for r in _csv.DictReader(open(b.DATA_DIR_DOCS / "condition_categories.csv")) if r["category"] == "무시"]
    assert len(ign) >= 2
    snap = {"matches": [
        {"nct_id": "NCT20000001", "mesh_terms": [ign[0]], "conditions": ["Obesity"]},   # 무시 → 다음 용어 = 비만·대사
        {"nct_id": "NCT20000002", "mesh_terms": [], "conditions": [ign[0], ign[1]]},     # 모두 무시 → 기타 (첫 원문)
    ]}
    (tmp_path / "ctgov_snapshot.json").write_text(_json.dumps(snap))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    t1, t2 = b._trial_display("NCT20000001"), b._trial_display("NCT20000002")
    assert t1["category"] == "비만·대사" and t1["category_source"] == "Obesity"
    assert t2["category"] == f"기타 ({ign[0]})"
    assert "무시" not in _json.dumps([t1["category"], t2["category"]], ensure_ascii=False)


def test_wp85_form4_ticker_not_cik_digits(tmp_path, monkeypatch):
    """표4 티커 = h65 issuer_ticker 또는 SEC 명부 · CIK 끝자리 (예 088082) 를 쓰지 않음 · CIK 는 별도 필드."""
    import asyncio
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "biotech_candidates_v3_20260930.csv").write_text("ticker,name,state_note_v50\n")
    (tmp_path / "h65_form4_daily_table_test.csv").write_text(
        "filing_date,tx_date,elapsed_days,issuer_cik,issuer_name,filer_cik,filer_type,shares,price_on_tx,amount_usd_approx,accession\n"
        "2026-09-23,2026-09-21,8,0002088082,\"Electra Therapeutics, Inc.\",0001055951,전문 펀드,333333,,,a\n"
        "2026-09-23,2026-09-21,8,0009999999,Unknown Bio,0001055951,전문 펀드,1,,,b\n")
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    rows = [r for r in asyncio.run(b.get_rumor_json(date="2026-09-30", _admin="x")).rows if r.table == "표4"]
    assert [(r.ticker, r.cik) for r in rows] == [("ETRA", "0002088082"), ("", "0009999999")]


def test_wp85_radar_rows_have_trial_fields(tmp_path, monkeypatch):
    import asyncio
    import json as _json
    c = tmp_path / "candidates"
    c.mkdir()
    (c / "radar_v1_3_20260930.csv").write_text("ticker,name,mcap,time_state,score,expert,crowd,near,unnoticed,risk,tag_bonus,why_easy\n"
                                               "ABCL,AbCellera,unknown,A,0.5,0.5,0,1,0.5,0,0,뉴스 예정 · 2027년 2월 28일 예정 · D-153\n")
    (c / "biotech_candidates_v3_20260930.csv").write_text(
        "ticker,name,state_note_v50\nABCL,AbCellera,CT.gov (AACT 2026-09-28) NCT07118891 완료 예정 D-153 (2027-02-28 · PHASE1/PHASE2)\n")
    (tmp_path / "ctgov_snapshot.json").write_text(_json.dumps({"matches": [{"nct_id": "NCT07118891", "conditions": ["Obesity"], "mesh_terms": []}]}))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    monkeypatch.setattr(b, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(b, "_today_kst", lambda: date(2026, 9, 28))   # 노트 작성일 기준이면 D-153 · WP87 부터 화면 날짜 기준
    b._FILE_CACHE.clear()
    r = asyncio.run(b.get_radar_json(_admin="x")).rows[0]
    assert (r.nct_id, r.phase, r.event_date, r.days_to) == ("NCT07118891", "PHASE1/PHASE2", "2027-02-28", 153)
    assert r.trial["category"] == "비만·대사"



def test_wp87_days_to_from_view_date(monkeypatch):
    """D-n = 화면 보는 날 (KST) 기준 · 노트의 D-2 (주간 잡 날짜 기준) 무시 · 오늘 = D-0 · 어제 = D+1 (음수)."""
    note = "CT.gov (AACT 2026-09-28) NCT06868264 완료 예정 D-2 (2026-09-30 · PHASE3)"
    monkeypatch.setattr(b, "_today_kst", lambda: date(2026, 9, 30))
    assert b._note_fields(note)["days_to"] == 0
    monkeypatch.setattr(b, "_today_kst", lambda: date(2026, 10, 1))
    assert b._note_fields(note)["days_to"] == -1
