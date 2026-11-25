"""1112-07 · 결과 발표 명부 보충 · 요청은 MockTransport (외부 요청 0)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from backend.scripts import biotech_readout_increment as ri
from backend.scripts import biotech_h48v3_candidates as cand
from backend.scripts.biotech_sec_common import SecBlockedError, SecDailyLedger

ROOT = Path(__file__).resolve().parents[2]
WP39 = ROOT / "docs" / "plans" / "biotech" / "data" / "h39_readouts_checkpoint.json"
WP39_SHA = "7de3afdea1a101090a88bc8804d824be0da84f228065bd8965c7d8bc96496a62"

BODY_HIT = "ACCEPTANCE-DATETIME>20261020070000\nThe trial met the primary endpoint with statistically significant topline results."
BODY_MISS = "ACCEPTANCE-DATETIME>20261021070000\nOther news."


def _efts(hits):
    return {"hits": {"total": {"value": len(hits)}, "hits": [{"_source": h} for h in hits]}}


def _client(routes: dict, seen: list):
    def handler(req: httpx.Request):
        seen.append(str(req.url))
        for k, v in routes.items():
            if k in str(req.url):
                status, payload = v
                if isinstance(payload, dict):
                    return httpx.Response(status, json=payload)
                return httpx.Response(status, text=payload)
        return httpx.Response(404, text="")
    return httpx.Client(transport=httpx.MockTransport(handler))


def _base():
    return {"processed_ciks": ["0000000001", "0000000002"],
            "events": [{"cik": "0000000001", "ticker": "AAA", "accession": "0000000001-26-000001"}]}


def _ledger(tmp_path):
    return SecDailyLedger(tmp_path / "sec_usage_20261112.json", "20261112")   # 파일 이름은 장부 규칙 (요청마다 다시 읽음)


def test_new_events_added_known_and_items_skipped(tmp_path):
    seen: list = []
    routes = {
        "ciks=0000000001": (200, _efts([
            {"adsh": "0000000001-26-000001", "items": "8.01", "file_date": "2026-09-10"},   # 명부에 있음 → 건너뜀
            {"adsh": "0000000001-26-000002", "items": "8.01", "file_date": "2026-10-20"},   # 새 사건
            {"adsh": "0000000001-26-000003", "items": "5.02", "file_date": "2026-10-21"},   # 대상 항목 아님
        ])),
        "ciks=0000000002": (200, _efts([{"adsh": "0000000002-26-000009", "items": "7.01", "file_date": "2026-10-21"}])),
        "000000000126000002": (200, BODY_HIT),
        "000000000226000009": (200, BODY_MISS),
    }
    d = ri.load_out(tmp_path / "o.json", "2026-09-02", "2026-11-12")
    with _client(routes, seen) as c:
        get = ri.make_getter(c, _ledger(tmp_path), 300, sleep=lambda s: None)
        ri.run(get, _base(), d, "2026-09-02", "2026-11-12", lambda: None)
    assert [e["accession"] for e in d["events"]] == ["0000000001-26-000002"]
    e = d["events"][0]
    assert e["ticker"] == "AAA" and e["direction"] == "positive" and e["d_day"] == "2026-10-20"
    assert d["complete"] is True and d["stats"]["bodies"] == 2
    assert not any("26000003" in u for u in seen)          # 5.02 본문은 받지 않음
    assert len(seen) == 4                                   # EFTS 2 + 본문 2


@pytest.mark.parametrize("status", [403, 429])
def test_block_stops_immediately(tmp_path, status):
    seen: list = []
    with _client({"ciks=": (status, "blocked")}, seen) as c:
        get = ri.make_getter(c, _ledger(tmp_path), 300, sleep=lambda s: None)
        d = ri.load_out(tmp_path / "o.json", "a", "b")
        with pytest.raises(SecBlockedError):
            ri.run(get, _base(), d, "a", "b", lambda: None)
    assert len(seen) == 1 and d["processed_ciks"] == []


def test_cap_counts_before_send(tmp_path):
    seen: list = []
    led = _ledger(tmp_path)
    led.add("form4", 299)
    led.save()                                              # 요청마다 장부 파일을 다시 읽으므로 디스크에도 있어야 함 (1112-08)
    with _client({"ciks=": (200, _efts([]))}, seen) as c:
        get = ri.make_getter(c, led, 300, sleep=lambda s: None)
        d = ri.load_out(tmp_path / "o.json", "a", "b")
        with pytest.raises(ri.CapReached):
            ri.run(get, _base(), d, "a", "b", lambda: None)
    assert len(seen) == 1 and led.total() == 300 and d["processed_ciks"] == ["0000000001"]


def test_resume_skips_processed(tmp_path):
    p = tmp_path / "o.json"
    d = ri.load_out(p, "a", "b")
    d["processed_ciks"] = ["0000000001"]
    ri.save_out(p, d)
    d2 = ri.load_out(p, "a", "b")
    seen: list = []
    with _client({"ciks=": (200, _efts([]))}, seen) as c:
        ri.run(ri.make_getter(c, _ledger(tmp_path), 300, sleep=lambda s: None), _base(), d2, "a", "b", lambda: None)
    assert len(seen) == 1 and "0000000002" in seen[0]


def _cand_dirs(tmp_path, monkeypatch, runtime=True):
    docs = tmp_path / "docs"
    rt = tmp_path / "rt"
    docs.mkdir()
    rt.mkdir()
    monkeypatch.setattr(cand, "FALLBACK_DIR", docs)
    monkeypatch.setattr(cand, "RUNTIME_DIR", rt if runtime else None)
    monkeypatch.setattr(cand, "DATA_DIR", tmp_path / "nodata")
    return docs, rt


def test_candidates_source_a_merges_increment(tmp_path, monkeypatch):
    docs, rt = _cand_dirs(tmp_path, monkeypatch)
    base = {"events": [{"cik": "0000000001", "accession": "x-1", "d_day": "2020-01-01", "direction": "positive"}]}
    inc = {"events": [{"cik": "0000000002", "accession": "x-2", "d_day": "2099-01-01", "direction": "negative"},
                      {"cik": "0000000001", "accession": "x-1", "d_day": "2099-01-01"}]}   # 같은 접수번호 → 한 번만
    (docs / "h39_readouts_checkpoint.json").write_text(json.dumps(base))
    (docs / "h39_readouts_increment.json").write_text(json.dumps(inc))
    out = cand.source_a_readout("sha", days_recent=90)
    assert [o["cik"] for o in out] == ["0000000002"]


def test_candidates_source_a_broken_increment_falls_back(tmp_path, monkeypatch):
    docs, rt = _cand_dirs(tmp_path, monkeypatch)
    (docs / "h39_readouts_checkpoint.json").write_text(json.dumps({"events": [
        {"cik": "0000000001", "accession": "x-1", "d_day": "2099-01-01"}]}))
    (docs / "h39_readouts_increment.json").write_text("{broken")
    assert [o["cik"] for o in cand.source_a_readout("sha")] == ["0000000001"]


def test_wp39_list_unchanged():
    assert hashlib.sha256(WP39.read_bytes()).hexdigest() == WP39_SHA


def test_efts_500_not_marked_processed(tmp_path):
    seen: list = []
    routes = {"ciks=0000000001": (500, "err"), "ciks=0000000002": (200, _efts([]))}
    d = ri.load_out(tmp_path / "o.json", "a", "b")
    with _client(routes, seen) as c:
        ri.run(ri.make_getter(c, _ledger(tmp_path), 300, sleep=lambda s: None), _base(), d, "a", "b", lambda: None)
    assert d["processed_ciks"] == ["0000000002"]
    assert d["failures"][0]["cik"] == "0000000001" and "500" in d["failures"][0]["status"]
    assert d["complete"] is False


def test_body_transport_error_recorded_and_saved(tmp_path, monkeypatch):
    def handler(req: httpx.Request):
        if "efts" in str(req.url):
            if "0000000001" in str(req.url):
                return httpx.Response(200, json=_efts([{"adsh": "0000000001-26-000005", "items": "8.01"}]))
            return httpx.Response(200, json=_efts([]))
        raise httpx.ConnectTimeout("timeout", request=req)
    d = ri.load_out(tmp_path / "o.json", "a", "b")
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        ri.run(ri.make_getter(c, _ledger(tmp_path), 300, sleep=lambda s: None), _base(), d, "a", "b", lambda: None)
    assert d["processed_ciks"] == ["0000000002"]
    assert d["failures"] == [{"cik": "0000000001", "accession": "0000000001-26-000005", "status": "ConnectTimeout"}]
    assert d["complete"] is False


def test_main_saves_on_block(tmp_path, monkeypatch):
    out = tmp_path / "inc.json"
    monkeypatch.setattr(ri, "out_path", lambda: out)
    monkeypatch.setattr(ri, "load_base", _base)
    monkeypatch.setattr(ri.SecDailyLedger, "load", classmethod(lambda cls, *a, **k: SecDailyLedger(tmp_path / "l.json", "d")))
    monkeypatch.setattr(ri, "build_client", lambda **k: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, text=""))))
    monkeypatch.setattr(ri.time, "sleep", lambda s: None)
    assert ri.main(["--since", "a", "--until", "b"]) == 2
    assert json.loads(out.read_text())["since"] == "a"
