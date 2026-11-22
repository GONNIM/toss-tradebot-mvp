"""1120-01 단계 4 · 고장 고침 13건 (화면 문구 · 안내 · 로그인 표시).

규칙을 바꾸지 않는다(점수 · 후보 조건 · 판정 · 경보 규칙 · 계산식 · 수집 방식 · 운영 값).
문구가 코드가 저장하는 값과 어긋나지 않는지만 본다. 화면 파일은 글자로 읽어 검사한다(화면 단위 시험 도구가 없음).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

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


# ── d · 오늘 화면 기한 경보: 규칙은 그대로, 「N일 지남」 문구만 ────────────────
def test_d_deadline_alert_rule_unchanged_and_wording_uses_helper():
    today = _read("backend/api/routes/today.py")
    assert "if dl <= today:" in today                     # 경보 규칙(기한 ≤ 오늘) 그대로
    page = _read("frontend/app/page.tsx")
    assert "deadlineFact(a.deadline, todayKst())" in page


def test_d_today_display_check_ts():
    import shutil
    import subprocess

    if not shutil.which("npx"):
        import pytest
        pytest.skip("npx 없음")
    r = subprocess.run(["npx", "--yes", "tsx", "lib/today-display.check.ts"], cwd=FE, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "today-display ok" in r.stdout


# ── e · Serenity Hunter 환율: 바깥 호출 없이 고정값임을 밝힘 ──────────────────
def test_e_fx_text_says_fixed_value_and_no_outside_call():
    comp = _read("frontend/app/influencer/serenity-hunter/components/ActionCardsSection.tsx")
    assert "고정값 ${won}원 기준" in comp and "원화 금액은 추정" in comp
    assert "FX {data.fx_rate" not in comp
    cards = _read("backend/discovery/serenity/action_cards.py")
    assert '"fx_source": "hardcoded"' in cards            # 값 · 출처 표시는 서버 그대로
    assert "get_toss_client" not in cards and "usd_krw(" not in cards   # 비로그인 요청이 토스를 부르지 않음


# ── g · 판단 기록: 비로그인은 API 401 그대로, 화면은 「로그인 필요」 ─────────────
def test_g_journal_screen_shows_login_needed_not_baseline_error():
    page = _read("frontend/app/journal/page.tsx")
    assert "로그인 필요" in page and "journal-login-needed" in page
    assert "baseline ${r.status}" not in page            # 영어 「에러: baseline 401」 문구가 사라짐
    assert "jr.status === 401 || br.status === 401" in page


@pytest.mark.asyncio
async def test_g_judgments_api_stays_401_without_login(monkeypatch):
    from backend.services.db import init_db

    monkeypatch.setenv("SNIPER_API_TOKEN", "stage4-g-token-0000000000000000")
    await init_db()
    from backend.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for path in ("/api/v1/judgments", "/api/v1/judgments/baseline?days=90"):
            r = await ac.get(path)
            assert r.status_code == 401, (path, r.status_code)
