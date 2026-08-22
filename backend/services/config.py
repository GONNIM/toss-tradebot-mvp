"""환경 변수·자격증명 로드 (B-2k).

다중 .env 위치 검색 — 사용자가 frontend/.env.local 또는 backend/.env 어디에 두든
자동으로 인식. 우선순위: project root > backend/ > frontend/.

⚠️ 본 모듈은 backend 만 사용. frontend는 Next.js 자체 .env.local 처리.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.services.logging_setup import setup_secure_logging

# 2026-08-22 · DART_API_KEY 로그 노출 사고 대응 · 모든 backend 진입점 공통 부팅.
# config 는 어떤 backend 모듈이든 첫 import 하는 지점이므로 여기서 자동 setup.
# idempotent · 여러 번 호출해도 필터 중복 등록 안 됨.
setup_secure_logging()

logger = logging.getLogger(__name__)


_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent

_ENV_SEARCH_PATHS = [
    _PROJECT_ROOT / ".env",
    _PROJECT_ROOT / ".env.local",
    _BACKEND_DIR / ".env",
    _BACKEND_DIR / ".env.local",
    _PROJECT_ROOT / "frontend" / ".env.local",  # 사용자 임시 위치 (2026-06-25)
]

_LOADED = False


def load_env_once() -> None:
    """후보 .env 파일을 우선순위 순으로 로드 (override=False)."""
    global _LOADED
    if _LOADED:
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        logger.warning("python-dotenv 미설치 — OS env 만 사용")
        _LOADED = True
        return

    for path in _ENV_SEARCH_PATHS:
        if path.exists():
            load_dotenv(path, override=False)
            logger.info(f"[config] loaded {path}")
    _LOADED = True


load_env_once()


def get(name: str, default: str | None = None) -> str | None:
    load_env_once()
    return os.environ.get(name, default)


def require(name: str) -> str:
    value = get(name)
    if not value:
        raise RuntimeError(
            f"필수 환경 변수 {name!r} 미설정. "
            f"검색 위치: {[str(p) for p in _ENV_SEARCH_PATHS]}"
        )
    return value


def customs_api_key() -> str:
    """관세청 공공데이터 API key (B-2k)."""
    return require("CUSTOMS_API_KEY")


def customs_endpoint() -> str:
    """관세청 cntyMmUtPrviExpAcrs base URL."""
    return get(
        "CUSTOM_END_POINT",
        "https://apis.data.go.kr/1220000/cntyMmUtPrviExpAcrs",
    ) or "https://apis.data.go.kr/1220000/cntyMmUtPrviExpAcrs"


# CORS 화이트리스트 기본값 — 개발(localhost 4000) + 운영(optimus8)
# 프론트 포트 변경 시 CORS_ORIGINS 환경변수만 갱신하면 코드 수정 불필요.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000,"
    "http://localhost:4000,"
    "http://localhost:5000,"
    "http://127.0.0.1:4000,"
    "https://optimus8.cafe24.com"
)


def cors_origins() -> list[str]:
    """CORS 허용 origin 목록 — 쉼표 구분 CSV → list.

    환경변수 CORS_ORIGINS 미설정 시 기본값 사용. 값 앞뒤 공백 자동 제거.
    """
    raw = get("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS) or _DEFAULT_CORS_ORIGINS
    return [o.strip() for o in raw.split(",") if o.strip()]


# ─────────────────────────────────────────────────────────────────
# DATABASE_URL 추상화 (Phase D 주 8 · 2026-07-31)
#   Stage 3 Postgres 전환 대비 · 진입점 단일화.
#   db.py 는 본 함수만 호출 · scheme 보정도 여기서.
# ─────────────────────────────────────────────────────────────────

_DEFAULT_SQLITE_ABS_PATH = _BACKEND_DIR / "data" / "tradebot.db"
_DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{_DEFAULT_SQLITE_ABS_PATH}"


def database_url() -> str:
    """DATABASE_URL 반환 · async 드라이버 스킴 자동 보정 · sqlite 상대경로 절대화.

    - 기본값은 backend/data/tradebot.db 절대 경로 (CWD 무관)
    - sqlite:///./... 상대경로는 backend/ 기준으로 승격 (CWD 무관 안정)
    - sqlite:/// → sqlite+aiosqlite:/// (async 강제)
    - postgresql:// → postgresql+asyncpg:// (async 강제)
    - 그 외는 그대로 반환.

    Postgres 전환 시 SOPS/env 의 DATABASE_URL 만 갱신하면 됨.
    """
    url = get("DATABASE_URL", _DEFAULT_DATABASE_URL) or _DEFAULT_DATABASE_URL
    # sqlite 상대경로 절대화 (예: sqlite:///./data/tradebot.db → sqlite:///{backend}/data/tradebot.db)
    _SQLITE_REL_PREFIXES = (
        ("sqlite:///./", "sqlite:///"),
        ("sqlite+aiosqlite:///./", "sqlite+aiosqlite:///"),
    )
    for src, dst in _SQLITE_REL_PREFIXES:
        if url.startswith(src):
            rel = url[len(src):]
            abs_path = (_BACKEND_DIR / rel).resolve()
            url = f"{dst}{abs_path}"
            break
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# ─────────────────────────────────────────────────────────────────
# 관측성 (Phase D 주 8 · 2026-07-31)
#   DSN 미설정 시 no-op · 코드는 항상 이 함수만 호출.
# ─────────────────────────────────────────────────────────────────


def sentry_dsn() -> str | None:
    """Sentry DSN · 미설정 시 None (no-op)."""
    v = (get("SENTRY_DSN") or "").strip()
    return v or None


def sentry_environment() -> str:
    """Sentry environment 라벨 · APP_ENV 우선, 없으면 'local'."""
    return (get("APP_ENV") or "local").strip() or "local"


def sentry_traces_sample_rate() -> float:
    """트레이스 샘플링 비율 · 기본 0 (성능 이슈 방지 · 필요 시 env 로 조정)."""
    raw = (get("SENTRY_TRACES_SAMPLE_RATE") or "0").strip()
    try:
        v = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, min(1.0, v))
