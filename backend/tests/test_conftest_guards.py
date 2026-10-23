"""tests/conftest.py 보호 장치 회귀 · 테스트가 실 DB 파일·실 텔레그램을 가리키지 않는지."""
import os

from backend.services import db


def test_engine_is_in_memory():
    assert str(db.engine.url).endswith(":memory:")


def test_telegram_env_blank():
    assert os.environ.get("TELEGRAM_BOT_TOKEN", "") == ""
    assert os.environ.get("TELEGRAM_CHAT_ID", "") == ""


def test_telegram_send_paths_stubbed():
    # _no_real_telegram 이 발송 경로를 모두 막았는지 (이름이 바뀌면 여기서 드러남)
    # meme 알림은 2026-10-23 부터 TelegramNotifier 를 거침 (1022-09 Task 5)
    from backend.discovery.meme_watch import alert
    from backend.services import notifier, telegram_notifier

    assert notifier.TelegramNotifier.send.__name__ == "_false"
    assert alert.TelegramNotifier is notifier.TelegramNotifier
    assert telegram_notifier.send_message.__name__ == "_false"
