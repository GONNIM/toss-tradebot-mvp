"""Activist Universe override 파일 · UI 편집기 대상.

파일: data/activist_universe_overrides.json
스키마:
    {
      "activists": [
        {
          "key": "trian_fund_management",   # 필수 · 안정 식별자
          "name": "Trian Fund Management",  # 선택 · 표기 override
          "country": "US",                  # 선택
          "tier": 1,                        # 선택
          "cik": "0001345471",              # 선택 (신규 항목은 필수)
          "corp_code": "TBD",               # 선택 (KR)
          "keywords": ["WEN", "WENDY"],     # 선택
          "enabled": true                   # 선택 · false 면 폴링에서 skip
        }
      ],
      "disabled_keys": ["marcato_capital"]  # 완전 제거 (Universe 목록에서 사라짐)
    }

Why 파일 기반: [[project_wen_vip_watch]] 의 vip_overrides.json 패턴 재활용.
사용자 UI 편집 → 재시작 없이 다음 tick 에서 반영.
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
_OVERRIDES_PATH = _PROJECT_ROOT / "data" / "activist_universe_overrides.json"


def path() -> Path:
    return _OVERRIDES_PATH


def load() -> Dict[str, Any]:
    try:
        with open(_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f"[activist.overrides] load 실패 — 빈 dict: {e}")
        return {}


def _normalize_activist(entry: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for k in ("key", "name", "country", "cik", "corp_code"):
        if k in entry and entry[k] is not None:
            clean[k] = str(entry[k]).strip()
    if "tier" in entry:
        try:
            clean["tier"] = int(entry["tier"])
        except (TypeError, ValueError):
            pass
    if "enabled" in entry:
        clean["enabled"] = bool(entry["enabled"])
    if "keywords" in entry:
        kw = entry["keywords"]
        if isinstance(kw, str):
            clean["keywords"] = [t.strip().upper() for t in kw.split(",") if t.strip()]
        elif isinstance(kw, list):
            clean["keywords"] = [str(x).strip().upper() for x in kw if str(x).strip()]
    return clean


def upsert_activist(entry: Dict[str, Any]) -> Dict[str, Any]:
    """key 기준 upsert. 저장된 최종 dict 반환."""
    key = entry.get("key")
    if not key:
        raise ValueError("activist entry 는 'key' 필수")
    clean = _normalize_activist(entry)

    existing = load()
    activists = existing.setdefault("activists", [])
    # 기존 key 있으면 교체
    for i, a in enumerate(activists):
        if a.get("key") == key:
            activists[i] = clean
            break
    else:
        activists.append(clean)

    _save(existing)
    return existing


def delete_activist(key: str) -> Dict[str, Any]:
    """activist 완전 제거 (disabled_keys 에 등재 · 다음 로드 시 제외)."""
    existing = load()
    disabled = existing.setdefault("disabled_keys", [])
    if key not in disabled:
        disabled.append(key)
    # activists 배열에서도 제거
    existing["activists"] = [
        a for a in (existing.get("activists") or []) if a.get("key") != key
    ]
    _save(existing)
    return existing


def _save(data: Dict[str, Any]) -> None:
    try:
        _OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _OVERRIDES_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _OVERRIDES_PATH)
    except Exception as e:
        logger.warning(f"[activist.overrides] save 실패: {e}")
