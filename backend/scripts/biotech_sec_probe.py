"""B104 · SEC 재개 탐침 (단일 요청 · 최소 2h 간격 규정).

용도:
- SEC data.sec.gov 접근 재개 여부 확인 단일 요청 1건
- 신원 선언 UA · From 헤더 · 0.5s 대기 후 호출 (사전 예방)
- 200 시 SEC 세션 6작업 (B98/B55+/B95/B60/companyfacts) 개시 가능
- 403 시 즉시 종료 · UA 순환·재시도 금지 (규정)

간격 규정:
- 최소 2h 사이 (권장 +2h → +6h → +24h)
- probe_log.json 이 직전 탐침 시각 보관 · 2h 미만 시 실행 거부

우회 금지 (B105):
- IP 차단 시 서버 실행·네트워크 변경 등 IP 교체로 접근하지 않는다.

실행:
    python -m backend.scripts.biotech_sec_probe          # 규정 확인 후 1건 호출
    python -m backend.scripts.biotech_sec_probe --force  # 간격 무시 (긴급 시만)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · WP8 · setup_secure_logging 자동 활성
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

LOG = logging.getLogger("biotech_sec_probe")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROBE_LOG = DATA_DIR / "sec_probe_log.json"

# WP23 (2026-09-09) · SEC 지정 헤더 형식 (biotech_sec_common 재사용)
from backend.scripts.biotech_sec_common import (  # noqa: E402
    SEC_UA,
    SEC_FROM,
    SEC_ACCEPT_ENCODING,
)

PROBE_URL = "https://data.sec.gov/submissions/CIK0001392402.json"  # RA Capital Healthcare Fund II
MIN_INTERVAL_SEC = 2 * 60 * 60  # 2h
REQ_PRE_SLEEP = 0.5


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_log() -> list[dict]:
    if not PROBE_LOG.exists():
        return []
    try:
        return json.loads(PROBE_LOG.read_text())
    except Exception:
        return []


def _save_log(entries: list[dict]) -> None:
    PROBE_LOG.write_text(json.dumps(entries, indent=2))


def check_interval(log: list[dict]) -> tuple[bool, float]:
    """직전 실 SEC 요청으로부터 MIN_INTERVAL_SEC 경과 여부.

    SKIPPED_INTERVAL 항목은 실 요청 아님 → 무시 (2h 리셋 방지).
    반환: (허용 여부, 경과 초 · 실 요청 이력 없으면 inf)
    """
    if not log:
        return True, float("inf")
    real_log = [e for e in log if e.get("status") != "SKIPPED_INTERVAL"]
    if not real_log:
        return True, float("inf")
    last_ts = real_log[-1].get("utc")
    if not last_ts:
        return True, float("inf")
    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
    elapsed = (_now_utc() - last_dt).total_seconds()
    return elapsed >= MIN_INTERVAL_SEC, elapsed


def probe(force: bool = False) -> dict:
    """단일 탐침 1건 · 로그 append.

    반환 dict: utc · status · reason · elapsed_since_last
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = _load_log()
    allowed, elapsed = check_interval(log)
    if not allowed and not force:
        entry = {
            "utc": _now_utc().isoformat(),
            "status": "SKIPPED_INTERVAL",
            "reason": f"직전 탐침 후 {elapsed:.0f}s (2h 미만 · 규정)",
            "elapsed_since_last_sec": elapsed,
        }
        LOG.warning("탐침 스킵 · %s", entry["reason"])
        log.append(entry)
        _save_log(log)
        return entry

    time.sleep(REQ_PRE_SLEEP)
    utc_at = _now_utc().isoformat()
    try:
        r = httpx.get(
            PROBE_URL,
            headers={
                "User-Agent": SEC_UA,
                "From": SEC_FROM,
                "Accept-Encoding": SEC_ACCEPT_ENCODING,
            },
            timeout=25.0,
        )
        status_code = r.status_code
        body_sig = ""
        if status_code == 403:
            body_sig = "Undeclared Automated Tool" if "Undeclared Automated Tool" in r.text[:2000] else r.text[:80].replace("\n", " ")
        entry = {
            "utc": utc_at,
            "status": "OK" if status_code == 200 else ("BLOCKED_403" if status_code == 403 else f"HTTP_{status_code}"),
            "http_status": status_code,
            "server_hdr": r.headers.get("Server", ""),
            "body_sig": body_sig,
            "elapsed_since_last_sec": elapsed if elapsed != float("inf") else None,
        }
    except Exception as e:
        entry = {
            "utc": utc_at,
            "status": "CONNECT_ERR",
            "reason": f"{type(e).__name__}: {e}",
            "elapsed_since_last_sec": elapsed if elapsed != float("inf") else None,
        }
    log.append(entry)
    _save_log(log)
    LOG.info("탐침 결과: %s", entry)
    return entry


def main() -> int:
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from backend.services import config as _config  # noqa: F401 · B44 마스킹

    force = "--force" in sys.argv
    result = probe(force=force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("status") == "OK":
        print("\n[재개 가능] PENDING.md 최상단 SEC 세션 지시대로 진행.")
        return 0
    if result.get("status") == "BLOCKED_403":
        print("\n[차단 유지] +2h → +6h → +24h 순 대기 · UA 순환 절대 금지.")
        return 2
    if result.get("status") == "SKIPPED_INTERVAL":
        print("\n[간격 규정] 최소 2h 대기 · --force 는 긴급 시만.")
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
