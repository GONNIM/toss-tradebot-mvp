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


# ── b · max_position_size_usd: 값 · 키 이름은 그대로, 설명과 단위 표시만 ─────
def test_b_unused_value_is_labeled_and_value_unchanged():
    from backend.api.routes.settings import STATIC_SETTINGS

    value, desc = STATIC_SETTINGS["max_position_size_usd"]
    assert value == "1000000"                      # 운영 값은 바꾸지 않았다
    assert "원" in desc and "읽는 매수 코드는 없음" in desc
    # 이 키를 읽는 코드가 정말 없는지 (생기면 이 시험이 알려 설명을 다시 본다)
    hits = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "backend").rglob("*.py")
        if "venv" not in p.parts and "tests" not in p.parts and "max_position_size_usd" in p.read_text(encoding="utf-8")
    ]
    assert hits == ["backend/api/routes/settings.py"]


def test_b_unit_follows_description_before_key_suffix():
    page = _read("frontend/app/admin/settings/page.tsx")
    body = page[page.index("function currencyUnit"):page.index("export default function")]
    assert body.index("KRW|원") < body.index('k.endsWith("_usd")')


# ── c · 섹터 시총 출처 안내 (점수 · 수집 방식은 그대로) ──────────────────────
def test_c_sector_market_cap_source_note_and_no_regular_writer():
    page = _read("frontend/app/sector-leaders/page.tsx")
    assert "정해진 일정으로 갱신하는 작업이 없어" in page
    # 안내가 거짓이 되지 않게: 종목 정보 표를 쓰는 곳은 정기 잡이 아니다 (생기면 안내를 고친다)
    writers = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "backend").rglob("*.py")
        if "venv" not in p.parts and "tests" not in p.parts and "upsert_meta(" in p.read_text(encoding="utf-8")
    ]
    assert writers == ["backend/discovery/data_sources/krx_price/loader.py"]   # 정의만 있고 부르는 곳 없음
