"""WP8 · biotech 스크립트 공용 부팅 (setup_secure_logging 강제).

용도
- 모든 biotech_*.py 스크립트 main() 첫 줄에서 `require_secure_logging()` 호출
- 호출 안 하면 SystemExit · 자격증명 노출 재발 방지 (2026-09-08 · DART 키 4차 재발 사고)

원칙
- 인프라 층 (config 재사용 허용 · B47) · 응용 로직 재사용 아님
- config 는 import 만으로 setup_secure_logging() 자동 실행 (backend/services/config.py:20)
- require_secure_logging() 은 idempotent
"""
from __future__ import annotations

import glob
import logging
import os
import re
import sys
from pathlib import Path


def require_secure_logging() -> None:
    """자격증명 마스킹 필터 로드 검증.

    실패 조건 (SystemExit):
    - backend.services.config 미로드 (import 순서 오류)
    - SecretMaskingFilter 루트 로거 등록 확인 실패
    - httpx logger level WARNING 이상 확인 실패
    """
    try:
        from backend.services import config  # noqa: F401 · import side-effect
        from backend.services.logging_setup import SecretMaskingFilter
    except Exception as e:
        print(f"CRITICAL: biotech bootstrap failed · backend.services import: {e}",
              file=sys.stderr)
        raise SystemExit(97)

    root = logging.getLogger()
    filters_ok = any(isinstance(f, SecretMaskingFilter) for f in root.filters) or any(
        isinstance(f, SecretMaskingFilter)
        for h in root.handlers
        for f in h.filters
    )
    httpx_level = logging.getLogger("httpx").getEffectiveLevel()
    if not filters_ok or httpx_level < logging.WARNING:
        print(
            "CRITICAL: setup_secure_logging not active · "
            f"masking={filters_ok} httpx_level={httpx_level} · aborting.",
            file=sys.stderr,
        )
        raise SystemExit(97)


def data_sha(data_dir: Path | str, anchor_pattern: str = "h3_targets_v2_*.csv") -> str:
    """일일 파이프용 · 데이터 파일 최신 sha 추출 (git_sha 와 별개).

    git commit 후 git_sha 가 바뀌면 이전 sha 로 저장된 데이터 파일 참조가 깨진다.
    파이프 진입점은 실행 시점 커밋이 아닌 **실제 존재하는 최신 데이터 파일 sha** 를 써야 한다.

    - 원칙: 데이터 재현성은 `git log --follow` + 원시 데이터 재수집으로 확보 (봉인 파일에는 실행 sha 병기)
    - fallback 순서: (1) anchor_pattern 최신 mtime 파일의 sha 추출 → (2) git_sha 원본 그대로

    사용 예:
        from backend.scripts._biotech_bootstrap import data_sha
        sha = data_sha(DATA_DIR)  # h3_targets_v2_*.csv 중 최신
    """
    data_dir = Path(data_dir)
    matches = sorted(data_dir.glob(anchor_pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not matches:
        return ""
    m = re.search(r"_([a-f0-9]{7,40})\.csv$", matches[0].name)
    return m.group(1) if m else ""
