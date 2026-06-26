"""Meme Score 백테스트 — 과거 폭등 사례에서 score 추적 (Phase 1g).

데이터 한계: 우리 운영 시작(2026-06-25) 이전 social 시그널(apewisdom)
시계열 데이터 없음. 일봉 시그널(volume z + RSI + 1D return)만 네이버
에서 5년 전까지 fetch 가능.

따라서 1g MVP 백테스트는 ③ volume + ④ oversold 2 요소 confluence
재구성. social 부재 시 가중치 재정규화 자동 적용 (volume 0.625 +
oversold 0.375 = 1.0).

합격 기준 (Q14 의 변형 — social 부재 보정):
  D-3 ~ D-1 사이 score ≥ 0.50 (WATCH 이상) 진입
  10중 6 이상 → 합격

03-backtest-cases.md 의 10 사례 (US 9 + 한국 1).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.discovery.data_sources.naver_quote import fetch_daily_us_range
from backend.discovery.meme_watch.confluence import compute_meme_score
from backend.discovery.meme_watch.oversold import (
    compute_return_1d,
    compute_rsi,
    compute_volume_ratio,
    compute_volume_z,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestCase:
    ticker: str       # 네이버 reuters_code (NYSE 는 suffix 없음)
    market: str       # "US" / "KRX"
    d_day: date
    note: str


@dataclass(frozen=True)
class DayPoint:
    d_offset: int     # D-day 기준 (-5, 0, +1 등)
    date: date
    score: float
    label: str
    emoji: str
    volume_z: Optional[float]
    volume_ratio: Optional[float]
    rsi: Optional[float]
    return_1d: Optional[float]


@dataclass(frozen=True)
class CaseResult:
    case: BacktestCase
    points: list[DayPoint]    # D-5 ~ D+5
    max_score: float
    max_score_offset: int     # D-? 에서 max 발생
    first_watch_offset: Optional[int]  # 첫 score ≥ 0.50 진입 D-offset
    first_hot_offset: Optional[int]    # 첫 score ≥ 0.75 진입 D-offset
    passed: bool              # D-3 ~ D-1 사이 ≥ 0.50 진입 여부


CASES: list[BacktestCase] = [
    # 운영 종목 (현존)
    BacktestCase("GME", "US", date(2021, 1, 27), "Reddit WSB GameStop 1차 squeeze"),
    BacktestCase("AMC", "US", date(2021, 6, 2), "AMC squeeze (GME 후속)"),
    BacktestCase("KOSS.O", "US", date(2021, 1, 27), "GME 동반 low float squeeze"),
    BacktestCase("ATER.O", "US", date(2021, 9, 23), "Short squeeze + WSB"),
    BacktestCase("WEN.O", "US", date(2026, 6, 24), "Reddit WSB Save Wendy's"),
    # 상장폐지 종목 — 네이버 데이터 없음: BBBY (2023 파산), SPRT (합병),
    # MULN (퇴출), APE (AMC 흡수)
]


async def run_case(case: BacktestCase) -> Optional[CaseResult]:
    """D-30 ~ D+5 일봉 fetch + 시계열 score 산출."""
    start = case.d_day - timedelta(days=40)
    end = case.d_day + timedelta(days=10)

    df = await fetch_daily_us_range(case.ticker, start, end)
    if df is None or df.empty:
        logger.warning(f"[backtest] {case.ticker} ({case.d_day}) no data")
        return None

    # D-5 ~ D+5 (D 포함)
    target_dates = []
    for offset in range(-5, 6):
        target_dates.append(case.d_day + timedelta(days=offset))

    points: list[DayPoint] = []
    for offset in range(-5, 6):
        target = case.d_day + timedelta(days=offset)
        target_ts = pd.Timestamp(target)
        # target 까지의 모든 데이터로 시그널 계산
        sub = df[df.index <= target_ts]
        if len(sub) < 21:  # 20D rolling 필요
            continue
        closes = sub["Close"]
        volumes = sub["Volume"]
        vol_z = compute_volume_z(volumes)
        vol_r = compute_volume_ratio(volumes)
        rsi = compute_rsi(closes)
        r1d = compute_return_1d(closes)

        # score 산출 (Phase 2 튜닝 — ratio 우선)
        score = compute_meme_score(
            ticker=case.ticker,
            volume_z_20d=vol_z,
            volume_ratio_20d=vol_r,
            rsi_14=rsi,
            return_1d_pct=r1d,
        )
        # 실제 그날 거래일이 있는지 확인 (주말/공휴일 skip)
        actual_dates = sub.index[sub.index <= target_ts]
        if not len(actual_dates):
            continue
        actual_date = actual_dates[-1].date()
        # actual_date 가 너무 옛날이면 skip (offset 안 맞음)
        date_diff_days = (target - actual_date).days
        if date_diff_days > 3:
            continue
        points.append(
            DayPoint(
                d_offset=offset,
                date=actual_date,
                score=score.score,
                label=score.label,
                emoji=score.emoji,
                volume_z=vol_z,
                volume_ratio=vol_r,
                rsi=rsi,
                return_1d=r1d,
            )
        )

    if not points:
        return None

    max_pt = max(points, key=lambda p: p.score)
    first_watch = next((p.d_offset for p in points if p.score >= 0.50), None)
    first_hot = next((p.d_offset for p in points if p.score >= 0.75), None)
    # 합격 — D-3 ~ D-1 사이 ≥ 0.50 진입
    pre_d = [p for p in points if -3 <= p.d_offset <= -1]
    passed = any(p.score >= 0.50 for p in pre_d)

    return CaseResult(
        case=case,
        points=points,
        max_score=max_pt.score,
        max_score_offset=max_pt.d_offset,
        first_watch_offset=first_watch,
        first_hot_offset=first_hot,
        passed=passed,
    )


async def run_backtest(cases: Optional[list[BacktestCase]] = None) -> list[CaseResult]:
    cases = cases or CASES
    results: list[CaseResult] = []
    for case in cases:
        try:
            r = await run_case(case)
            if r is not None:
                results.append(r)
            else:
                logger.warning(f"[backtest] {case.ticker} skip — no result")
        except Exception as e:
            logger.exception(f"[backtest] {case.ticker} error: {e}")
        await asyncio.sleep(0.5)  # rate limit
    return results


def report_markdown(results: list[CaseResult]) -> str:
    passed_count = sum(1 for r in results if r.passed)
    pass_rate = (passed_count / len(results) * 100) if results else 0

    lines = [
        f"# Meme Score 백테스트 보고 — {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## 합격률",
        f"- D-3 ~ D-1 사이 score ≥ 0.50 (WATCH 이상) 진입: "
        f"**{passed_count} / {len(results)}** ({pass_rate:.0f}%)",
        f"- 합격선: 6/10 이상 (Q14 의 social-부재 변형)",
        "",
        "## 데이터 한계",
        "- 우리 운영 시작(2026-06-25) 이전 social(apewisdom) 시계열 데이터 없음",
        "- 일봉 시그널 (volume z + RSI + 1D return) 만 5년 전까지 fetch 가능",
        "- 따라서 ③ volume + ④ oversold 2-요소 confluence 만 재구성",
        "- 가중치 재정규화: volume 0.625 / oversold 0.375 = 1.0 합 (가용 시그널만)",
        "",
        "## 사례별 상세",
        "",
    ]

    for r in results:
        c = r.case
        status = "✅ 합격" if r.passed else "❌ 미합격"
        lines += [
            f"### {c.ticker} ({c.d_day.strftime('%Y-%m-%d')}) {status}",
            f"- 사례: {c.note}",
            f"- D-day score: " + next(
                (f"{p.score:.3f} {p.emoji} {p.label}" for p in r.points if p.d_offset == 0),
                "(no D-day data)",
            ),
            f"- 최대 score: {r.max_score:.3f} (D{r.max_score_offset:+d})",
            f"- 첫 WATCH (≥0.50) 진입: "
            + (f"D{r.first_watch_offset:+d}" if r.first_watch_offset is not None else "—"),
            f"- 첫 HOT (≥0.75) 진입: "
            + (f"D{r.first_hot_offset:+d}" if r.first_hot_offset is not None else "—"),
            "",
            "| D | date | score | label | vol× | vol_z | RSI | 1D% |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for p in r.points:
            if p.rsi is not None and p.return_1d is not None:
                vol_r_str = f"{p.volume_ratio:.1f}×" if p.volume_ratio else "—"
                vol_z_str = f"{p.volume_z:+.1f}σ" if p.volume_z is not None else "—"
                lines.append(
                    f"| D{p.d_offset:+d} | {p.date} | {p.score:.3f} | "
                    f"{p.emoji} {p.label} | {vol_r_str} | {vol_z_str} | "
                    f"{p.rsi:.0f} | {p.return_1d:+.1f}% |"
                )
            else:
                lines.append(
                    f"| D{p.d_offset:+d} | {p.date} | — | — | — | — | — | — |"
                )
        lines.append("")

    lines += [
        "## 결론",
        "",
        f"- volume + oversold 단독으로 폭등 사례 {passed_count}/{len(results)} 사전 detect",
        "- social 시그널 추가 시 detect 정확도 ↑ 예상 (apewisdom 30일 누적 후 재검증)",
        "- false positive 검증은 본 보고서 범위 밖 — Phase 2 에서 6,000 random "
        "ticker × month 시뮬 후 추가",
        "",
        f"**보고서 생성**: {datetime.now().isoformat()}",
    ]
    return "\n".join(lines)


async def false_positive_sample(
    n_tickers: int = 100, period_days: int = 90
) -> dict:
    """Random universe sample → 임계 통과 일수 / 전체 = false positive rate.

    실제 폭등 사례 없는 random 종목 × 일자 조합에서 score ≥ 임계가 얼마나
    자주 발생하는지 측정. 5% 미만이면 합격 (Q14 변형).
    """
    import random

    from sqlalchemy import select

    from backend.discovery.data_sources.naver_quote import fetch_daily_us_batch
    from backend.services.db import get_session
    from backend.services.models import MemeUniverse

    async with get_session() as session:
        all_tickers = (
            await session.execute(
                select(MemeUniverse.ticker).where(
                    MemeUniverse.market == "US",
                    MemeUniverse.is_active.is_(True),
                )
            )
        ).scalars().all()

    sample = random.sample(list(all_tickers), min(n_tickers, len(all_tickers)))
    logger.info(f"[fp-sample] {len(sample)} random tickers fetching {period_days}D")
    daily = await fetch_daily_us_batch(sample, days_back=period_days, concurrency=10)
    logger.info(f"[fp-sample] fetched {len(daily)} / {len(sample)}")

    total_days = 0
    counts = {"watch": 0, "hot": 0, "blazing": 0}

    for ticker, df in daily.items():
        if df is None or len(df) < 21:
            continue
        for i in range(20, len(df)):
            sub = df.iloc[: i + 1]
            volumes = sub["Volume"]
            closes = sub["Close"]
            vr = compute_volume_ratio(volumes)
            vz = compute_volume_z(volumes)
            rsi = compute_rsi(closes)
            r1d = compute_return_1d(closes)
            if r1d is None:
                continue
            score = compute_meme_score(
                ticker=ticker,
                volume_z_20d=vz,
                volume_ratio_20d=vr,
                rsi_14=rsi,
                return_1d_pct=r1d,
            )
            total_days += 1
            if score.score >= 0.50:
                counts["watch"] += 1
            if score.score >= 0.75:
                counts["hot"] += 1
            if score.score >= 1.00:
                counts["blazing"] += 1

    rates = {
        k: (v / total_days if total_days > 0 else 0.0) for k, v in counts.items()
    }
    return {
        "n_tickers_sampled": len(sample),
        "n_tickers_with_data": len(daily),
        "total_score_days": total_days,
        "watch_count": counts["watch"],
        "watch_rate": rates["watch"],
        "hot_count": counts["hot"],
        "hot_rate": rates["hot"],
        "blazing_count": counts["blazing"],
        "blazing_rate": rates["blazing"],
    }


def fp_report_markdown(stats: dict) -> str:
    rate_pct = lambda r: f"{r * 100:.2f}%"  # noqa: E731
    pass_hot = stats["hot_rate"] < 0.05
    lines = [
        "## False Positive 시뮬 — Random Universe Sample",
        "",
        f"- Sample: {stats['n_tickers_sampled']} random US tickers "
        f"({stats['n_tickers_with_data']} fetched)",
        f"- 총 score days: {stats['total_score_days']:,}",
        "",
        "| 임계 | 진입 count | 비율 |",
        "|---|---|---|",
        f"| ⚠️ WATCH (≥0.50) | {stats['watch_count']:,} | {rate_pct(stats['watch_rate'])} |",
        f"| 🔥 HOT (≥0.75)   | {stats['hot_count']:,} | {rate_pct(stats['hot_rate'])} |",
        f"| 🔥🔥 BLAZING (≥1.00) | {stats['blazing_count']:,} | {rate_pct(stats['blazing_rate'])} |",
        "",
        f"**HOT false positive rate**: {rate_pct(stats['hot_rate'])} — "
        f"{'✅ 합격 (<5%)' if pass_hot else '❌ 미합격 (≥5%)'}",
    ]
    return "\n".join(lines)


async def main() -> None:
    """CLI 진입점."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    results = await run_backtest()
    backtest_report = report_markdown(results)

    # False positive 시뮬 (옵션 — 환경변수 BACKTEST_FP=1 시 활성)
    import os

    fp_report = ""
    if os.getenv("BACKTEST_FP") == "1":
        logger.info("[backtest] running false positive simulation...")
        fp_stats = await false_positive_sample(n_tickers=100, period_days=90)
        fp_report = fp_report_markdown(fp_stats)
        print(fp_report)

    full_report = backtest_report
    if fp_report:
        full_report += "\n\n---\n\n" + fp_report

    out_path = Path(__file__).resolve().parents[3] / (
        "docs/plans/meme-stock-discovery/03-backtest-report.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_report, encoding="utf-8")
    logger.info(f"[backtest] report saved → {out_path}")

    passed = sum(1 for r in results if r.passed)
    print(f"\n=== 합격률: {passed} / {len(results)} ===")
    for r in results:
        flag = "✅" if r.passed else "❌"
        print(
            f"  {flag} {r.case.ticker} ({r.case.d_day}) max={r.max_score:.3f} "
            f"@D{r.max_score_offset:+d} first_watch=D{r.first_watch_offset or 99:+d}"
        )


if __name__ == "__main__":
    asyncio.run(main())
