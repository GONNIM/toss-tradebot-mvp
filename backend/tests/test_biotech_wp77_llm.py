"""WP77 · 모델 선택 3단계 · 출처 번호 검증 · 금지어 · 키 미출력 · 브리핑 수집 순수 함수."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from backend.scripts import biotech_h77_alert_brief as br
from backend.scripts import biotech_llm as llm

FAKE_KEY = "zz-test-key-" + "q" * 30


MODELS_20260928 = [  # 2026-09-28 서버 실측 목록 (id · created)
    {"id": "glm-4.5", "created": 1753632000}, {"id": "glm-4.5-air", "created": 1753632000},
    {"id": "glm-4.6", "created": 1759276800}, {"id": "glm-4.7", "created": 1766332800},
    {"id": "glm-5", "created": 1770739200}, {"id": "glm-5-turbo", "created": 1773504000},
    {"id": "glm-5.1", "created": 1774620000}, {"id": "glm-5.2", "created": 1781625600},
    {"id": "glm-5.3", "created": 1786636800}, {"id": "glm-5.3-flash", "created": 1786636800},
    {"id": "glm-5.3-flashx", "created": 1786636800},
]


def test_stable_detection():
    assert llm.is_stable("glm-5.3") and llm.is_stable("glm-5") and llm.is_stable("glm-4.6")
    for bad in ("glm-5.3-flash", "glm-5.3-flashx", "glm-4.5-air", "glm-5-turbo", "glm-4.5v", "glm-6-preview", "gpt-4", "glm-5.3-beta"):
        assert not llm.is_stable(bad), bad


def test_latest_by_version_then_created():
    assert llm.pick_latest_stable(MODELS_20260928) == "glm-5.3"
    tie = [{"id": "glm-5.3", "created": 1}, {"id": "glm-5.3.0", "created": 9}]
    assert llm.pick_latest_stable(tie) == "glm-5.3.0"          # 버전 동률 (5.3 == 5.3.0) → 생성 시각 최신
    assert llm.pick_latest_stable([{"id": "glm-5.10", "created": 1}, {"id": "glm-5.9", "created": 2}]) == "glm-5.10"


def test_list_first_even_if_env_set(monkeypatch, tmp_path):
    monkeypatch.setenv("ZAI_MODEL", "glm-5.2")
    assert llm.resolve_zai_model(lambda: MODELS_20260928, tmp_path / "c.json", "2026-09-29") == ("glm-5.3", "list")
    assert llm.resolve_zai_model(lambda: 1 / 0, tmp_path / "c.json", "2026-09-29") == ("glm-5.3", "list_cache")


def test_fallback_order_env_then_constant(monkeypatch, tmp_path):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setenv("ZAI_MODEL", "glm-5.2")
    assert llm.resolve_zai_model(boom, tmp_path / "a.json", "2026-09-29") == ("glm-5.2", "env")
    monkeypatch.delenv("ZAI_MODEL")
    assert llm.resolve_zai_model(boom, tmp_path / "b.json", "2026-09-29") == (llm.ZAI_MODEL_FALLBACK, "fallback")


def test_notify_once_when_model_changes(tmp_path):
    sent = []
    c = tmp_path / "c.json"
    llm.resolve_zai_model(lambda: [{"id": "glm-5.2", "created": 1}], c, "2026-09-28", notify=lambda a, b: sent.append((a, b)))
    llm.resolve_zai_model(lambda: MODELS_20260928, c, "2026-09-28", notify=lambda a, b: sent.append((a, b)))  # 같은 날 = 캐시
    llm.resolve_zai_model(lambda: MODELS_20260928, c, "2026-09-29", notify=lambda a, b: sent.append((a, b)))
    llm.resolve_zai_model(lambda: MODELS_20260928, c, "2026-09-30", notify=lambda a, b: sent.append((a, b)))
    assert sent == [("glm-5.2", "glm-5.3")]


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
    monkeypatch.setattr(llm, "resolve_zai_model", lambda: ("glm-x", "list"))
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
    monkeypatch.setattr(llm, "resolve_zai_model", lambda: ("glm-x", "list"))

    def fail(url, payload):
        raise TimeoutError("20s")

    res = llm.summarize("ENTX", ["a"], post=fail)
    assert res["ok"] is False and res["error"] == "TimeoutError" and FAKE_KEY not in json.dumps(res)


# ── 브리핑 수집 순수 함수 ─────────────────────────────────────

def test_alert_rule_wp78():
    from backend.scripts.biotech_alert_rule import judge
    # 2026-09-28 IOVA · 기준선 6일 · 1건 6배 → 수집 중 (판정 제외)
    assert judge({"st_baseline_n": "6", "st_baseline_mult": "6.0", "apewisdom_24h": "1", "reddit_rss_matches": "0"}) == (False, "collecting")
    # 기준선 7일 · 6배지만 오늘 1건 → 절대량 미달
    assert judge({"st_baseline_n": "7", "st_baseline_mult": "6.0", "apewisdom_24h": "1", "reddit_rss_matches": "0"}) == (False, "none")
    assert judge({"st_baseline_n": "7", "st_baseline_mult": "5.0", "apewisdom_24h": "5", "reddit_rss_matches": "0"}) == (True, "mult")
    assert judge({"st_baseline_n": "8", "st_baseline_mult": "collecting", "apewisdom_24h": "0", "reddit_rss_matches": "3"}) == (True, "rss")
    # ENTX 형태 · 레딧 3건이어도 기준선 6일이면 수집 중
    assert judge({"st_baseline_n": "6", "st_baseline_mult": "collecting", "apewisdom_24h": "0", "reddit_rss_matches": "3"}) == (False, "collecting")


def test_pick_alerts_cap_and_order():
    rows = [{"ticker": f"T{i}", "st_baseline_n": "7", "st_baseline_mult": "1.0", "apewisdom_24h": "0", "reddit_rss_matches": "3"} for i in range(7)]
    rows.append({"ticker": "M", "st_baseline_n": "9", "st_baseline_mult": "6.0", "apewisdom_24h": "12", "reddit_rss_matches": "0"})
    picked = [r["ticker"] for r in br.pick_alerts(rows)]
    assert picked[0] == "M" and len(picked) == 5


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
    monkeypatch.setattr(llm, "resolve_zai_model", lambda: ("glm-x", "list"))
    seen = {}

    def fake_post(url, payload):
        seen.update(payload)
        return {"choices": [{"message": {"content": "a [1]"}}]}

    llm.summarize("X", ["s"], post=fake_post)
    assert seen["thinking"] == {"type": "disabled"} and seen["max_tokens"] >= 800
    assert "출처 이름" in llm.SYSTEM_PROMPT
