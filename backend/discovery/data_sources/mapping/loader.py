"""17품목 ↔ KRX 매핑 YAML 로더.

YAML 위치: backend/discovery/data_sources/mapping/mti_to_krx.yaml
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Optional

import yaml

DEFAULT_YAML_PATH = Path(__file__).resolve().parent / "mti_to_krx.yaml"


class MappingError(Exception):
    """매핑 YAML 로드/조회 실패."""


@dataclass(frozen=True)
class MappingTicker:
    item: str                # 'item' 키 (예: '반도체')
    code: str                # KRX 6자리
    name: str
    export_ratio_hint: float  # 0.0~1.0 (DART 보강 전 임시값)
    notes: Optional[str] = None


@lru_cache(maxsize=4)
def load_mapping(yaml_path: Optional[Path] = None) -> dict:
    """YAML 파일 → dict.

    캐시 — 같은 경로 재호출 시 디스크 안 읽음.
    """
    path = yaml_path or DEFAULT_YAML_PATH
    if not path.exists():
        raise MappingError(f"매핑 YAML 미존재: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if "items" not in data:
        raise MappingError(f"매핑 YAML 'items' 키 부재: {path}")
    return data


def tickers_for_item(item: str, yaml_path: Optional[Path] = None) -> list[MappingTicker]:
    """품목 → 종목 리스트."""
    data = load_mapping(yaml_path)
    item_data = data["items"].get(item)
    if item_data is None:
        raise MappingError(f"품목 매핑 없음: {item}")
    out: list[MappingTicker] = []
    for t in item_data.get("tickers", []):
        out.append(
            MappingTicker(
                item=item,
                code=t["code"],
                name=t["name"],
                export_ratio_hint=float(t.get("export_ratio_hint", 0.5)),
                notes=t.get("notes"),
            )
        )
    return out


def iter_all_tickers(yaml_path: Optional[Path] = None) -> Iterator[MappingTicker]:
    """전체 매핑 종목 순회 (중복 코드 가능 — 한 종목이 여러 품목)."""
    data = load_mapping(yaml_path)
    for item, item_data in data["items"].items():
        for t in item_data.get("tickers", []):
            yield MappingTicker(
                item=item,
                code=t["code"],
                name=t["name"],
                export_ratio_hint=float(t.get("export_ratio_hint", 0.5)),
                notes=t.get("notes"),
            )
