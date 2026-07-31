"""관측성 초기화 · Phase D 주 8 · 2026-07-31.

Sentry SDK · DSN 미설정 시 no-op (init 스킵).
FastAPI lifespan startup 에서 1회 호출.

env:
- SENTRY_DSN                 · 미설정 시 완전 비활성
- APP_ENV                    · 태그 (production/staging/local · 기본 local)
- SENTRY_TRACES_SAMPLE_RATE  · 성능 트레이싱 샘플링 (0~1 · 기본 0)

설계:
- 초기화 실패해도 앱 부팅 막지 않음 (경고 로그 후 계속).
- 이후 코드는 sentry_sdk 직접 import 하여 capture_exception 등 사용 가능.
- 미init 상태에서 capture_exception 호출은 sentry-sdk 가 안전하게 무시.
"""
from __future__ import annotations

import logging

from backend.services import config

logger = logging.getLogger(__name__)

_INITIALIZED = False


def init_sentry() -> bool:
    """Sentry 초기화 · 성공 시 True · DSN 없거나 오류 시 False.

    idempotent · 여러 번 호출 안전 (첫 성공 후 skip).
    """
    global _INITIALIZED
    if _INITIALIZED:
        return True

    dsn = config.sentry_dsn()
    if not dsn:
        logger.info("[observability] SENTRY_DSN 미설정 · Sentry 비활성 (no-op)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError as exc:
        logger.warning("[observability] sentry-sdk 미설치 · %s", exc)
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=config.sentry_environment(),
            traces_sample_rate=config.sentry_traces_sample_rate(),
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
            # 세션 토큰·감사 이벤트는 detail 필드에 담김. 필요 시 PII 스크러버 확장.
            send_default_pii=False,
        )
        _INITIALIZED = True
        logger.info(
            "[observability] Sentry 활성 · env=%s · traces_sample_rate=%.2f",
            config.sentry_environment(),
            config.sentry_traces_sample_rate(),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[observability] Sentry 초기화 실패 · %s", exc)
        return False
