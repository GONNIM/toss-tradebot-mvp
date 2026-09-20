"""WP69-3c · AACT 주간 스냅샷 잡 · 서버 파이프.

CT.gov v2 서버 IP 차단 대안 (사용자 결정 2026-09-20):
- AACT 주간 daily zip 다운 (실측 URL · 2026-09-19 자 ≈ 2.35 GB)
- studies.txt · sponsors.txt 스트리밍 파싱 (전체 압축해제 없이 zipfile.open)
- 후보 우주 (candidates_v3) 스폰서 매칭 → JSON (<5 MB) · 후보별 최근·예정 primary_completion_date
- zip 삭제 · 실패 시 텔레그램 · 3회 재시도 (기본 · 별도 sleep)

산출: $BIOTECH_RUNTIME_DIR/ctgov_snapshot.json (없으면 fallback docs/plans/biotech/data/)
스키마:
{
  "generated_utc": "...",
  "aact_snapshot_date": "2026-09-19",
  "candidate_matches": N,
  "matches": [
    {"ticker": "AVIR", "sponsor_name": "Atea Pharmaceuticals", "nct_id": "NCT06...",
     "phase": "PHASE3", "overall_status": "RECRUITING",
     "primary_completion_date": "2026-09-30", "days_to": 10}
  ]
}

**보안·규칙**:
- biotech_sec_common.SEC_UA / SEC_FROM / SEC_ACCEPT_ENCODING 상수 참조 (하드코딩 금지)
- 응답 본문 노출 없음 (로그는 상태/크기만)
- setup_secure_logging 강제
- 403/429 즉시 중단·기록

cron (사용자 지시 · KST 서버):
    0 6 * * 1 /bin/bash /root/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily_server.sh --aact-weekly-only >> ... 2>&1

이 스크립트는 단독 실행도 가능:
    cd /root/toss-tradebot-mvp
    PYTHONPATH=. backend/.venv/bin/python -m backend.scripts.biotech_h69_aact_weekly
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts.biotech_sec_common import SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING

import argparse
import asyncio
import csv
import io
import json
import logging
import os
import re
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_h69_aact_weekly")

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 산출 폴더 · WP69-3b · RUNTIME 우선 · fallback docs/plans/biotech/data
_rt = os.environ.get("BIOTECH_RUNTIME_DIR", "").strip()
RUNTIME_DIR = Path(_rt) if _rt else None
FALLBACK_DIR = PROJECT_ROOT / "docs" / "plans" / "biotech" / "data"
OUT_DIR = RUNTIME_DIR if RUNTIME_DIR else FALLBACK_DIR
OUT_JSON = OUT_DIR / "ctgov_snapshot.json"

# candidates_v3 조회 · WP69-3b _search_dirs 정합
CANDIDATES_SEARCH = [
    (RUNTIME_DIR / "candidates") if RUNTIME_DIR else None,
    FALLBACK_DIR,
    PROJECT_ROOT / "backend" / "data" / "biotech" / "candidates",
]

# AACT 실측 (2026-09-20 서버 HEAD 확증)
AACT_BASE = "https://aact.ctti-clinicaltrials.org/static/exported_files/daily"
HEADERS = {
    "User-Agent": SEC_UA,
    "From": SEC_FROM,
    "Accept-Encoding": SEC_ACCEPT_ENCODING,
}

REQUEST_TIMEOUT = 60.0
DOWNLOAD_TIMEOUT = 900.0  # 15분 · 2.35GB @ 30MB/s 서버 대역폭 가정 시 여유


def _latest_candidates_csv() -> Path | None:
    """최신 candidates CSV · 사용자 지시 조회 순서."""
    hits: list[Path] = []
    for base in CANDIDATES_SEARCH:
        if base is None or not base.exists():
            continue
        hits.extend(sorted(base.glob("biotech_candidates_v3_*.csv")))
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def _pick_aact_url() -> tuple[str, str] | None:
    """최근 10일 중 200 OK 응답 첫 URL · (date, url) 반환."""
    with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as c:
        for i in range(0, 10):
            d = (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()
            url = f"{AACT_BASE}/{d}_daily-clinical-trials.zip"
            try:
                r = c.head(url)
                if r.status_code == 200:
                    size_gb = int(r.headers.get("content-length", 0)) / (1024**3)
                    LOG.info("AACT snapshot found · %s · %.2f GB", d, size_gb)
                    return d, url
                if r.status_code in (403, 429):
                    LOG.error("AACT HEAD %d · %s · 즉시 중단", r.status_code, d)
                    return None
            except httpx.HTTPError as e:
                LOG.warning("AACT HEAD %s · %s", d, e.__class__.__name__)
    return None


def _download_zip(url: str, dst: Path) -> bool:
    """스트리밍 다운로드 · 3회 재시도 · chunk 진행 로그."""
    for attempt in range(1, 4):
        try:
            with httpx.stream("GET", url, headers=HEADERS, timeout=DOWNLOAD_TIMEOUT,
                              follow_redirects=True) as r:
                if r.status_code != 200:
                    LOG.warning("attempt %d · HTTP %d", attempt, r.status_code)
                    if r.status_code in (403, 429):
                        return False
                    continue
                total = int(r.headers.get("content-length", 0))
                got = 0
                last_log_bytes = 0
                with dst.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        got += len(chunk)
                        if got - last_log_bytes >= 200 * 1024 * 1024:  # 200MB 마다
                            pct = (got / total * 100) if total else 0
                            LOG.info("  ... %d MB / %d MB (%.1f%%)",
                                     got // (1024 * 1024), total // (1024 * 1024), pct)
                            last_log_bytes = got
                if total and got < total * 0.99:
                    LOG.warning("attempt %d · 다운 미완 (%d/%d)", attempt, got, total)
                    continue
                LOG.info("다운 완료 · %d MB", got // (1024 * 1024))
                return True
        except httpx.HTTPError as e:
            LOG.warning("attempt %d · %s", attempt, e.__class__.__name__)
            time.sleep(5 * attempt)
    return False


def _unzip_test(zip_path: Path) -> bool:
    """무결성 검증 · zipfile.testzip() 우선 (내장 · 서버 unzip 바이너리 미의존) · unzip -tq fallback."""
    # Python 내장 · CRC 전수 검증
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad is None:
                LOG.info("zipfile.testzip() OK · CRC 전수 통과")
                return True
            LOG.error("zipfile.testzip() 실패 · 첫 손상 항목 = %s", bad)
            return False
    except zipfile.BadZipFile as e:
        LOG.error("BadZipFile · %s", e)
        return False
    except Exception as e:
        LOG.warning("zipfile.testzip() 예외 · %s · unzip -tq fallback 시도", e.__class__.__name__)
    # fallback: unzip -tq (있으면)
    try:
        r = subprocess.run(
            ["unzip", "-tq", str(zip_path)],
            capture_output=True, text=True, timeout=300,
        )
        ok = r.returncode == 0
        if not ok:
            LOG.error("unzip -t 실패 · rc=%d · stderr=%s", r.returncode, r.stderr[:200])
        return ok
    except FileNotFoundError:
        LOG.error("unzip 바이너리 없음 · zipfile.testzip 도 실패 · 무결성 미확증")
        return False
    except Exception as e:
        LOG.error("unzip -t 예외 · %s", e.__class__.__name__)
        return False


def _norm(s: str) -> str:
    """회사명 정규화 (매칭용) · lower · 공백/특수 제거."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _parse_studies_and_sponsors(zip_path: Path, candidate_norm_map: dict[str, str]) -> list[dict]:
    """studies.txt · sponsors.txt 스트리밍 파싱 · 후보 매칭.

    candidate_norm_map: {normalized_sponsor_name: ticker}
    반환: 매칭된 studies 리스트 (핵심 필드만).
    """
    matches: list[dict] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        # 파일명 실측 · AACT daily zip 내부 최상위에 파일들
        studies_name = next((n for n in names if n.endswith("studies.txt")), None)
        sponsors_name = next((n for n in names if n.endswith("sponsors.txt")), None)
        LOG.info("zip 내부 · studies=%s · sponsors=%s · total_entries=%d",
                 studies_name, sponsors_name, len(names))
        if not studies_name or not sponsors_name:
            LOG.error("AACT zip 구조 예상과 다름 · 파일 부재")
            return []

        # 1) sponsors.txt · nct_id → ticker 매핑 (lead_or_collaborator=lead · 매칭된 것만)
        LOG.info("sponsors.txt 파싱 · 매칭 시작")
        nct_to_ticker: dict[str, str] = {}
        with zf.open(sponsors_name, "r") as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            reader = csv.DictReader(text, delimiter="|")
            # 실측: AACT sponsors columns · id, nct_id, agency_class, lead_or_collaborator, name
            processed = 0
            for row in reader:
                processed += 1
                if row.get("lead_or_collaborator", "").lower() != "lead":
                    continue
                name_norm = _norm(row.get("name", ""))
                ticker = candidate_norm_map.get(name_norm)
                if ticker:
                    nct_to_ticker[row.get("nct_id", "")] = ticker
                if processed % 500_000 == 0:
                    LOG.info("  sponsors 진행 · %d 행 · 매칭 %d", processed, len(nct_to_ticker))
        LOG.info("sponsors 파싱 완료 · 총 %d 행 · 후보 스폰서 매칭 %d nct", processed, len(nct_to_ticker))

        if not nct_to_ticker:
            LOG.warning("후보 스폰서 매칭 0 · 매칭기 v2 개선 필요")
            return []

        # 2) studies.txt · 매칭된 nct_id 만 추출
        LOG.info("studies.txt 파싱 · 매칭 %d nct 만 추출", len(nct_to_ticker))
        today = datetime.now(timezone.utc).date()
        with zf.open(studies_name, "r") as f:
            text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
            reader = csv.DictReader(text, delimiter="|")
            processed = 0
            for row in reader:
                processed += 1
                nct = row.get("nct_id", "")
                if nct not in nct_to_ticker:
                    continue
                pcd_raw = row.get("primary_completion_date", "").strip()
                pcd_date = None
                days_to = None
                if pcd_raw:
                    for fmt in ("%Y-%m-%d", "%B %Y", "%Y-%m"):
                        try:
                            pcd_date = datetime.strptime(pcd_raw, fmt).date()
                            break
                        except ValueError:
                            continue
                    if pcd_date:
                        days_to = (pcd_date - today).days
                matches.append({
                    "ticker": nct_to_ticker[nct],
                    "nct_id": nct,
                    "phase": row.get("phase", ""),
                    "overall_status": row.get("overall_status", ""),
                    "primary_completion_date": pcd_raw,
                    "days_to": days_to,
                    "brief_title": (row.get("brief_title") or "")[:120],
                })
                if processed % 100_000 == 0:
                    LOG.info("  studies 진행 · %d 행 · 매칭 study %d", processed, len(matches))
        LOG.info("studies 파싱 완료 · 총 %d 행 · 매칭 study %d", processed, len(matches))
    return matches


def _load_candidate_norm_map() -> tuple[dict[str, str], int]:
    """candidates_v3 · normalized_sponsor_name → ticker 사전."""
    p = _latest_candidates_csv()
    if not p:
        return {}, 0
    norm_map: dict[str, str] = {}
    n = 0
    with p.open() as f:
        for row in csv.DictReader(f):
            ticker = (row.get("ticker") or "").strip()
            name = (row.get("name") or "").strip()
            if ticker and name:
                norm_map[_norm(name)] = ticker
                n += 1
    LOG.info("candidates=%s · %d 후보 (스폰서 매칭용)", p.name, n)
    return norm_map, n


def _notify_failure_sync(step: str, detail: str) -> None:
    """텔레그램 알림 · sync wrapper."""
    try:
        from backend.services.notifier import TelegramNotifier
        n = TelegramNotifier()
        asyncio.run(n.send_critical(
            title=f"biotech AACT weekly 실패 · {step}",
            body=f"단계: {step}\n상세: {detail}\n서버: optimus8\n스크립트: biotech_h69_aact_weekly",
        ))
    except Exception as e:
        LOG.warning("notifier 실패 · %s", e.__class__.__name__)


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--tmp-dir", default="/tmp/aact_zip", help="임시 zip 저장 폴더 (실행 후 삭제)")
    args = parser.parse_args()

    tmp_dir = Path(args.tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 1) URL 실측
    picked = _pick_aact_url()
    if not picked:
        _notify_failure_sync("head", "최근 10일 안 200 OK 없음")
        raise SystemExit(21)
    date_str, url = picked

    # 2) 다운
    zip_path = tmp_dir / f"aact_{date_str}.zip"
    if zip_path.exists():
        LOG.info("기존 zip 재사용 · %s", zip_path)
    else:
        ok = _download_zip(url, zip_path)
        if not ok:
            _notify_failure_sync("download", f"3회 재시도 실패 · {date_str}")
            zip_path.unlink(missing_ok=True)
            raise SystemExit(22)

    # 3) 무결성
    if not _unzip_test(zip_path):
        _notify_failure_sync("integrity", "unzip -t 실패")
        zip_path.unlink(missing_ok=True)
        raise SystemExit(23)

    # 4) 후보 매칭 사전 로드
    candidate_norm_map, n_cand = _load_candidate_norm_map()
    if not candidate_norm_map:
        _notify_failure_sync("candidates", "candidates CSV 미확보")
        zip_path.unlink(missing_ok=True)
        raise SystemExit(24)

    # 5) 파싱 · 매칭
    matches = _parse_studies_and_sponsors(zip_path, candidate_norm_map)

    # 6) JSON 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "aact_snapshot_date": date_str,
        "candidates_v3_count": n_cand,
        "candidate_matches": len({m["ticker"] for m in matches}),
        "study_matches": len(matches),
        "matches": matches,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    LOG.info("ctgov_snapshot.json · %d study · %d unique ticker · %s",
             len(matches), len({m["ticker"] for m in matches}), OUT_JSON)

    # 7) zip 삭제 (사용자 지시)
    size_mb = zip_path.stat().st_size // (1024 * 1024)
    zip_path.unlink(missing_ok=True)
    LOG.info("zip 삭제 · %d MB 회수", size_mb)

    # 요약 print
    print(json.dumps({
        "aact_snapshot_date": date_str,
        "study_matches": len(matches),
        "unique_tickers": len({m["ticker"] for m in matches}),
        "output": str(OUT_JSON.relative_to(PROJECT_ROOT)),
        "zip_size_mb": size_mb,
    }, indent=2))


if __name__ == "__main__":
    main()
