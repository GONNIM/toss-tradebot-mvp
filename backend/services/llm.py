"""LLM provider — Z.ai GLM (기본) + OpenAI gpt-5-mini + Anthropic Claude (모두 병행).

번갈아 사용 가능 (메모리: keep-alternatives-alongside). `LLM_PROVIDER` 환경변수로 전환:
  - LLM_PROVIDER=zai         (기본) — glm-4.5-flash 무료 / glm-4.6 paid
  - LLM_PROVIDER=openai      — gpt-5-mini
  - LLM_PROVIDER=anthropic   — claude-opus-5-5 1순위 · 키 없음/오류 시 Z.ai 로 대체 (FallbackLLM · 2026-10-23 결정)

공통 인터페이스:
    async with get_llm_client() as llm:
        thesis = await llm.generate_pick_thesis(
            ticker="EHGO", scores={...}, news=["..."], risk_level="HIGH",
        )

비용 (월 ~10 picks × 30일 ≈ 3K 호출):
  - Z.ai glm-4.5-flash: 무료
  - Z.ai glm-4.6:       ~$0.3 (저렴)
  - OpenAI gpt-5-mini:  ~$0.5-1
  - Claude Sonnet 5.5:  ~$5 (하루 13회 · 상한 ~$44)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


# 기본 모델 (환경변수로 override 가능)
DEFAULT_ZAI_MODEL = os.environ.get("ZAI_MODEL", "glm-4.5-flash")  # 무료 tier
DEFAULT_ZAI_BASE_URL = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4/")
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
DEFAULT_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")  # 정확도 우선 · 2026-10-25 사용자 결정
# Anthropic 은 짧게 끊고 남은 시간을 Z.ai 대체에 쓴다 (호출 측 wait_for 150초 안: 30 + Z.ai 90)
ANTHROPIC_TIMEOUT_SEC = 30.0


@dataclass(frozen=True)
class PickThesis:
    """LLM 생성 종목 분석 결과 (provider 공통)."""

    thesis: str
    catalysts: list[str]
    risks: list[str]
    news_summary: str
    manipulation_risk: int


class LLMClient(Protocol):
    """LLM provider 공통 인터페이스."""

    async def __aenter__(self) -> "LLMClient": ...
    async def __aexit__(self, *exc) -> None: ...
    async def generate_pick_thesis(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        current_price: float,
        market_cap: Optional[float],
        scores: dict[str, float],
        catalysts_hint: Optional[list[str]] = None,
        news_headlines: Optional[list[str]] = None,
        risk_level: str = "MED",
    ) -> PickThesis: ...


# ─────────────────────────────────────────────
# 공통 프롬프트
# ─────────────────────────────────────────────

def _build_prompt(
    ticker: str,
    company_name: str,
    sector: str,
    current_price: float,
    market_cap: Optional[float],
    scores: dict[str, float],
    catalysts_hint: Optional[list[str]],
    news_headlines: Optional[list[str]],
    risk_level: str,
) -> str:
    scores_text = "\n".join(f"  - {k}: {v:.1f}/100" for k, v in scores.items())
    catalysts_text = ", ".join(catalysts_hint) if catalysts_hint else "(없음)"
    news_text = "\n".join(f"  - {h}" for h in (news_headlines or [])[:5]) or "  (데이터 없음)"
    mcap_text = f"${market_cap:,.0f}M" if market_cap else "(미상)"

    return f"""다음 종목을 분석해 JSON 형식으로 응답해라.

종목: {ticker} ({company_name})
섹터: {sector}
현재가: ${current_price}
시가총액: {mcap_text}
위험 수준: {risk_level} (HIGH=페니스톡·마이크로캡, MED=소형주, LOW=중형주)

인자 점수 (0~100):
{scores_text}

카탈리스트 힌트:
  {catalysts_text}

최근 뉴스 (상위 5건):
{news_text}

다음 형식의 JSON 만 출력 (다른 설명 X):
{{
  "thesis": "왜 미친 상승 후보인지 3~5줄 한국어",
  "catalysts": ["임박 이벤트 1", "임박 이벤트 2"],
  "risks": ["위험 1", "위험 2"],
  "news_summary": "최근 뉴스 핵심 2~3줄 한국어",
  "manipulation_risk": 1~5 (1=낮음, 5=매우 의심 / paid promoter, pump&dump 신호)
}}

규칙:
- 한국어로 작성
- 카지노 자금 운영 본질 인지 (시드 100% 소실 OK)
- HIGH 위험 종목엔 manipulation_risk 3~5 권고
- 사실 기반 (추측 X, 데이터 없으면 "(데이터 없음)" 표기)
- catalysts·risks 각 1~5건"""


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.replace("```json", "").replace("```", "").strip()
    return text


def _try_parse_thesis_json(raw: str) -> Optional[PickThesis]:
    """LLM 응답 텍스트 → PickThesis. JSON 이 아니면 None (대체 판단용)."""
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return _thesis_from_dict(data)
    except (TypeError, ValueError):
        return None


def _parse_thesis_json(raw: str, ticker: str) -> PickThesis:
    """LLM 응답 텍스트 → PickThesis. 마크다운 코드블록 제거 + 파싱 실패 graceful.

    JSON 이지만 dict 가 아니거나 형변환이 안 되면 예전처럼 예외 (호출 측 재시도).
    """
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"[LLM] JSON parse failed for {ticker}: {e}. Raw: {text[:200]}")
        return PickThesis(
            thesis=text[:500] if text else "(파싱 실패)",
            catalysts=[],
            risks=["LLM 응답 형식 오류"],
            news_summary="",
            manipulation_risk=3,
        )
    return _thesis_from_dict(data)


def _thesis_from_dict(data: dict) -> PickThesis:
    return PickThesis(
        thesis=str(data.get("thesis", "")).strip(),
        catalysts=list(data.get("catalysts", [])),
        risks=list(data.get("risks", [])),
        news_summary=str(data.get("news_summary", "")).strip(),
        manipulation_risk=int(data.get("manipulation_risk", 3)),
    )


# ─────────────────────────────────────────────
# Z.ai provider (기본 — OpenAI SDK 호환, glm-4.5-flash 무료)
# ─────────────────────────────────────────────


class ZaiLLM:
    """Z.ai GLM provider — OpenAI SDK 호환 (base_url 만 변경).

    무료 tier: glm-4.5-flash. paid 권장: glm-4.6 / glm-5.1.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ZAI_API_KEY", "")
        self.model = model or DEFAULT_ZAI_MODEL
        self.base_url = base_url or DEFAULT_ZAI_BASE_URL
        # None = SDK 기본 (LLM_PROVIDER=zai 동작 유지) · FallbackLLM 은 0 (wait_for 150초 안에 들게)
        self.max_retries = max_retries
        # 마지막 호출이 API 오류였는지 — FallbackLLM 집계용 (문자열 비교 대신)
        self.last_call_failed = False
        if not self.api_key:
            logger.warning("[ZaiLLM] ZAI_API_KEY 미설정 — 호출 시 401")
        self._client = None

    async def __aenter__(self) -> "ZaiLLM":
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise RuntimeError("openai 미설치 (Z.ai 도 OpenAI SDK 사용). `pip install openai`") from e
        # timeout 명시 — OpenAI SDK default 600s 는 cron stuck 원인
        # glm-4.6 (paid) 실측 max 56.9s → 90s SDK timeout 마진
        kwargs = {} if self.max_retries is None else {"max_retries": self.max_retries}
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=90.0, **kwargs)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    async def generate_pick_thesis(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        current_price: float,
        market_cap: Optional[float],
        scores: dict[str, float],
        catalysts_hint: Optional[list[str]] = None,
        news_headlines: Optional[list[str]] = None,
        risk_level: str = "MED",
    ) -> PickThesis:
        if self._client is None:
            raise RuntimeError("ZaiLLM 컨텍스트 미진입 — `async with` 사용")

        prompt = _build_prompt(
            ticker, company_name, sector, current_price, market_cap,
            scores, catalysts_hint, news_headlines, risk_level,
        )

        self.last_call_failed = False
        try:
            # Z.ai 는 response_format json_object 가 모델별 차이 — 보수적으로 미사용,
            # 프롬프트의 "JSON 만 출력" 지시 + _parse_thesis_json 의 코드블록 제거 의존
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 한국어로 응답하는 금융 분석가다. 반드시 유효한 JSON 만 출력하고 다른 설명은 절대 추가하지 않는다.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4000,  # GLM-4.5-flash 안전 최대치 (~4K output limit)
                temperature=0.3,
            )
        except Exception as e:
            logger.error(f"[ZaiLLM] {ticker} call failed: {e}")
            self.last_call_failed = True
            return PickThesis(
                thesis="(LLM 호출 실패)",
                catalysts=[],
                risks=[f"Z.ai 분석 불가: {e.__class__.__name__}"],
                news_summary="",
                manipulation_risk=3,
            )

        raw = (completion.choices[0].message.content or "").strip()
        return _parse_thesis_json(raw, ticker)


# ─────────────────────────────────────────────
# OpenAI provider (대안)
# ─────────────────────────────────────────────


class OpenAILLM:
    """OpenAI GPT-5-mini (기본 LLM provider)."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or DEFAULT_OPENAI_MODEL
        if not self.api_key:
            logger.warning("[OpenAILLM] OPENAI_API_KEY 미설정 — 호출 시 401")
        self._client = None

    async def __aenter__(self) -> "OpenAILLM":
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise RuntimeError("openai 미설치. `pip install openai`") from e
        self._client = AsyncOpenAI(api_key=self.api_key, timeout=45.0)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    async def generate_pick_thesis(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        current_price: float,
        market_cap: Optional[float],
        scores: dict[str, float],
        catalysts_hint: Optional[list[str]] = None,
        news_headlines: Optional[list[str]] = None,
        risk_level: str = "MED",
    ) -> PickThesis:
        if self._client is None:
            raise RuntimeError("OpenAILLM 컨텍스트 미진입 — `async with` 사용")

        prompt = _build_prompt(
            ticker, company_name, sector, current_price, market_cap,
            scores, catalysts_hint, news_headlines, risk_level,
        )

        try:
            completion = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 한국어로 응답하는 금융 분석가다. 반드시 유효한 JSON 만 출력한다.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=2500,
            )
        except Exception as e:
            logger.error(f"[OpenAILLM] {ticker} call failed: {e}")
            return PickThesis(
                thesis="(LLM 호출 실패)",
                catalysts=[],
                risks=[f"OpenAI 분석 불가: {e.__class__.__name__}"],
                news_summary="",
                manipulation_risk=3,
            )

        raw = (completion.choices[0].message.content or "").strip()
        return _parse_thesis_json(raw, ticker)


# ─────────────────────────────────────────────
# Anthropic provider (대안, 번갈아 사용)
# ─────────────────────────────────────────────


class LLMCallError(Exception):
    """Anthropic 호출 실패 — FallbackLLM 이 Z.ai 로 넘길지 판단하는 신호.

    kind: no_key · auth (401/403) · billing (잔액) · api (그 밖의 API·연결·timeout)
          · refusal · max_tokens (잘림) · parse (JSON 아님)
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def _classify_anthropic_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if status == 402 or "credit balance" in text:
        return "billing"
    if status in (401, 403):
        return "auth"
    return "api"


class ClaudeLLM:
    """Anthropic Claude (기본 Opus 5.5) — LLM_PROVIDER=anthropic 일 때 FallbackLLM 의 1순위."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        if not self.api_key:
            logger.warning("[ClaudeLLM] ANTHROPIC_API_KEY 미설정 — 호출 시 401")
        self._client = None

    async def __aenter__(self) -> "ClaudeLLM":
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError("anthropic 미설치. `pip install anthropic`") from e
        # SDK 재시도 0회 — 실패하면 FallbackLLM 이 Z.ai 로 넘긴다 (SDK 기본 600초·2회는 cron 을 붙잡음)
        self._client = anthropic.AsyncAnthropic(
            api_key=self.api_key, timeout=ANTHROPIC_TIMEOUT_SEC, max_retries=0,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    async def _request_thesis(self, ticker: str, prompt: str) -> PickThesis:
        """실패하면 LLMCallError 를 올린다 (대체 판단은 호출 측)."""
        if self._client is None:
            raise RuntimeError("ClaudeLLM 컨텍스트 미진입 — `async with` 사용")
        try:
            # effort medium (Opus 5.5 기본값) — 실측 13.8초 · 출력 1.2천 토큰 (10/25) · thinking 은 끌 수 없어 보내지 않음
            message = await self._client.messages.create(
                model=self.model,
                max_tokens=4000,
                output_config={"effort": "medium"},
                system="당신은 한국어로 응답하는 금융 분석가다. 반드시 유효한 JSON 만 출력한다.",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise LLMCallError(_classify_anthropic_error(e), f"{e.__class__.__name__}: {e}") from e

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            logger.warning(f"[ClaudeLLM] {ticker} refusal · category={category}")
            raise LLMCallError("refusal", str(category))
        if stop_reason == "max_tokens":
            logger.warning(f"[ClaudeLLM] {ticker} max_tokens 도달 — 응답 잘림")
            raise LLMCallError("max_tokens")

        # 블록 type 으로 읽는다 — thinking 블록이 먼저 올 수 있음
        raw = "".join(
            block.text for block in message.content if getattr(block, "type", "text") == "text" and hasattr(block, "text")
        ).strip()
        parsed = _try_parse_thesis_json(raw)
        if parsed is None:
            logger.warning(f"[ClaudeLLM] {ticker} JSON parse failed. Raw: {raw[:200]}")
            raise LLMCallError("parse")
        if not parsed.thesis:
            raise LLMCallError("empty")
        return parsed

    async def generate_pick_thesis(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        current_price: float,
        market_cap: Optional[float],
        scores: dict[str, float],
        catalysts_hint: Optional[list[str]] = None,
        news_headlines: Optional[list[str]] = None,
        risk_level: str = "MED",
    ) -> PickThesis:
        prompt = _build_prompt(
            ticker, company_name, sector, current_price, market_cap,
            scores, catalysts_hint, news_headlines, risk_level,
        )
        try:
            return await self._request_thesis(ticker, prompt)
        except LLMCallError as e:
            if e.kind == "parse":
                return PickThesis(
                    thesis="(파싱 실패)",
                    catalysts=[],
                    risks=["LLM 응답 형식 오류"],
                    news_summary="",
                    manipulation_risk=3,
                )
            logger.error(f"[ClaudeLLM] {ticker} call failed: {e}")
            return PickThesis(
                thesis="(LLM 호출 실패)",
                catalysts=[],
                risks=[f"Claude 분석 불가: {e.kind}"],
                news_summary="",
                manipulation_risk=3,
            )


# ─────────────────────────────────────────────
# Fallback — Anthropic 1순위 · 키 없음/오류 시 Z.ai (2026-10-23 결정)
# ─────────────────────────────────────────────

# 이 종류의 실패는 사람이 손봐야 하므로 대체 경고를 보낸다 (그 밖은 전 종목이 대체됐을 때만)
ALERT_FAILURE_KINDS = frozenset({"no_key", "auth", "billing"})


class FallbackLLM:
    """ClaudeLLM 을 먼저 부르고 실패하면 같은 종목을 ZaiLLM 으로 다시 부른다.

    Z.ai 는 처음 필요할 때 진입 (Z.ai 동시 1건 제한 — cron.py `_enter_clients` 설명 참고).
    `usage` · `failure_kinds` 는 잡 끝 요약 로그와 대체 경고에 쓴다.
    키·인증·잔액 실패가 한 번 나면 그 잡의 나머지 종목은 바로 Z.ai 로 보낸다.
    """

    # 호출 측 wait_for — Anthropic 30초 + Z.ai 90초 (Z.ai 재시도 0회) 가 들어가게 (ZaiLLM 단독은 120초)
    call_timeout = 150.0

    def __init__(self, primary: Optional[ClaudeLLM] = None, secondary: Optional[ZaiLLM] = None) -> None:
        self.primary = primary or ClaudeLLM()
        self.secondary = secondary or ZaiLLM(max_retries=0)
        self._secondary_entered = False
        self._primary_disabled = False
        self.attempts = 0
        self.usage: dict[str, int] = {"anthropic": 0, "zai": 0, "zai_failed": 0}
        self.failure_kinds: dict[str, int] = {}

    @property
    def primary_configured(self) -> bool:
        return bool(self.primary.api_key)

    async def __aenter__(self) -> "FallbackLLM":
        if self.primary_configured:
            await self.primary.__aenter__()
        else:
            logger.warning("[FallbackLLM] ANTHROPIC_API_KEY 미설정 — 모든 호출을 Z.ai 로 보냄")
        return self

    async def __aexit__(self, *exc) -> None:
        await self.primary.__aexit__(*exc)
        if self._secondary_entered:
            await self.secondary.__aexit__(*exc)
            self._secondary_entered = False

    def _record_failure(self, kind: str) -> None:
        self.failure_kinds[kind] = self.failure_kinds.get(kind, 0) + 1

    async def generate_pick_thesis(
        self,
        ticker: str,
        company_name: str,
        sector: str,
        current_price: float,
        market_cap: Optional[float],
        scores: dict[str, float],
        catalysts_hint: Optional[list[str]] = None,
        news_headlines: Optional[list[str]] = None,
        risk_level: str = "MED",
    ) -> PickThesis:
        self.attempts += 1
        if not self.primary_configured:
            self._record_failure("no_key")
        elif not self._primary_disabled:
            prompt = _build_prompt(
                ticker, company_name, sector, current_price, market_cap,
                scores, catalysts_hint, news_headlines, risk_level,
            )
            try:
                thesis = await self.primary._request_thesis(ticker, prompt)
                self.usage["anthropic"] += 1
                logger.info(f"[FallbackLLM] {ticker} provider=anthropic")
                return thesis
            except LLMCallError as e:
                self._record_failure(e.kind)
                logger.warning(f"[FallbackLLM] {ticker} anthropic 실패 ({e}) → zai")
                if e.kind in ALERT_FAILURE_KINDS:
                    # 고칠 때까지 계속 실패하는 종류 — 나머지 종목은 Anthropic 을 건너뛴다
                    self._primary_disabled = True

        if not self._secondary_entered:
            await self.secondary.__aenter__()
            self._secondary_entered = True
        thesis = await self.secondary.generate_pick_thesis(
            ticker=ticker, company_name=company_name, sector=sector,
            current_price=current_price, market_cap=market_cap, scores=scores,
            catalysts_hint=catalysts_hint, news_headlines=news_headlines, risk_level=risk_level,
        )
        if getattr(self.secondary, "last_call_failed", False):
            self.usage["zai_failed"] += 1
            logger.warning(f"[FallbackLLM] {ticker} zai 도 실패")
        else:
            self.usage["zai"] += 1
            logger.info(f"[FallbackLLM] {ticker} provider=zai")
        return thesis

    def summary(self) -> str:
        fails = ", ".join(f"{k} {v}" for k, v in sorted(self.failure_kinds.items())) or "없음"
        u = self.usage
        return (
            f"시도 {self.attempts} · anthropic {u['anthropic']} · zai {u['zai']} · 둘 다 실패 {u['zai_failed']}"
            f" · anthropic 실패: {fails}"
        )

    def needs_alert(self) -> bool:
        """키·인증·잔액 문제 · 둘 다 실패한 종목 · 시도했는데 Anthropic 성공 0 이면 True.

        시도 수로 판단해 wait_for 취소로 집계가 빠진 경우도 잡는다.
        """
        if ALERT_FAILURE_KINDS & self.failure_kinds.keys():
            return True
        if self.usage["zai_failed"] > 0:
            return True
        return self.attempts > 0 and self.usage["anthropic"] == 0


# ─────────────────────────────────────────────
# Factory — LLM_PROVIDER 환경변수 기반 선택
# ─────────────────────────────────────────────


def get_llm_client(provider: Optional[str] = None) -> LLMClient:
    """LLM provider 선택. provider=None 이면 LLM_PROVIDER env 또는 'zai' 기본."""
    name = (provider or os.environ.get("LLM_PROVIDER") or "zai").lower()
    if name == "zai":
        return ZaiLLM()  # type: ignore[return-value]
    if name == "openai":
        return OpenAILLM()  # type: ignore[return-value]
    if name == "anthropic":
        return FallbackLLM()  # type: ignore[return-value]
    logger.warning(f"[LLM] unknown provider {name!r}, falling back to zai")
    return ZaiLLM()  # type: ignore[return-value]
