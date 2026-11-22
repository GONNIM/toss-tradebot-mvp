"""1120-01 단계 4 · 고장 고침 13건 (화면 문구 · 안내 · 로그인 표시).

규칙을 바꾸지 않는다(점수 · 후보 조건 · 판정 · 경보 규칙 · 계산식 · 수집 방식 · 운영 값).
문구가 코드가 저장하는 값과 어긋나지 않는지만 본다. 화면 파일은 글자로 읽어 검사한다(화면 단위 시험 도구가 없음).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FE = ROOT / "frontend"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── a · Moonshot 매수 가격대 문구는 저장하는 값과 같아야 한다 ────────────────
def test_a_moonshot_price_labels_match_stored_values():
    cron = _read("backend/scheduler/cron.py")
    assert "buy_price_b=p.buy_price_limit_3pct" in cron and "buy_price_c=p.buy_price_limit_7pct" in cron
    picks = _read("backend/discovery/moonshot_picks.py")
    assert "round(cur_price * 0.97, 4)" in picks and "round(cur_price * 0.93, 4)" in picks
    page = _read("frontend/app/lab/moonshot/page.tsx")
    assert "B 현재가 -3% 지정가" in page and "C 현재가 -7% 지정가" in page
    assert "+8% 돌파" not in page and "-5% drop" not in page
