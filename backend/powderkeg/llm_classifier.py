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

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("POWDERKEG_LLM_MODEL", "claude-sonnet-5-5")
_CONFIDENCE_THRESHOLD = 0.8    # 지시서 §7-3 · < 0.8 이면 needs_human_review
# api 요청 처리 중에 돌므로 짧게 끊는다 · 최악 30 + 60 = 90초 (SDK 기본 600초·재시도 2회 대신)
_ANTHROPIC_TIMEOUT_SEC = 30.0
_ZAI_TIMEOUT_SEC = 60.0
_SYSTEM = "당신은 한국어로 응답하는 지배구조 분석가입니다. 반드시 JSON 만 출력하세요."


@dataclass
class LLMClassification:
    label: str                   # "company_related" / "personal_only" / "unclear"
    confidence: float            # 0.0 ~ 1.0
    rationale: str               # 근거 문장 (한국어)
    needs_human_review: bool     # confidence < 임계값
    used_llm: bool               # True = 실제 API 호출 · False = keyword fallback / no key


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def is_llm_configured() -> bool:
    """LLM_PROVIDER=anthropic 일 때만 LLM 판정 (Anthropic → Z.ai → 키워드 · 2026-10-23 결정).

    그 밖에는 키가 있어도 키워드 판정 — 설정 PR 전에는 A1 판정 규칙이 바뀌지 않게 묶는다.
    """
    if os.environ.get("LLM_PROVIDER", "").strip().lower() != "anthropic":
        return False
    return bool(_key("ANTHROPIC_API_KEY") or _key("ZAI_API_KEY"))


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


async def _classify_anthropic(prompt: str) -> Optional[dict]:
    """실패하면 None (Z.ai 로 넘어감)."""
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.AsyncAnthropic(
        api_key=_key("ANTHROPIC_API_KEY"), timeout=_ANTHROPIC_TIMEOUT_SEC, max_retries=0,
    )
    try:
        msg = await asyncio.wait_for(
            client.messages.create(
                model=_MODEL,
                max_tokens=1500,
                output_config={"effort": "low"},
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=_ANTHROPIC_TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[llm_classify] anthropic 실패 · %s · zai 로 대체", exc)
        return None
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    stop_reason = getattr(msg, "stop_reason", None)
    if stop_reason in ("refusal", "max_tokens"):
        details = getattr(msg, "stop_details", None)
        logger.warning(
            "[llm_classify] anthropic stop_reason=%s category=%s · zai 로 대체",
            stop_reason, getattr(details, "category", None) if details is not None else None,
        )
        return None
    # 블록 type 으로 읽는다 — thinking 블록이 먼저 올 수 있음
    text = "".join(
        b.text for b in (msg.content or []) if getattr(b, "type", "text") == "text" and hasattr(b, "text")
    )
    parsed = _parse_json_response(text)
    if not parsed:
        logger.warning("[llm_classify] anthropic JSON 파싱 실패 · %s", text[:100])
        return None
    logger.info("[llm_classify] provider=anthropic")
    return parsed


async def _classify_zai(prompt: str) -> Optional[dict]:
    """실패하면 None (키워드 판정으로 넘어감)."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    from backend.services.llm import DEFAULT_ZAI_BASE_URL, DEFAULT_ZAI_MODEL

    client = AsyncOpenAI(
        api_key=_key("ZAI_API_KEY"), base_url=DEFAULT_ZAI_BASE_URL,
        timeout=_ZAI_TIMEOUT_SEC, max_retries=0,
    )
    try:
        completion = await asyncio.wait_for(
            client.chat.completions.create(
                model=DEFAULT_ZAI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1500,
                temperature=0.3,
            ),
            timeout=_ZAI_TIMEOUT_SEC,
        )
        text = (completion.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[llm_classify] zai 실패 · %s · keyword fallback", exc)
        return None
    finally:
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass
    parsed = _parse_json_response(text)
    if not parsed:
        logger.warning("[llm_classify] zai JSON 파싱 실패 · %s", text[:100])
        return None
    logger.info("[llm_classify] provider=zai")
    return parsed


async def classify_owner_event(
    title: str,
    description: Optional[str] = None,
    threshold: float = _CONFIDENCE_THRESHOLD,
) -> LLMClassification:
    """A1 오너 사법 이벤트 · 회사자금 관련 여부 판별.

    순서: Anthropic → Z.ai → keyword fallback (confidence=0.5 · needs_human_review=True).
    """
    if not is_llm_configured():
        return _keyword_fallback(title, description)

    desc_block = f"본문 발췌: \"{description}\"" if description else ""
    prompt = _PROMPT_TEMPLATE.format(title=title, description_block=desc_block)

    parsed = None
    if _key("ANTHROPIC_API_KEY"):
        parsed = await _classify_anthropic(prompt)
    if parsed is None and _key("ZAI_API_KEY"):
        parsed = await _classify_zai(prompt)
    if parsed is None:
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
