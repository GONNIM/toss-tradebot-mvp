"""WP88 · 8-K 보도자료 (EX-99.1) 제목·첫 문단 · 하루 SEC 상한 · 7.01 포함 · z.ai 입력 금지어 문장 제외."""
from __future__ import annotations

import json
import logging
from datetime import date

from backend.scripts import biotech_h77_alert_brief as br
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecDailyLedger

SUBMISSIONS = {"filings": {"recent": {
    "form": ["8-K", "8-K", "8-K"],
    "filingDate": ["2026-09-29", "2026-09-29", "2026-09-28"],
    "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002", "0000000001-26-000003"],
    "items": ["8.01,9.01", "7.01,9.01", "5.02"],
    "primaryDocDescription": ["8-K", "8-K", "8-K"],
}}}
INDEX = '<table><tr><td>2</td><td>EX-99.1</td><td><a href="/Archives/edgar/data/1/x/ex991.htm">ex991.htm</a></td><td>EX-99.1</td></tr></table>'
PRESS = """<html><head><title>EX-99.1</title></head><body>
<p><b>Acme Bio Announces Positive Topline Results from Phase 3 ACME-1 Trial</b></p>
<p>BOSTON, Sept. 29, 2026 /PRNewswire/ -- Acme Bio, Inc. (Nasdaq: ACME) today announced that the Phase 3 ACME-1 trial met its primary endpoint. The company plans to submit a marketing application in 2027.</p>
<p>Forward-Looking Statements</p>
<p>This press release contains forward-looking statements about future results.</p>
</body></html>"""


class _Resp:
    def __init__(self, text):
        self.status_code, self.text = 200, text


class _Client:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if "submissions" in url:
            return _Resp(json.dumps(SUBMISSIONS))
        if url.endswith("-index.htm"):
            return _Resp(INDEX)
        return _Resp(PRESS)


def _run(tmp_path, monkeypatch, used: int):
    monkeypatch.setattr(br.time, "sleep", lambda s: None)
    led = SecDailyLedger.load("20261001", base=tmp_path)
    if used:
        led.add("form4", used)
    counter = {"sec_requests": 0, "zai_calls": 0, "ledger": led}
    client = _Client()
    items = br.sec_8k(client, "1", date(2026, 9, 24), counter)
    return items, client, counter, led


def test_title_lead_and_701_included(tmp_path, monkeypatch):
    items, client, counter, led = _run(tmp_path, monkeypatch, 0)
    by = {it["items"]: it for it in items}
    for key in ("8.01,9.01", "7.01,9.01"):          # 7.01 + 9.01 도 대상
        it = by[key]
        assert it["ex99_1_status"] == "ok"
        assert it["ex99_1_title"] == "Acme Bio Announces Positive Topline Results from Phase 3 ACME-1 Trial"
        assert it["ex99_1_lead"].startswith("Acme Bio, Inc. (Nasdaq: ACME) today announced")   # 머리말 제거
        assert "forward-looking" not in it["ex99_1_lead"].lower()
    assert by["5.02"]["ex99_1_lead"] == ""             # 대상 아닌 8-K 는 첫 문단 없음 (제목만 예전처럼)
    assert led.counts == {"brief": 4, "exhibit": 3}


def test_daily_cap_skips_only_press_release(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    items, client, counter, led = _run(tmp_path, monkeypatch, SEC_DAILY_CAP)
    assert [it["ex99_1_status"] for it in items] == ["daily_cap"] * 3
    assert not any(u.endswith("ex991.htm") for u in client.urls)       # 보도자료 요청 0회
    assert sum(u.endswith("-index.htm") for u in client.urls) == 3     # 나머지 (8-K 목록·색인) 는 계속
    assert counter["exhibit_skipped"] == 3 and "보도자료 읽기 건너뜀" in caplog.text


def test_cut_lead_400_at_sentence_boundary():
    text = ("Sentence number one is here. " * 30).strip()
    out = br.cut_lead(text)
    assert len(out) <= br.LEAD_MAX == 400 and out.endswith(".…")
    assert br.cut_lead("짧은 문단입니다.") == "짧은 문단입니다."
    assert len(br.cut_lead("x" * 1000)) == 400                          # 문장 경계가 없으면 글자 수로


def test_forbidden_sentences_removed_before_llm():
    lead = ("Acme Bio today announced topline results. Analysts raised the price target to $40. "
            "The trial enrolled 300 patients.")
    assert br.safe_lead_for_llm(lead) == "Acme Bio today announced topline results. The trial enrolled 300 patients."
    assert br.safe_lead_for_llm("We see strong upside. Investors should buy now.") == ""
    b = {"mentions": {"history": []}, "reddit": [], "form4": {"available": False}, "schedule": "예정 일정 없음",
         "sec_8k": [{"filing_date": "2026-09-29", "items": "8.01,9.01", "description": "", "ex99_1_title": "t",
                     "ex99_1_lead": "We see strong upside. Investors should buy now."}]}
    assert not any("첫 문단" in s for s in br.sources_for(b))          # 다 걸리면 출처 항목 자체를 넣지 않음


def test_exhibit_target_rule():
    assert br.exhibit_target("8.01,9.01") and br.exhibit_target("7.01, 9.01")
    assert not br.exhibit_target("8.01") and not br.exhibit_target("5.02,9.01") and not br.exhibit_target("")


# WP92 · EDGAR 보도자료 실제 모양 (IOVA 2026-09-29 EX-99.1 구조를 줄인 것) · 한 <P> 안 줄바꿈 · 첫 굵은 글씨가 "Exhibit 99.1"
EDGAR_LIKE = """<html><head><title>EX-99.1</title></head><body>
<P STYLE="text-align: right"><FONT><B>Exhibit 99.1</B></FONT></P>
<P STYLE="text-align: center"><FONT><B>Acme Bio
Raises Full Year 2026 Revenue Guidance to $410 to $420 Million</B></FONT></P>
<P STYLE="text-align: center"><FONT><I>Represents an Increase of $55 Million at the Midpoint</I></FONT></P>
<P><FONT><B>PHILADELPHIA, Pennsylvania, September&nbsp;29,
2026 --&nbsp;</B>Acme Bio,&nbsp;Inc. (NASDAQ: ACME), a commercial biotechnology company, today raised its full year 2026
total revenue guidance range to $410 to $420 million.</FONT></P>
</body></html>"""


def test_edgar_like_title_and_lead():
    t = br.exhibit_title(EDGAR_LIKE)
    assert t == "Acme Bio Raises Full Year 2026 Revenue Guidance to $410 to $420 Million"
    lead = br.exhibit_lead(EDGAR_LIKE, t)
    assert lead.startswith("Acme Bio, Inc. (NASDAQ: ACME), a commercial biotechnology company, today raised")
    assert "Represents an Increase" not in lead and "PHILADELPHIA" not in lead
