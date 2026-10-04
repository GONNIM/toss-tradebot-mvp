"""P3a ⑥ · 원천 우주 (h3_targets_v2 sic_biotech · 13D 명부) 밖 CIK 도 SEC 명부로 티커 · 이름을 채운다 (INCY 879169 · SIC 8731)."""
from __future__ import annotations

import json

from backend.scripts import biotech_h48v3_candidates as c


def test_sec_fallback_fills_ticker_without_widening_universe(tmp_path, monkeypatch):
    targets = tmp_path / "h3_targets_v2_x.csv"
    targets.write_text("ticker,target_cik,target_name,sic_biotech\n"
                       "INCY,0000879169,INCYTE CORP,False\n"
                       "ABCL,0001703057,AbCellera,True\n")
    sec = tmp_path / "sec_company_tickers.json"
    sec.write_text(json.dumps({"0": {"cik_str": 879169, "ticker": "INCY", "title": "INCYTE CORP"},
                               "1": {"cik_str": 1703057, "ticker": "ABCL", "title": "AbCellera Biologics Inc."}}))
    files = {"h3_targets_v2_x.csv": targets, "sec_company_tickers.json": sec}
    monkeypatch.setattr(c, "_find", lambda name: files.get(name))
    monkeypatch.setattr(c, "_find_glob", lambda pat: targets if pat.startswith("h3_targets_v2") else None)
    cik_meta, _ = c.load_cik_ticker_map("x")
    assert "0000879169" not in cik_meta                                     # 우주는 그대로
    assert c.SEC_BY_CIK["0000879169"] == {"ticker": "INCY", "name": "INCYTE CORP"}
    assert cik_meta["0001703057"]["ticker"] == "ABCL"


def test_add_candidate_uses_sec_fallback():
    src = open(c.__file__).read()
    assert 'cik_meta.get(key_cik) or SEC_BY_CIK.get(key_cik)' in src
