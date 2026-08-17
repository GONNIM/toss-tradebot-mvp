"""Principles 라우트 (2026-08-17 · v1.0).

엔드포인트:
  GET /charter — 헌장 JSON 그대로 반환 (frontend 정적 렌더용)

향후 (v1.1 / 다음 단계):
  GET /screener/latest — 최신 스크리너 결과
  GET /gate/logs — 게이트 차단 이력
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.principles.charter import load_charter

router = APIRouter()


@router.get("/charter")
async def get_charter() -> dict:
    """헌장 JSON · frontend 가 fetch 하여 렌더."""
    return load_charter()
