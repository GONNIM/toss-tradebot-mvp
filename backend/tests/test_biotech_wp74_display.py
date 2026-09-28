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
