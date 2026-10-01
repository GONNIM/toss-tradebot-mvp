"""WP93 · BIOTECH_API_ONLY=1 이면 스케줄러 미시작 · 기본값은 그대로 (시작 함수 코드 검사)."""
from __future__ import annotations

from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "api" / "main.py").read_text()


def test_api_only_branch_returns_before_scheduler():
    body = SRC[SRC.index("async def lifespan"):SRC.index("app = FastAPI(")]
    branch = body.index('environ.get("BIOTECH_API_ONLY"')
    assert branch < body.index("AsyncIOScheduler(")            # 스케줄러 만들기 전에 분기
    seg = body[branch:body.index("AsyncIOScheduler(")]
    assert "yield" in seg and "return" in seg and "scheduler.start()" not in seg


def test_default_path_unchanged():
    body = SRC[SRC.index("async def lifespan"):SRC.index("app = FastAPI(")]
    assert body.count("scheduler.start()") == 1 and "register_sniper_jobs(scheduler)" in body
