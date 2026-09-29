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


def test_note_fields_parse_and_fallback():
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
    """검수 v1 · 참가 조건 3건 = '기타' · 미용 신설 · 미등재 = '기타 (원문)'."""
    import json as _json
    snap = {"matches": [
        {"nct_id": f"NCT0000000{i}", "conditions": [c], "mesh_terms": []}
        for i, c in enumerate(["Hepatic Impairment", "Hepatic Impairment (HI)", "Renal Impairments", "Wrinkle", "Pigmentation", "Some Unlisted Thing"])
    ]}
    (tmp_path / "ctgov_snapshot.json").write_text(_json.dumps(snap))
    monkeypatch.setattr(b, "DATA_DIR_RUNTIME", tmp_path)
    b._FILE_CACHE.clear()
    cats = [b._trial_display(f"NCT0000000{i}")["category"] for i in range(6)]
    assert cats[:3] == ["기타", "기타", "기타"]
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
