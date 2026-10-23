"""FallbackLLM 단위 테스트 — Anthropic 1순위 · 키 없음/오류 시 Z.ai (2026-10-23 결정)."""
from __future__ import annotations

import pytest

from backend.services import llm as llm_mod
from backend.services.llm import (
    ClaudeLLM,
    FallbackLLM,
    LLMCallError,
    PickThesis,
    get_llm_client,
)

GOOD_JSON = '{"thesis": "좋은 분석", "catalysts": ["c"], "risks": ["r"], "news_summary": "n", "manipulation_risk": 2}'

ARGS = dict(
    ticker="TEST", company_name="Test", sector="Tech", current_price=10.0,
    market_cap=None, scores={"catalyst": 50.0},
)


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeAnthropicClient:
    """messages.create 를 흉내 · 호출 인자를 기록."""

    def __init__(self, *, content=None, stop_reason="end_turn", exc=None):
        self.calls: list[dict] = []
        outer = self

        class _Msg:
            pass

        msg = _Msg()
        msg.content = content if content is not None else [_Block("text", text=GOOD_JSON)]
        msg.stop_reason = stop_reason
        msg.stop_details = None

        class _Messages:
            async def create(self, **kw):
                outer.calls.append(kw)
                if exc:
                    raise exc
                return msg

        self.messages = _Messages()

    async def close(self):
        pass


class _FakeZai:
    """ZaiLLM 자리 · 진입 횟수와 호출 횟수를 기록."""

    def __init__(self, thesis: PickThesis | None = None, fail: bool = False):
        self.entered = 0
        self.calls = 0
        self.thesis = thesis or PickThesis("Z.ai 분석", [], [], "", 3)
        self.api_key = "zai_key"
        self.fail = fail
        self.last_call_failed = False

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *exc):
        pass

    async def generate_pick_thesis(self, **kw):
        self.calls += 1
        self.last_call_failed = self.fail
        if self.fail:
            return PickThesis("(LLM 호출 실패)", [], ["Z.ai 분석 불가: X"], "", 3)
        return self.thesis


def _fallback(claude_client: _FakeAnthropicClient | None, *, key: str = "test_key", zai_fail: bool = False):
    primary = ClaudeLLM(api_key=key)
    zai = _FakeZai(fail=zai_fail)
    fb = FallbackLLM(primary=primary, secondary=zai)  # type: ignore[arg-type]
    return fb, primary, zai


async def _run(fb: FallbackLLM, primary: ClaudeLLM, client) -> PickThesis:
    if client is not None and fb.primary_configured:
        primary._client = client  # 진입 대신 가짜 클라이언트를 꽂는다
    return await fb.generate_pick_thesis(**ARGS)


@pytest.mark.asyncio
async def test_success_uses_anthropic_only():
    client = _FakeAnthropicClient()
    fb, primary, zai = _fallback(client)
    t = await _run(fb, primary, client)
    assert t.thesis == "좋은 분석"
    assert fb.usage == {"anthropic": 1, "zai": 0, "zai_failed": 0}
    assert zai.entered == 0  # Z.ai 는 필요할 때만 진입
    assert fb.needs_alert() is False


@pytest.mark.asyncio
async def test_request_params_default_model_and_effort():
    client = _FakeAnthropicClient()
    fb, primary, _ = _fallback(client)
    await _run(fb, primary, client)
    kw = client.calls[0]
    assert kw["model"] == llm_mod.DEFAULT_ANTHROPIC_MODEL
    assert kw["output_config"] == {"effort": "low"}
    assert kw["max_tokens"] == 4000
    assert "temperature" not in kw
    assert "thinking" not in kw


def test_default_model_is_sonnet_5_5():
    # ANTHROPIC_MODEL 을 넣지 않으면 코드 기본값 (모듈을 다시 읽으면 다른 테스트의 클래스 비교가 깨져 소스로 확인)
    import inspect

    from backend.powderkeg import llm_classifier

    assert 'os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")' in inspect.getsource(llm_mod)
    assert 'os.environ.get("POWDERKEG_LLM_MODEL", "claude-sonnet-5-5")' in inspect.getsource(llm_classifier)


@pytest.mark.asyncio
async def test_no_key_goes_straight_to_zai():
    fb, primary, zai = _fallback(None, key="")
    t = await _run(fb, primary, None)
    assert t.thesis == "Z.ai 분석"
    assert fb.usage == {"anthropic": 0, "zai": 1, "zai_failed": 0}
    assert fb.failure_kinds == {"no_key": 1}
    assert fb.needs_alert() is True


@pytest.mark.asyncio
async def test_api_error_falls_back_to_zai():
    client = _FakeAnthropicClient(exc=RuntimeError("connection reset"))
    fb, primary, zai = _fallback(client)
    t = await _run(fb, primary, client)
    assert t.thesis == "Z.ai 분석"
    assert fb.failure_kinds == {"api": 1}
    assert zai.entered == 1


@pytest.mark.asyncio
async def test_auth_error_triggers_alert():
    class _AuthError(Exception):
        status_code = 401

    client = _FakeAnthropicClient(exc=_AuthError("invalid x-api-key"))
    fb, primary, _ = _fallback(client)
    await _run(fb, primary, client)
    assert fb.failure_kinds == {"auth": 1}
    assert fb.needs_alert() is True


@pytest.mark.asyncio
async def test_billing_error_triggers_alert():
    class _BadRequest(Exception):
        status_code = 400

    client = _FakeAnthropicClient(exc=_BadRequest("Your credit balance is too low"))
    fb, primary, _ = _fallback(client)
    await _run(fb, primary, client)
    assert fb.failure_kinds == {"billing": 1}
    assert fb.needs_alert() is True


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
@pytest.mark.asyncio
async def test_refusal_and_truncation_fall_back(stop_reason):
    client = _FakeAnthropicClient(stop_reason=stop_reason)
    fb, primary, zai = _fallback(client)
    t = await _run(fb, primary, client)
    assert t.thesis == "Z.ai 분석"
    assert fb.failure_kinds == {stop_reason: 1}


@pytest.mark.asyncio
async def test_parse_failure_falls_back():
    client = _FakeAnthropicClient(content=[_Block("text", text="not json")])
    fb, primary, zai = _fallback(client)
    t = await _run(fb, primary, client)
    assert t.thesis == "Z.ai 분석"
    assert fb.failure_kinds == {"parse": 1}


@pytest.mark.asyncio
async def test_thinking_block_first_is_skipped():
    client = _FakeAnthropicClient(content=[_Block("thinking", thinking=""), _Block("text", text=GOOD_JSON)])
    fb, primary, zai = _fallback(client)
    t = await _run(fb, primary, client)
    assert t.thesis == "좋은 분석"
    assert zai.calls == 0


@pytest.mark.asyncio
async def test_single_failure_among_successes_no_alert():
    """일부만 대체(종목 하나가 잘림 등)는 경고 없이 요약 로그만."""
    ok = _FakeAnthropicClient()
    bad = _FakeAnthropicClient(stop_reason="max_tokens")
    fb, primary, zai = _fallback(ok)
    await _run(fb, primary, ok)
    await _run(fb, primary, bad)
    assert fb.usage == {"anthropic": 1, "zai": 1, "zai_failed": 0}
    assert fb.needs_alert() is False
    assert "anthropic 1 · zai 1" in fb.summary()


@pytest.mark.asyncio
async def test_all_fallen_back_triggers_alert():
    bad = _FakeAnthropicClient(stop_reason="refusal")
    fb, primary, zai = _fallback(bad)
    await _run(fb, primary, bad)
    await _run(fb, primary, bad)
    assert fb.usage == {"anthropic": 0, "zai": 2, "zai_failed": 0}
    assert zai.entered == 1  # 한 번만 진입
    assert fb.needs_alert() is True


@pytest.mark.asyncio
async def test_claude_request_raises_llm_call_error_kind():
    client = _FakeAnthropicClient(stop_reason="refusal")
    primary = ClaudeLLM(api_key="k")
    primary._client = client
    with pytest.raises(LLMCallError) as ei:
        await primary._request_thesis("T", "prompt")
    assert ei.value.kind == "refusal"


def test_factory_by_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(get_llm_client(), FallbackLLM)
    monkeypatch.setenv("LLM_PROVIDER", "zai")
    assert isinstance(get_llm_client(), llm_mod.ZaiLLM)


@pytest.mark.asyncio
async def test_report_llm_usage_alert_once_per_day(monkeypatch):
    """잡 끝 요약 · 조건이면 하루 1회 warning · 발송 성공 때만 기록."""
    from backend.scheduler import cron
    from backend.services import notifier as notifier_mod

    sent: list[tuple[str, str]] = []

    async def _send_warning(self, title, body, **kw):
        sent.append((title, body))
        return True

    monkeypatch.setattr(notifier_mod.TelegramNotifier, "send_warning", _send_warning)
    monkeypatch.setattr(cron, "_llm_fallback_alerted", {})

    fb, primary, _ = _fallback(None, key="")
    await _run(fb, primary, None)
    await cron._report_llm_usage("Crazy Picks", fb)
    await cron._report_llm_usage("Moonshot Picks", fb)
    assert len(sent) == 1
    assert "Anthropic" in sent[0][0]

    # FallbackLLM 이 아니면 아무것도 안 함
    await cron._report_llm_usage("Crazy Picks", object())
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_both_fail_counts_and_alerts():
    """Anthropic·Z.ai 둘 다 실패하면 성공으로 세지 않고 경고."""
    ok = _FakeAnthropicClient()
    bad = _FakeAnthropicClient(exc=RuntimeError("down"))
    fb, primary, _ = _fallback(ok, zai_fail=True)
    await _run(fb, primary, ok)
    await _run(fb, primary, bad)
    assert fb.usage == {"anthropic": 1, "zai": 0, "zai_failed": 1}
    assert fb.needs_alert() is True
    assert "둘 다 실패 1" in fb.summary()


@pytest.mark.asyncio
async def test_cancelled_calls_still_alert():
    """wait_for 취소로 usage 가 비어도 시도가 있고 Anthropic 성공 0 이면 경고."""
    fb, _, _ = _fallback(None)
    fb.attempts = 3  # 세 번 시작했지만 모두 바깥에서 취소된 상황
    assert fb.needs_alert() is True


@pytest.mark.asyncio
async def test_auth_failure_disables_primary_for_rest():
    class _AuthError(Exception):
        status_code = 401

    client = _FakeAnthropicClient(exc=_AuthError("invalid x-api-key"))
    fb, primary, zai = _fallback(client)
    await _run(fb, primary, client)
    await _run(fb, primary, client)
    assert len(client.calls) == 1  # 두 번째 종목은 Anthropic 을 건너뜀
    assert zai.calls == 2


@pytest.mark.asyncio
async def test_empty_thesis_falls_back():
    client = _FakeAnthropicClient(content=[_Block("text", text='{"thesis": "", "manipulation_risk": 2}')])
    fb, primary, zai = _fallback(client)
    t = await _run(fb, primary, client)
    assert t.thesis == "Z.ai 분석"
    assert fb.failure_kinds == {"empty": 1}


def test_call_timeout_only_on_fallback():
    assert FallbackLLM.call_timeout == 150.0
    assert getattr(llm_mod.ZaiLLM(api_key="k"), "call_timeout", 120.0) == 120.0


def test_fallback_secondary_has_no_sdk_retry():
    fb = FallbackLLM(primary=ClaudeLLM(api_key="k"))
    assert fb.secondary.max_retries == 0
    assert llm_mod.ZaiLLM(api_key="k").max_retries is None  # LLM_PROVIDER=zai 동작 유지


def test_zai_mode_parse_keeps_old_behavior():
    """LLM_PROVIDER=zai 경로: JSON 이 dict 가 아니거나 형변환 실패면 예전처럼 예외 (호출 측 재시도)."""
    from backend.services.llm import _parse_thesis_json

    with pytest.raises(AttributeError):
        _parse_thesis_json("[1, 2]", "T")
    with pytest.raises(ValueError):
        _parse_thesis_json('{"thesis": "x", "manipulation_risk": "high"}', "T")
    assert "LLM 응답 형식 오류" in _parse_thesis_json("not json", "T").risks
