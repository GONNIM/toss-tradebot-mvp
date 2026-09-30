"""WP88-3 · Form 4 XML 원문 보관 (요청 추가 없음) · 30일 지난 파일 삭제 · 주식수 조회 예외에도 장부 기록."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from backend.scripts import _biotech_paths as _P
from backend.scripts import biotech_h65_form4_daily as h65
from backend.scripts import biotech_mcap_daily as mc

FIXTURE = Path(__file__).parent / "fixtures" / "biotech_form4_sample.xml"
ACC = "0000947871-26-000880"


def test_h65_keeps_new_xml_without_extra_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    today = time.strftime("%Y-%m-%d")
    sent = []

    @contextmanager
    def fake_client(on_request):
        yield object()

    monkeypatch.setattr(h65, "sec_client", fake_client)
    monkeypatch.setattr(h65, "load_fund_ciks", lambda: ["0001055951"])
    monkeypatch.setattr(h65, "fetch_form4_accessions", lambda c, f: sent.append("list") or [{"accession": ACC, "date": today}])
    monkeypatch.setattr(h65, "fetch_form4_xml", lambda c, f, a: sent.append("xml") or FIXTURE.read_text())
    h65.main()
    kept = tmp_path / "form4_xml" / f"{ACC}.xml"
    assert kept.read_text() == FIXTURE.read_text()
    assert sent == ["list", "xml"]                       # 보관 때문에 늘어난 요청 없음


def test_prune_removes_31_day_old_files(tmp_path):
    old, new = tmp_path / "old.xml", tmp_path / "new.xml"
    old.write_text("x")
    new.write_text("y")
    now = time.time()
    os.utime(old, (now - 31 * 86400, now - 31 * 86400))
    os.utime(new, (now - 29 * 86400, now - 29 * 86400))
    assert h65.prune_xml(tmp_path, now=now) == 1
    assert not old.exists() and new.exists()


def test_mcap_exception_still_records_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(_P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(mc._P, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv(mc.FLAG, "1")
    monkeypatch.setattr(mc, "load_candidates", lambda: {"AAA": "1", "BBB": "2", "CCC": "3", "DDD": "4"})
    n = {"i": 0}

    def get(url):
        n["i"] += 1
        if n["i"] == 3:
            raise ConnectionError("3번째 요청 실패")
        return {"status": 404, "json": None}

    try:
        mc.run("weekly", get_sec=get, today=date(2026, 10, 5))
    except ConnectionError:
        pass
    else:
        raise AssertionError("예외가 전달되어야 함")
    led = json.loads((tmp_path / "sec_usage" / "sec_usage_20261005.json").read_text())
    assert led["counts"]["mcap_shares"] >= 2
