"""Phase C 3 · H6 소속 확장 · AACT 스냅샷에서 "테마 키워드 매치 임상 전량" 추출 (서버).

배경:
- 기존 H6 소속 (h6_membership · CT.gov API 300건 상한) = 분기당 2~5종목 → 백테스트 불성립
- 서버 주간 AACT 잡 (biotech_h69_aact_weekly) 의 ctgov_snapshot.json 은 후보 79 필터본 → 재사용 불가
- 본 스크립트 = 같은 AACT daily zip 을 같은 방식 (HEAD 실측 · 재시도 3 · CRC 무결성 · zip 삭제) 으로
  받아 테마 사전 v1 (주 6 + 대조군 2) 키워드 매치 임상 **전량** 을 CSV 로 추출

매치 대상 컬럼 (사용자 지시):
- studies.txt   · brief_title · official_title
- conditions.txt · name (질환명)
- interventions.txt · name (약물·시술명)

추출 필드: nct_id · lead_sponsor · agency_class (스폰서 유형) · phase · overall_status ·
          study_first_posted (최초 공개일 · point-in-time 기준) · primary_completion_date · themes

키워드 규칙 (H6-design §2 · 사전 커밋 그대로):
- 사전 = biotech_h6_theme_probe.THEMES (v1 · 사후 추가 금지)
- 대소문자 무시 · 단어 경계 일치 (예: "MASH" 는 "smash" 에 매치 안 함)
- 서로소 규칙: "GLP-1 combination" 은 식사대용·대사 전용 → 비만·GLP-1 의 "GLP-1" 매치 전에 가림
- 한 임상이 여러 테마에 매치되면 테마마다 1행씩 기록 (배정은 순위 단계에서 · §3 최고 순위 테마)

산출: <RUNTIME>/h6/aact_theme_studies_<스냅샷일>.csv  (로컬은 backend/data/biotech/h6/)

실행 (서버 · 사용자 승인 후):
    cd /root/toss-tradebot-mvp
    BIOTECH_RUNTIME_DIR=/root/toss-tradebot-mvp/var/biotech PYTHONPATH=. \\
      backend/.venv/bin/python -m backend.scripts.biotech_h6_aact_theme_extract
로컬 검증 (이미 받은 zip · 다운 없음 · zip 보존):
    PYTHONPATH=. backend/venv/bin/python -m backend.scripts.biotech_h6_aact_theme_extract --zip <path> --keep-zip

**보안·규칙**: 선언 UA·헤더 = biotech_sec_common 상수 (h69 경유) · 403/429 즉시 중단 · 응답 본문 로그 없음
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import csv
import io
import json
import logging
import re
import zipfile
from pathlib import Path

from backend.scripts import _biotech_paths as _P
from backend.scripts.biotech_h6_theme_probe import THEMES
from backend.scripts.biotech_h69_aact_weekly import (
    _download_zip,
    _notify_failure_sync,
    _pick_aact_url,
    _unzip_test,
)

LOG = logging.getLogger("biotech_h6_aact_theme_extract")

# 서로소 규칙 · 이 구절은 식사대용·대사 (meal_replacement_metabolic) 전용 · 비만 테마 매치 전 가림
GLP1_COMBO_RE = re.compile(r"glp-1 combination", re.IGNORECASE)
OBESITY_THEME = "obesity_glp1"

OUT_FIELDS = [
    "nct_id", "lead_sponsor", "agency_class", "phase", "overall_status",
    "study_first_posted", "primary_completion_date", "theme", "matched_in", "matched_keywords",
]


def compile_themes(themes: dict[str, list[str]]) -> dict[str, re.Pattern]:
    """테마 → 단어 경계 정규식 (영숫자 앞뒤 붙으면 불일치)."""
    out = {}
    for theme, kws in themes.items():
        alt = "|".join(re.escape(k) for k in sorted(kws, key=len, reverse=True))
        out[theme] = re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])", re.IGNORECASE)
    return out


def match_text(text: str, patterns: dict[str, re.Pattern]) -> dict[str, set[str]]:
    """본문 → {theme: {매치 키워드(소문자)}} · 서로소 규칙 적용."""
    hits: dict[str, set[str]] = {}
    if not text:
        return hits
    for theme, pat in patterns.items():
        t = GLP1_COMBO_RE.sub(" ", text) if theme == OBESITY_THEME else text
        found = {m.group(0).lower() for m in pat.finditer(t)}
        if found:
            hits[theme] = found
    return hits


class _Acc:
    """nct_id → theme → (매치 위치 집합, 키워드 집합) 누적 · 매치된 임상만 메모리 보유."""

    def __init__(self) -> None:
        self.d: dict[str, dict[str, tuple[set[str], set[str]]]] = {}

    def add(self, nct: str, where: str, hits: dict[str, set[str]]) -> None:
        if not nct or not hits:
            return
        per = self.d.setdefault(nct, {})
        for theme, kws in hits.items():
            w, k = per.setdefault(theme, (set(), set()))
            w.add(where)
            k.update(kws)


def _reader(zf: zipfile.ZipFile, name: str):
    f = zf.open(name, "r")
    return csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="|")


def _member(names: list[str], suffix: str) -> str | None:
    return next((n for n in names if n.endswith(suffix)), None)


def extract(zip_path: Path, themes: dict[str, list[str]] | None = None) -> tuple[list[dict], dict]:
    """zip → 테마 매치 임상 행 목록 + 집계 (스트리밍 · 전체 압축해제 없음)."""
    patterns = compile_themes(themes or THEMES)
    acc = _Acc()
    stats: dict = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        f_studies = _member(names, "studies.txt")
        f_cond = _member(names, "conditions.txt")
        f_intv = _member(names, "interventions.txt")
        f_spon = _member(names, "sponsors.txt")
        if not all([f_studies, f_cond, f_intv, f_spon]):
            raise RuntimeError(f"AACT zip 구조 예상과 다름 · studies={f_studies} conditions={f_cond} "
                               f"interventions={f_intv} sponsors={f_spon}")

        # 1) 질환명 (conditions) · 2) 약물명 (interventions)
        for fname, where in ((f_cond, "condition"), (f_intv, "intervention")):
            n = 0
            for row in _reader(zf, fname):
                n += 1
                acc.add(row.get("nct_id", ""), where, match_text(row.get("name", ""), patterns))
            stats[f"{where}_rows"] = n
            LOG.info("%s 파싱 · %d 행 · 누적 매치 임상 %d", fname, n, len(acc.d))

        # 3) studies · 제목 매치 + 매치 임상의 기본 필드 보관
        study_meta: dict[str, dict] = {}
        n = 0
        for row in _reader(zf, f_studies):
            n += 1
            nct = row.get("nct_id", "")
            title = f"{row.get('brief_title', '')} || {row.get('official_title', '')}"
            acc.add(nct, "title", match_text(title, patterns))
            if nct in acc.d:
                study_meta[nct] = {
                    "phase": row.get("phase", ""),
                    "overall_status": row.get("overall_status", ""),
                    # AACT 컬럼명 = study_first_posted_date (CT.gov 최초 공개일)
                    "study_first_posted": row.get("study_first_posted_date", "") or row.get("study_first_posted", ""),
                    "primary_completion_date": row.get("primary_completion_date", ""),
                }
        stats["study_rows"] = n
        LOG.info("studies 파싱 · %d 행 · 매치 임상 %d", n, len(acc.d))

        # 4) sponsors · lead 스폰서 (매치 임상만)
        lead: dict[str, tuple[str, str]] = {}
        n = 0
        for row in _reader(zf, f_spon):
            n += 1
            nct = row.get("nct_id", "")
            if nct in acc.d and (row.get("lead_or_collaborator", "") or "").lower() == "lead":
                lead[nct] = (row.get("name", "").strip(), row.get("agency_class", "").strip())
        stats["sponsor_rows"] = n

    rows: list[dict] = []
    for nct, per in acc.d.items():
        meta = study_meta.get(nct)
        if meta is None:  # conditions 에만 있고 studies 에 없는 고아 행 (드묾) · 제외
            continue
        sp, ac = lead.get(nct, ("", ""))
        for theme, (where, kws) in sorted(per.items()):
            rows.append({
                "nct_id": nct, "lead_sponsor": sp, "agency_class": ac, **meta,
                "theme": theme, "matched_in": "|".join(sorted(where)), "matched_keywords": "|".join(sorted(kws)),
            })
    stats["matched_studies"] = len({r["nct_id"] for r in rows})
    stats["matched_rows"] = len(rows)
    stats["sponsors_unique"] = len({r["lead_sponsor"] for r in rows if r["lead_sponsor"]})
    stats["by_theme"] = {t: sum(1 for r in rows if r["theme"] == t) for t in (themes or THEMES)}
    return rows, stats


def write_rows(rows: list[dict], out_path: Path) -> None:
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["theme"], r["study_first_posted"], r["nct_id"])))


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="이미 받은 AACT zip 경로 (지정 시 다운로드 생략)")
    ap.add_argument("--keep-zip", action="store_true", help="zip 보존 (로컬 검증용 · 서버 기본은 삭제)")
    ap.add_argument("--tmp-dir", default="/tmp/aact_zip_h6", help="임시 zip 폴더 (실행 후 삭제)")
    args = ap.parse_args()

    if args.zip:
        zip_path = Path(args.zip)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", zip_path.name)
        date_str = m.group(1) if m else _P.today_kst_str("%Y-%m-%d")
    else:
        picked = _pick_aact_url()  # 최근 10일 HEAD 200 · 403/429 즉시 중단
        if not picked:
            _notify_failure_sync("h6_extract_head", "최근 10일 안 200 OK 없음")
            raise SystemExit(31)
        date_str, url = picked
        tmp = Path(args.tmp_dir)
        tmp.mkdir(parents=True, exist_ok=True)
        zip_path = tmp / f"aact_{date_str}.zip"
        if not zip_path.exists() and not _download_zip(url, zip_path):
            _notify_failure_sync("h6_extract_download", f"3회 재시도 실패 · {date_str}")
            zip_path.unlink(missing_ok=True)
            raise SystemExit(32)

    try:
        if not _unzip_test(zip_path):
            _notify_failure_sync("h6_extract_integrity", "CRC 검증 실패")
            raise SystemExit(33)
        rows, stats = extract(zip_path)
        out_path = _P.out_dir("h6") / f"aact_theme_studies_{date_str}.csv"
        write_rows(rows, out_path)
    finally:
        if not args.keep_zip and zip_path.exists():
            size_mb = zip_path.stat().st_size // (1024 * 1024)
            zip_path.unlink(missing_ok=True)
            LOG.info("zip 삭제 · %d MB 회수", size_mb)

    summary = {"aact_snapshot_date": date_str, "output": str(out_path), **stats}
    (out_path.with_suffix(".summary.json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
