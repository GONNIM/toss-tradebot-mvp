"""Anthropic Claude Haiku 4.5 — Discovery thesis 생성 (결정 16).

- 입력: 종목 정보 + 인자 점수 + 뉴스 요약
- 출력: thesis (3~5줄) + catalysts + risks + manipulation_risk (1~5)
- 비용: ~$5~15/월 (Top 10 × 30일)

사용:
    async with ClaudeLLM() as llm:
        thesis = await llm.generate_pick_thesis(
            ticker="EHGO",
            scores={...},
            news=["..."],
            risk_level="HIGH",
        )
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class PickThesis:
    """LLM 생성 종목 분석 결과 (Crazy + Moonshot 공통)."""

    thesis: str           # 3~5줄, 왜 오를 후보인가
    catalysts: list[str]  # 임박 이벤트 목록
    risks: list[str]      # 위험 요소
    news_summary: str     # 최근 뉴스 핵심
    manipulation_risk: int  # 1~5 (HIGH 종목 강조)


class ClaudeLLM:
    """Anthropic Claude Haiku 4.5 클라이언트 (결정 16)."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            logger.warning(
                "[LLM] ANTHROPIC_API_KEY 미설정 — 호출 시 401. "
                ".env 에 추가 (upbit-tradebot-mvp/.env 에 동일 키 보유 — 사용자 확인 2026-06-17)"
            )
        self._client = None  # anthropic.AsyncAnthropic, lazy

    def _ensure_client(self):
        """anthropic SDK lazy 초기화."""
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic 미설치. `pip install anthropic` 또는 `pip install -e .[dev]`"
            ) from e
        self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

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
        """종목 thesis 생성 (Crazy + Moonshot 공통).

        Returns:
            PickThesis (Pydantic-like dataclass)
        """
        client = self._ensure_client()

        # 입력 데이터 구성
        scores_text = "\n".join(f"  - {k}: {v:.1f}/100" for k, v in scores.items())
        catalysts_text = ", ".join(catalysts_hint) if catalysts_hint else "(없음)"
        news_text = "\n".join(f"  - {h}" for h in (news_headlines or [])[:5])
        mcap_text = f"${market_cap:,.0f}M" if market_cap else "(미상)"

        prompt = f"""다음 종목을 분석해 JSON 형식으로 응답해라.

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
{news_text or "  (데이터 없음)"}

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

        try:
            message = await client.messages.create(
                model=MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.error(f"[LLM] generate_pick_thesis failed for {ticker}: {e}")
            return PickThesis(
                thesis="(LLM 호출 실패)",
                catalysts=[],
                risks=["LLM 분석 불가"],
                news_summary="",
                manipulation_risk=3,
            )

        # 응답 파싱 (JSON 추출)
        raw = "".join(
            block.text for block in message.content if hasattr(block, "text")
        ).strip()

        # JSON 추출 (마크다운 코드 블록 제거)
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"[LLM] JSON parse failed for {ticker}: {e}. Raw: {raw[:200]}")
            return PickThesis(
                thesis=raw[:500] if raw else "(파싱 실패)",
                catalysts=[],
                risks=["LLM 응답 형식 오류"],
                news_summary="",
                manipulation_risk=3,
            )

        return PickThesis(
            thesis=data.get("thesis", "").strip(),
            catalysts=list(data.get("catalysts", [])),
            risks=list(data.get("risks", [])),
            news_summary=data.get("news_summary", "").strip(),
            manipulation_risk=int(data.get("manipulation_risk", 3)),
        )
