"""Phase 0 부트스트랩 — Toss Open API 계정 확보 · 헬스체크.

용도:
    1) POST /oauth2/token (client_credentials) 로 Access Token 발급
    2) GET /api/v1/accounts 로 accountSeq 확보 → .env `TOSS_ACCOUNT_SEQ` 저장 안내
    3) TOSS_ACCOUNT_SEQ 가 이미 설정된 경우 GET /api/v1/holdings + /buying-power 스모크 체크

실행:
    # 1단계 (accountSeq 확보 전)
    python -m scripts.toss.bootstrap_account

    # 2단계 (accountSeq 저장 후 스모크 체크)
    python -m scripts.toss.bootstrap_account --smoke

환경 변수 (backend/services/config.py 검색 경로 그대로 사용):
    TOSS_CLIENT_ID              (필수)
    TOSS_CLIENT_SECRET          (필수)
    TOSS_ACCOUNT_SEQ            (--smoke 시 필수)
    TOSS_TOKEN_CACHE_PATH       (선택, 기본 backend/data/toss_token.json)

주의:
    - 토큰 캐시 파일은 .gitignore 등재 필수 (backend/data/toss_token.json).
    - 이 스크립트는 값 자체를 파일에 쓰지 않음 — accountSeq 는 stdout 출력만.
    - 허용 IP 미등록 시 403 forbidden — WTS 허용 IP 등록 필수.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# backend/ 를 import path 에 넣어 config 재사용
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
from backend.services import config  # noqa: E402  (load_env_once 자동 실행)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("toss-bootstrap")

_BASE_URL = "https://openapi.tossinvest.com"
_TIMEOUT_SEC = 10.0
_DEFAULT_TOKEN_CACHE = _PROJECT_ROOT / "backend" / "data" / "toss_token.json"


def _token_cache_path() -> Path:
    raw = config.get("TOSS_TOKEN_CACHE_PATH")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else _PROJECT_ROOT / p
    return _DEFAULT_TOKEN_CACHE


def _dump_error(resp: httpx.Response) -> str:
    request_id = resp.headers.get("X-Request-Id") or resp.headers.get("x-amz-cf-id") or "-"
    try:
        body = resp.json()
        err = body.get("error", {}) if isinstance(body, dict) else {}
        code = err.get("code", "-")
        message = err.get("message", "-")
        data = err.get("data")
        tail = f" data={data}" if data else ""
        return f"[{resp.status_code}] requestId={request_id} code={code} message={message}{tail}"
    except ValueError:
        return f"[{resp.status_code}] requestId={request_id} body={resp.text[:400]}"


def fetch_access_token() -> str:
    """POST /oauth2/token — client_credentials · 캐시 재사용 (만료 5분 전 갱신)."""
    cache_path = _token_cache_path()
    now = time.time()
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("expires_at", 0) - now > 300:  # 5분 여유
                logger.info(
                    "토큰 캐시 재사용 (만료까지 %d초 · %s)",
                    int(cached["expires_at"] - now),
                    cache_path,
                )
                return cached["access_token"]
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("토큰 캐시 무효 (%s) — 재발급", exc)

    client_id = config.require("TOSS_CLIENT_ID")
    client_secret = config.require("TOSS_CLIENT_SECRET")

    logger.info("POST /oauth2/token — Access Token 발급")
    with httpx.Client(timeout=_TIMEOUT_SEC) as client:
        resp = client.post(
            f"{_BASE_URL}/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(f"토큰 발급 실패: {_dump_error(resp)}")

    payload = resp.json()
    token = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "access_token": token,
                "token_type": payload.get("token_type", "Bearer"),
                "expires_in": expires_in,
                "expires_at": now + expires_in,
                "issued_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("토큰 발급 완료 (%s초 유효 · 캐시=%s)", expires_in, cache_path)
    return token


def fetch_accounts(token: str) -> list[dict]:
    """GET /api/v1/accounts — 계좌 목록 (accountSeq · accountNo · accountType)."""
    logger.info("GET /api/v1/accounts")
    with httpx.Client(timeout=_TIMEOUT_SEC) as client:
        resp = client.get(
            f"{_BASE_URL}/api/v1/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"계좌 조회 실패: {_dump_error(resp)}")
    body = resp.json()
    accounts = None
    if isinstance(body, dict):
        # 응답 랩퍼: `result` (실측) · `accounts` (스펙) 둘 다 대응
        accounts = body.get("result") or body.get("accounts")
    else:
        accounts = body
    if not isinstance(accounts, list) or not accounts:
        raise RuntimeError(f"계좌 목록이 비어있음: {body}")
    return accounts


def smoke_check(token: str, account_seq: str) -> None:
    """GET /holdings + /buying-power — Phase 0 DoD 스모크 체크."""
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Tossinvest-Account": str(account_seq),
    }
    with httpx.Client(timeout=_TIMEOUT_SEC, headers=headers) as client:
        logger.info("GET /api/v1/holdings")
        h = client.get(f"{_BASE_URL}/api/v1/holdings")
        if h.status_code != 200:
            raise RuntimeError(f"holdings 실패: {_dump_error(h)}")
        holdings = h.json()

        buying_power: dict[str, dict] = {}
        for cur in ("KRW", "USD"):
            logger.info("GET /api/v1/buying-power?currency=%s", cur)
            b = client.get(f"{_BASE_URL}/api/v1/buying-power", params={"currency": cur})
            if b.status_code != 200:
                raise RuntimeError(f"buying-power({cur}) 실패: {_dump_error(b)}")
            buying_power[cur] = b.json()

    positions = None
    if isinstance(holdings, dict):
        positions = holdings.get("result") or holdings.get("holdings")
    else:
        positions = holdings
    n_positions = len(positions) if isinstance(positions, list) else 0
    logger.info("holdings — %d개 종목", n_positions)
    logger.info("buying-power — %s", json.dumps(buying_power, ensure_ascii=False))
    print()
    print("✅ Phase 0 스모크 체크 통과")
    print(f"   보유 종목: {n_positions}개")
    print(f"   매수 가능 금액: {json.dumps(buying_power, ensure_ascii=False)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Toss Open API Phase 0 부트스트랩")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="TOSS_ACCOUNT_SEQ 저장 후 스모크 체크 (holdings · buying-power)",
    )
    args = parser.parse_args()

    try:
        token = fetch_access_token()
    except Exception as exc:  # noqa: BLE001
        logger.error("토큰 발급 실패 — %s", exc)
        logger.error("확인: 허용 IP 등록 · TOSS_CLIENT_ID/SECRET 값 · SOPS 복호화 여부")
        return 2

    if args.smoke:
        account_seq = config.get("TOSS_ACCOUNT_SEQ")
        if not account_seq:
            logger.error("--smoke 옵션은 TOSS_ACCOUNT_SEQ 설정 필요")
            return 2
        try:
            smoke_check(token, account_seq)
        except Exception as exc:  # noqa: BLE001
            logger.error("스모크 체크 실패 — %s", exc)
            return 3
        return 0

    try:
        accounts = fetch_accounts(token)
    except Exception as exc:  # noqa: BLE001
        logger.error("계좌 조회 실패 — %s", exc)
        return 3

    print()
    print("=" * 60)
    print("📋 계좌 목록")
    print("=" * 60)
    for i, acc in enumerate(accounts, 1):
        seq = acc.get("accountSeq")
        no = acc.get("accountNo", "-")
        kind = acc.get("accountType", "-")
        print(f"  [{i}] accountSeq={seq}  accountNo={no}  type={kind}")
    print()
    print("👉 다음 스텝:")
    print("   1) 위 accountSeq 중 BROKERAGE 계좌를 선택")
    print("   2) sops edit backend/.env.sops.yaml 로 TOSS_ACCOUNT_SEQ 저장 후 git push")
    print("   3) 서버 반영 후 재실행: python -m scripts.toss.bootstrap_account --smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
