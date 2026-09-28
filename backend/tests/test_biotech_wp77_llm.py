"""WP77 · 모델 선택 3단계 · 출처 번호 검증 · 금지어 · 키 미출력 · 브리핑 수집 순수 함수."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from backend.scripts import biotech_h77_alert_brief as br
from backend.scripts import biotech_llm as llm

FAKE_KEY = "zz-test-key-" + "q" * 30


def test_model_env_first(monkeypatch, tmp_path):
    monkeypatch.setenv("ZAI_MODEL", "glm-x")
    assert llm.resolve_zai_model(fetch_models=lambda: 1 / 0, cache_path=tmp_path / "c.json") == ("glm-x", "env")


def test_model_list_default_flag_then_first_stable(monkeypatch, tmp_path):
    monkeypatch.setenv("ZAI_MODEL", "")
    items = [{"id": "glm-a-preview"}, {"id": "glm-b"}, {"id": "glm-c", "recommended": True}]
    assert llm.resolve_zai_model(lambda: items, tmp_path / "c1.json", "2026-09-28") == ("glm-c", "list")
    items2 = [{"id": "glm-a-preview"}, {"id": "glm-b"}]
    assert llm.resolve_zai_model(lambda: items2, tmp_path / "c2.json", "2026-09-28") == ("glm-b", "list")
    # 하루 1회 캐시 · 같은 날 재호출은 목록 조회 없이 캐시
    assert llm.resolve_zai_model(lambda: 1 / 0, tmp_path / "c2.json", "2026-09-28") == ("glm-b", "list_cache")


def test_model_fallback_on_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("ZAI_MODEL", raising=False)

    def boom():
        raise RuntimeError("down")

    assert llm.resolve_zai_model(boom, tmp_path / "c.json", "2026-09-28") == (llm.ZAI_MODEL_FALLBACK, "fallback")


def test_drop_lines_without_citation_or_out_of_range():
    kept, dropped = llm.validate_lines("레딧 매치가 3건입니다 [2]\n출처 없는 문장입니다\n범위 밖 [9]", n_sources=3)
    assert kept == ["레딧 매치가 3건입니다 [2]"]
    assert {d["reason"] for d in dropped} == {"no_or_bad_citation"}


def test_drop_forbidden_words():
    text = "지금 매수하세요 [1]\n임원 매수 신고가 0건입니다 [2]\n주가가 오를 것으로 보입니다 [1]\nPrice Target raised [1]"
    kept, dropped = llm.validate_lines(text, n_sources=2)
    assert kept == ["임원 매수 신고가 0건입니다 [2]"]
    assert len(dropped) == 3 and all(d["reason"] == "forbidden_word" for d in dropped)


def test_max_three_lines():
    kept, _ = llm.validate_lines("\n".join(f"사실 {i} [1]" for i in range(5)), n_sources=1)
    assert len(kept) == 3


def test_key_never_in_logs_or_result(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("ZAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ZAI_MODEL", "glm-x")
    caplog.set_level(logging.DEBUG)
    seen = {}

    def fake_post(url, payload):
        seen["url"] = url
        seen["headers"] = llm._headers()
        return {"choices": [{"message": {"content": "언급량이 늘었습니다 [1]"}}]}

    res = llm.summarize("ENTX", ["언급량 어제 0 → 오늘 3"], post=fake_post)
    assert res["ok"] and res["lines"] == ["언급량이 늘었습니다 [1]"] and res["model"] == "glm-x"
    assert FAKE_KEY not in seen["url"]                          # URL 에 키 없음
    assert seen["headers"]["Authorization"].endswith(FAKE_KEY)  # 헤더로만
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in json.dumps(res)


def test_summary_failure_returns_panel_only(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ZAI_MODEL", "glm-x")

    def fail(url, payload):
        raise TimeoutError("20s")

    res = llm.summarize("ENTX", ["a"], post=fail)
    assert res["ok"] is False and res["error"] == "TimeoutError" and FAKE_KEY not in json.dumps(res)


# ── 브리핑 수집 순수 함수 ─────────────────────────────────────

def test_pick_alerts_rule_and_cap():
    rows = [{"ticker": f"T{i}", "st_baseline_mult": "collecting", "reddit_rss_matches": "3"} for i in range(7)]
    rows.append({"ticker": "M", "st_baseline_mult": "6.0", "reddit_rss_matches": "0"})
    rows.append({"ticker": "N", "st_baseline_mult": "4.9", "reddit_rss_matches": "2"})
    picked = [r["ticker"] for r in br.pick_alerts(rows)]
    assert picked[0] == "M" and "N" not in picked and len(picked) == 5


def test_recent_posts_24h_only():
    now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
    row = {"reddit_posts": json.dumps([
        {"title": "new", "link": "l1", "updated": "2026-09-28T01:00:00+00:00"},
        {"title": "old", "link": "l2", "updated": "2026-09-26T01:00:00+00:00"},
        {"title": "no time", "link": "l3", "updated": ""},
    ])}
    assert [p["title"] for p in br.recent_posts(row, now)] == ["new"]


def test_business_days_and_schedule():
    assert br.business_days_back(date(2026, 9, 28), 5) == date(2026, 9, 21)   # 월요일 기준 5거래일 전
    assert br.schedule_note({"state_note_v50": "CT.gov (AACT 2026-09-27) NCT1 완료 예정 D-3 (2026-09-30 · PHASE3)"}) \
        == "임상 종료 예정일 2026-09-30 (D-3)"
    assert br.schedule_note(None) == "예정 일정 없음"


def test_reddit_block_fallback_marks_unchecked():
    now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
    posts, checked = br.reddit_block({"reddit_samples": json.dumps([{"title": "t", "link": "l"}])}, now)
    assert posts == [{"title": "t", "link": "l", "updated": ""}] and checked is False
    posts, checked = br.reddit_block({"reddit_posts": "[]", "reddit_samples": "[]"}, now)
    assert posts == [] and checked is True


def test_payload_disables_thinking(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ZAI_MODEL", "glm-x")
    seen = {}

    def fake_post(url, payload):
        seen.update(payload)
        return {"choices": [{"message": {"content": "a [1]"}}]}

    llm.summarize("X", ["s"], post=fake_post)
    assert seen["thinking"] == {"type": "disabled"} and seen["max_tokens"] >= 800
    assert "출처 이름" in llm.SYSTEM_PROMPT
