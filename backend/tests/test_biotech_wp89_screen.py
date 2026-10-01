"""WP89 · 임원 매수 표 = 신고 묶음 단위 최근 30건 · 언급 단계 값이 화면 대응표에 모두 있음."""
from __future__ import annotations

import re
from pathlib import Path

from backend.scripts.biotech_h65_form4_daily import select_recent_groups

ROOT = Path(__file__).resolve().parents[2]
KOD, BAKER = "0001468748", "0001263508"


def test_kod_filing_group_kept_whole():
    # Baker Bros. KOD 9/30 신고 · 82행 · 1,941,755주 (2026-10-01 서버 캐시와 같은 모양)
    kod = [{"filer_cik": BAKER, "issuer_cik": KOD, "filing_date": "2026-09-30",
            "tx_date": "2026-09-28" if i < 76 else "2026-09-29", "shares": 23_000} for i in range(81)]
    kod.append({"filer_cik": BAKER, "issuer_cik": KOD, "filing_date": "2026-09-30", "tx_date": "2026-09-29",
                "shares": 1_941_755 - 23_000 * 81})
    others = [{"filer_cik": f"F{i}", "issuer_cik": f"I{i}", "filing_date": f"2026-09-{i % 20 + 1:02d}",
               "tx_date": "2026-09-30", "shares": 1} for i in range(40)]
    out = select_recent_groups(others + kod, 30)
    k = [r for r in out if r["issuer_cik"] == KOD]
    assert len(k) == 82 and sum(r["shares"] for r in k) == 1_941_755
    assert len({(r["filer_cik"], r["issuer_cik"], r["filing_date"]) for r in out}) == 30


def test_every_stage_value_has_korean_label():
    src = (ROOT / "backend/scripts/biotech_h48v3_confirm.py").read_text()
    body = src[src.index("def stage("):src.index("def main(")]
    values = set(re.findall(r'return "([a-z_]+)"', body))
    ts = (ROOT / "frontend/lib/biotech-display.ts").read_text()
    table = ts[ts.index("const STAGE_KO"):ts.index("};", ts.index("const STAGE_KO"))]
    labels = set(re.findall(r"^\s*([a-z_]+):", table, re.M))
    assert values == {"collecting", "quiet", "frenzy", "early", "spread"}
    assert values <= labels, values - labels
