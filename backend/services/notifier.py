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
import html
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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


def starts_with_icon(title: str) -> bool:
    """제목 첫 글자가 그림 기호(유니코드 So)인지."""
    import unicodedata

    return bool(title) and unicodedata.category(title[0]) == "So"


def strip_icon(title: str) -> str:
    """앞쪽 아이콘(이모지 변형 선택자 포함)과 공백을 뗀 제목 — 하루 요약 줄용."""
    import unicodedata

    i = 0
    while i < len(title) and (unicodedata.category(title[i]) in ("So", "Mn") or title[i] == "‍"):
        i += 1
    return title[i:].lstrip() if i else title


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


# 알림 종류 → TELEGRAM_PROFILE 출처 (제목이 바뀌어도 프로필 필터가 같게 동작)
_CATEGORY_SOURCE = {
    "kill_switch": "kill_switch",
    "execution": "execution",
    "vip": "vip",
    "activist_strong": "activist",
    "activist_info": "activist",
    "meme_erupting": "meme_stock",
    "meme_blazing": "meme_stock",
}


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
        # 마지막 send 결과: sent | queued | skipped | failed (호출 측이 '처리됨' 판단에 씀 · 예: meme 이력)
        self.last_result: Optional[str] = None

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

    def _scrub(self, text: str) -> str:
        """기록·로그 문구에서 봇 토큰을 지운다 (_mask 는 `token=` 꼴만 잡음)."""
        token = self.config.bot_token
        return text.replace(token, "***") if token else text

    async def _gate(self, level: Level, title: str, body: str, category: str, dedupe_key: str) -> Optional[bool]:
        """설정 확인·최소 등급·재발송 간격·하루 요약 대기. 계속 보내면 None, 멈추면 반환값."""
        from . import notification_log as nl
        from . import notification_settings as ns

        if category not in ns.CATEGORIES:
            return None  # 모르는 종류는 항상 발송 (기록만)
        setting = await ns.get_setting(category)
        editable = ns.editable_fields(category)
        if not editable:
            return None  # Kill Switch·실주문은 DB 값과 상관없이 즉시 발송
        if "enabled" in editable and not setting.enabled:
            await nl.record(category, dedupe_key, title, "skipped", "설정: 꺼짐")
            return False
        try:
            below = ns.LEVELS.index(level.value) < ns.LEVELS.index(setting.min_level)
        except ValueError:  # 알 수 없는 등급 값 = 설정 못 읽음 = 발송
            below = False
        if "min_level" in editable and below:
            await nl.record(category, dedupe_key, title, "skipped", f"설정: 최소 등급 {setting.min_level}")
            return False
        if "resend_minutes" in editable and setting.resend_minutes > 0:
            try:
                last = await nl.last_activity_at(category, dedupe_key)
            except Exception:  # noqa: BLE001 — 읽기 실패 = 발송
                last = None
            if last is not None and (nl.utcnow() - last).total_seconds() < setting.resend_minutes * 60:
                await nl.record(category, dedupe_key, title, "skipped", f"설정: 재발송 간격 {setting.resend_minutes}분")
                return False
        if setting.mode == "digest":
            try:
                await nl.enqueue_digest(category, title, body)
            except Exception as exc:  # noqa: BLE001 — 대기열 실패 = 즉시 발송
                logger.warning(f"[Notifier] 요약 대기열 실패 · 즉시 발송: {exc.__class__.__name__}")
                return None
            await nl.record(category, dedupe_key, title, "queued")
            self.last_result = "queued"
            return False
        return None

    async def send(
        self,
        level: Level,
        title: str,
        body: str,
        force: bool = False,
        category: Optional[str] = None,
        dedupe_id: Optional[str] = None,
        gate: bool = True,
    ) -> bool:
        """알림 전송. 보냈으면 True, 건너뛰거나 실패하면 False.

        순서 (1022-09 · docs/plans/alert-settings/design.md):
        1. 알림 설정 (category 별 켜기·최소 등급·재발송 간격·하루 요약) — gate=False 면 건너뜀
           (하루 요약 잡·WATCH 배치 전용). 끌 수 없는 종류(kill_switch·execution·system)는 꺼짐 무시.
        2. TELEGRAM_PROFILE (SCOUT/SNIPER/WATCH) 필터 — force=True 면 우회
        3. 60초 메모리 중복 억제 — force=True 면 우회
        모든 시도는 notification_log 에 기록 (기록 실패는 발송과 무관).
        """
        from . import notification_log as nl

        self.last_result = "skipped"
        if not self.config.bot_token or not self.config.chat_id:
            logger.debug(f"[Notifier] credentials 없음 — skip: {title}")
            return False

        category = category or self._infer_category(title)
        # 기록·대기열은 원문 제목 (호출 측이 HTML escape 한 제목도 하루 요약에서 다시 escape 되므로)
        plain_title = html.unescape(title)
        dedupe_key = dedupe_id or plain_title
        if gate:
            stop = await self._gate(level, plain_title, body, category, dedupe_key)
            if stop is not None:
                return stop

        # 프로파일 필터 (force=True 시 우회 · 예: Kill Switch · WATCH 배치 자체)
        if not force:
            try:
                from .notifier_profile import (
                    NotifyContext,
                    current_profile,
                    get_watch_queue,
                    should_send_by_profile,
                )
                source = _CATEGORY_SOURCE.get(category) or self._infer_source(title)
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
                    await nl.record(category, dedupe_key, plain_title, "skipped", f"프로필 {current_profile()}")
                    return False
            except ImportError:
                pass  # profile 모듈 없으면 기본 동작

        key = self._hash(title, body)
        if not force and not self._dedupe_check(key):
            logger.debug(f"[Notifier] dedupe skip: {title}")
            return False

        # 제목이 아이콘으로 시작하면 등급 아이콘을 붙이지 않는다 (아이콘 1개 · 1023-05)
        text = f"<b>{title}</b>\n\n{body}" if starts_with_icon(title) else f"<b>{LEVEL_ICONS[level]} {title}</b>\n\n{body}"

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
            await nl.record(category, dedupe_key, plain_title, "sent")
            self.last_result = "sent"
            return True
        except httpx.HTTPStatusError as e:
            # 토큰이 든 URL 은 남기지 않고 상태 코드와 응답 본문 앞 200자만 기록
            error = self._scrub(f"HTTP {e.response.status_code} body={e.response.text[:200]!r}")
            logger.error(f"[Notifier] send failed: {error}")
            await nl.record(category, dedupe_key, plain_title, "failed", error)
            self.last_result = "failed"
            return False
        except Exception as e:
            from .logging_setup import _mask

            error = self._scrub(f"{type(e).__name__}: {_mask(str(e))[:200]}")
            logger.error(f"[Notifier] send failed: {error}")
            await nl.record(category, dedupe_key, plain_title, "failed", error)
            self.last_result = "failed"
            return False

    async def send_critical(self, title: str, body: str, category: Optional[str] = None, dedupe_id: Optional[str] = None) -> bool:
        return await self.send(Level.CRITICAL, title, body, force=True, category=category, dedupe_id=dedupe_id)

    async def send_warning(self, title: str, body: str, category: Optional[str] = None, dedupe_id: Optional[str] = None) -> bool:
        return await self.send(Level.WARNING, title, body, category=category, dedupe_id=dedupe_id)

    async def send_info(self, title: str, body: str, category: Optional[str] = None, dedupe_id: Optional[str] = None) -> bool:
        return await self.send(Level.INFO, title, body, category=category, dedupe_id=dedupe_id)

    @classmethod
    def _infer_category(cls, title: str) -> str:
        """category 를 넘기지 않은 호출 — 제목으로 확실한 것만 추정, 나머지는 unknown (항상 발송)."""
        return {"vip": "vip", "kill_switch": "kill_switch", "execution": "execution"}.get(cls._infer_source(title), "unknown")

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


def _fmt_won(v: Optional[float]) -> str:
    """원화 가격. None(예: 과열 시 진입가 없음) 이면 "-"."""
    return "-" if v is None else f"{v:,.0f}원"


def _fmt_pct(v: Optional[float]) -> str:
    """부호 있는 % . None 이면 "-"."""
    return "-" if v is None else f"{v:+.1f}%"


_RISK_TEXT = {"HIGH": "높음", "MED": "보통", "LOW": "낮음"}


def _today_md() -> str:
    from backend.services import alert_text as at

    return at.kst(datetime.now(timezone.utc))[:5]


def format_moonshot_alert(picks: list) -> tuple[str, str]:
    """Moonshot 상위 N → Telegram (title, body) · 종목당 3줄 (1023-05)."""
    from backend.services import alert_text as at

    title = at.title("discovery_moonshot", f"{_today_md()} 상위 {len(picks)}", "🚀")
    lines = []
    for p in picks:
        risk = _RISK_TEXT.get(p.risk_level, at.esc(p.risk_level or "—"))
        lines.append(f"{p.rank}. {at.esc(p.ticker)} {at.usd(p.current_price)} · {int(p.total_score + 0.5)}점 · 조작 위험 {p.manipulation_risk}/5 ({risk})")
        lines.append(f"   지정가 참고: 지금 {at.usd(p.buy_price_market)} · 3% 아래 {at.usd(p.buy_price_limit_3pct)} · 7% 아래 {at.usd(p.buy_price_limit_7pct)}")
        note = f" · 주의: {at.esc(p.risk_warning)}" if p.risk_warning else ""
        lines.append(f"   분석: {at.esc(_cut(p.thesis, 40))}{note}")
    lines.append(at.link("discovery_moonshot"))
    return title, "\n".join(lines)


def _cut(text: Optional[str], n: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


CRAZY_ALERT_TOP = 5   # 사용자 결정 10/23 — 나머지는 화면에서


def format_crazy_alert(picks: list) -> tuple[str, str]:
    """Crazy 상위 5 → Telegram · 종목당 1줄 (1023-05)."""
    from backend.services import alert_text as at

    shown = picks[:CRAZY_ALERT_TOP]
    title = at.title("discovery_crazy", f"{_today_md()} 상위 {len(shown)}", "🎯")
    lines = ["커뮤니티 언급·공매도·내부자 매매·뉴스 등으로 점수를 매긴 미국 종목입니다."]
    for p in shown:
        lines.append(f"{p.rank}. {at.esc(p.ticker)} {at.usd(p.current_price)} · {int(p.total_score + 0.5)}점 · {at.esc(_cut(p.thesis, 30))}")
    rest = len(picks) - len(shown)
    lines.append(f"나머지 {rest}종목과 분석 전문은 화면에서" if rest > 0 else "분석 전문은 화면에서")
    lines.append(at.link("discovery_crazy"))
    return title, "\n".join(lines)


# ─────────────────────────────────────────────
# 섹터 리더 — 매력도 임계 알림 (KRX)
# ─────────────────────────────────────────────


def format_sector_leaders_alert(
    items: list,
    bucket_label: str,
    expanded: bool = False,
) -> tuple[str, str]:
    """섹터 리더 매력도 임계 통과 종목 → Telegram (title, body) · 종목당 1줄 (1023-05).

    Args:
        items: list[Top10Item] — 발송 대상 (이미 상위 N 컷·rank 재계산된 상태).
        bucket_label: "0.6" / "0.5" / "empty".
        expanded: 0.6 이상이 5개 이하라 0.5 이상까지 확장된 경우 True.
    """
    from backend.services import alert_text as at

    if not items or bucket_label == "empty":
        title = at.title("discovery_sector", "오늘 기준을 넘은 종목 없음", "📊")
        body = "\n".join(["매력도 0.5 이상인 종목이 오늘은 없습니다.", at.link("discovery_sector")])
        return title, body

    title = at.title("discovery_sector", f"오늘 상위 {len(items)}종목", "📊")
    head = f"수출 자료로 고른 업종 대표 종목입니다 (매력도 {bucket_label} 이상"
    lines = [head + (" · 0.6 이상이 적어 넓힘)." if expanded else ").")]
    for it in items:
        price_tag = "" if it.price_source == "live" else " (전일 종가)"
        months = getattr(it, "horizon_months", None)
        horizon = f"{months}개월 뒤 " if months else ""
        pct_text = at.NONE if it.point_pct is None else _fmt_pct(it.point_pct)
        lines.append(
            f"{it.rank}. {at.esc(it.name)} {at.won(it.current_price)}{price_tag}"
            f" · 지정가 참고 {at.won(it.entry_price)}"
            f" · 통계 추정 {horizon}{at.won(it.point_price)} ({pct_text})"
            f" · {at.entry_status_text(it.entry_status)}"
        )
    lines.append("추정은 수출 자료와 과거 상관으로 계산 · 보장 아님")
    lines.append(at.link("discovery_sector"))
    return title, "\n".join(lines)
