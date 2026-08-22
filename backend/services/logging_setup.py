"""자격증명 노출 방지 로깅 설정 (2026-08-22 · DART_API_KEY 사고 대응).

앱 부팅 시 1회 호출 · idempotent.

기능
----
1. httpx / httpcore 로거 WARNING 승격
   - httpx INFO 는 요청 URL 전체 (query string 포함) 를 로깅 → crtfc_key 등 노출
2. 루트 로거 + 모든 핸들러에 SecretMaskingFilter 장착
   - `key=value` 형태의 자격증명 파라미터를 `key=***MASKED***` 로 치환
   - 대상 라벨: crtfc_key, api_key, api-key, apikey, token, secret, password

특징
----
- idempotent · 여러 번 호출해도 필터 중복 등록 안 됨
- side-effect 최소화 · config 모듈 import 시 자동 호출 (아래 config.py 참조)
- 향후 신규 자격증명 파라미터 추가 시 _MASK_PATTERN 만 갱신
"""
from __future__ import annotations

import logging
import re

_MASK_PATTERN = re.compile(
    r"(crtfc_key|api[_-]?key|apikey|token|secret|password)=[^&\s]+",
    re.IGNORECASE,
)
_MASKED_REPL = r"\1=***MASKED***"


def _mask(v):
    if isinstance(v, str):
        return _MASK_PATTERN.sub(_MASKED_REPL, v)
    return v


class SecretMaskingFilter(logging.Filter):
    """로그 record 의 msg / args 에서 자격증명 파라미터 마스킹."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = _mask(record.msg)
        except Exception:
            pass
        if record.args:
            try:
                if isinstance(record.args, tuple):
                    record.args = tuple(_mask(a) for a in record.args)
                elif isinstance(record.args, dict):
                    record.args = {k: _mask(v) for k, v in record.args.items()}
            except Exception:
                pass
        return True


_QUIET_LOGGERS = (
    "httpx",      # 요청 URL INFO 로그 억제
    "httpcore",   # httpx 내부
)


def setup_secure_logging() -> None:
    """앱 부팅 시 1회 호출 · idempotent.

    - httpx / httpcore 로거 → WARNING (INFO URL 로그 억제 · 1차 방어)
    - logging.setLogRecordFactory 후킹 → 모든 로거·모든 record 마스킹 (2차 방어)
      Python logging 규칙상 Logger.filter 는 자기 로거의 record 만 체크 ·
      하위 로거 (httpx 등) record 가 상위 filter 를 통과하지 않는 문제 회피.
    - 루트 로거 및 모든 handler → SecretMaskingFilter 장착 (3차 방어 · 백업)
    """
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _install_masking_record_factory()

    root = logging.getLogger()
    if not any(isinstance(f, SecretMaskingFilter) for f in root.filters):
        root.addFilter(SecretMaskingFilter())
    for h in list(root.handlers):
        if not any(isinstance(f, SecretMaskingFilter) for f in h.filters):
            h.addFilter(SecretMaskingFilter())


def _install_masking_record_factory() -> None:
    """logging.setLogRecordFactory 후킹 · idempotent (sentinel 로 중복 설치 방지).

    setLogRecordFactory 는 모든 record 생성 시 호출 · Logger.filter 를 우회하는
    하위 로거 (httpx 등) record 도 100% 커버.
    """
    if getattr(logging, "_toss_secret_mask_installed", False):
        return
    original_factory = logging.getLogRecordFactory()

    def _masking_factory(*args, **kwargs):
        record = original_factory(*args, **kwargs)
        try:
            record.msg = _mask(record.msg)
        except Exception:
            pass
        if record.args:
            try:
                if isinstance(record.args, tuple):
                    record.args = tuple(_mask(a) for a in record.args)
                elif isinstance(record.args, dict):
                    record.args = {k: _mask(v) for k, v in record.args.items()}
            except Exception:
                pass
        return record

    logging.setLogRecordFactory(_masking_factory)
    logging._toss_secret_mask_installed = True  # type: ignore[attr-defined]
