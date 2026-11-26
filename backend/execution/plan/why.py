"""1125-02 · 계획 상세 · 목록의 「이 종목이 계획에 오른 까닭」 표시 전용 값 (응답 때만 계산).

원칙 (계획서 3절 · Fable 11/25 막음 반영)
- 응답을 만들 때만 계산한다. `params_json` · APPROVAL_KEYS · `runtime_json` · `content_hash` · `revision` · 주문 경로에 쓰지 않는다.
- 자료는 기존 바이오 산출물을 읽기만 한다 (`backend/api/routes/biotech.py` 의 같은 읽기 함수 · 파일 수정 시각 캐시 `_cached`). 바깥 호출 0.
- 레이더 파일이 없거나 깨졌거나 계산 중 오류가 나면 호출한 쪽이 `why=None` 으로 끝낸다 (응답은 200).
- 낱말: 방향은 「후보 방향 · 자동 낱말 표시 · 확정 전」, 날짜는 「1차 완료 예정일 · 결과 발표일 아님 · 등록부 · 추정」. 명령문 · 신호 낱말(골든 · 데드 · 크로스 · 교차 · 정배열 · 역배열) 없음.
"""
from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .draft_sources import RAISE_DAYS, RAISE_FORMS, going_concern_flag, listing_flags, offering_flag

logger = logging.getLogger(__name__)

DIR_KO = {"positive": "긍정", "mixed": "혼재", "negative": "부정"}
PHASE_KO = {"EARLY_PHASE1": "초기 1상", "PHASE1": "1상", "PHASE1/PHASE2": "1·2상", "PHASE2": "2상",
            "PHASE2/PHASE3": "2·3상", "PHASE3": "3상", "PHASE4": "4상"}
# 8-K 항목 번호 → 쉬운 말 (모르는 번호는 「항목 N」 그대로)
ITEM_KO = {"1.01": "주요 계약 체결", "1.02": "주요 계약 종료", "2.01": "자산 인수·처분 완료", "2.02": "분기 실적",
           "2.03": "채무 발생", "3.01": "상장 요건 미달 통지", "3.02": "미등록 주식 판매", "3.03": "주주 권리 변경",
           "4.01": "회계 감사인 변경", "5.01": "회사 지배 변경", "5.02": "임원·이사 변경", "5.03": "정관 변경",
           "5.07": "주주 투표 결과", "7.01": "공시 의무 자료", "8.01": "기타 사건", "9.01": "첨부 서류"}
FACTORS = (
    ("expert", "전문가 신호", "5% 지분 신고 · 테마 소속 · 논문 · 임원 매수"),
    ("crowd", "대중 관심", "온라인 언급이 평소보다 늘었는지 (기준선이 모자라면 0.5)"),
    ("near", "예정일 임박", "다음 임상 일정까지 남은 날"),
    ("unnoticed", "덜 알려짐", "90일 주가가 바이오 지수(XBI)보다 덜 오름"),
    ("risk", "위험 감점", "나쁜 결과 · 증자 낱말이 있으면 감점"),
)
QUOTE_MAX = 240


def _fnum(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_file(bt, subrel: str, pattern: str) -> Optional[Path]:
    """filings 같은 폴더 조회 순서(RUNTIME > docs > backend/data)에서 처음 나오는 폴더의 가장 늦은 날짜 파일."""
    for d in bt._search_dirs(subrel):
        hits = sorted(d.glob(pattern)) if d.exists() else []
        if hits:
            return hits[-1]
    return None


@dataclass
class WhySources:
    """한 응답에서 쓰는 자료 묶음 · 파일은 한 번만 읽는다 (수정 시각 캐시)."""
    bt: Any
    radar_path: Optional[Path]
    radar_rows: list[dict[str, str]]
    by_ticker: dict[str, tuple[int, dict[str, str]]]
    notes: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)
    gc_store: Optional[dict] = None
    derived: dict = field(default_factory=dict)
    readouts: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)

    @property
    def asof(self) -> Optional[str]:
        m = re.search(r"radar_v1_3_(\d{4})(\d{2})(\d{2})\.csv$", self.radar_path.name) if self.radar_path else None
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def load_sources() -> WhySources:
    """레이더 파일이 없거나 깨졌으면 예외 (호출한 쪽이 why=None). 나머지 자료는 없으면 그 칸만 「자료 없음」."""
    from backend.api.routes import biotech as bt

    path = bt._latest_radar_csv()
    rows = bt._cached(path, _csv_rows) if path is not None else None
    if not rows:
        raise FileNotFoundError("레이더 파일 없음")
    by: dict[str, tuple[int, dict[str, str]]] = {}
    for i, r in enumerate(rows, 1):
        t = (r.get("ticker") or "").strip().upper()
        if t:
            by.setdefault(t, (i, r))
    src = WhySources(bt=bt, radar_path=path, radar_rows=rows, by_ticker=by)
    for name, fn in (("notes", lambda: bt._latest_candidate_notes()),
                     ("gc_store", lambda: bt._going_concern_store())):
        try:
            setattr(src, name, fn() or ({} if name == "notes" else None))
        except Exception as exc:  # noqa: BLE001 — 한 자료가 깨져도 다른 칸은 보인다
            logger.warning("[plan-why] %s 읽기 실패 · %s", name, exc.__class__.__name__)
    try:
        out_x, out_m = bt._excluded_lists(path)
        src.excluded = {e.ticker.upper(): e.status for e in [*out_x, *out_m]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-why] 제외 목록 읽기 실패 · %s", exc.__class__.__name__)
    try:
        dp = _first_file(bt, "filings", "filings_derived_????????.json")
        j = bt._cached(dp, _json_load) if dp is not None else None
        src.derived = (j or {}).get("rows") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-why] 서류 파생 읽기 실패 · %s", exc.__class__.__name__)
    try:
        base = bt._fr6c_runtime()
        if base is not None:
            ro = bt._cached(base / "readout_text.json", _json_load)
            src.readouts = (ro or {}).get("rows") or {}
            de = bt._cached(base / "decisions.json", _json_load)
            src.decisions = (de or {}).get("rows") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-why] 8-K 방향 읽기 실패 · %s", exc.__class__.__name__)
    return src


# ── 목록용 최소 칸 ───────────────────────────────────────────────────

def _trial(src: WhySources, sym: str) -> Optional[dict]:
    f = src.bt._note_fields(src.notes.get(sym, ""))
    if not f:
        return None
    ph = f["phase"]
    return {"nct_id": f["nct_id"], "phase": ph, "phase_ko": PHASE_KO.get(ph, "단계 미확인"), "pcd": f["event_date"],
            "days_to": f["days_to"], "url": f"https://clinicaltrials.gov/study/{f['nct_id']}",
            "note": "1차 완료 예정일 · 결과 발표일 아님 · 등록부 · 추정"}


def brief(src: WhySources, symbol: str) -> dict:
    """목록 카드 한 줄용 · 레이더 순위/전체 수 · 자료 날짜 · 다음 임상 1차 완료 예정일 (방향은 넣지 않는다)."""
    sym = symbol.upper()
    hit = src.by_ticker.get(sym)
    t = _trial(src, sym)
    return {"rank": hit[0] if hit else None, "total": len(src.radar_rows), "asof": src.asof,
            "pcd": t["pcd"] if t else None}


# ── 1125-02 추가 · 레이더 카드와 같은 시험 상세 · 회사 · 테마 · 언급 · 내부자 (읽기만 · 칸마다 실패하면 그 칸만 비움) ──

def _safe(label: str, fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — 한 칸이 깨져도 why 전체는 산다
        logger.warning("[plan-why] %s 계산 실패 · %s", label, exc.__class__.__name__)
        return None


def _trial_detail(src: WhySources, trial: Optional[dict]) -> Optional[dict]:
    """레이더 카드 문장의 재료 (AACT 시험 상세) · 없으면 None."""
    if not trial:
        return None
    return src.bt._trial_display(trial["nct_id"]) or None


def _company(src: WhySources, sym: str, row: Optional[dict]) -> Optional[dict]:
    name = ((row or {}).get("name") or "").strip()
    bucket, asof = src.bt._mcap_display(sym, (row or {}).get("mcap", ""))
    if not name and not bucket:
        return None
    shares = src.bt._mcap_shares_carried(sym) if asof else ""
    return {"name": name[:40], "mcap_bucket": bucket, "mcap_asof": asof, "mcap_shares_asof": shares}


def _mention(src: WhySources, sym: str) -> Optional[dict]:
    """커뮤니티 언급 단계 (가장 늦은 community_confirm 파일 · 공개 자료)."""
    path = _first_file(src.bt, "community_daily", "community_confirm_????????.csv")
    rows = src.bt._cached(path, _csv_rows) if path is not None else None
    for r in rows or []:
        if (r.get("ticker") or "").upper() == sym:
            n = _fnum(r.get("st_baseline_n"))
            return {"stage": r.get("stage") or "", "baseline_n": int(n) if n is not None else None,
                    "st_24h": int(_fnum(r.get("st_24h")) or 0), "mult": str(r.get("st_baseline_mult") or ""),
                    "baseline_mean": _fnum(r.get("st_baseline_mean"))}
    return None


def _insider(src: WhySources, sym: str, limit: int = 3) -> list[dict]:
    """내부자 Form 4 최근 거래 (h65 일별 표 · 공개 SEC 신고) · 가장 늦은 신고 순 · 없으면 빈 목록."""
    bt = src.bt
    path = None
    for base in [d for d in (bt.DATA_DIR_RUNTIME, bt.DATA_DIR_DOCS, bt.DATA_DIR) if d is not None]:
        if base.exists():
            hits = sorted(base.glob("h65_form4_daily_table_*.csv"))
            if hits:
                path = hits[-1]
                break
    rows = bt._cached(path, _csv_rows) if path is not None else None
    if not rows:
        return []
    cik2tk = bt._cik_ticker_map()
    out = []
    for r in rows:
        cik10 = (r.get("issuer_cik") or "").zfill(10)
        if (r.get("issuer_ticker") or cik2tk.get(cik10, "")).upper() != sym:
            continue
        out.append({"shares": _fnum(r.get("shares")), "price": _fnum(r.get("price_per_share")),
                    "tx_date": r.get("tx_date") or "", "filing_date": r.get("filing_date") or "",
                    "filer_type": r.get("filer_type") or ""})
    out.sort(key=lambda x: x["filing_date"], reverse=True)
    return out[:limit]


# ── 상세 ─────────────────────────────────────────────────────────────

def _items_text(items: str) -> str:
    parts = [p.strip() for p in (items or "").split(",") if p.strip()]
    words = [ITEM_KO.get(p, f"항목 {p}") for p in parts if p != "9.01"] or [ITEM_KO.get(p, f"항목 {p}") for p in parts]
    return " · ".join(words)


def _sec_url(cik: str, acc: str) -> str:
    try:
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/"
    except (TypeError, ValueError):
        return ""


def _eight_k(src: WhySources, sym: str, cik: str, derived_row: Optional[dict]) -> Optional[dict]:
    best_acc, best = None, None
    for acc, r in src.readouts.items():
        if (r.get("ticker") or "").upper() != sym:
            continue
        if best is None or (r.get("accept_et") or "") > (best.get("accept_et") or ""):
            best_acc, best = acc, r
    last = (derived_row or {}).get("last_8k") or None
    if last and (best is None or (last.get("acceptance_et") or "") > (best.get("accept_et") or "")) \
            and last.get("accessionNumber") != best_acc:
        # 서류 목록의 마지막 8-K 가 방향 표시 파일보다 늦으면 방향 없이 날짜와 서류 종류만 보인다
        return {"date": (last.get("acceptance_et") or last.get("filingDate") or "")[:10],
                "items": last.get("items") or "", "items_text": _items_text(last.get("items") or ""),
                "direction": None, "direction_ko": None, "quote": None, "keywords": [],
                "accession": last.get("accessionNumber"), "url": _sec_url(cik, last.get("accessionNumber") or ""),
                "decision": None, "has_body_tag": False}
    if best is None:
        return None
    cand = best.get("candidate_direction") or ""
    dec = src.decisions.get(best_acc)
    decision = None
    if dec:
        decision = {"clinical": bool(dec.get("clinical")), "direction": dec.get("direction"),
                    "direction_ko": DIR_KO.get(dec.get("direction") or "")}
    quote = (best.get("quote") or "").strip() or None
    if quote and len(quote) > QUOTE_MAX:
        quote = quote[:QUOTE_MAX].rstrip() + " …"
    return {"date": (best.get("accept_et") or "")[:10], "items": best.get("items") or "",
            "items_text": _items_text(best.get("items") or ""),
            "direction": cand if cand in DIR_KO else None, "direction_ko": DIR_KO.get(cand),
            "quote": quote, "keywords": list(best.get("keywords") or [])[:6], "accession": best_acc,
            "url": _sec_url(best.get("cik") or cik, best_acc), "decision": decision, "has_body_tag": True}


def _md(ymd: Optional[str]) -> str:
    return f"{ymd[5:7]}/{ymd[8:10]}" if ymd and len(ymd) >= 10 else ""


def _risks(src: WhySources, sym: str, row: Optional[dict], cik: str, today: date) -> list[dict]:
    bt = src.bt
    out: list[dict] = []
    # 계속기업 의문
    gc = bt._going_concern_for(src.gc_store, cik) if cik else None
    flag = going_concern_flag(gc)
    if gc is None:
        out.append({"key": "going_concern", "label": "계속기업 의문 문구", "value": "확인 못 함", "tone": "none", "note": "자료 없음"})
    else:
        if flag is True:
            val, tone = "있음", "bad"
        elif flag is False:
            val, tone = "없음", "ok"
        elif gc.state == "present" and gc.hypothetical_only:
            val, tone = "가정 문장뿐", "mid"
        else:
            val, tone = {"alleviated": ("해소 문구 있음", "mid"), "past_only": ("과거 기록에만", "mid"),
                         "unclear": ("판정 못 함", "none")}.get(gc.state, ("확인 못 함", "none"))
        note = " ".join(x for x in (gc.form, _md(gc.filed)) if x)
        if gc.stale or gc.updates_stopped:
            note += " · 자료가 낡았을 수 있음"
        out.append({"key": "going_concern", "label": "계속기업 의문 문구", "value": val, "tone": tone, "note": note.strip(),
                    "url": gc.url or None})
    # 파생 서류
    key = str(int(cik)).zfill(10) if cik.isdigit() else ""
    d = src.derived.get(key) if key else None
    of = offering_flag(d, today) if d is not None else None
    if of is None:
        out.append({"key": "offering_30d", "label": "최근 30일 증자 서류", "value": "확인 못 함", "tone": "none", "note": "자료 없음"})
    elif of:
        since = (today - timedelta(days=RAISE_DAYS)).isoformat()
        hits = [o for o in d.get("offerings_12m") or [] if o.get("form") in RAISE_FORMS and (o.get("filingDate") or "") >= since]
        note = " · ".join(f"{o.get('form')} {_md(o.get('filingDate'))}" for o in hits[:3])
        out.append({"key": "offering_30d", "label": "최근 30일 증자 서류", "value": "있음", "tone": "bad", "note": note})
    else:
        out.append({"key": "offering_30d", "label": "최근 30일 증자 서류", "value": "없음", "tone": "ok", "note": ""})
    s3 = (d or {}).get("s3") or {}
    if d is None or s3.get("effective") is None:
        out.append({"key": "s3", "label": "증자에 쓸 수 있는 서류(S-3)", "value": "확인 못 함", "tone": "none", "note": s3.get("reason") or "자료 없음"})
    elif s3.get("effective"):
        exp = s3.get("expires") or ""
        out.append({"key": "s3", "label": "증자에 쓸 수 있는 서류(S-3)", "value": "유효", "tone": "mid",
                    "note": f"{exp}까지" if exp else ""})
    else:
        out.append({"key": "s3", "label": "증자에 쓸 수 있는 서류(S-3)", "value": "없음", "tone": "ok", "note": ""})
    atm = (d or {}).get("atm")
    basis = (d or {}).get("atm_basis") or {}
    if d is not None and isinstance(atm, str) and atm.startswith("확인"):
        out.append({"key": "atm", "label": "시장가 분할 증자(ATM)", "value": "확인됨", "tone": "bad",
                    "note": f"424B5 {_md(basis.get('filingDate'))} 표지 규칙 · 잔여 한도 미확인".strip()})
    else:
        out.append({"key": "atm", "label": "시장가 분할 증자(ATM)", "value": "확인 못 함", "tone": "mid" if d is not None else "none",
                    "note": "표지 규칙에 걸린 서류 없음 · 없다는 뜻은 아님" if d is not None else "자료 없음"})
    # 상장 상태
    status = (row or {}).get("status") or src.excluded.get(sym, "")
    checked = ((row or {}).get("status_checked") or ("Y" if sym in src.excluded else "N")) != "N"
    fl = listing_flags(status, checked)
    if fl["delisted"]:
        lv, lt = "상장폐지", "bad"
    elif fl["acquired"]:
        lv, lt = "인수 완료", "bad"
    elif fl["merger_pending"]:
        lv, lt = "합병 진행", "bad"
    elif fl["delisted"] is None:
        lv, lt = "확인 못 함", "none"
    else:
        lv, lt = "정상", "ok"
    out.append({"key": "listing", "label": "상장 상태", "value": lv, "tone": lt, "note": ""})
    out.append({"key": "halt", "label": "거래 정지 · 최저가 미달", "value": "자료 없음", "tone": "none",
                "note": "저장소에 이 판정이 없습니다"})
    return out


def detail(src: WhySources, symbol: str, *, now: Optional[datetime] = None) -> dict:
    sym = symbol.upper()
    today = (now or datetime.utcnow()).date()
    hit = src.by_ticker.get(sym)
    row = hit[1] if hit else None
    radar = None
    if hit:
        radar = {"rank": hit[0], "total": len(src.radar_rows), "score": _fnum(row.get("score")),
                 "factors": [{"key": k, "label": lab, "value": _fnum(row.get(k)), "meaning": mean} for k, lab, mean in FACTORS],
                 "why_easy": (row.get("why_easy") or "")[:100] or None}
    readout_row = next((r for r in src.readouts.values() if (r.get("ticker") or "").upper() == sym), None)
    cik = ((row or {}).get("cik") or (readout_row or {}).get("cik") or "").strip()
    key = str(int(cik)).zfill(10) if cik.isdigit() else ""
    trial = _trial(src, sym)
    return {"asof": src.asof, "in_radar": hit is not None, "radar": radar,
            "eight_k": _eight_k(src, sym, cik, src.derived.get(key) if key else None),
            "trial": trial, "trial_detail": _safe("시험 상세", lambda: _trial_detail(src, trial)),
            "theme": _safe("테마 순위", lambda: src.bt._theme_rank(sym) or None),
            "company": _safe("회사", lambda: _company(src, sym, row)),
            "mention": _safe("언급 단계", lambda: _mention(src, sym)),
            "insider": _safe("내부자 신고", lambda: _insider(src, sym)) or [], "risks": _risks(src, sym, row, cik, today)}
