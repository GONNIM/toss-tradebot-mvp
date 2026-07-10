"""Kill Switch — v2 트랙 C Phase 1.

발동 시: 모든 신규 주문 차단 · 기존 미체결 취소 · 텔레그램 🚨 URGENT 발송 · 수동 해제 필요.

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §8-1
     docs/plans/tradebot-mvp-v2/01-track-c-roadmap.md §2-3
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.services.notifier import TelegramNotifier

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_STATE_PATH = _PROJECT_ROOT / "backend" / "data" / "kill_switch.json"


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    reason: Optional[str] = None
    activated_at: Optional[datetime] = None
    activated_by: Optional[str] = None       # auto:<trigger> · user:<actor>
    deactivated_at: Optional[datetime] = None
    deactivated_by: Optional[str] = None


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

    def activate(self, reason: str, actor: str = "auto:unknown") -> KillSwitchState:
        """자동/수동 공통 발동. 이미 active 이면 no-op."""
        with self._lock:
            current = self.status()
            if current.active:
                logger.info("Kill Switch 이미 발동 상태 · reason=%s", current.reason)
                return current
            new_state = KillSwitchState(
                active=True,
                reason=reason,
                activated_at=datetime.now(tz=timezone.utc),
                activated_by=actor,
                deactivated_at=None,
                deactivated_by=None,
            )
            self._save(new_state)
            self._cached = new_state
            logger.critical(
                "🚨 KILL SWITCH ACTIVATED · reason=%s · actor=%s", reason, actor
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

        title = "🚨 URGENT · Kill Switch 발동"
        body = (
            f"<b>Reason</b>: {state.reason}\n"
            f"<b>Actor</b>: {state.activated_by}\n"
            f"<b>발동 시각</b>: {state.activated_at.isoformat() if state.activated_at else '-'}\n\n"
            "모든 신규 주문 차단됨. 수동 해제 시까지 유지.\n"
            "해제: <code>DELETE /api/v1/execution/kill-switch</code>"
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is not None and loop.is_running():
                loop.create_task(notifier.send_critical(title, body))
            else:
                asyncio.run(notifier.send_critical(title, body))
        except Exception as exc:  # noqa: BLE001
            logger.warning("URGENT 알림 전송 실패 — %s", exc)


# 프로세스 lifetime 싱글턴
_switch: Optional[KillSwitch] = None


def get_kill_switch() -> KillSwitch:
    global _switch
    if _switch is None:
        _switch = KillSwitch()
    return _switch
