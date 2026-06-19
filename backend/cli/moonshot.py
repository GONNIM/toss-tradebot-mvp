"""moonshot CLI — click + rich.

설치 후 사용:
    pip install -e ./backend
    moonshot top                 # 오늘 Top 3
    moonshot detail EHGO         # 단일 종목 상세
    moonshot history --days 7    # 7일 히스토리
    moonshot perf                # 성과 추적
    moonshot live                # 실시간 모드 (cron 즉시 실행)
    moonshot positions           # 보유 종목 (Phase K 후)
    moonshot crazy               # Crazy Picks Top 10
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DB 헬퍼
# ─────────────────────────────────────────────


async def _fetch_recent_moonshot_picks(limit: int = 3):
    """최근 moonshot picks 조회."""
    from sqlalchemy import desc, select
    from backend.services.db import get_session
    from backend.services.models import MoonshotPick

    async with get_session() as session:
        stmt = select(MoonshotPick).order_by(desc(MoonshotPick.created_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


async def _fetch_recent_crazy_picks(limit: int = 10):
    """최근 crazy picks 조회."""
    from sqlalchemy import desc, select
    from backend.services.db import get_session
    from backend.services.models import CrazyPick

    async with get_session() as session:
        stmt = select(CrazyPick).order_by(desc(CrazyPick.created_at)).limit(limit)
        result = await session.execute(stmt)
        return result.scalars().all()


# ─────────────────────────────────────────────
# 렌더링 헬퍼
# ─────────────────────────────────────────────


def _risk_badge(level: str) -> str:
    """위험 레벨 컬러 배지."""
    return {
        "HIGH": "[bold red]HIGH[/]",
        "MED":  "[yellow]MED[/]",
        "LOW":  "[green]LOW[/]",
    }.get(level, level)


def _manipulation_badge(score: int) -> str:
    """조작 위험 1~5 배지."""
    if score >= 4:
        return f"[bold red]🚨 {score}/5[/]"
    if score == 3:
        return f"[yellow]⚠️  {score}/5[/]"
    return f"[green]{score}/5[/]"


def render_moonshot_pick(pick) -> Panel:
    """단일 Moonshot Pick → rich Panel."""
    body = Text()
    body.append(f"종목: ", style="dim")
    body.append(f"{pick.ticker} ", style="bold cyan")
    body.append(f"({pick.company_name or '-'})\n", style="white")
    body.append(f"섹터: {pick.sector or '-'}\n", style="dim")
    body.append(f"현재가: ${pick.current_price:.4f}  |  ", style="white")
    if pick.market_cap_usd:
        body.append(f"시총: ${pick.market_cap_usd/1_000_000:.1f}M\n", style="white")
    else:
        body.append(f"시총: 미상\n", style="dim")
    body.append("\n")
    body.append(f"위험: ", style="dim")
    body.append(Text.from_markup(_risk_badge(pick.risk_level)))
    body.append("  ·  조작 위험: ", style="dim")
    body.append(Text.from_markup(_manipulation_badge(pick.manipulation_risk)))
    body.append(f"  ·  총점: {pick.total_score:.1f}/100\n", style="white")
    body.append("\n")
    body.append("📊 Thesis:\n", style="bold")
    body.append(f"{pick.thesis or '(thesis 없음)'}\n\n", style="white")

    if pick.catalysts:
        body.append("🎯 카탈리스트:\n", style="bold")
        for c in pick.catalysts:
            body.append(f"  • {c}\n", style="green")
        body.append("\n")

    if pick.risks:
        body.append("⚠️  위험:\n", style="bold")
        for r in pick.risks:
            body.append(f"  • {r}\n", style="red")
        body.append("\n")

    body.append("💰 매수 가격대 (Decision 43):\n", style="bold")
    body.append(f"  • 시장가:    ${pick.buy_price_market:.4f}\n", style="white")
    body.append(f"  • -3% 지정: ${pick.buy_price_limit_3pct:.4f}\n", style="cyan")
    body.append(f"  • -7% 지정: ${pick.buy_price_limit_7pct:.4f}\n", style="cyan")
    if pick.risk_warning:
        body.append(f"\n{pick.risk_warning}\n", style="bold red")

    return Panel(
        body,
        title=f"[bold]#{pick.rank} {pick.ticker}[/]",
        subtitle=f"{datetime.now().strftime('%Y-%m-%d %H:%M KST')}",
        border_style="cyan" if pick.risk_level == "LOW" else ("yellow" if pick.risk_level == "MED" else "red"),
    )


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """🚀 Moonshot Picks CLI — Toss Tradebot MVP

    카지노 자금 100만원 Moonshot 운영 도구.
    매일 16:50 KST 한국시간 (미국 장 시작 10분 전) cron 실행.
    """
    if ctx.invoked_subcommand is None:
        # 기본: 오늘 Top 3 표시
        ctx.invoke(top)


@cli.command()
@click.option("--limit", default=3, help="표시할 Pick 개수 (기본 3)")
def top(limit):
    """오늘 Moonshot Top N 출력 (기본 3)."""
    picks = asyncio.run(_fetch_recent_moonshot_picks(limit=limit))
    if not picks:
        console.print("[yellow]저장된 Moonshot Pick 없음. `moonshot live` 로 즉시 실행 가능.[/]")
        return

    console.print(f"\n[bold cyan]🚀 Moonshot Picks — Top {len(picks)}[/]\n")
    for pick in picks:
        console.print(render_moonshot_pick(pick))
        console.print()


@cli.command()
@click.argument("ticker")
def detail(ticker):
    """단일 종목 상세 (가장 최근 Pick)."""
    async def _run():
        from sqlalchemy import desc, select
        from backend.services.db import get_session
        from backend.services.models import MoonshotPick

        async with get_session() as session:
            stmt = (
                select(MoonshotPick)
                .where(MoonshotPick.ticker == ticker.upper())
                .order_by(desc(MoonshotPick.created_at))
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    pick = asyncio.run(_run())
    if not pick:
        console.print(f"[red]{ticker} Pick 이력 없음.[/]")
        return
    console.print(render_moonshot_pick(pick))


@cli.command()
@click.option("--days", default=7, help="조회 일수")
def history(days):
    """최근 N일 Moonshot 픽 히스토리 (테이블)."""
    async def _run():
        from sqlalchemy import desc, select
        from backend.services.db import get_session
        from backend.services.models import MoonshotPick

        cutoff = datetime.now() - timedelta(days=days)
        async with get_session() as session:
            stmt = (
                select(MoonshotPick)
                .where(MoonshotPick.created_at >= cutoff)
                .order_by(desc(MoonshotPick.created_at))
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    picks = asyncio.run(_run())
    if not picks:
        console.print(f"[yellow]최근 {days}일 Pick 없음.[/]")
        return

    table = Table(title=f"Moonshot History — 최근 {days}일")
    table.add_column("날짜", style="cyan")
    table.add_column("순위", justify="right")
    table.add_column("티커", style="bold")
    table.add_column("가격", justify="right")
    table.add_column("위험", justify="center")
    table.add_column("점수", justify="right")
    table.add_column("조작", justify="center")

    for p in picks:
        table.add_row(
            p.created_at.strftime("%m-%d %H:%M") if p.created_at else "-",
            f"#{p.rank}",
            p.ticker,
            f"${p.current_price:.2f}",
            _risk_badge(p.risk_level),
            f"{p.total_score:.1f}",
            _manipulation_badge(p.manipulation_risk),
        )
    console.print(table)


@cli.command()
def perf():
    """Pick 성과 추적 (가격 변화 — 추후 Phase G API).

    현재는 placeholder. Phase D 백테스트 통합 예정.
    """
    console.print("[yellow]⚠️  perf 명령은 Phase D 백테스트 통합 후 활성화됩니다.[/]")
    console.print("[dim]임시: `python -m backend.discovery.backtest` 직접 호출 가능.[/]")


@cli.command()
def live():
    """즉시 Moonshot 실행 (cron 우회 — 디버그·테스트용)."""
    console.print("[bold cyan]🚀 Moonshot Live 실행 시작...[/]")
    console.print("[yellow]⚠️  필요 자격증명:[/]")
    console.print("  - ANTHROPIC_API_KEY (LLM thesis)")
    console.print("  - FINNHUB_API_KEY (어닝 캘린더)")
    console.print("  - REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET (소셜)")
    console.print("[dim].env 확인 후 진행. 데모 모드는 Phase D 통합 후 활성화.[/]")
    console.print()
    console.print("[red]현재 placeholder — 실 데이터 소스 통합은 Phase D 후속 PR.[/]")


@cli.command()
def positions():
    """현재 보유 종목 — Phase K (Toss API) 활성 후 가능."""
    console.print("[yellow]⚠️  Phase K (Toss API 자동매매) 활성 후 사용 가능.[/]")
    console.print("[dim]현재는 정보 전용 (Crazy/Moonshot) 만 지원.[/]")


@cli.command()
@click.option("--limit", default=10, help="표시할 Crazy Pick 개수 (기본 10)")
def crazy(limit):
    """Crazy Picks Top N (시총 ≥ $1B 안전 universe)."""
    picks = asyncio.run(_fetch_recent_crazy_picks(limit=limit))
    if not picks:
        console.print("[yellow]저장된 Crazy Pick 없음.[/]")
        return

    table = Table(title=f"🎯 Crazy Picks — Top {len(picks)}")
    table.add_column("순위", justify="right")
    table.add_column("티커", style="bold")
    table.add_column("회사", style="cyan")
    table.add_column("섹터", style="dim")
    table.add_column("시총($B)", justify="right")
    table.add_column("점수", justify="right")
    table.add_column("Thesis", style="white", max_width=50)

    for p in picks:
        table.add_row(
            f"#{p.rank}",
            p.ticker,
            (p.company_name or "")[:25],
            (p.sector or "")[:15],
            f"{(p.market_cap_usd or 0)/1_000_000_000:.1f}",
            f"{p.total_score:.1f}",
            (p.thesis or "")[:80],
        )
    console.print(table)


if __name__ == "__main__":
    cli()
