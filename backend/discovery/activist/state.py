"""Activist Radar 상태 (파일 기반).

파일: data/activist_state.json

스키마:
    {
      "filer_last_seen": {
        "0001345471": ["accession1", "accession2", ...]  # 최근 10개 dedup
      },
      "events": [
        {
          "id": "us:0001345471:0001345471-24-000012",
          "country": "US",
          "filer_key": "trian_fund_management",
          "filer_name": "Trian Fund Management, L.P.",
          "form": "SC 13D/A",
          "accession": "0001345471-24-000012",
          "filing_date": "2024-05-14",
          "target_desc": "THE WENDY'S COMPANY - 13D",
          "target_ticker": "WEN",
          "score": 84,
          "intensity_label": "CRITICAL",
          "wolf_pack": ["elliott_investment_mgmt"],
          "detected_at": 1783571500
        }
      ]
    }

이벤트는 최대 200개 유지 (90일 이상 지난 것 자동 삭제).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_DIR.parent
_STATE_PATH = _PROJECT_ROOT / "data" / "activist_state.json"

_LAST_SEEN_CAP = 1000        # filer 당 recent accession 저장 (SEC `filings.recent` 최대 ~1000)
_EVENTS_CAP = 200            # 전체 이벤트 유지 상한
_EVENT_TTL_SEC = 90 * 86400  # 90일


@dataclass
class ActivistEvent:
    id: str
    country: str                  # "US" | "KR"
    filer_key: str
    filer_name: str
    form: str
    accession: str
    filing_date: str
    target_desc: str
    target_ticker: Optional[str] = None
    score: int = 0
    intensity_label: str = "WATCH"       # CRITICAL | STRONG | WATCH | NOTE
    wolf_pack: List[str] = field(default_factory=list)
    detected_at: float = 0.0


@dataclass
class ActivistState:
    filer_last_seen: Dict[str, List[str]] = field(default_factory=dict)
    events: List[ActivistEvent] = field(default_factory=list)

    @classmethod
    def load(cls) -> "ActivistState":
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls(
                filer_last_seen=dict(raw.get("filer_last_seen") or {}),
                events=[ActivistEvent(**e) for e in (raw.get("events") or [])],
            )
        except FileNotFoundError:
            return cls()
        except Exception as e:
            logger.warning(f"[activist.state] load 실패 — 초기화: {e}")
            return cls()

    def save(self) -> None:
        # 오래된 이벤트 정리 (90일 초과 제거)
        now = time.time()
        self.events = [
            e for e in self.events if (now - (e.detected_at or now)) < _EVENT_TTL_SEC
        ]
        self.events = self.events[-_EVENTS_CAP:]

        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATE_PATH.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "filer_last_seen": self.filer_last_seen,
                        "events": [asdict(e) for e in self.events],
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp, _STATE_PATH)
        except Exception as e:
            logger.warning(f"[activist.state] save 실패: {e}")

    # ─── filer accession dedup ──────────────────
    def has_seen(self, filer_key: str, accession: str) -> bool:
        return accession in (self.filer_last_seen.get(filer_key) or [])

    def mark_seen(self, filer_key: str, accession: str) -> None:
        lst = self.filer_last_seen.setdefault(filer_key, [])
        if accession in lst:
            return
        lst.append(accession)
        if len(lst) > _LAST_SEEN_CAP:
            del lst[:-_LAST_SEEN_CAP]

    # ─── event 추가/조회 ────────────────────────
    def add_event(self, evt: ActivistEvent) -> None:
        # id 중복이면 skip
        if any(e.id == evt.id for e in self.events):
            return
        self.events.append(evt)

    def recent_events(self, limit: int = 50) -> List[ActivistEvent]:
        return sorted(self.events, key=lambda e: e.detected_at, reverse=True)[:limit]

    def events_by_target(self, target_desc: str, since_ts: float) -> List[ActivistEvent]:
        return [
            e for e in self.events
            if target_desc.upper() in (e.target_desc or "").upper()
            and e.detected_at >= since_ts
        ]
