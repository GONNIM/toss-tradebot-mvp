"""1030-03 · 정해진 시각에 도는 잡(cron)의 늦음 허용과 건너뜀 감시.

왜 필요한가 (docs: .claude/lessons-learned.md 교훈 #3):
- APScheduler 3.x 는 잡마다 `misfire_grace_time` 을 적지 않으면 1초만 기다린다.
  이벤트 루프가 1초 넘게 막히면 그 회차를 「건너뜀」 WARNING 한 줄만 남기고 버린다.
- 06:00 에 serenity crawler 의 동기 git pull · 파일 읽기가 루프를 1.8~5초 막아,
  06:00 국회 잡이 10/31~11/06 7일 모두 돌지 않았다. 아무도 알림을 받지 못했다.

이 모듈이 하는 일:
- 잡마다 쓸 늦음 허용 값 두 가지 (장 시작 전에 끝나야 하는 잡은 짧게).
- 정해진 시각 잡(CronTrigger)이 건너뛰어지면 ERROR 로그 + 텔레그램 시스템 경고 (잡·날짜당 1회).
  interval 잡은 다음 회차가 곧 돌기 때문에 알리지 않는다 (WARNING 로그는 APScheduler 가 그대로 남김).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# 늦음 허용 (초)
GRACE_DEFAULT = 1800       # 30분 · 하루·주·월 단위 잡 기본
GRACE_BEFORE_OPEN = 600    # 10분 · 09:00 개장 전에 끝나야 하는 잡 (08:20 공시 · 08:30 관심 종목 목록) · 장중 매시 잡

# 경고 기준: 이보다 짧은 허용은 루프가 잠깐 막혀도 건너뛴다 (serenity 동기 호출 최악 약 70초)
GRACE_MIN = 120

_sent_keys: set[str] = set()
_tasks: set = set()   # 만든 알림 task 참조 보관 (참조 없는 task 는 수거될 수 있음)


def _is_cron(job: Any) -> bool:
    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception:  # pragma: no cover
        return False
    return isinstance(getattr(job, "trigger", None), CronTrigger)


def missed_alert_text(job_id: str, job_name: str, scheduled: datetime, process: str) -> tuple[str, str]:
    """(제목, 본문) · escape 는 alert_text.title 이 한다."""
    from backend.services import alert_text as at

    when = scheduled.strftime("%m/%d %H:%M")
    title = at.title("system", f"정해진 작업 건너뜀 · {when}", "⏰")
    body = (
        f"「{job_name}」 작업이 정해진 시각({when})에 시작하지 못해 이번 회차를 건너뛰었습니다.\n"
        f"서버가 허용 시간보다 오래 멈춰 있었다는 뜻입니다. 다음 회차는 정해진 시각에 다시 돕니다.\n"
        f"작업 이름: {job_id} · 프로세스: {process}\n"
        f"로그: /var/log/toss-tradebot/{'api' if process == 'api' else 'cron'}.error.log 에서 「was missed by」"
    )
    return title, body


def attach_missed_alert(
    scheduler: Any,
    *,
    process: str,
    send: Optional[Callable[[str, str, str], Any]] = None,
) -> None:
    """scheduler 에 「건너뜀」 감시를 붙인다.

    send(title, body, dedupe_id) 는 시험용 주입. 없으면 TelegramNotifier().send_warning(category="system").
    """
    from apscheduler.events import EVENT_JOB_MISSED

    def _on_missed(event: Any) -> None:
        try:
            job = scheduler.get_job(event.job_id)
            if job is not None and not _is_cron(job):
                return
            scheduled: datetime = event.scheduled_run_time
            key = f"job_missed:{process}:{event.job_id}:{scheduled:%Y%m%d%H%M}"
            if key in _sent_keys:
                return
            _sent_keys.add(key)
            name = getattr(job, "name", None) or event.job_id
            logger.error(
                "[job_watch] 정해진 작업 건너뜀 · id=%s · 예정=%s · process=%s",
                event.job_id, scheduled.isoformat(), process,
            )
            title, body = missed_alert_text(event.job_id, name, scheduled, process)
            coro = _send(title, body, key, send)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                task = loop.create_task(coro)
                _tasks.add(task)
                task.add_done_callback(_tasks.discard)
            else:  # pragma: no cover · AsyncIOScheduler 는 루프 안에서 부른다
                asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001 · 감시가 스케줄러를 멈추면 안 된다
            logger.warning("[job_watch] 건너뜀 감시 실패 · %s", exc)

    scheduler.add_listener(_on_missed, EVENT_JOB_MISSED)


async def _send(title: str, body: str, dedupe_id: str, send: Optional[Callable]) -> None:
    try:
        if send is not None:
            res = send(title, body, dedupe_id)
            if asyncio.iscoroutine(res):
                await res
            return
        from backend.services.notifier import TelegramNotifier

        await TelegramNotifier().send_warning(title, body, category="system", dedupe_id=dedupe_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[job_watch] 건너뜀 알림 실패 · %s", exc)
