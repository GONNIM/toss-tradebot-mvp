"""Moonshot Picks 모듈 — 모든 미국 주식 (페니스톡·마이크로캡 포함).

스케줄: 매일 16:50 KST (한국 시간) ← 미국 장 시작 10분 전 (서머타임 기준)
출력: Top 3 후보 → DB `moonshot_picks` 테이블
운영:
  - 100만원 카지노 자금
  - 수동 매수 (자동 매매 X)
  - 시드 100% 소실 OK
  - HIGH 위험 ≥ 60% (페니스톡 가능성 극대화)

특화 기능:
  - 위험 분류 (HIGH/MED/LOW)
  - manipulation_risk 강조 (paid promoter 신호)
  - 3 가격대 추천: 시장가 / -3% 지정가 / -7% 지정가
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from backend.discovery.crazy_picks import collect_factor_inputs
from backend.discovery.scoring import FactorScores, compute_factor_scores

logger = logging.getLogger(__name__)


@dataclass
class MoonshotPickResult:
    """Moonshot Picks 최종 결과."""

    ticker: str
    rank: int
    company_name: str
    sector: str
    current_price: float
    market_cap_usd: Optional[float]
    risk_level: str           # HIGH/MED/LOW
    total_score: float
    factor_scores: FactorScores
    thesis: str
    catalysts: list
    risks: list
    news_summary: str
    manipulation_risk: int    # 1~5

    # 3 가격대 추천 (Decision 43)
    buy_price_market: float           # 현재가 (시장가 매수)
    buy_price_limit_3pct: float       # 현재가 -3%
    buy_price_limit_7pct: float       # 현재가 -7%

    # 위험 경고 메시지
    risk_warning: str


def build_risk_warning(
    risk_level: str,
    manipulation_risk: int,
    market_cap_usd: Optional[float],
    current_price: float,
) -> str:
    """위험 경고 메시지 생성."""
    parts = []
    if risk_level == "HIGH":
        parts.append("⚠️ 페니스톡·마이크로캡 (시드 100% 소실 가능)")
    if manipulation_risk >= 4:
        parts.append("🚨 pump&dump 의심 신호 강함")
    elif manipulation_risk == 3:
        parts.append("주의: 시장 조작 신호 감지")
    if current_price < 1.0:
        parts.append(f"페니스톡 (현재 ${current_price:.4f})")
    if market_cap_usd and market_cap_usd < 50_000_000:
        parts.append(f"마이크로캡 (시총 ${market_cap_usd/1_000_000:.1f}M)")
    return " · ".join(parts) if parts else "일반 위험"


async def run_moonshot_picks(
    universe_tickers: list,  # list[TickerInfo]
    clients: dict,
    top_n: int = 3,
    high_risk_min_ratio: float = 0.6,  # HIGH 위험 60% 이상 보장
    skip_slow: bool = False,
) -> list[MoonshotPickResult]:
    """Moonshot Picks 메인 실행.

    Top N 선정 시 HIGH 위험 종목 비율 보장 (페니스톡 발견 우선).

    Args:
        skip_slow: True 시 SEC/FINRA skip — 빠른 데모·디버그 용.
    """
    logger.info(f"[Moonshot] start — universe: {len(universe_tickers)} skip_slow={skip_slow}")

    sem = asyncio.Semaphore(10)

    async def collect_one(info):
        async with sem:
            inputs = await collect_factor_inputs(info.ticker, clients, skip_slow=skip_slow)
            return info, inputs

    # 모든 moonshot 후보 (universe 필터 통과)
    targets = [info for info in universe_tickers if info.is_moonshot]
    results = await asyncio.gather(
        *(collect_one(info) for info in targets),
        return_exceptions=True,
    )

    # 스코어링
    scored: list[tuple] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        info, inputs = r
        inputs["has_thesis"] = False
        inputs["llm_manipulation_risk"] = 3
        scores = compute_factor_scores(info.ticker, inputs)
        scored.append((info, scores))

    scored.sort(key=lambda x: x[1].total(), reverse=True)

    # HIGH 위험 우선 채우기 (Moonshot 본질)
    high_quota = max(1, int(top_n * high_risk_min_ratio))
    high_picks = [s for s in scored if s[0].risk_level == "HIGH"][:high_quota]
    remaining_quota = top_n - len(high_picks)
    high_tickers = {s[0].ticker for s in high_picks}
    others = [s for s in scored if s[0].ticker not in high_tickers][:remaining_quota]

    selected = high_picks + others
    selected.sort(key=lambda x: x[1].total(), reverse=True)
    logger.info(f"[Moonshot] {len(scored)} scored → Top {len(selected)} (HIGH: {len(high_picks)})")

    # LLM thesis (필수 — Moonshot 은 thesis 가 핵심)
    final: list[MoonshotPickResult] = []
    if "llm" not in clients:
        logger.warning("[Moonshot] LLM client 미제공 — thesis 생략")
        return final

    llm = clients["llm"]
    async with llm:
        for rank, (info, scores) in enumerate(selected, start=1):
            scores_dict = {
                "catalyst": scores.catalyst,
                "gap_volume": scores.gap_volume,
                "volatility": scores.volatility,
                "insider": scores.insider,
                "social": scores.social,
                "technical": scores.technical,
                "squeeze": scores.squeeze,
                "low_52w": scores.low_52w,
            }
            try:
                thesis = await asyncio.wait_for(
                    llm.generate_pick_thesis(
                        ticker=info.ticker,
                        company_name=info.name,
                        sector=info.sector or "Unknown",
                        current_price=info.current_price or 0,
                        market_cap=(info.market_cap_usd / 1_000_000) if info.market_cap_usd else None,
                        scores=scores_dict,
                        catalysts_hint=[],
                        news_headlines=[],
                        risk_level=info.risk_level,
                    ),
                    timeout=60.0,
                )
            except Exception as e:
                logger.warning(f"[Moonshot] {info.ticker} LLM fail: {e}")
                from backend.services.llm import PickThesis
                thesis = PickThesis("", [], ["LLM 호출 실패"], "", 3)

            # 뉴스 점수 갱신
            from backend.discovery.scoring import score_news_llm
            scores.news_llm = score_news_llm(thesis.manipulation_risk, has_thesis=True)

            cur_price = info.current_price or 0
            final.append(MoonshotPickResult(
                ticker=info.ticker,
                rank=rank,
                company_name=info.name,
                sector=info.sector or "",
                current_price=cur_price,
                market_cap_usd=info.market_cap_usd,
                risk_level=info.risk_level,
                total_score=scores.total(),
                factor_scores=scores,
                thesis=thesis.thesis,
                catalysts=thesis.catalysts,
                risks=thesis.risks,
                news_summary=thesis.news_summary,
                manipulation_risk=thesis.manipulation_risk,
                buy_price_market=cur_price,
                buy_price_limit_3pct=round(cur_price * 0.97, 4),
                buy_price_limit_7pct=round(cur_price * 0.93, 4),
                risk_warning=build_risk_warning(
                    info.risk_level,
                    thesis.manipulation_risk,
                    info.market_cap_usd,
                    cur_price,
                ),
            ))

    logger.info(f"[Moonshot] complete — Top {len(final)} picks")
    return final
