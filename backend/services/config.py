"""환경 변수·자격증명 로드 (B-2k).

다중 .env 위치 검색 — 사용자가 frontend/.env.local 또는 backend/.env 어디에 두든
자동으로 인식. 우선순위: project root > backend/ > frontend/.

⚠️ 본 모듈은 backend 만 사용. frontend는 Next.js 자체 .env.local 처리.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

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
