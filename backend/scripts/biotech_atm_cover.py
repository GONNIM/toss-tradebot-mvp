"""P3a-2 ③ · 424B5 표지 규칙 ATM (시장가 분할 발행) 확인 판정 (PRD v0.6 FR-6a · 확인 판정 전용).

규칙 (제안 파일 docs/plans/biotech/data/proposals/atm_cover_rule_20261004.md 2절 · 고정 · 넓히지 않음):
  본문 앞 6,000자에 (A) 판매 대리인 계약 문구가 있고 (B) "Up to $" 금액이 있고 (C) 주식 수 공모 문구가 없으면
  "확인(표지 규칙)". 그 밖은 모두 "미확인". "없음" 은 만들지 않는다 (놓침 유형이 있음).
저장 값: 판정 · A · B · C 검출 여부 · 검출 문구 앞뒤 60자 인용 · 424B5 접수번호 · 제출일.

요청 (SEC · 헤더 = biotech_sec_common.build_client 단일 상수 · 장부 범주 "atm_cover" · 403 · 429 즉시 중단):
  - 백필 1회 (Fable 승인 PRD 12절): 최근 12개월 424B5 중 받지 않은 것 · 상한 80 · 하루 300 장부 안
    · 실행 직전 장부 실측 조건 (P3a-3 ⓪ · 요일 금지 대체): 서버 장부 오늘 파일 (ssh 조회 전용 · 없으면 0) + 로컬 장부 오늘 합계
      + 이번 실행 예정 건수 ≤ 300 일 때만 실행. 둘 중 하나라도 읽지 못하면 실행하지 않는다.
      결과는 저장소 시드 파일 (atm_cover_seed.json) 로 커밋한다.
  - 일일 (submissions 단계 안): 제출일이 최근 7일 안이고 아직 판정하지 않은 424B5 표지 · 하루 상한 10.
판정 저장: 시드 (저장소 · docs/plans/biotech/data/atm_cover_seed.json) + 런타임 (<RUNTIME>/filings/atm_cover.json).

실행 (백필 · 로컬 1회):
    python -m backend.scripts.biotech_atm_cover backfill --derived <filings_derived_YYYYMMDD.json>
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import html
import json
import logging
import re
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_sec_common import SEC_DAILY_CAP, SecBlockedError, SecDailyLedger, build_client, sec_get_text

LOG = logging.getLogger("biotech_atm_cover")

HEAD = 6000
QUOTE = 60
A = re.compile(r"\bsales agreement\b|\bsales agents?\b|equity distribution agreement|open market sale agreement"
               r"|at[- ]the[- ]market (?:issuance |offering )?sales agreement|controlled equity offering", re.I)
B = re.compile(r"\bup to \$\s?\d[\d,.]*(?:\s*(?:million|billion))?", re.I)
C = re.compile(r"\b(?:we are|are) (?:offering|selling)\s+(?:an aggregate of\s+)?\d{1,3}(?:,\d{3})+\s+(?:shares|common shares)\b",
               re.I)
CONFIRMED = "확인(표지 규칙)"
UNKNOWN = "미확인"
FORM = "424B5"
LEDGER_CAT = "atm_cover"
BACKFILL_MAX = 80
SERVER_SSH = "root@optimus8.cafe24.com"   # P3a-3 ⓪ · 서버 장부 조회 전용 (cat) · 쓰기 · 실행 없음
SERVER_LEDGER = "/root/toss-tradebot-mvp/var/biotech/sec_usage/sec_usage_{day}.json"
DAILY_MAX = 10
NEW_DAYS = 7
YEAR_DAYS = 365
STORE_NAME = "atm_cover.json"
SEED_NAME = "atm_cover_seed.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"
_BAD = re.compile(r"[\x00-\x1f]|[\ud800-\udfff]")


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def plain(t: str) -> str:
    """HTML → 글자 · 태그 제거 · 엔티티 해제 · 제어 문자 · 단독 surrogate 제거 · 공백 하나로."""
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", _BAD.sub(" ", t)).strip()


def judge(text: str) -> dict:
    """원문 (HTML) → 판정 · 검출 여부 · 인용 (검출 위치 앞뒤 60자)."""
    h = plain(text)[:HEAD]
    m = {k: rx.search(h) for k, rx in (("A", A), ("B", B), ("C", C))}
    q = {f"{k}_quote": (h[max(0, v.start() - QUOTE):v.end() + QUOTE] if v else None) for k, v in m.items()}
    ok = bool(m["A"] and m["B"] and not m["C"])
    return {"result": CONFIRMED if ok else UNKNOWN, **{k: bool(v) for k, v in m.items()}, **q, "head_len": len(h)}


def doc_url(cik: str, accn: str, doc: str) -> str:
    return DOC_URL.format(cik=int(cik), accn=accn.replace("-", ""), doc=doc)


def seed_path() -> Path:
    return _P.DATA_DIR_DOCS / SEED_NAME


def store_path() -> Path:
    return _P.out_dir("filings") / STORE_NAME


def _rows(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("rows", {})
    except (ValueError, OSError):
        LOG.warning("ATM 판정 파일 읽기 실패 · %s", p)
        return {}


def load_judged() -> dict[str, dict]:
    """접수번호 → 판정 · 시드 (저장소) 위에 런타임 판정을 덮는다."""
    return {**_rows(seed_path()), **_rows(store_path())}


def save_rows(p: Path, rows: dict, meta: dict | None = None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({**(meta or {}), "rule": {"A": A.pattern, "B": B.pattern, "C": C.pattern, "head_chars": HEAD},
                             "rows": dict(sorted(rows.items()))}, ensure_ascii=False, indent=1))


def items_from_derived(derived: dict[str, dict]) -> list[dict]:
    """파생 제출 목록 (CIK → 값) → 최근 12개월 424B5 (cik · ticker · 접수번호 · 제출일 · 문서)."""
    out = []
    for cik, d in derived.items():
        for o in d.get("offerings_12m") or []:
            if o["form"] == FORM:
                out.append({"cik": cik, "ticker": d.get("ticker") or "", "accessionNumber": o["accessionNumber"],
                            "filingDate": o["filingDate"], "primaryDocument": o.get("primaryDocument") or ""})
    return sorted(out, key=lambda x: (x["filingDate"], x["accessionNumber"]))


def fetch_judge(items: list[dict], get_text: Callable[[str], dict], ledger: SecDailyLedger, limit: int,
                source: str, today: date) -> dict:
    """표지 원문을 받아 판정 · 보내기 직전에 장부에 더함 · 403 · 429 즉시 중단 · 하루 300 에 닿으면 멈춤."""
    rows, errors, sent, blocked, capped = {}, [], 0, None, 0
    for it in items:
        if sent >= limit:
            break
        if ledger.total() >= SEC_DAILY_CAP:
            capped = len(items) - sent
            break
        if not it.get("primaryDocument"):
            errors.append({"accessionNumber": it["accessionNumber"], "error": "primaryDocument 없음"})
            continue
        ledger.add(LEDGER_CAT)
        ledger.save()
        sent += 1
        try:
            r = get_text(doc_url(it["cik"], it["accessionNumber"], it["primaryDocument"]))
        except SecBlockedError as e:
            blocked = str(e)
            break
        if r.get("status") == 429:
            blocked = "SEC HTTP 429"
            break
        if r.get("status") != 200 or not r.get("text"):
            errors.append({"accessionNumber": it["accessionNumber"], "status": r.get("status")})
            continue
        rows[it["accessionNumber"]] = {"ticker": it["ticker"], "cik": it["cik"], "filingDate": it["filingDate"],
                                       "primaryDocument": it["primaryDocument"], **judge(r["text"]),
                                       "source": source, "judged_on": today.isoformat()}
    if blocked:
        LOG.error("%s · ATM 표지 즉시 중단 (보낸 요청 %d)", blocked, sent)
    return {"rows": rows, "sent": sent, "blocked": blocked, "capped": capped, "errors": errors}


def company_atm(offerings: list[dict], judged: dict[str, dict]) -> dict:
    """한 회사의 최근 12개월 424B5 판정 → "확인(표지 규칙)" (가장 최근 양성 · 설정일 · 인용) 또는 "미확인"."""
    accns = [o["accessionNumber"] for o in offerings if o["form"] == FORM]
    pos = sorted((judged[a] | {"accessionNumber": a} for a in accns if judged.get(a, {}).get("result") == CONFIRMED),
                 key=lambda r: r["filingDate"], reverse=True)
    base = {"judged": sum(1 for a in accns if a in judged), "424b5_12m": len(accns)}
    if not pos:
        return {"status": UNKNOWN, **base}
    p = pos[0]
    return {"status": CONFIRMED, "accessionNumber": p["accessionNumber"], "filingDate": p["filingDate"],
            "A_quote": p["A_quote"], "B_quote": p["B_quote"], "remaining": "잔여 한도 미확인", **base}


def judge_new(derived: dict[str, dict], today: date, get_text: Callable[[str], dict] | None,
              ledger: SecDailyLedger) -> dict:
    """일일 · 최근 7일 안에 제출됐고 아직 판정하지 않은 424B5 표지 · 하루 상한 10 · 판정 뒤 회사별 ATM 값."""
    judged = load_judged()
    lo = (today - timedelta(days=NEW_DAYS)).isoformat()
    new = [it for it in items_from_derived(derived) if it["filingDate"] >= lo and it["accessionNumber"] not in judged]
    res = {"rows": {}, "sent": 0, "blocked": None, "capped": 0, "errors": []}
    if new and get_text is not None:
        res = fetch_judge(new, get_text, ledger, DAILY_MAX, "daily", today)
        if res["rows"]:
            store = _rows(store_path())
            store.update(res["rows"])
            save_rows(store_path(), store)
            judged.update(res["rows"])
    for d in derived.values():
        a = company_atm(d.get("offerings_12m") or [], judged)
        d["atm"], d["atm_basis"] = a["status"], a
    return {"new": len(new), **{k: res[k] for k in ("sent", "blocked", "capped")},
            "positive": sum(1 for r in res["rows"].values() if r["result"] == CONFIRMED)}


def _ledger_sum(text: str) -> int:
    return sum(int(v) for v in (json.loads(text).get("counts") or {}).values())


def read_server_ledger_total(day: str, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> int | None:
    """P3a-3 ⓪ · 서버 장부 오늘 합계 · ssh 로 파일을 읽기만 한다 · 파일이 없으면 0 · 읽지 못하면 None."""
    path = SERVER_LEDGER.format(day=day)
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SERVER_SSH,
           f"if [ -f {path} ]; then cat {path}; else echo NO_FILE; fi"]
    try:
        r = run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    out = (r.stdout or "").strip()
    if out == "NO_FILE":
        return 0
    try:
        return _ledger_sum(out)
    except (ValueError, TypeError, AttributeError):
        return None


def read_local_ledger_total(day: str) -> int | None:
    """P3a-3 ⓪ · 로컬 장부 오늘 합계 · 파일이 없으면 0 · 읽지 못하면 None."""
    p = _P.out_dir("sec_usage") / f"sec_usage_{day}.json"
    if not p.exists():
        return 0
    try:
        return _ledger_sum(p.read_text())
    except (ValueError, TypeError, AttributeError, OSError):
        return None


def ledger_gate(server_total: int | None, local_total: int | None, planned: int) -> tuple[bool, str]:
    """P3a-3 ⓪ · 서버 + 로컬 + 예정 ≤ 300 일 때만 실행 · 하나라도 읽지 못하면 실행하지 않음."""
    if server_total is None:
        return False, "서버 장부를 읽지 못함 · 실행하지 않음"
    if local_total is None:
        return False, "로컬 장부를 읽지 못함 · 실행하지 않음"
    total = server_total + local_total + planned
    msg = f"서버 {server_total} + 로컬 {local_total} + 예정 {planned} = {total} (상한 {SEC_DAILY_CAP})"
    return total <= SEC_DAILY_CAP, msg + (" · 실행" if total <= SEC_DAILY_CAP else " · 초과 · 실행하지 않음")


def backfill(derived: dict[str, dict], today: date, get_text: Callable[[str], dict], ledger: SecDailyLedger,
             already: set[str], gate: Callable[[int], tuple[bool, str]] | None = None) -> dict:
    """1회 백필 · 최근 12개월 424B5 중 시드 · 런타임 · already (P2 · P3a 에서 받은 원문) 에 없는 것 · 상한 80.

    gate (P3a-3 ⓪) · 대상 건수를 받아 (실행 여부, 설명) · 거부면 요청 0 으로 끝냄."""
    judged = load_judged()
    lo = (today - timedelta(days=YEAR_DAYS)).isoformat()
    todo = [it for it in items_from_derived(derived)
            if it["filingDate"] >= lo and it["accessionNumber"] not in judged and it["accessionNumber"] not in already]
    if len(todo) > BACKFILL_MAX:
        raise SystemExit(f"백필 대상 {len(todo)}건 > 승인 상한 {BACKFILL_MAX} · 실행하지 않음")
    if gate is not None:
        ok, why = gate(len(todo))
        LOG.info("SEC 장부 조건 · %s", why)
        if not ok:
            raise SystemExit(f"SEC 장부 조건 불충족 · {why}")
    res = fetch_judge(todo, get_text, ledger, BACKFILL_MAX, f"backfill_{today:%Y%m%d}", today)
    seed = _rows(seed_path())
    seed.update(res["rows"])
    save_rows(seed_path(), seed, {"note": "P3a-2 ③ 424B5 표지 판정 시드 (백필 · 이미 받은 원문)"})
    return {"todo": len(todo), **{k: res[k] for k in ("sent", "blocked", "capped", "errors")},
            "judged": len(res["rows"]), "positive": sum(1 for r in res["rows"].values() if r["result"] == CONFIRMED)}


def primary_from_sgml(t: str) -> str:
    """전체 제출 원문 (.txt · SGML) 이면 첫 문서 (= primaryDocument) 의 <TEXT> 만 · 그 밖은 그대로."""
    if not t.lstrip().startswith("<SEC-DOCUMENT>"):
        return t
    m = re.search(r"(?is)<TEXT>(.*?)</TEXT>", t)
    return m.group(1) if m else t


def judge_local(texts: dict[str, str], items: list[dict], source: str, today: date) -> dict:
    """이미 받은 원문 (요청 0) 판정 → 시드에 더함."""
    by = {it["accessionNumber"]: it for it in items}
    rows = {a: {"ticker": by[a]["ticker"], "cik": by[a]["cik"], "filingDate": by[a]["filingDate"],
                "primaryDocument": by[a]["primaryDocument"], **judge(t), "source": source, "judged_on": today.isoformat()}
            for a, t in texts.items() if a in by}
    seed = _rows(seed_path())
    seed.update(rows)
    save_rows(seed_path(), seed, {"note": "P3a-2 ③ 424B5 표지 판정 시드 (백필 · 이미 받은 원문)"})
    return rows


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backfill", "local"])
    ap.add_argument("--derived", required=True, help="filings_derived_<날짜>.json")
    ap.add_argument("--texts", help="local: 이미 받은 원문 폴더 (쉼표 구분 · <접수번호>.htm | .txt)")
    ap.add_argument("--already", help="backfill: 이미 받은 원문 폴더 (쉼표 구분 · 이 접수번호는 요청하지 않음)")
    a = ap.parse_args()
    derived = json.loads(Path(a.derived).read_text())["rows"]
    today = _kst_today()
    if a.mode == "local":
        texts = {f.stem: primary_from_sgml(f.read_text(errors="replace"))
                 for d in a.texts.split(",") for f in sorted(Path(d).iterdir()) if f.suffix in (".htm", ".txt")}
        rows = judge_local(texts, items_from_derived(derived), "p2_p3a_existing", today)
        print(json.dumps({"judged": len(rows), "positive": sum(r["result"] == CONFIRMED for r in rows.values())}))
        return
    already = {f.stem for d in (a.already or "").split(",") if d for f in Path(d).iterdir()}
    day = f"{today:%Y%m%d}"
    ledger = SecDailyLedger.load(day)

    def gate(n: int) -> tuple[bool, str]:
        return ledger_gate(read_server_ledger_total(day), read_local_ledger_total(day), n)

    with build_client() as client:
        out = backfill(derived, today, lambda u: sec_get_text(client, u), ledger, already, gate)
    print(json.dumps({**out, "ledger_total": ledger.total(), "ledger": ledger.counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
