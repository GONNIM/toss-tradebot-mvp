"""Telegram 알림 서비스 — upbit-tradebot-mvp 패턴 차용.

핵심 기능 (upbit 검증):
- dedupe: 동일 메시지 60초 내 재전송 차단 (메모리 dict)
- LEVEL_CRITICAL: 빨간 아이콘 + 즉시 전송
- HTML 포맷
- 봇 토큰·chat_id env 로부터 로드

사용:
    notifier = TelegramNotifier()
    await notifier.send_critical("🚨 거래 실패", "EHGO 매수 거부됨")
    await notifier.send_info("ℹ️ 일일 요약", "...")
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class Level(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


LEVEL_ICONS = {
    Level.CRITICAL: "🚨",
    Level.WARNING: "⚠️",
    Level.INFO: "ℹ️",
}


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        return cls(
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )


class TelegramNotifier:
    """Telegram 알림 클라이언트 (HTML 포맷, dedupe, 비동기)."""

    DEDUPE_TTL = 60  # 60초

    def __init__(self, config: Optional[TelegramConfig] = None) -> None:
        self.config = config or TelegramConfig.from_env()
        if not self.config.bot_token or not self.config.chat_id:
            logger.warning(
                "[Notifier] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정. send 시 무시됨."
            )
        # dedupe 메모리: {hash: timestamp}
        self._sent: dict[str, float] = {}

    def _dedupe_check(self, key: str) -> bool:
        """동일 메시지 60초 내 재전송 차단."""
        now = time.time()
        # 만료된 키 청소
        self._sent = {k: v for k, v in self._sent.items() if now - v < self.DEDUPE_TTL}
        if key in self._sent:
            return False
        self._sent[key] = now
        return True

    @staticmethod
    def _hash(title: str, body: str) -> str:
        return hashlib.md5(f"{title}|{body[:200]}".encode()).hexdigest()

    async def send(
        self,
        level: Level,
        title: str,
        body: str,
        force: bool = False,
    ) -> bool:
        """알림 전송. dedupe 통과 시 True, skip 시 False.

        TELEGRAM_PROFILE (SCOUT/SNIPER/WATCH) 필터 적용:
        - SCOUT: 모두 발송
        - SNIPER: SUPER_SIGNAL · URGENT/CRITICAL · execution/kill_switch 만
        - WATCH: 즉시 발송 스킵, 큐잉 후 30분 배치 발송
        """
        if not self.config.bot_token or not self.config.chat_id:
            logger.debug(f"[Notifier] credentials 없음 — skip: {title}")
            return False

        # 프로파일 필터 (force=True 시 우회 · 예: Kill Switch · WATCH 배치 자체)
        if not force:
            try:
                from .notifier_profile import (
                    NotifyContext,
                    current_profile,
                    get_watch_queue,
                    should_send_by_profile,
                )
                source = self._infer_source(title)
                tags: tuple[str, ...] = ()
                if "SUPER" in title.upper() or "🌟" in title:
                    tags = ("SUPER_SIGNAL",)
                level_str = {Level.CRITICAL: "CRITICAL", Level.WARNING: "WARNING", Level.INFO: "INFO"}[level]
                ctx = NotifyContext(source=source, level=level_str, tags=tags)
                if not should_send_by_profile(ctx):
                    if current_profile() == "WATCH":
                        get_watch_queue().enqueue(ctx, title, body)
                        logger.debug(f"[Notifier] WATCH 큐잉: {title}")
                    else:
                        logger.debug(f"[Notifier] 프로파일 필터 skip: {title}")
                    return False
            except ImportError:
                pass  # profile 모듈 없으면 기본 동작

        key = self._hash(title, body)
        if not force and not self._dedupe_check(key):
            logger.debug(f"[Notifier] dedupe skip: {title}")
            return False

        icon = LEVEL_ICONS[level]
        text = f"<b>{icon} {title}</b>\n\n{body}"

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            logger.info(f"[Notifier] sent [{level.value}] {title}")
            return True
        except Exception as e:
            logger.error(f"[Notifier] send failed: {e}")
            return False

    async def send_critical(self, title: str, body: str) -> bool:
        return await self.send(Level.CRITICAL, title, body, force=True)

    async def send_warning(self, title: str, body: str) -> bool:
        return await self.send(Level.WARNING, title, body)

    async def send_info(self, title: str, body: str) -> bool:
        return await self.send(Level.INFO, title, body)

    @staticmethod
    def _infer_source(title: str) -> str:
        """title 프리픽스 → 소스 추정."""
        t = title.upper()
        if "SUPER" in t or "🌟" in title:
            return "super_signal"
        if "KILL SWITCH" in t or "🚨" in title and "URGENT" in t:
            return "kill_switch"
        if "VIP-" in t or "VIP " in t:
            return "vip"
        if "ACTIVIST" in t or "WOLF PACK" in t:
            return "activist"
        if "ERUPTING" in t or "BLAZING" in t or "MEME" in t or "🌋" in title or "🔥🔥" in title:
            return "meme_stock"
        if "EXECUTION" in t or "ORDER" in t:
            return "execution"
        return "unknown"


# ─────────────────────────────────────────────
# Moonshot/Crazy Picks 알림 포맷
# ─────────────────────────────────────────────


def format_moonshot_alert(picks: list) -> tuple[str, str]:
    """Moonshot Top N → Telegram 메시지 (title, body)."""
    title = f"🚀 Moonshot Picks — Top {len(picks)}"
    lines = []
    for p in picks:
        risk_icon = {"HIGH": "🔴", "MED": "🟡", "LOW": "🟢"}.get(p.risk_level, "⚪")
        lines.append(
            f"\n<b>#{p.rank} {p.ticker}</b> {risk_icon} ${p.current_price:.4f}\n"
            f"점수: {p.total_score:.1f}/100  ·  조작위험: {p.manipulation_risk}/5\n"
            f"💡 {p.thesis[:200]}{'...' if len(p.thesis) > 200 else ''}\n"
            f"💰 매수가: ${p.buy_price_market:.4f} / -3%: ${p.buy_price_limit_3pct:.4f} / -7%: ${p.buy_price_limit_7pct:.4f}\n"
        )
        if p.risk_warning:
            lines.append(f"⚠️ {p.risk_warning}\n")
    return title, "".join(lines)


def format_crazy_alert(picks: list) -> tuple[str, str]:
    """Crazy Top 10 → Telegram 메시지."""
    title = f"🎯 Crazy Picks — Top {len(picks)}"
    lines = []
    for p in picks[:10]:
        lines.append(
            f"\n<b>#{p.rank} {p.ticker}</b> ${p.current_price:.2f} "
            f"({(p.market_cap_usd or 0)/1_000_000_000:.1f}B)\n"
            f"점수: {p.total_score:.1f}/100\n"
            f"💡 {p.thesis[:150]}{'...' if len(p.thesis) > 150 else ''}\n"
        )
    return title, "".join(lines)


# ─────────────────────────────────────────────
# Sector Leaders Top — 매력도 임계 알림 (KRX)
# ─────────────────────────────────────────────


def format_sector_leaders_alert(
    items: list,
    bucket_label: str,
    expanded: bool = False,
) -> tuple[str, str]:
    """Sector Leaders 매력도 임계 통과 종목 → Telegram (title, body).

    Args:
        items: list[Top10Item] — 발송 대상 (이미 상위 N 컷·rank 재계산된 상태).
        bucket_label: "0.6" / "0.5" / "empty".
        expanded: 0.6 이상이 5개 이하라 0.5 이상까지 확장된 경우 True.
    """
    if not items or bucket_label == "empty":
        title = "📊 Sector Leaders — 오늘 매수 후보 없음"
        body = (
            "매력도 0.5 이상 종목이 없습니다.\n"
            "<i>모든 시그널이 약하거나 음의 영역에 있는 상황입니다.</i>"
        )
        return title, body

    title = f"📊 Sector Leaders Top {len(items)} — 매력도 {bucket_label}+"

    lines = []
    if expanded:
        lines.append(
            "<i>※ 0.6 이상이 5개 이하라 0.5 이상까지 확장한 결과입니다.</i>\n"
        )

    for it in items:
        price_tag = "" if it.price_source == "live" else " <i>(전일종가)</i>"
        lines.append(
            f"\n<b>#{it.rank} {it.name} ({it.ticker})</b>"
            f"  매력도 <b>{it.attractiveness:.3f}</b>\n"
            f"품목: {it.item}\n"
            f"현재가: {it.current_price:,.0f}원{price_tag}\n"
            f"진입가: {it.entry_price:,.0f}원  ({it.entry_status})\n"
            f"예측수익가: {it.point_price:,.0f}원  (+{it.point_pct:.1f}%)\n"
        )

    return title, "".join(lines)
