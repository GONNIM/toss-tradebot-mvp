"""자동 초안 자료 연결 · 기존 바이오 파이프 산출물을 읽기만 한다 (1116-01 v4 7절).

저장 위치는 기존 규칙(BIOTECH_RUNTIME_DIR > docs/plans/biotech/data > backend/data)을 그대로 쓴다 —
`backend/api/routes/biotech.py` 의 `_search_dirs` 가 화면과 같은 파일을 읽는다. 서버 자료는 보지 않는다.

연결한 것 (각 줄 = 어디서 읽나)
- 상장폐지 · 합병 진행 · 인수 완료: radar_v1_3_<날짜>.csv 의 status 열 (biotech_listing_status.py 가 판정 · status_checked 가 N 이면 자료 없음)
  · 순위에서 빠진 종목은 같은 날짜 radar_excluded_<날짜>.json 에서
- 계속기업 의문: going_concern.json → biotech.py `_going_concern_for` (present = 있음 · not_found = 없음 · 그 밖 · 낡음 = 자료 없음)
- 최근 30일 증자: filings_derived_<날짜>.json 의 offerings_12m (424B5 · S-1 · S-1/A 가 30일 안)
- 촉매 날짜(등록부 추정): biotech_candidates_v3 의 state_note (임상 1차 완료 예정일 · 결과 발표일 아님)
- 기준가: 토스 시세 읽기(RealRaw.last_price_rest) · 호출할 종목은 촉매가 있고 제외되지 않은 것만

연결하지 못한 것 (자료 없음 → 경고 줄): 거래 정지 · 최저가 미달 · 회사 8-K 보도자료 촉매 날짜 · 대표 입력 촉매 날짜 · 예산 · TP1 폭
(저장소에 그 판정이나 날짜를 뽑는 코드가 없다. 8-K 본문 단계는 방향 태그만 저장하고 날짜는 저장하지 않는다.)
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .drafts import CatalystInput

logger = logging.getLogger(__name__)

RAISE_FORMS = ("424B5", "S-1", "S-1/A")       # 증자 신호 (S-3 는 일괄 신고라 증자 자체가 아님)
RAISE_DAYS = 30

PriceFn = Callable[[str], Awaitable[Optional[Any]]]


def listing_flags(status: str, checked: bool) -> dict:
    """radar 의 status → 제외 판정 3칸. 확인하지 않은 행(status_checked N · unchecked)은 모두 None(자료 없음).
    거래 정지는 이 저장소에 판정이 없어 늘 None."""
    if not checked or status in ("", "unchecked"):
        return {"delisted": None, "acquired": None, "merger_pending": None, "halted": None}
    return {
        "delisted": status == "excluded_delisted",
        "acquired": status == "merge_done_hold",
        "merger_pending": status in ("merging_seller", "merging_fact"),
        "halted": None,
    }


def going_concern_flag(gc) -> Optional[bool]:
    """GoingConcern(표시 값) → 있음 True · 없음 False · 그 밖(불명 · 낡음 · 가정 문장뿐)은 None."""
    if gc is None or gc.stale or gc.updates_stopped:
        return None
    if gc.state == "present" and not gc.hypothetical_only:
        return True
    if gc.state == "not_found":
        return False
    return None


def offering_flag(derived_row: Optional[dict], today: date) -> Optional[bool]:
    if derived_row is None:
        return None
    since = (today - timedelta(days=RAISE_DAYS)).isoformat()
    return any(o.get("form") in RAISE_FORMS and (o.get("filingDate") or "") >= since
               for o in derived_row.get("offerings_12m") or [])


class BiotechDraftLoader:
    """CandidateLoader · 호출하면 한 종목의 자료 dict 를 돌려준다(async · 기준가 때문). 파일은 한 번만 읽는다."""

    def __init__(self, today: date, price_fn: Optional[PriceFn] = None):
        self.today = today
        self.price_fn = price_fn
        self._loaded = False
        self._bt = None
        self._rows: dict[str, dict] = {}
        self._excluded: dict[str, str] = {}
        self._gc_store = None
        self._derived: dict = {}
        self._notes: dict[str, str] = {}

    # ── 읽기 (기존 규칙 그대로) ──
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from backend.api.routes import biotech as bt
        except Exception as exc:  # noqa: BLE001 — 불러오지 못하면 모든 자료가 「없음」
            logger.warning("[plan-draft] 바이오 모듈을 불러오지 못함 · %s", exc.__class__.__name__)
            return
        self._bt = bt
        try:
            path = bt._latest_radar_csv()
            if path is not None and path.exists():
                with path.open(encoding="utf-8", newline="") as f:
                    for r in csv.DictReader(f):
                        if r.get("ticker"):
                            self._rows[r["ticker"].strip().upper()] = r
                out_x, out_m = bt._excluded_lists(path)
                for e in out_x:
                    self._excluded[e.ticker.upper()] = "excluded_delisted"
                for e in out_m:
                    self._excluded.setdefault(e.ticker.upper(), e.status)
            self._gc_store = bt._going_concern_store()
            self._notes = bt._latest_candidate_notes()
            for d in bt._search_dirs("filings"):
                hits = sorted(d.glob("filings_derived_????????.json")) if d.exists() else []
                if hits:
                    self._derived = (json.loads(hits[-1].read_text()).get("rows") or {})
                    break
        except Exception as exc:  # noqa: BLE001 — 깨진 파일 하나로 잡 전체가 멈추지 않는다
            logger.warning("[plan-draft] 바이오 산출물 읽기 실패 · %s", exc.__class__.__name__)

    def _catalysts(self, symbol: str) -> list[CatalystInput]:
        note = self._notes.get(symbol, "")
        m = self._bt._NOTE_RE.search(note) if self._bt and note else None
        if not m:
            return []
        try:
            return [CatalystInput("registry", day=datetime.strptime(m.group(3), "%Y-%m-%d").date())]
        except ValueError:
            return []

    async def __call__(self, symbol: str) -> dict:
        self._load()
        sym = symbol.upper()
        row = self._rows.get(sym)
        flags: dict[str, Optional[bool]] = {}
        status = (row or {}).get("status") or self._excluded.get(sym, "")
        checked = ((row or {}).get("status_checked") or ("Y" if sym in self._excluded else "N")) != "N"
        flags.update(listing_flags(status, checked))
        cik = (row or {}).get("cik") or ""
        gc = self._bt._going_concern_for(self._gc_store, cik) if (self._bt and cik) else None
        flags["going_concern"] = going_concern_flag(gc)
        key = str(int(cik)).zfill(10) if cik.isdigit() else ""
        flags["offering_30d"] = offering_flag(self._derived.get(key), self.today) if key else None
        flags["below_min_price"] = None            # 판정 코드가 저장소에 없음 → 자료 없음
        cats = self._catalysts(sym)
        ref = None
        excluded = any(flags.get(k) is True for k in ("delisted", "acquired", "merger_pending"))
        if cats and not excluded and self.price_fn is not None:
            try:
                ref = await self.price_fn(sym)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[plan-draft] 기준가 읽기 실패 · %s", exc.__class__.__name__)
        return {"catalysts": cats, "flags": flags, "ref_price": ref, "budget_usd": None, "tp1_pct": None}
