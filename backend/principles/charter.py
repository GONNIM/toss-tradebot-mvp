"""헌장 JSON 로더 · 캐시 · 임계값 조회 helper.

charter.json 은 SSOT. 임계값 수정은 파일 편집 + revision_history 항목 추가로만 이뤄짐.
코드에서는 절대 하드코딩 안 함.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CHARTER_PATH = Path(__file__).resolve().parent / "charter.json"


@lru_cache(maxsize=1)
def load_charter() -> dict[str, Any]:
    """헌장 JSON 로드 (프로세스 lifecycle 동안 캐시).

    파일 변경 후 반영은 프로세스 재시작 (systemd restart tradebot-api) 필요.
    """
    return json.loads(CHARTER_PATH.read_text(encoding="utf-8"))


def get_threshold(principle_code: str, key: str) -> Any:
    """헌장에서 특정 원칙의 임계값 조회 · 하드코딩 방지.

    Args:
        principle_code: 'per', 'shareholder_return', 'dividend_continuity',
                        'financial_soundness', 'diversification'
        key: threshold dict 안의 키명 (예: 'per_ttm_max')

    Raises:
        KeyError: 원칙 미존재 또는 threshold 키 미존재
    """
    charter = load_charter()
    for p in charter.get("principles", []):
        if p.get("code") == principle_code:
            thresholds = p.get("thresholds", {})
            if key not in thresholds:
                raise KeyError(
                    f"principle '{principle_code}' 에 threshold '{key}' 없음 · charter.json 확인"
                )
            return thresholds[key]
    raise KeyError(f"principle code '{principle_code}' 헌장에 없음")


def get_exempt_signal_types() -> list[str]:
    """게이트 화이트리스트 · 명시적 면제 signal type 목록."""
    charter = load_charter()
    return charter.get("gate_policy", {}).get("exempt_signal_types", [])


def get_manual_override_financial_sector(ticker: str) -> bool | None:
    """티커별 금융업 수동 강제 지정 조회.

    Returns:
        True/False 로 override 되어 있으면 값 반환 · 미지정이면 None (auto-detect 사용).
    """
    charter = load_charter()
    entries = (
        charter.get("manual_overrides", {})
        .get("financial_sector", {})
        .get("entries", [])
    )
    for e in entries:
        if e.get("ticker") == ticker:
            return bool(e.get("value"))
    return None
