"""Kill Switch — v2 트랙 C Phase 1.

발동 시: 새 매수 차단 · 보유 종목 매도는 sell_allowed 일 때 허용 (기본 · 1105-02) ·
  sell_allowed=False 면 모든 주문 차단 · 텔레그램 🚨 URGENT 발송 · 수동 해제 필요.
  (기존 미체결 취소는 구현 없음)

상태는 파일 + 프로세스 메모리 (_cached). 운영은 uvicorn 1 워커 · 같은 프로세스 스케줄러라 문제없음.
다른 프로세스에서 발동하면 서로 보이지 않음 (재시작 전까지).

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §8-1
     docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §2-3
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backend.services.notifier import TelegramNotifier

_KST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STATE_PATH = _PROJECT_ROOT / "backend" / "data" / "kill_switch.json"


def _actor_text(actor: str) -> str:
    from backend.services import alert_text as at

    if actor == "auto:sniper":
        return "자동 (스나이퍼)"
    if actor.startswith("auto:"):
        return f"자동 ({at.esc(actor[5:])})"
    if actor in ("user:manual", "user", ""):
        return "직접"
    if actor.startswith("user:"):
        return f"직접 ({at.esc(actor[5:])})"
    return at.esc(actor)


def _reason_text(reason: str) -> str:
    import re

    from backend.services import alert_text as at

    m = re.fullmatch(r"daily_loss_limit_reached\((.*)\)", reason or "")
    if m:
        return f"오늘 손실 한도 도달 ({at.esc(m.group(1))})"
    return at.esc(reason or "—")


def _kill_switch_message(state) -> tuple[str, str]:
    """Kill Switch 발동 알림 (제목, 본문) · 풀기는 화면 주소 (1023-05)."""
    from backend.services import alert_text as at
    from backend.services.notification_settings import SITE_BASE_URL

    if getattr(state, "sell_allowed", True):
        title = at.title("kill_switch", "새 매수 멈춤", "🚨")
        rule = "직접 풀기 전까지 새 매수는 나가지 않습니다. 보유 종목의 손절·추적 매도는 계속됩니다."
    else:
        title = at.title("kill_switch", "모든 주문 멈춤", "🚨")
        rule = "직접 풀기 전까지 매수와 매도 모두 나가지 않습니다. 보유 종목은 직접 정리해야 합니다."
    body = "\n".join([
        f"이유: {_reason_text(state.reason)}",
        f"누가: {_actor_text(state.activated_by or '')}",
        f"시각: {at.kst(state.activated_at)}",
        rule,
        f"풀기: {SITE_BASE_URL}/sniper 의 「수동 해제」 (관리자 로그인)",
    ])
    return title, body


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    reason: Optional[str] = None
    activated_at: Optional[datetime] = None
    activated_by: Optional[str] = None       # auto:<trigger> · user:<actor>
    deactivated_at: Optional[datetime] = None
    deactivated_by: Optional[str] = None
    sell_allowed: bool = True                # 1105-02 · 켜진 동안 매도 허용 여부 (옛 파일은 칸 없음 → True)


class KillSwitch:
    """파일 기반 Kill Switch · thread-safe · 텔레그램 URGENT 알림.

    자동 해제 없음 — deactivate() 는 수동 API 로만 호출.
    """

    def __init__(
        self,
        state_path: Optional[Path] = None,
        notifier: Optional[TelegramNotifier] = None,
    ):
        self._path = state_path or _DEFAULT_STATE_PATH
        self._lock = threading.RLock()
        self._notifier = notifier
        self._cached: Optional[KillSwitchState] = None

    # ─── 상태 로드/저장 ───
    def _load(self) -> KillSwitchState:
        if not self._path.exists():
            return KillSwitchState(active=False)
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("kill_switch.json 파싱 실패 — %s · active=False 로 간주", exc)
            return KillSwitchState(active=False)

        def _dt(s: Optional[str]) -> Optional[datetime]:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return None

        return KillSwitchState(
            active=bool(raw.get("active", False)),
            reason=raw.get("reason"),
            activated_at=_dt(raw.get("activated_at")),
            activated_by=raw.get("activated_by"),
            deactivated_at=_dt(raw.get("deactivated_at")),
            deactivated_by=raw.get("deactivated_by"),
            sell_allowed=bool(raw.get("sell_allowed", True)),
        )

    def _save(self, state: KillSwitchState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": state.active,
            "reason": state.reason,
            "activated_at": state.activated_at.isoformat() if state.activated_at else None,
            "activated_by": state.activated_by,
            "deactivated_at": state.deactivated_at.isoformat() if state.deactivated_at else None,
            "deactivated_by": state.deactivated_by,
            "sell_allowed": state.sell_allowed,
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ─── Public API ───
    def status(self) -> KillSwitchState:
        with self._lock:
            if self._cached is None:
                self._cached = self._load()
            return self._cached

    def is_active(self) -> bool:
        return self.status().active

    def blocks(self, side) -> bool:
        """이 주문 방향을 막는지 (1105-02). 매수는 켜지면 늘 막음 · 매도는 sell_allowed 가 False 일 때만."""
        st = self.status()
        if not st.active:
            return False
        side_value = getattr(side, "value", side)
        if side_value == "sell":
            return not st.sell_allowed
        return True

    def activate(self, reason: str, actor: str = "auto:unknown", sell_allowed: bool = True) -> KillSwitchState:
        """자동/수동 공통 발동.

        - 꺼져 있으면 발동 (sell_allowed 그대로 기록).
        - 이미 켜져 있고 sell_allowed=False 가 오면 「매도도 멈춤」 으로 좁힘 (1105-02 · 알림 1회).
        - 이미 켜져 있고 sell_allowed=True 면 그대로 (False→True 로 푸는 것은 해제 뒤 재발동으로만).
        """
        with self._lock:
            current = self.status()
            if current.active:
                if current.sell_allowed and not sell_allowed:
                    now = datetime.now(tz=timezone.utc)
                    narrowed = replace(
                        current,
                        sell_allowed=False,
                        reason=f"{current.reason or '—'} · 매도도 멈춤 ({actor} · {now.astimezone(_KST).strftime('%m/%d %H:%M')} KST)"[:300],
                    )
                    self._save(narrowed)
                    self._cached = narrowed
                    logger.critical("🚨 KILL SWITCH 매도도 멈춤으로 좁힘 · actor=%s", actor)
                    self._notify_urgent(narrowed)
                    return narrowed
                logger.info("Kill Switch 이미 발동 상태 · reason=%s", current.reason)
                return current
            new_state = KillSwitchState(
                active=True,
                reason=reason,
                activated_at=datetime.now(tz=timezone.utc),
                activated_by=actor,
                deactivated_at=None,
                deactivated_by=None,
                sell_allowed=sell_allowed,
            )
            self._save(new_state)
            self._cached = new_state
            logger.critical(
                "🚨 KILL SWITCH ACTIVATED · reason=%s · actor=%s · sell_allowed=%s", reason, actor, sell_allowed
            )
            self._notify_urgent(new_state)
            return new_state

    def deactivate(self, actor: str) -> KillSwitchState:
        """수동 해제 전용. active 가 아니면 no-op."""
        with self._lock:
            current = self.status()
            if not current.active:
                return current
            new_state = KillSwitchState(
                active=False,
                reason=current.reason,
                activated_at=current.activated_at,
                activated_by=current.activated_by,
                deactivated_at=datetime.now(tz=timezone.utc),
                deactivated_by=actor,
                sell_allowed=current.sell_allowed,
            )
            self._save(new_state)
            self._cached = new_state
            logger.warning("Kill Switch 해제 · actor=%s", actor)
            return new_state

    # ─── URGENT 알림 (기존 봇 재활용 · CRITICAL level) ───
    def _notify_urgent(self, state: KillSwitchState) -> None:
        try:
            notifier = self._notifier or TelegramNotifier()
        except Exception as exc:  # noqa: BLE001
            logger.warning("텔레그램 알림 인스턴스 생성 실패 — %s", exc)
            return

        title, body = _kill_switch_message(state)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is not None and loop.is_running():
                loop.create_task(notifier.send_critical(title, body, category="kill_switch"))
            else:
                asyncio.run(notifier.send_critical(title, body, category="kill_switch"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("URGENT 알림 전송 실패 — %s", exc)


# 프로세스 lifetime 싱글턴
_switch: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    global _switch
    if _switch is None:
        _switch = KillSwitch()
    return _switch
