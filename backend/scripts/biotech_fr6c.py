"""FR-6c 과거 발표 반응 분포 · 봉인 설계 `docs/plans/biotech/design/fr6c_design_v1.md` (SHA-256 e1cd8490…) 구현.

P4-1 · 가격 고정 (설계 10절 3 · 요청 0):
  - 봉인 표본 목록 (`fr6c_retro_sample_v1.csv` · SHA-256 ecc855dc…) 의 기준일 · 반응일 종가를 가격 기록
    (<RUNTIME>/prices/iex_daily_history.csv) 에서 채워 <RUNTIME>/fr6c/retro_prices_v1.csv 에 한 번만 쓴다.
  - 표본 목록을 읽을 때마다 SHA-256 을 다시 계산한다 · 봉인값과 다르면 멈춘다 (아무 파일도 쓰지 않음).
  - 표본의 base_date · reaction_date 를 `biotech_reaction_day.reaction()` 으로 다시 계산한다 · 하나라도 다르면 멈춘다.
  - 종목 기준가 · 종목 반응가 · XBI 기준가 · XBI 반응가 중 하나라도 없으면 "가격 없음" (설계 3절 60행) · 칸 n 에서 뺀다.
  - 이미 retro_prices_v1.csv 가 있으면 다시 쓰지 않는다 (가격 고정 · 전향 표본은 다른 파일).
  - price_source: 가격 기록에는 출처 열이 없다. 백필 전 기록은 2026-06-26 에 시작했다 (P2b 측정 q6 server_hist_first_date).
    그래서 종목 기록이 이 날보다 먼저 시작하면 12개월 백필 종목이고, 백필 끝 (2026-10-06) 이하 날짜는 백필 일봉 값이다
    (백필이 같은 행을 덮어씀 · biotech_mcap_daily.backfill_prices). 나머지는 IEX 일괄 종가다.
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import hashlib
import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_h6_collect_prices import load_usage
from backend.scripts.biotech_mcap_daily import FR6C_SAMPLE, FR6C_SAMPLE_SHA256, history_path, load_history
from backend.scripts.biotech_reaction_day import reaction

LOG = logging.getLogger("biotech_fr6c")

FR6C_DESIGN = _P.PROJECT_ROOT / "docs" / "plans" / "biotech" / "design" / "fr6c_design_v1.md"
FR6C_DESIGN_SHA256 = "e1cd8490daffa7c829bd4874f34f467f848e4737219db034541debdaac7c7e42"   # 봉인값 (2026-10-06 · PRD 20절)
XBI = "XBI"
PRICE_COLS = ("price_base", "price_reaction", "xbi_base", "xbi_reaction")
IEX_HISTORY_START = "2026-06-26"    # 백필 전 가격 기록 첫 날 (P2b measure_result.json q6)
BACKFILL_LAST = "2026-10-06"        # 10/7 백필 마지막 일봉 (end=10/07 KST 오전) · 10/8 · 10/9 분은 그 뒤까지
SRC_BACKFILL = "tiingo_daily_backfill"
SRC_IEX = "iex_tngoLast"


class SealError(RuntimeError):
    """봉인 파일 해시 불일치 · 반응일 재계산 불일치 · 이 오류가 나면 아무것도 쓰지 않는다."""


def _kst_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def out_path() -> Path:
    return _P.out_dir("fr6c") / "retro_prices_v1.csv"


def meta_path() -> Path:
    return _P.out_dir("fr6c") / "retro_prices_v1.meta.json"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_sealed(path: Path, expected: str, what: str) -> bytes:
    """봉인 파일을 읽고 SHA-256 을 다시 계산 · 다르면 멈춤 (로그 · SealError)."""
    if not path.exists():
        LOG.error("FR-6c %s 없음 · %s · 멈춤", what, path)
        raise SealError(f"{what} 없음")
    raw = path.read_bytes()
    got = sha256_bytes(raw)
    if got != expected:
        LOG.error("FR-6c %s SHA-256 불일치 · 봉인 %s · 지금 %s · 멈춤", what, expected, got)
        raise SealError(f"{what} SHA-256 불일치")
    return raw


def sealed_sample(path: Path | None = None, expected: str | None = None) -> list[dict]:
    raw = read_sealed(path or FR6C_SAMPLE, expected or FR6C_SAMPLE_SHA256, "봉인 표본 목록")
    return list(csv.DictReader(raw.decode("utf-8").splitlines()))


def check_reaction_days(rows: list[dict]) -> None:
    """봉인 목록의 base_date · reaction_date 를 reaction() 으로 다시 계산 · 하나라도 다르면 멈춤."""
    bad = []
    for r in rows:
        re_ = reaction(r["accept_et"])
        if (re_["base_date"], re_["reaction_date"]) != (r["base_date"], r["reaction_date"]):
            bad.append((r["accession"], r["base_date"], r["reaction_date"], re_["base_date"], re_["reaction_date"]))
    if bad:
        LOG.error("FR-6c 반응일 재계산 불일치 %d건 · 첫 건 %s · 멈춤", len(bad), bad[0])
        raise SealError(f"반응일 재계산 불일치 {len(bad)}건")


def price_source(ticker: str, d: str, starts: dict[str, str], short: dict[str, str] | None = None) -> str:
    """가격 한 칸의 출처 (모듈 설명의 규칙)."""
    backfilled = starts.get(ticker, "9") < IEX_HISTORY_START or ticker in (short or {})
    if d < IEX_HISTORY_START or (backfilled and d <= BACKFILL_LAST):
        return SRC_BACKFILL
    return SRC_IEX


def fill_prices(rows: list[dict], hist: dict[tuple[str, str], float],
                short: dict[str, str] | None = None) -> tuple[list[dict], list[str], Counter]:
    """봉인 목록 열 + 가격 네 칸 + price_source · 가격 없음 accession 목록 · 출처 건수 (칸 단위)."""
    starts: dict[str, str] = {}
    for tk, d in hist:
        if d < starts.get(tk, "9"):
            starts[tk] = d
    out, missing, src = [], [], Counter()
    for r in rows:
        tk, b, x = r["ticker"], r["base_date"], r["reaction_date"]
        cells = {"price_base": (tk, b), "price_reaction": (tk, x), "xbi_base": (XBI, b), "xbi_reaction": (XBI, x)}
        row = dict(r)
        srcs = []
        for col, key in cells.items():
            v = hist.get(key)
            row[col] = "" if v is None else repr(v)
            if v is not None:
                s = price_source(key[0], key[1], starts, short)
                srcs.append(s)
                src[s] += 1
        if any(row[c] == "" for c in PRICE_COLS):
            missing.append(r["accession"])
            row["price_source"] = "가격 없음"
        else:
            row["price_source"] = "+".join(sorted(set(srcs)))
        out.append(row)
    return out, missing, src


def _backfill_dates(today: date) -> dict[str, list[str]]:
    """Tiingo 장부의 시간별 기록에서 백필 실행일 (WP75-backfill · WP75-backfill-fr6c)."""
    out: dict[str, set[str]] = {}
    m = date(2026, 10, 1)
    while m <= today:
        for hour, by in (load_usage(f"{m:%Y%m}").get("hourly") or {}).items():
            for k in by:
                if k.startswith("WP75-backfill"):
                    out.setdefault(k, set()).add(hour[:10])
        m = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {k: sorted(v) for k, v in sorted(out.items())}


def _short() -> dict[str, str]:
    p = _P.out_dir("prices") / "backfill_short.json"
    return json.loads(p.read_text()) if p.exists() else {}


def fix_prices(today: date | None = None) -> dict:
    """P4-1 · retro_prices_v1.csv 를 한 번만 만든다 · 이미 있으면 해시만 다시 계산해 보고."""
    today = today or _kst_today()
    out = out_path()
    if out.exists():
        h = sha256_bytes(out.read_bytes())
        LOG.info("FR-6c 가격 고정됨 · %s · SHA-256 %s · 다시 쓰지 않음", out.name, h)
        return {"status": "fixed", "sha256": h}
    rows = sealed_sample()
    read_sealed(FR6C_DESIGN, FR6C_DESIGN_SHA256, "봉인 설계 파일")
    check_reaction_days(rows)
    src_path = history_path()
    hist = load_history(src_path)
    filled, missing, src = fill_prices(rows, hist, _short())
    cols = list(rows[0].keys()) + ["price_source"]
    tmp = out.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(filled)
    tmp.replace(out)
    h = sha256_bytes(out.read_bytes())
    meta = {
        "file": out.name, "sha256": h, "rows": len(filled),
        "sample": {"path": "docs/plans/biotech/design/fr6c_retro_sample_v1.csv", "sha256": FR6C_SAMPLE_SHA256},
        "design": {"path": "docs/plans/biotech/design/fr6c_design_v1.md", "sha256": FR6C_DESIGN_SHA256},
        "price_file": {"path": str(src_path), "sha256": sha256_bytes(src_path.read_bytes()) if src_path.exists() else None},
        "filled_on": today.isoformat(),
        "missing": {"count": len(missing), "accessions": missing},
        "price_source_cells": dict(src),
        "price_source_rule": {"iex_history_start": IEX_HISTORY_START, "backfill_last": BACKFILL_LAST},
        "backfill_dates": _backfill_dates(today),
    }
    meta_path().write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    LOG.info("FR-6c 가격 고정 · %s · %d행 · 가격 없음 %d건 · 출처 %s · SHA-256 %s", out.name, len(filled), len(missing), dict(src), h)
    return {"status": "created", "sha256": h, "rows": len(filled), "missing": len(missing), "sources": dict(src)}


def run(today: date | None = None) -> dict:
    try:
        return {"prices": fix_prices(today)}
    except SealError as e:
        return {"prices": {"status": "stopped", "reason": str(e)}}


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argparse.ArgumentParser().parse_args()
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
