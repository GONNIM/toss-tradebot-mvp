"""WP93 · 실제 8-K 보도자료 (IOVA 2026-09-29 EX-99.1 · 2026-10-01 받은 응답을 줄인 것 · 추가 SEC 요청 없음) 추출 테스트."""
from __future__ import annotations

from pathlib import Path

from backend.scripts import biotech_h77_alert_brief as br

DOC = (Path(__file__).parent / "fixtures" / "biotech_8k_ex991_iova_20260929.htm").read_text()


def test_title_from_bold_headline_skipping_exhibit_label():
    assert br.exhibit_title(DOC) == "Iovance Biotherapeutics Raises Full Year 2026 Revenue Guidance to $410 to $420 Million"


def test_lead_is_dateline_paragraph_without_dateline_or_forward_looking():
    lead = br.exhibit_lead(DOC, br.exhibit_title(DOC))
    assert lead.startswith("Iovance Biotherapeutics, Inc. (NASDAQ: IOVA), a commercial biotechnology company")
    assert len(lead) <= br.LEAD_MAX and lead.endswith("…")
    assert "PHILADELPHIA" not in lead and "New Guidance" not in lead and "forward-looking" not in lead.lower()
