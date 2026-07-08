"""VIP 런타임 override (data/vip_overrides.json).

env 는 기본값. UI/API 로 activist 설정을 프로세스 재시작 없이 바꿀 수 있게
override 파일을 tick 마다 재로드한다. 파일이 없으면 빈 dict — env 기본값이 그대로 쓰임.

허용 키 (그 외는 무시):
    activist_enabled: bool
    activist_cik: str
    activist_name: str
    activist_keywords: List[str]

Why 파일 기반: DB 모델 추가는 P-A 스코프 부풀림. 단일 프로세스에서 tick 마다
읽기만 하고 쓰기는 드문(사용자 UI 편집 시) 이라 파일이 적합.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_DIR.parent
_OVERRIDES_PATH = _PROJECT_ROOT / "data" / "vip_overrides.json"

_ALLOWED_KEYS = {
    "activist_enabled",
    "activist_cik",
    "activist_name",
    "activist_keywords",
}


def path() -> Path:
    return _OVERRIDES_PATH


def load() -> Dict[str, Any]:
    """override 파일 로드 (없거나 파싱 실패 → 빈 dict)."""
    try:
        with open(_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning(f"[vip.overrides] 최상위 dict 아님 — 무시: {type(data)}")
            return {}
        return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"[vip.overrides] load 실패 — 빈 dict: {e}")
        return {}


def _normalize_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    """허용 키만 골라내고 타입 정제. activist_keywords 는 List[str] 로 강제."""
    clean: Dict[str, Any] = {}
    for k, v in patch.items():
        if k not in _ALLOWED_KEYS:
            continue
        if k == "activist_enabled":
            clean[k] = bool(v)
        elif k == "activist_keywords":
            if isinstance(v, str):
                clean[k] = [tok.strip().upper() for tok in v.split(",") if tok.strip()]
            elif isinstance(v, list):
                clean[k] = [str(x).strip().upper() for x in v if str(x).strip()]
            else:
                clean[k] = []
        elif v is None:
            clean[k] = ""
        else:
            clean[k] = str(v).strip()
    return clean


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """기존 override 위에 patch 를 병합 저장. 저장된 최종 dict 반환.

    빈 문자열/빈 리스트를 넘기면 해당 키는 override 삭제 (env 기본값 복귀).
    """
    existing = load()
    clean = _normalize_patch(patch)

    for k, v in clean.items():
        if v == "" or (isinstance(v, list) and not v):
            existing.pop(k, None)
        else:
            existing[k] = v

    try:
        _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OVERRIDES_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _OVERRIDES_PATH)
    except Exception as e:
        logger.warning(f"[vip.overrides] save 실패: {e}")
    return existing
