"""자동 초안 · 계획서 10절 (v4 7절 · 남은 문제 7 고침).

- 실행 조건: 최신 레이더 파일 이름(`radar_v1_3_YYYYMMDD.csv`)의 날짜가 오늘(KST)일 때. 파일 수정 시각 · radar.json 의
  `generated` 는 쓰지 않는다.
- 첫 시도는 07:15, 이어서 10분 간격 최대 6번(07:15 · 07:25 · 07:35 · 07:45 · 07:55 · 08:05). 그때까지 없으면
  그날 초안 없음 + 시스템 경고 1건.
- 초안은 승인 전 상태(DRAFT)다. 승인은 대표(모의 계획은 Aside 도 가능).

[미구현 · 확인 못 함] 대상 · 제외 · 촉매 날짜 · 진입 창 · 값 규칙(v4 7절)은 저장소 밖 지시문에만 있고 이 저장소에 없다.
그래서 후보를 고르는 `select_candidates` 는 비어 있고, 후보 값을 받아 6절 규칙으로 초안 값을 만드는
`build_draft_params` 와 「오늘 레이더가 나왔는가 · 몇 번째 시도인가」 판단만 구현했다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from . import sessions as sess
from .pricing import D, buy_order, buy_watch, qty_for_budget, sell_watch

_KST = timezone(timedelta(hours=9))
RADAR_RE = re.compile(r"^radar_v1_3_(\d{8})\.csv$")
ATTEMPT_TIMES = ((7, 15), (7, 25), (7, 35), (7, 45), (7, 55), (8, 5))
MAX_ATTEMPTS = len(ATTEMPT_TIMES)


def radar_dir() -> Optional[Path]:
    import os

    raw = os.environ.get("PLAN_RADAR_DIR")
    return Path(raw) if raw else None


def latest_radar_date(directory: Optional[Path]) -> Optional[date]:
    """파일 이름의 날짜만 본다."""
    if directory is None or not directory.is_dir():
        return None
    best: Optional[date] = None
    for f in directory.iterdir():
        m = RADAR_RE.match(f.name)
        if m:
            try:
                d = datetime.strptime(m.group(1), "%Y%m%d").date()
            except ValueError:
                continue
            best = d if best is None or d > best else best
    return best


def today_kst(now_utc: Optional[datetime] = None) -> date:
    n = now_utc or datetime.now(timezone.utc)
    if n.tzinfo is None:
        n = n.replace(tzinfo=timezone.utc)
    return n.astimezone(_KST).date()


def radar_ready(directory: Optional[Path], today: date) -> bool:
    """어제 날짜 · 파일 없음이면 False (초안을 만들지 않는다)."""
    return latest_radar_date(directory) == today


def attempt_number(now_kst: datetime) -> Optional[int]:
    """지금 시각이 몇 번째 시도 시각인가(1~6). 시각이 아니면 None."""
    for i, (h, m) in enumerate(ATTEMPT_TIMES, start=1):
        if (now_kst.hour, now_kst.minute) == (h, m):
            return i
    return None


def select_candidates(directory: Optional[Path], today: date) -> list[dict]:
    """[미구현] v4 7절 대상 · 제외 · 촉매 규칙이 저장소에 없다. 추측하지 않고 비워 둔다."""
    return []


def build_draft_params(*, ref_price, budget_usd, announce_at: datetime, entry_close_at: datetime,
                       entry_window_end: datetime, wide: bool = False, tp1_pct=None) -> dict:
    """후보 값 → 초안 값 (6절 규칙 · D7 사다리 기본 −3·−5·−7%). 넓은 폭은 「제안」으로만 쓴다(기본 아님)."""
    watch = buy_watch(ref_price)
    order = buy_order(ref_price)
    out = {
        "budget_usd": float(budget_usd),
        "buy_watch": float(watch),
        "buy_order": float(order),
        "qty": qty_for_budget(budget_usd, order),
        "ladder_pcts": [float(x) for x in (sess.WIDE_LADDER_PCTS if wide else sess.DEFAULT_LADDER_PCTS)],
        "announce_at": announce_at.isoformat(),
        "entry_close_at": entry_close_at.isoformat(),
        "entry_window_end": entry_window_end.isoformat(),
    }
    if tp1_pct is not None:
        tp = sell_watch(D(order) * (1 + D(tp1_pct)))
        out["tp1_watch"], out["tp1_order"] = float(tp), float(tp)
    return out
