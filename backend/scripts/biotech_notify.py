"""WP69-3h · biotech 파이프 실패 알림 (biotech 이름공간 · config 로더).

- shell source 없이 config 로더로 TELEGRAM_BOT_TOKEN / CHAT_ID 로드
  (setup_secure_logging 자동 · config.load_env_once 로 .env 파싱)
- notifier.TelegramNotifier 재사용 (기존 응용 무변경)
- daily_server.sh 각 단계 실패 시 이 스크립트를 호출 (`python -m ...`)

사용:
    # 실패 알림
    python -m backend.scripts.biotech_notify critical "매일 작업 실패 · {step}" "원인: exit 11" --step candidates --next 07:00
    # 정보 (테스트)
    python -m backend.scripts.biotech_notify info "biotech daily test" "dry-run 7/7"
"""
from __future__ import annotations

from backend.services import config
from backend.scripts._biotech_bootstrap import require_secure_logging

import argparse
import asyncio
import logging
import sys


LOG = logging.getLogger("biotech_notify")


def build_message(level: str, title: str, body: str, step: str | None = None,
                  next_spec: str | None = None, now=None) -> tuple[str, str]:
    """셸이 넘긴 제목·본문 → 바이오 알림 틀 (1023-05). `{step}` 은 단계 한국어 이름으로 바꾼다."""
    from backend.services import alert_text as at

    if step is not None:
        step_text = at.BIOTECH_STEP.get(step, step)
        title, body = title.replace("{step}", step_text), body.replace("{step}", step_text)
    lines = [at.esc(line) for line in body.split("\n") if line.strip()]
    return at.biotech_message(level, at.esc(title), lines, next_spec=next_spec, now=now)


async def _send(level: str, title: str, body: str, category: str = "biotech") -> bool:
    from backend.services.notifier import TelegramNotifier
    n = TelegramNotifier()
    if level == "critical":
        return await n.send_critical(title=title, body=body, category=category)
    if level == "warning":
        return await n.send_warning(title=title, body=body, category=category)
    return await n.send_info(title=title, body=body, category=category)


def main() -> int:
    require_secure_logging()
    config.load_env_once()  # .env → os.environ (홑따옴표·특수문자 안전 · python-dotenv 파서)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("level", choices=["critical", "warning", "info"])
    p.add_argument("title")
    p.add_argument("body")
    p.add_argument("--category", default="biotech", help="알림 종류 (알림 설정 화면 · 기본 biotech)")
    p.add_argument("--step", default=None, help="단계 코드 · 제목·본문의 {step} 을 한국어 이름으로")
    p.add_argument("--next", dest="next_spec", default=None, help='다음 실행 · "07:00" 또는 "mon 06:00"')
    args = p.parse_args()
    title, body = build_message(args.level, args.title, args.body, step=args.step, next_spec=args.next_spec)

    # 값 노출 없이 존재 여부만 로깅
    import os
    has_token = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())
    has_chat = bool(os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    if not (has_token and has_chat):
        LOG.error("텔레그램 자격증명 부재 · token_present=%s chat_present=%s", has_token, has_chat)
        return 2

    try:
        ok = asyncio.run(_send(args.level, title, body, args.category))
    except Exception as e:
        LOG.error("발송 예외 · %s", e.__class__.__name__)
        return 3
    if not ok:
        LOG.error("발송 실패 (Telegram API 응답 실패)")
        return 4
    LOG.info("발송 성공 · level=%s", args.level)
    return 0


if __name__ == "__main__":
    sys.exit(main())
