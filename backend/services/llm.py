"""LLM provider — Z.ai GLM (기본) + OpenAI gpt-5-mini + Anthropic Claude (모두 병행).

번갈아 사용 가능 (메모리: keep-alternatives-alongside). `LLM_PROVIDER` 환경변수로 전환:
  - LLM_PROVIDER=zai         (기본) — glm-4.5-flash 무료 / glm-4.6 paid
  - LLM_PROVIDER=openai      — gpt-5-mini
  - LLM_PROVIDER=anthropic   — claude-haiku-4-5

공통 인터페이스:
    async with get_llm_client() as llm:
        thesis = await llm.generate_pick_thesis(
            ticker="EHGO", scores={...}, news=["..."], risk_level="HIGH",
        )

비용 (월 ~10 picks × 30일 ≈ 3K 호출):
  - Z.ai glm-4.5-flash: 무료
  - Z.ai glm-4.6:       ~$0.3 (저렴)
  - OpenAI gpt-5-mini:  ~$0.5-1
  - Claude Haiku 4.5:   ~$5-15
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
DEFAULT_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


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


def _parse_thesis_json(raw: str, ticker: str) -> PickThesis:
    """LLM 응답 텍스트 → PickThesis. 마크다운 코드블록 제거 + 파싱 실패 graceful."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.replace("```json", "").replace("```", "").strip()

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
    ) -> None:
        self.api_key = api_key or os.environ.get("ZAI_API_KEY", "")
        self.model = model or DEFAULT_ZAI_MODEL
        self.base_url = base_url or DEFAULT_ZAI_BASE_URL
        if not self.api_key:
            logger.warning("[ZaiLLM] ZAI_API_KEY 미설정 — 호출 시 401")
        self._client = None

    async def __aenter__(self) -> "ZaiLLM":
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise RuntimeError("openai 미설치 (Z.ai 도 OpenAI SDK 사용). `pip install openai`") from e
        # timeout 명시 — OpenAI SDK default 600s 는 cron stuck 원인
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=45.0)
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


class ClaudeLLM:
    """Anthropic Claude Haiku 4.5 (대안 LLM provider)."""

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
        self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self

    async def __aexit__(self, *exc) -> None:
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
            raise RuntimeError("ClaudeLLM 컨텍스트 미진입 — `async with` 사용")

        prompt = _build_prompt(
            ticker, company_name, sector, current_price, market_cap,
            scores, catalysts_hint, news_headlines, risk_level,
        )

        try:
            message = await self._client.messages.create(
                model=self.model,
                max_tokens=2000,
                system="당신은 한국어로 응답하는 금융 분석가다. 반드시 유효한 JSON 만 출력한다.",
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.error(f"[ClaudeLLM] {ticker} call failed: {e}")
            return PickThesis(
                thesis="(LLM 호출 실패)",
                catalysts=[],
                risks=[f"Claude 분석 불가: {e.__class__.__name__}"],
                news_summary="",
                manipulation_risk=3,
            )

        raw = "".join(
            block.text for block in message.content if hasattr(block, "text")
        ).strip()
        return _parse_thesis_json(raw, ticker)


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
        return ClaudeLLM()  # type: ignore[return-value]
    logger.warning(f"[LLM] unknown provider {name!r}, falling back to zai")
    return ZaiLLM()  # type: ignore[return-value]
