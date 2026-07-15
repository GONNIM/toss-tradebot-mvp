"""LLM classifier · A1 오너 사법 리스크 회사자금 관련성 판별 · Phase 7-3.

지시서 §7-3 분류 규칙:
    뉴스 기반 A1 분류는 키워드 매칭 + (가능 시) LLM 분류기(Anthropic API)로
    "회사 자금 관련 여부"를 판별. LLM 판별 결과는 confidence와 근거 문장을 함께 저장하고,
    confidence < 0.8이면 `needs_human_review` 상태로 알림만 발송.

목적:
    "삼성전자 이재용 회장 구속" 처럼 오너 개인 사법 리스크가 회사 자금과
      · 무관 (개인 폭행·개인 비리) → A1 신호 (매수 후보 · 오너에게 현금 필요)
      · 관련 (회사 자금 횡령·배임 혐의) → Type B (자금 소실 · 즉시 제외)
    를 구분.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("POWDERKEG_LLM_MODEL", "claude-haiku-4-5-20251001")
_CONFIDENCE_THRESHOLD = 0.8    # 지시서 §7-3 · < 0.8 이면 needs_human_review


@dataclass
class LLMClassification:
    label: str                   # "company_related" / "personal_only" / "unclear"
    confidence: float            # 0.0 ~ 1.0
    rationale: str               # 근거 문장 (한국어)
    needs_human_review: bool     # confidence < 임계값
    used_llm: bool               # True = 실제 API 호출 · False = keyword fallback / no key


def is_llm_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


_PROMPT_TEMPLATE = """당신은 한국 기업 지배구조 분석가입니다.
아래 공시·뉴스 제목을 읽고, 사건이 **회사 자금** 과 관련이 있는지 판별하세요.

제목: "{title}"
{description_block}

판별 기준:
- company_related: 회사 자금 횡령·배임·사기·회계부정 등 · 회사 재무에 직접 손실.
  예: "삼성전자 회사 자금 횡령 혐의", "SK 배임 혐의 기소"
- personal_only: 오너 개인의 사법·건강·상속 등 · 회사 자금과 무관.
  예: "회장 개인 폭행 혐의", "회장 별세", "개인 소송"
- unclear: 문맥만으로 판단 어려움.

반드시 다음 JSON 형식으로만 응답하세요:
{{"label": "company_related" | "personal_only" | "unclear",
  "confidence": 0.0~1.0 float,
  "rationale": "한 문장 근거"}}
"""


_KEYWORDS_COMPANY = ("회사자금", "회사 자금", "법인자금", "법인 자금", "회계부정", "재무 사기")
_KEYWORDS_PERSONAL = ("개인", "폭행", "음주", "가족", "사택", "별세", "사망", "타계", "상속")


def _keyword_fallback(title: str, description: Optional[str]) -> LLMClassification:
    """LLM 미사용 시 · 키워드 근사 판정."""
    text = (title or "") + " " + (description or "")
    if any(kw in text for kw in _KEYWORDS_COMPANY):
        return LLMClassification(
            label="company_related", confidence=0.5,
            rationale=f"keyword hit: {[k for k in _KEYWORDS_COMPANY if k in text][:1]}",
            needs_human_review=True, used_llm=False,
        )
    if any(kw in text for kw in _KEYWORDS_PERSONAL):
        return LLMClassification(
            label="personal_only", confidence=0.5,
            rationale=f"keyword hit: {[k for k in _KEYWORDS_PERSONAL if k in text][:1]}",
            needs_human_review=True, used_llm=False,
        )
    return LLMClassification(
        label="unclear", confidence=0.0,
        rationale="키워드 미매치 · LLM 필요",
        needs_human_review=True, used_llm=False,
    )


def _parse_json_response(text: str) -> Optional[dict]:
    """LLM 응답에서 JSON 추출."""
    # ```json ... ``` 블록 대응
    match = re.search(r"\{[^{}]*?\"label\"[^{}]*?\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


async def classify_owner_event(
    title: str,
    description: Optional[str] = None,
    threshold: float = _CONFIDENCE_THRESHOLD,
) -> LLMClassification:
    """A1 오너 사법 이벤트 · 회사자금 관련 여부 판별.

    LLM 미설정 시 keyword fallback · confidence=0.5 · needs_human_review=True.
    """
    if not is_llm_configured():
        return _keyword_fallback(title, description)

    try:
        import anthropic
    except ImportError:
        return _keyword_fallback(title, description)

    api_key = os.environ["ANTHROPIC_API_KEY"]
    client = anthropic.AsyncAnthropic(api_key=api_key)
    desc_block = f"본문 발췌: \"{description}\"" if description else ""
    prompt = _PROMPT_TEMPLATE.format(title=title, description_block=desc_block)

    try:
        msg = await client.messages.create(
            model=_MODEL,
            max_tokens=400,
            system="당신은 한국어로 응답하는 지배구조 분석가입니다. 반드시 JSON 만 출력하세요.",
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[llm_classify] API 실패 · %s · keyword fallback", exc)
        return _keyword_fallback(title, description)

    parsed = _parse_json_response(text)
    if not parsed:
        logger.warning("[llm_classify] JSON 파싱 실패 · %s", text[:100])
        return _keyword_fallback(title, description)

    label = parsed.get("label", "unclear")
    if label not in ("company_related", "personal_only", "unclear"):
        label = "unclear"
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    rationale = str(parsed.get("rationale", ""))[:200]

    return LLMClassification(
        label=label,
        confidence=confidence,
        rationale=rationale,
        needs_human_review=confidence < threshold,
        used_llm=True,
    )
