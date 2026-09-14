"""B106-4 · SEC 세션 공통 유틸 · 진행률 체크포인트 + 403 즉시 중단.

용도:
- B98 (h3_events) · B95 (라벨) · companyfacts 3 작업 공유
- 순수 함수 (fixture 테스트 가능) + httpx 얇은 래퍼

원칙:
- 403 → SecBlockedError 즉시 raise · 이후 호출 금지 (규정)
- 200 만 정상 · 4xx/5xx 은 상위에서 판단
- 체크포인트 JSON · 인덱스 기반 이어받기
- UA·From·간격 상수 통일
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

LOG = logging.getLogger("biotech_sec_common")

# WP23 (2026-09-09) · SEC 웹 그룹 회신 요지 반영 · 지정 형식 정확 일치
# 형식: "회사명 연락처이메일" (버전·괄호 제거) · Accept-Encoding "gzip, deflate" 필수
SEC_UA = "TossTradebot BiotechRadar suauncle@gmail.com"
SEC_FROM = "suauncle@gmail.com"
SEC_ACCEPT_ENCODING = "gzip, deflate"
REQ_INTERVAL = 0.5  # SEC 10 req/s 이내 · 보수적


class SecBlockedError(RuntimeError):
    """403 감지 시 raise · 상위에서 즉시 종료·보고만 (재시도·UA 순환 금지)."""


@dataclass
class Checkpoint:
    """작업 진행률 · JSON 파일 지속.

    keys: task · started_utc · updated_utc · processed_ids · counts · notes
    """
    path: Path
    task: str
    processed_ids: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def load_or_new(cls, path: Path, task: str) -> "Checkpoint":
        if path.exists():
            try:
                d = json.loads(path.read_text())
                if d.get("task") == task:
                    return cls(
                        path=path,
                        task=task,
                        processed_ids=list(d.get("processed_ids", [])),
                        counts=dict(d.get("counts", {})),
                        notes=list(d.get("notes", [])),
                    )
            except Exception:
                pass
        return cls(path=path, task=task)

    def save(self) -> None:
        from datetime import datetime, timezone
        d = {
            "task": self.task,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "processed_ids": self.processed_ids,
            "counts": self.counts,
            "notes": self.notes,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, indent=2, ensure_ascii=False))

    def has(self, item_id: str) -> bool:
        return item_id in self.processed_ids

    def mark(self, item_id: str, bucket: str = "processed") -> None:
        if item_id not in self.processed_ids:
            self.processed_ids.append(item_id)
        self.counts[bucket] = self.counts.get(bucket, 0) + 1


def sec_get(client: httpx.Client, url: str, params: dict | None = None) -> dict:
    """단일 SEC GET · 403 즉시 raise · 200 은 JSON 반환.

    반환 shape:
      {'status': 200, 'json': dict}
      {'status': 4xx/5xx, 'json': None, 'text_sig': str}  # 상위 판단
    """
    time.sleep(REQ_INTERVAL)
    r = client.get(url, params=params, timeout=25.0)
    if r.status_code == 403:
        sig = "Undeclared Automated Tool" if "Undeclared Automated Tool" in r.text[:2000] else r.text[:80]
        raise SecBlockedError(f"403 · {sig} · UA 순환·재시도 금지 · 대기+탐침 프로토콜 (biotech_sec_probe)")
    if r.status_code == 200:
        try:
            return {"status": 200, "json": r.json()}
        except Exception as e:
            return {"status": 200, "json": None, "text_sig": f"json_parse_err:{e}"}
    return {"status": r.status_code, "json": None, "text_sig": r.text[:80].replace("\n", " ")}


def build_client() -> httpx.Client:
    """공용 SEC httpx.Client · UA·From·Accept-Encoding (WP23 지정 형식)."""
    return httpx.Client(
        headers={
            "User-Agent": SEC_UA,
            "From": SEC_FROM,
            "Accept-Encoding": SEC_ACCEPT_ENCODING,
        },
        timeout=25.0,
    )


# ─ B98 · 이벤트 추출 규칙 ────────────────────────────────────────

NEW_13D_FORMS = {"SC 13D"}     # /A (amendment) 제외
NEW_13G_FORMS = {"SC 13G"}


def is_new_13d(form: str) -> bool:
    return form == "SC 13D"


def is_new_13g(form: str) -> bool:
    return form == "SC 13G"


def event_type_for(form: str) -> str | None:
    """신규 13D/13G 만 이벤트 · 그 외 (/A · 다른 form) None."""
    if is_new_13d(form):
        return "13D_new"
    if is_new_13g(form):
        return "13G_new"
    return None


# ─ B95 · 라벨 규칙 ──────────────────────────────────────────────

def label_from_filings(filings: list[dict], form25_date: str | None = None) -> str:
    """filings = [{form, date, item_codes(list · 8-K 만), meta_type(선택)}]
    규칙:
      - 8-K Item 1.03 (Bankruptcy or Receivership) → BANKRUPT (무조건)
      - DEFM14A / SC 14D9 → ACQUIRED (무조건)
      - 8-K Item 2.01 (Completion of Acquisition) → ACQUIRED (B107 게이트: form25_date 제공 시 |filing_date - form25_date| ≤ 120d 만 인정 · 매수측 자산 인수 오분류 차단 · form25_date None 이면 인정 안 함 · fail-closed)
    다중 매치 시: BANKRUPT > ACQUIRED > OTHER_DELISTED 우선.
    """
    from datetime import datetime

    f25: datetime | None = None
    if form25_date:
        try:
            f25 = datetime.strptime(form25_date, "%Y-%m-%d")
        except ValueError:
            f25 = None

    seen_bank = False
    seen_acq = False
    for f in filings:
        form = f.get("form", "")
        items = f.get("item_codes", []) or []
        if form == "8-K" and "1.03" in items:
            seen_bank = True
        if form in {"DEFM14A", "SC 14D9"}:
            seen_acq = True
        if form == "8-K" and "2.01" in items:
            if f25 is None:
                continue  # form25 부재 · Item 2.01 단독 증거 불인정 (fail-closed)
            try:
                fdate = datetime.strptime(f.get("date", ""), "%Y-%m-%d")
            except ValueError:
                continue
            if abs((fdate - f25).days) <= 120:
                seen_acq = True
    if seen_bank:
        return "BANKRUPT"
    if seen_acq:
        return "ACQUIRED"
    return "OTHER_DELISTED"


# ─ companyfacts · 최근접 분기 shares ─────────────────────────────

def nearest_shares_outstanding(facts: dict, event_date: str) -> dict | None:
    """companyfacts JSON 에서 이벤트일 최근접 분기 CommonStockSharesOutstanding.

    facts shape: {'facts': {'dei': {'EntityCommonStockSharesOutstanding':
        {'units': {'shares': [{'end': 'YYYY-MM-DD', 'val': N, 'accn': '...', 'fy':..., 'fp':...}, ...]}}}}}
    또는 us-gaap · CommonStockSharesOutstanding.

    반환: {'asof': 'YYYY-MM-DD', 'shares': int, 'accn': str, 'concept': str}
        · 데이터 부재 시 None.

    선택 규칙:
    1) event_date 이하 중 가장 가까운 end (past-preferred · 미래 참조 배제)
    2) past 부재 시 event_date 이후 중 가장 가까운 end (fallback · 표시)
    """
    from datetime import datetime

    candidates: list[dict] = []
    facts_root = facts.get("facts", {}) or {}
    for taxonomy in ("dei", "us-gaap"):
        for concept in ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"):
            node = facts_root.get(taxonomy, {}).get(concept, {})
            units = node.get("units", {}) or {}
            for unit, arr in units.items():
                if unit not in ("shares", "USD/shares"):
                    if unit != "shares":
                        continue
                for it in arr:
                    end = it.get("end")
                    val = it.get("val")
                    if not end or val is None:
                        continue
                    candidates.append({
                        "asof": end,
                        "shares": int(val),
                        "accn": it.get("accn", ""),
                        "concept": f"{taxonomy}:{concept}",
                    })

    if not candidates:
        return None

    ev = datetime.strptime(event_date, "%Y-%m-%d")
    past = [c for c in candidates if datetime.strptime(c["asof"], "%Y-%m-%d") <= ev]
    if past:
        past.sort(key=lambda c: datetime.strptime(c["asof"], "%Y-%m-%d"), reverse=True)
        return past[0]
    future = candidates[:]
    future.sort(key=lambda c: datetime.strptime(c["asof"], "%Y-%m-%d"))
    return future[0] if future else None


# ─ 헬퍼 · filings.recent zip → dict list ─────────────────────────

def zip_recent(recent: dict, wanted_forms: set[str] | None = None) -> list[dict]:
    """submissions.filings.recent 병렬 배열 → list of dicts (form/date/accession).

    wanted_forms 지정 시 필터. items 배열이 있으면 items_codes 파싱.
    """
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    accs = recent.get("accessionNumber", []) or []
    items_arr = recent.get("items", []) or []
    out: list[dict] = []
    for i, f in enumerate(forms):
        if wanted_forms is not None and f not in wanted_forms:
            continue
        item_codes: list[str] = []
        if i < len(items_arr):
            raw = items_arr[i] or ""
            # "1.03,2.01" 또는 "Item 1.03" 형태 대응
            for tok in str(raw).replace("Item ", "").split(","):
                t = tok.strip()
                if t:
                    item_codes.append(t)
        out.append({
            "form": f,
            "date": dates[i] if i < len(dates) else "",
            "accession": accs[i] if i < len(accs) else "",
            "item_codes": item_codes,
        })
    return out
