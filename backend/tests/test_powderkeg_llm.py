"""P7-3a LLM classifier 단위 테스트."""
from __future__ import annotations

import os

import pytest

from backend.powderkeg import llm_classifier as lc
from backend.powderkeg.llm_classifier import (
    _keyword_fallback,
    _parse_json_response,
    classify_owner_event,
    is_llm_configured,
)


def test_keyword_fallback_company_related():
    r = _keyword_fallback("회장 회사자금 횡령 혐의", None)
    assert r.label == "company_related"
    assert r.used_llm is False
    assert r.needs_human_review is True   # confidence=0.5 < 0.8


def test_keyword_fallback_personal_only():
    r = _keyword_fallback("회장 별세에 따른 상속 개시", None)
    assert r.label == "personal_only"
    assert r.used_llm is False


def test_keyword_fallback_unclear():
    r = _keyword_fallback("일반 실적 발표", None)
    assert r.label == "unclear"
    assert r.confidence == 0.0
    assert r.needs_human_review is True


def test_parse_json_response_direct():
    text = '{"label": "personal_only", "confidence": 0.9, "rationale": "개인 사건"}'
    p = _parse_json_response(text)
    assert p is not None
    assert p["label"] == "personal_only"
    assert p["confidence"] == 0.9


def test_parse_json_response_embedded():
    """LLM 이 부가 설명 붙이는 경우도 추출."""
    text = 'Here is the analysis:\n{"label": "company_related", "confidence": 0.85, "rationale": "회사 자금"}\n감사합니다.'
    p = _parse_json_response(text)
    assert p is not None
    assert p["label"] == "company_related"


def test_parse_json_response_invalid_returns_none():
    assert _parse_json_response("not json") is None
    assert _parse_json_response("") is None


@pytest.mark.asyncio
async def test_classify_no_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = await classify_owner_event("회사자금 횡령 혐의")
    assert r.used_llm is False
    assert r.label == "company_related"


@pytest.mark.asyncio
async def test_classify_api_failure_falls_back(monkeypatch):
    """API 호출 실패 시 keyword fallback."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    class _FakeMsg:
        content = []
    class _FakeMessages:
        async def create(self, **kw):
            raise RuntimeError("simulated API error")
    class _FakeClient:
        def __init__(self, api_key): self.messages = _FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)

    r = await classify_owner_event("회사자금 횡령")
    assert r.used_llm is False       # fallback
    assert r.label == "company_related"


@pytest.mark.asyncio
async def test_classify_api_json_response(monkeypatch):
    """실제 API 반환 값 파싱 · needs_human_review 판정."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    class _TextBlock:
        def __init__(self, text): self.text = text
    class _FakeMsg:
        content = [_TextBlock('{"label": "personal_only", "confidence": 0.92, "rationale": "명백히 개인 폭행 사건"}')]
    class _FakeMessages:
        async def create(self, **kw): return _FakeMsg()
    class _FakeClient:
        def __init__(self, api_key): self.messages = _FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)

    r = await classify_owner_event("회장 폭행 사건")
    assert r.used_llm is True
    assert r.label == "personal_only"
    assert r.confidence == pytest.approx(0.92)
    assert r.needs_human_review is False    # 0.92 >= 0.8


@pytest.mark.asyncio
async def test_classify_low_confidence_marks_human_review(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

    class _TextBlock:
        def __init__(self, text): self.text = text
    class _FakeMsg:
        content = [_TextBlock('{"label": "unclear", "confidence": 0.6, "rationale": "문맥 부족"}')]
    class _FakeMessages:
        async def create(self, **kw): return _FakeMsg()
    class _FakeClient:
        def __init__(self, api_key): self.messages = _FakeMessages()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _FakeClient)

    r = await classify_owner_event("애매한 제목")
    assert r.needs_human_review is True    # 0.6 < 0.8


def test_is_llm_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
    assert is_llm_configured() is True
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert is_llm_configured() is False
