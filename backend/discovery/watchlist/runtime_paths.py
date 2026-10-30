"""Watchlist 런타임 파일 경로 · 저장소 밖에 둔다 (배포 때 저장소를 덮어써도 지워지지 않게 · 1030-04).

우선순위 (biotech 의 backend/scripts/_biotech_paths.py 와 같은 관례):
    WATCHLIST_RUNTIME_DIR (env · 테스트·특별 배치)
    > BIOTECH_RUNTIME_DIR/watchlist (서버: /root/toss-tradebot-mvp/var/biotech/watchlist)
    > backend/data/watchlist (로컬 · data/ 는 .gitignore)
환경변수는 호출 때마다 읽는다 (import 때 굳히면 테스트가 바꿀 수 없다).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_LOCAL_DIR = Path(__file__).resolve().parents[2] / "data" / "watchlist"


def runtime_dir() -> Path:
    explicit = os.environ.get("WATCHLIST_RUNTIME_DIR", "").strip()
    if explicit:
        return Path(explicit)
    biotech = os.environ.get("BIOTECH_RUNTIME_DIR", "").strip()
    if biotech:
        return Path(biotech) / "watchlist"
    return _LOCAL_DIR


def read_json(name: str) -> Optional[Any]:
    path = runtime_dir() / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("[watchlist] 런타임 파일 읽기 실패 · %s · %s", name, exc)
        return None


def write_json(name: str, data: Any) -> bool:
    """임시 파일에 쓴 뒤 교체 (쓰다 끊겨도 옛 파일이 남는다)."""
    path = runtime_dir() / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as exc:
        logger.warning("[watchlist] 런타임 파일 쓰기 실패 · %s · %s", name, exc)
        return False
