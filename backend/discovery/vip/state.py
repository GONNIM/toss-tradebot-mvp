"""VIP 감시 상태 (파일 기반, 티커별 격리).

Why 티커별 격리: 감시 종목이 바뀌면 이전 상태가 오염된 채 새 종목에 적용될 수 있음.
`data/vip_{ticker_slug}_state.json` 로 종목별로 파일이 분리되면 자연스럽게 초기화.

Why 파일 기반: DB 모델 추가는 P-A 스코프 부풀림. tick 마다 read/write 만 하면 충분.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_DIR.parent

_EVENT_COOLDOWN_SEC = 24 * 3600


def _slug(ticker: str) -> str:
    """티커 → 파일명 slug (WEN.O → WEN_O)."""
    return re.sub(r"[^A-Za-z0-9]", "_", ticker.upper()) or "TICKER"


def state_path(ticker: str) -> Path:
    return _PROJECT_ROOT / "data" / f"vip_{_slug(ticker)}_state.json"


@dataclass
class VipState:
    ticker: str
    sent: Dict[str, float] = field(default_factory=dict)
    trail_armed_at: Optional[float] = None
    trail_peak_pnl: Optional[float] = None
    activist_last_accession: Optional[str] = None

    @classmethod
    def load(cls, ticker: str) -> "VipState":
        p = state_path(ticker)
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(
                ticker=ticker,
                sent=dict(raw.get("sent", {})),
                trail_armed_at=raw.get("trail_armed_at"),
                trail_peak_pnl=raw.get("trail_peak_pnl"),
                activist_last_accession=raw.get("activist_last_accession"),
            )
        except FileNotFoundError:
            return cls(ticker=ticker)
        except Exception as e:
            logger.warning(f"[vip.state] load 실패({p.name}) — 초기화: {e}")
            return cls(ticker=ticker)

    def save(self) -> None:
        p = state_path(self.ticker)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "sent": self.sent,
                        "trail_armed_at": self.trail_armed_at,
                        "trail_peak_pnl": self.trail_peak_pnl,
                        "activist_last_accession": self.activist_last_accession,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp, p)
        except Exception as e:
            logger.warning(f"[vip.state] save 실패({p.name}): {e}")

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
