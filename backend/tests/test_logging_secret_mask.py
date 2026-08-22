"""자격증명 마스킹 필터 단위 테스트 (2026-08-22 · DART_API_KEY 사고 대응).

CRITICAL: 이 테스트가 실패하면 · 로그에 자격증명 재노출 위험. 배포 전 필수 통과.
"""
from __future__ import annotations

import io
import logging

from backend.services.logging_setup import (
    SecretMaskingFilter,
    _MASK_PATTERN,
    setup_secure_logging,
)


def test_mask_pattern_covers_dart_crtfc_key():
    """DART opendart URL 의 crtfc_key 마스킹 (fake 40자 hex 사용 · gitleaks 회피)."""
    fake_key = "0" * 40  # 실키 아님 · 형식만 모사
    url = (
        f"https://opendart.fss.or.kr/api/list.json"
        f"?crtfc_key={fake_key}"
        f"&bgn_de=20260814&end_de=20260821"
    )
    masked = _MASK_PATTERN.sub(r"\1=***MASKED***", url)
    assert "***MASKED***" in masked
    assert fake_key not in masked
    # 다른 파라미터는 보존
    assert "bgn_de=20260814" in masked


def test_mask_pattern_covers_common_secret_labels():
    """일반적 자격증명 라벨 (api_key · token · secret · password) 마스킹."""
    samples = [
        ("api_key=abc123XYZ", "api_key=***MASKED***"),
        ("api-key=xyz", "api-key=***MASKED***"),
        ("apikey=deadbeef", "apikey=***MASKED***"),
        ("token=eyJhbGciOi", "token=***MASKED***"),
        ("secret=hunter2", "secret=***MASKED***"),
        ("password=hunter2", "password=***MASKED***"),
        ("Password=Hunter2", "Password=***MASKED***"),  # 대소문자 무관
    ]
    for src, expected in samples:
        assert _MASK_PATTERN.sub(r"\1=***MASKED***", src) == expected


def test_masking_via_root_logger_stream():
    """루트 로거 경로에서 실제 마스킹 발동 확인 (crtfc_key 실사고 URL)."""
    setup_secure_logging()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(SecretMaskingFilter())

    logger = logging.getLogger("test.mask.stream")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info(
            "HTTP Request: GET https://opendart.fss.or.kr/api/list.json"
            "?crtfc_key=deadbeef012345678901234567890123456789012345"
            "&bgn_de=20260821 HTTP/1.1"
        )
    finally:
        logger.removeHandler(handler)

    out = stream.getvalue()
    assert "***MASKED***" in out
    assert "deadbeef" not in out
    assert "bgn_de=20260821" in out


def test_httpx_logger_warning_level_after_setup():
    """httpx / httpcore 로거가 WARNING 승격됐는지 확인."""
    setup_secure_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_setup_is_idempotent():
    """여러 번 호출해도 필터 중복 등록 안 됨."""
    setup_secure_logging()
    setup_secure_logging()
    setup_secure_logging()
    root = logging.getLogger()
    filters = [f for f in root.filters if isinstance(f, SecretMaskingFilter)]
    assert len(filters) == 1


def test_masking_via_child_logger_bypasses_root_filter_but_factory_covers():
    """CRITICAL 회귀 · 2026-08-22 probe 실증 실패 사고.

    Python logging 규칙: Logger.filter 는 자기 로거의 record 만 체크.
    하위 로거 (httpx 등) record 는 root logger 의 filter 를 통과하지 않음.
    → setLogRecordFactory 후킹으로 record 생성 자체를 마스킹.

    실증: httpx 자체 logger 로 crtfc_key 포함 URL 로그 → 마스킹 발동.
    """
    setup_secure_logging()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    # 이 handler 에는 filter 명시 미부착 · setLogRecordFactory 만으로 커버돼야 함

    fake_key = "1" * 40
    child = logging.getLogger("httpx")  # 실 사고 로거
    prev_level = child.level
    child.setLevel(logging.INFO)  # WARNING 승격 무시 · factory 마스킹 순수 검증
    child.addHandler(handler)
    try:
        child.info(
            f"HTTP Request: GET https://opendart.fss.or.kr/api/list.json"
            f"?crtfc_key={fake_key}&bgn_de=20260822 HTTP/1.1 \"HTTP/1.1 200 OK\""
        )
    finally:
        child.removeHandler(handler)
        child.setLevel(prev_level)

    out = stream.getvalue()
    assert "***MASKED***" in out, f"마스킹 미발동 · out={out!r}"
    assert fake_key not in out, f"평문 재노출 · out={out!r}"
    assert "bgn_de=20260822" in out  # 타 파라미터 보존


def test_masking_via_basicConfig_new_handler_covered_by_factory():
    """setup 이후 basicConfig 로 추가된 handler 도 factory 로 마스킹 커버."""
    setup_secure_logging()
    # 새 stream handler · filter 명시 없음 · basicConfig 유사
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))

    fake_key = "2" * 40
    child = logging.getLogger("test.new_handler")
    child.setLevel(logging.INFO)
    child.addHandler(handler)
    try:
        child.info(f"probe crtfc_key={fake_key} tail")
    finally:
        child.removeHandler(handler)

    out = stream.getvalue()
    assert "***MASKED***" in out
    assert fake_key not in out
