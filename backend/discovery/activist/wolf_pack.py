"""Wolf Pack 그룹 추출 · Phase C+.

정의: 30일 window 안에 **서로 다른 2명 이상의 activist** 가 **같은 종목** (target_ticker 기준)
      에 진입한 경우. 특히 Tier 1 activist 다수 동시 진입은 매매 개시의 강한 선행 신호.

이 모듈은 [[state.ActivistEvent]] 리스트에서 target_ticker 별로 그룹화 → 30일 이내 unique
activist 수 >= 2 인 종목만 필터 → 진입 순서 정렬.

Insider (Phase E/F) 이벤트는 제외 (activism 원 신호만 · self-reference 방지).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .state import ActivistEvent, ActivistState
from .universe import Activist, load as load_universe

_WOLF_WINDOW_SEC = 30 * 86400   # 30일


@dataclass(frozen=True)
class WolfPackEntry:
    """개별 activist 진입 이벤트."""
    filer_key: str
    filer_name: str
    tier: int
    form: str
    filing_date: str            # 이벤트 filing_date (YYYY-MM-DD)
    detected_at: float          # unix
    accession: str
    intensity_label: str


@dataclass(frozen=True)
class WolfPackGroup:
    """종목별 Wolf Pack 그룹."""
    target_ticker: str
    target_desc: str
    target_cik: Optional[str]
    country: str
    entries: List[WolfPackEntry] = field(default_factory=list)

    @property
    def activist_count(self) -> int:
        return len({e.filer_key for e in self.entries})

    @property
    def tier1_count(self) -> int:
        return len({e.filer_key for e in self.entries if e.tier == 1})

    @property
    def first_entry_at(self) -> float:
        return min(e.detected_at for e in self.entries) if self.entries else 0.0

    @property
    def latest_entry_at(self) -> float:
        return max(e.detected_at for e in self.entries) if self.entries else 0.0

    @property
    def days_span(self) -> int:
        if len(self.entries) < 2:
            return 0
        return int((self.latest_entry_at - self.first_entry_at) / 86400)

    @property
    def intensity_score(self) -> int:
        """Wolf Pack 강도 (그룹 관점) — activist 수 + Tier 1 비중."""
        base = 40
        n = self.activist_count
        if n >= 4:
            base += 40
        elif n >= 3:
            base += 30
        elif n >= 2:
            base += 15
        if self.tier1_count >= 3:
            base += 15
        elif self.tier1_count >= 2:
            base += 10
        elif self.tier1_count >= 1:
            base += 5
        return min(100, base)

    @property
    def intensity_label(self) -> str:
        s = self.intensity_score
        if s >= 90:
            return "CRITICAL_PACK"
        if s >= 75:
            return "STRONG_PACK"
        return "PACK"


def _activist_lookup() -> Dict[str, Activist]:
    return {a.key: a for a in load_universe()}


def extract_groups(state: ActivistState, now: Optional[float] = None) -> List[WolfPackGroup]:
    """state.events 에서 Wolf Pack 그룹 추출.

    필터:
    - event_type == "ACTIVIST" (INSIDER/REGIME_CHANGE 제외)
    - target_ticker 존재
    - 최근 30일 이내
    - 그룹 내 unique filer >= 2
    """
    now = now if now is not None else time.time()
    cutoff = now - _WOLF_WINDOW_SEC
    lookup = _activist_lookup()

    by_ticker: Dict[str, List[ActivistEvent]] = {}
    for e in state.events:
        if e.event_type != "ACTIVIST":
            continue
        if not e.target_ticker:
            continue
        if e.detected_at < cutoff:
            continue
        by_ticker.setdefault(e.target_ticker, []).append(e)

    groups: List[WolfPackGroup] = []
    for ticker, evs in by_ticker.items():
        unique_filers = {e.filer_key for e in evs}
        if len(unique_filers) < 2:
            continue

        # filer 별 대표 이벤트 (해당 filer 최신) → entries
        latest_per_filer: Dict[str, ActivistEvent] = {}
        for e in evs:
            prev = latest_per_filer.get(e.filer_key)
            if prev is None or e.detected_at > prev.detected_at:
                latest_per_filer[e.filer_key] = e

        entries: List[WolfPackEntry] = []
        for filer_key, e in latest_per_filer.items():
            a = lookup.get(filer_key)
            tier = a.tier if a else 3
            entries.append(WolfPackEntry(
                filer_key=filer_key,
                filer_name=e.filer_name,
                tier=tier,
                form=e.form,
                filing_date=e.filing_date,
                detected_at=e.detected_at,
                accession=e.accession,
                intensity_label=e.intensity_label,
            ))
        entries.sort(key=lambda x: x.detected_at)

        # 대표 이벤트 하나에서 desc/cik/country 취득
        rep = latest_per_filer[entries[-1].filer_key]
        groups.append(WolfPackGroup(
            target_ticker=ticker,
            target_desc=rep.target_desc,
            target_cik=rep.target_cik,
            country=rep.country,
            entries=entries,
        ))

    # 강도·최신 진입 시각 순 정렬
    groups.sort(key=lambda g: (-g.intensity_score, -g.latest_entry_at))
    return groups


def to_dict(g: WolfPackGroup) -> dict:
    return {
        "target_ticker": g.target_ticker,
        "target_desc": g.target_desc,
        "target_cik": g.target_cik,
        "country": g.country,
        "activist_count": g.activist_count,
        "tier1_count": g.tier1_count,
        "days_span": g.days_span,
        "first_entry_at": g.first_entry_at,
        "latest_entry_at": g.latest_entry_at,
        "intensity_score": g.intensity_score,
        "intensity_label": g.intensity_label,
        "entries": [
            {
                "filer_key": e.filer_key,
                "filer_name": e.filer_name,
                "tier": e.tier,
                "form": e.form,
                "filing_date": e.filing_date,
                "detected_at": e.detected_at,
                "accession": e.accession,
                "intensity_label": e.intensity_label,
            }
            for e in g.entries
        ],
    }
