"""큰손 발자국 확인 스크립트 (1119-03 ① · 기획서 3-1-1) · 운영 서버에서 사용자 승인 뒤 손으로 한 번만 실행한다.

이 맥(로컬)에서는 실행하지 않는다. 잡에 걸지 않고 서버 시작 때 불리지 않는다.

토큰 길 (Fable 조건 다):
  1. 저장 파일의 토큰을 직접 읽어 httpx 로 GET 한다 · 기존 `client.get()` 길은 쓰지 않는다.
     (`TossClient` 의 발급 · 갱신 · 토큰 파일 지움 길은 클래스 단위로 막아 둔다 — 실수로 불려도 예외.)
  2. 토큰 파일을 쓰지도 지우지도 않는다.
  3. 호출마다 저장 파일을 다시 읽어 만료 5분 안이면 그 자리에서 끝낸다 (종료 코드 2).
  4. 401 이 오면 다시 시도하지 않고 끝낸다 (토큰 파일은 그대로).
  5. httpx · httpcore 로그를 WARNING 으로 올린다 (요청 주소 줄에 종목 코드 · DART 키가 찍히지 않게).
  6. 호출 사이를 1초 이상 띄운다 (속도 제한기는 프로세스마다 따로라 서버 사용량을 모른다).

호출 수 상한: 토스 30회 · DART 30회. 로그에는 개수 · 연도 · 상태 코드만 남긴다.
종목 · 회사는 실행할 때 인자로 넣는다 (저장소에 적지 않음). 비밀값은 환경변수 DART_API_KEY 에서만 읽는다.
실행 시각 제한: 장 시간과 정해진 작업 시각 앞뒤에는 실행하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger("big_hands_probe")

_KST = timezone(timedelta(hours=9))
TOSS_BASE = "https://openapi.tossinvest.com"
DART_BASE = "https://opendart.fss.or.kr/api"
TOSS_MAX_CALLS = 30
DART_MAX_CALLS = 30
MIN_GAP_SEC = 1.0
EXPIRY_MARGIN_SEC = 300
EXIT_OK, EXIT_NO_TOKEN, EXIT_UNAUTHORIZED, EXIT_BAD_TIME, EXIT_LIMIT = 0, 2, 3, 4, 5

# (시작, 끝) KST 분 단위 · 정해진 작업 시각 앞뒤 (기획서 3-1-1) + 장 시간
_FORBIDDEN = [(5 * 60 + 55, 6 * 60 + 45), (9 * 60, 9 * 60 + 15), (9 * 60 + 15, 15 * 60 + 30),
              (16 * 60 + 40, 17 * 60 + 15), (17 * 60 + 40, 18 * 60 + 20), (20 * 60 + 20, 20 * 60 + 45)]


class ProbeStop(Exception):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def in_forbidden_window(now: Optional[datetime] = None) -> bool:
    now = (now or datetime.now(tz=_KST)).astimezone(_KST)
    m = now.hour * 60 + now.minute
    return any(a <= m < b for a, b in _FORBIDDEN)


def block_token_issue_paths() -> None:
    """TossClient 의 발급 · 갱신 · 토큰 파일 지움 길을 클래스 단위로 「부르면 바로 예외」로 바꾼다 (이 프로세스 안에서만)."""
    from backend.execution.brokers.toss_client import TossClient

    def _blocked(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("확인 스크립트에서는 토큰 발급 · 갱신 · 파일 지움 길을 쓰지 않습니다")

    for name in ("access_token", "_refresh_token", "_issue_token_locked", "_raise_from_response"):
        setattr(TossClient, name, _blocked)


def read_token_file(path: Path) -> str:
    """저장 파일을 매번 다시 읽는다 · 만료 5분 안이거나 없으면 아무 호출 없이 끝낸다 (쓰기 · 지우기 없음)."""
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("expires_at", 0) - time.time() > EXPIRY_MARGIN_SEC:
            return str(cached["access_token"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    raise ProbeStop(EXIT_NO_TOKEN, "저장된 토큰이 없거나 만료 5분 안입니다 · 호출 없이 끝냅니다")


class Prober:
    """호출 수 · 간격 · 토큰 길을 한곳에서 지킨다. 시험은 http 를 바꿔 끼운다."""

    def __init__(
        self, token_path: Path, *, http: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep, dart_key: Optional[str] = None,
    ):
        self.token_path = token_path
        self.http = http or httpx.Client(timeout=15.0)
        self._sleep = sleep
        self.dart_key = dart_key
        self.toss_calls = 0
        self.dart_calls = 0
        self._last_call = 0.0

    def _gap(self) -> None:
        wait = MIN_GAP_SEC - (time.monotonic() - self._last_call)
        if wait > 0:
            self._sleep(wait)
        self._last_call = time.monotonic()

    def toss_get(self, path: str, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        if self.toss_calls >= TOSS_MAX_CALLS:
            raise ProbeStop(EXIT_LIMIT, "토스 호출 상한")
        token = read_token_file(self.token_path)          # 호출마다 다시 읽음
        self._gap()
        self.toss_calls += 1
        resp = self.http.get(f"{TOSS_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code == 401:
            raise ProbeStop(EXIT_UNAUTHORIZED, "401 · 다시 시도하지 않고 끝냅니다 (토큰 파일은 그대로)")
        return resp

    def dart_get(self, name: str, params: dict[str, Any]) -> httpx.Response:
        if self.dart_calls >= DART_MAX_CALLS:
            raise ProbeStop(EXIT_LIMIT, "DART 호출 상한")
        if not self.dart_key:
            raise ProbeStop(EXIT_NO_TOKEN, "DART_API_KEY 환경변수가 없습니다")
        self._gap()
        self.dart_calls += 1
        return self.http.get(f"{DART_BASE}/{name}", params={"crtfc_key": self.dart_key, **params})


def _oldest_year(rows: Any) -> Optional[int]:
    years = [int(str(r.get("timestamp") or "")[:4]) for r in rows if isinstance(r, dict)
             and str(r.get("timestamp") or "")[:4].isdigit()]
    return min(years) if years else None


def _candle_rows(resp: httpx.Response) -> list[dict[str, Any]]:
    try:
        body = resp.json()
    except ValueError:
        return []
    result = body.get("result") if isinstance(body, dict) else body
    return [r for r in (result or []) if isinstance(r, dict)] if isinstance(result, list) else []


def probe_toss(p: Prober, symbol: str, delisted_symbol: Optional[str], max_pages: int = 8) -> dict[str, Any]:
    """(나) 가장 오래된 일봉 연도와 수정주가 차이 수 · (다) 상장폐지 종목 상태 코드 · 지수 일봉 가장 오래된 연도."""
    out: dict[str, Any] = {}

    def oldest(path: str, base: dict[str, Any]) -> tuple[Optional[int], list[dict[str, Any]]]:
        rows_all: list[dict[str, Any]] = []
        before: Optional[str] = None
        for _ in range(max_pages):
            params = dict(base)
            if before:
                params["before"] = before
            rows = _candle_rows(p.toss_get(path, params))
            if not rows:
                break
            rows_all.extend(rows)
            before = str(rows[-1].get("timestamp") or "") or None
            if before is None:
                break
        return _oldest_year(rows_all), rows_all

    y_raw, raw = oldest("/api/v1/candles", {"symbol": symbol, "interval": "1d", "count": 200, "adjusted": "false"})
    y_adj, adj = oldest("/api/v1/candles", {"symbol": symbol, "interval": "1d", "count": 200, "adjusted": "true"})
    by_ts = {str(r.get("timestamp"))[:10]: r.get("closePrice") for r in adj}
    diff = sum(1 for r in raw if by_ts.get(str(r.get("timestamp"))[:10]) not in (None, r.get("closePrice")))
    out["stock_oldest_year"] = y_raw
    out["stock_adjusted_oldest_year"] = y_adj
    out["adjusted_diff_count"] = diff
    if delisted_symbol:
        out["delisted_status"] = p.toss_get("/api/v1/candles", {"symbol": delisted_symbol, "interval": "1d", "count": 5}).status_code
    for idx in ("KOSPI", "KOSDAQ"):
        y, _ = oldest(f"/api/v1/market-indicators/{idx}/candles", {"interval": "1d", "count": 200})
        out[f"{idx.lower()}_oldest_year"] = y
    return out


def probe_dart(p: Prober, corp_code: str, receipt_no: str, first_receipt_no: Optional[str]) -> dict[str, Any]:
    """(마) 원문에 시각 칸이 있는지 · (바) 정정 전 접수번호 원문을 받았는지 · (사) elestock 2016년 건수."""
    out: dict[str, Any] = {}
    doc = p.dart_get("document.xml", {"rcept_no": receipt_no})
    out["document_status"] = doc.status_code
    out["document_has_time_field"] = b"rcept_tm" in doc.content    # [추정] 칸 이름 · 아니오가 나오면 원문을 눈으로 한 번 더 본다
    if first_receipt_no:
        out["first_version_status"] = p.dart_get("document.xml", {"rcept_no": first_receipt_no}).status_code
    ele = p.dart_get("elestock.json", {"corp_code": corp_code})
    try:
        rows = (ele.json() or {}).get("list") or []
    except ValueError:
        rows = []
    out["elestock_total"] = len(rows)
    out["elestock_2016_count"] = sum(1 for r in rows if str(r.get("rcept_dt") or "").startswith("2016"))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="큰손 발자국 확인 스크립트 (운영 서버에서 승인 뒤 손으로 한 번)")
    ap.add_argument("--symbol", required=True, help="상장 중 종목 코드 (실행할 때만 넣음)")
    ap.add_argument("--delisted-symbol", default=None, help="상장폐지 종목 코드")
    ap.add_argument("--corp-code", default=None, help="DART 회사 고유번호")
    ap.add_argument("--receipt-no", default=None, help="DART 접수번호")
    ap.add_argument("--first-receipt-no", default=None, help="정정 전 접수번호")
    ap.add_argument("--ignore-time-window", action="store_true", help="시각 제한 무시 (시험용)")
    args = ap.parse_args(argv)

    for noisy in ("httpx", "httpcore"):          # 요청 주소 줄(종목 코드 · DART 키)이 찍히지 않게
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.ignore_time_window and in_forbidden_window():
        logger.info("실행 제한 시각입니다 · 호출 없이 끝냅니다")
        return EXIT_BAD_TIME
    block_token_issue_paths()
    from backend.execution.brokers.toss_client import TossClient

    token_path = TossClient()._token_cache_path          # 경로만 얻음 · 발급 길을 부르지 않음
    prober = Prober(token_path, dart_key=os.environ.get("DART_API_KEY", "").strip() or None)
    code = EXIT_OK
    try:
        logger.info("토스 확인 결과: %s", json.dumps(probe_toss(prober, args.symbol, args.delisted_symbol), ensure_ascii=False))
        if args.corp_code and args.receipt_no:
            logger.info("DART 확인 결과: %s", json.dumps(
                probe_dart(prober, args.corp_code, args.receipt_no, args.first_receipt_no), ensure_ascii=False))
    except ProbeStop as stop:
        logger.info("중단(종료 코드 %s): %s", stop.code, stop.reason)
        code = stop.code
    logger.info("호출 수 · 토스 %s · DART %s", prober.toss_calls, prober.dart_calls)
    return code


if __name__ == "__main__":
    sys.exit(main())
