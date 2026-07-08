"""VIP 감시 상태 (파일 기반, JSON).

Why 파일 기반: P-A 스코프에서 DB 모델 추가는 과함. Trian accession dedup 과
이벤트별 cooldown 만 필요. 프로세스 재시작에도 살아남으면 충분.

파일 경로: data/vip_wen_state.json (프로젝트 root 기준).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_DIR.parent
_STATE_PATH = _PROJECT_ROOT / "data" / "vip_wen_state.json"

# 이벤트별 cooldown (초). 동일 이벤트는 이 시간 동안 재발송 안 함.
_EVENT_COOLDOWN_SEC = 24 * 3600  # 24h


@dataclass
class VipState:
    # 이벤트 발송 이력: {event_name: last_sent_unix}
    sent: Dict[str, float] = field(default_factory=dict)
    # Trailing peak P&L (armed 이후 최대 수익률). 미armed 상태면 None.
    trail_armed_at: Optional[float] = None   # armed 시점 unix
    trail_peak_pnl: Optional[float] = None
    # Trian 최신 accession (SEC EDGAR)
    trian_last_accession: Optional[str] = None

    @classmethod
    def load(cls) -> "VipState":
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(
                sent=dict(raw.get("sent", {})),
                trail_armed_at=raw.get("trail_armed_at"),
                trail_peak_pnl=raw.get("trail_peak_pnl"),
                trian_last_accession=raw.get("trian_last_accession"),
            )
        except FileNotFoundError:
            return cls()
        except Exception as e:
            logger.warning(f"[vip.state] load 실패 — 초기화: {e}")
            return cls()

    def save(self) -> None:
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATE_PATH.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "sent": self.sent,
                        "trail_armed_at": self.trail_armed_at,
                        "trail_peak_pnl": self.trail_peak_pnl,
                        "trian_last_accession": self.trian_last_accession,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp, _STATE_PATH)
        except Exception as e:
            logger.warning(f"[vip.state] save 실패: {e}")

    def can_send(self, event: str, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        last = self.sent.get(event)
        if last is None:
            return True
        return (now - last) >= _EVENT_COOLDOWN_SEC

    def mark_sent(self, event: str, now: Optional[float] = None) -> None:
        self.sent[event] = now if now is not None else time.time()

    def arm_trail(self, pnl: float, now: Optional[float] = None) -> None:
        self.trail_armed_at = now if now is not None else time.time()
        self.trail_peak_pnl = pnl

    def update_peak(self, pnl: float) -> None:
        if self.trail_armed_at is None:
            return
        if self.trail_peak_pnl is None or pnl > self.trail_peak_pnl:
            self.trail_peak_pnl = pnl

    def reset_trail(self) -> None:
        self.trail_armed_at = None
        self.trail_peak_pnl = None
