"""백업 지연 알림 (1105-06) — 매일 09:10 KST API 스케줄러 잡.

`scripts/backup.sh` 는 매일 03:30 KST (cron) 에 DB 스냅샷을 만들고, 모든 검사를 통과하면
`<프로젝트>/.backup/LATEST` 링크를 그 스냅샷 폴더 (YYYYMMDD_HHMMSS · 서버 시각) 로 바꾼다.
백업이 실패하면 LATEST 가 그대로 남지만 지금까지는 알림이 없었다.

판단 (Fable 1105-04-01 권고 5):
- LATEST 가 없거나 가리키는 폴더가 없음 → 알림
- 그 폴더에 성공 표식 `.ok` 가 없음 → 알림
- 스냅샷 시각 (폴더 이름 · 없으면 폴더 수정 시각) 이 36시간보다 오래됨 → 알림
알림은 텔레그램 「시스템 경고」 (끌 수 없는 종류) · 잡이 하루 한 번이라 따로 중복 막기는 하지 않는다.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
STALE_HOURS = 36


def _backup_dir() -> Path:
    """backup.sh 와 같은 규칙 · BACKUP_DIR (상대 경로면 프로젝트 기준) · 기본 .backup."""
    raw = os.environ.get("BACKUP_DIR") or ".backup"
    p = Path(raw)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def _snapshot_time(snap: Path) -> datetime:
    """폴더 이름 YYYYMMDD_HHMMSS (서버 시각 · 운영은 KST) → aware datetime. 이름이 다르면 수정 시각."""
    try:
        return datetime.strptime(snap.name, "%Y%m%d_%H%M%S").replace(tzinfo=_KST)
    except ValueError:
        return datetime.fromtimestamp(snap.stat().st_mtime, tz=timezone.utc)


def backup_problem(base: Optional[Path] = None, now: Optional[datetime] = None) -> Optional[str]:
    """문제가 있으면 사용자에게 보일 한 문장 · 없으면 None."""
    base = base or _backup_dir()
    now = now or datetime.now(tz=timezone.utc)
    latest = base / "LATEST"
    if not latest.exists():
        return "최근 백업 표시(LATEST)가 없습니다. 백업이 한 번도 성공하지 않았거나 표시가 지워졌습니다."
    snap = latest.resolve()
    if not snap.is_dir():
        return "최근 백업 표시(LATEST)가 가리키는 폴더가 없습니다."
    if not (snap / ".ok").exists():
        return f"최근 백업({snap.name})에 성공 표식이 없습니다."
    age = now - _snapshot_time(snap)
    if age > timedelta(hours=STALE_HOURS):
        hours = int(age.total_seconds() // 3600)
        return f"마지막 성공 백업({snap.name})이 {hours}시간 전입니다. 매일 03:30 백업이 {STALE_HOURS}시간 넘게 성공하지 않았습니다."
    return None


async def check_backup_fresh() -> dict:
    """스케줄러 잡 · 문제가 있으면 WARNING 로그 + 텔레그램."""
    try:
        problem = backup_problem()
    except Exception as exc:  # noqa: BLE001
        problem = f"백업 상태를 읽지 못했습니다 ({type(exc).__name__})."
    if problem is None:
        logger.info("[backup_watch] 최근 백업 정상")
        return {"ok": True}
    logger.warning("[backup_watch] %s", problem)
    try:
        from backend.services import alert_text as at
        from backend.services.notifier import TelegramNotifier

        await TelegramNotifier().send_warning(
            at.title("system", "DB 백업 늦음", "🗄️"),
            f"{problem}\n로그: /var/log/toss-tradebot/backup.log",
            category="system",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[backup_watch] 알림 실패 · %s", exc)
    return {"ok": False, "problem": problem}
