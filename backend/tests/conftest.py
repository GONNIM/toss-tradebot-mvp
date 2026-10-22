import os

# backend/.env 의 실 DB·텔레그램 값이 services.config import 시점에 먼저 잡히지 않게 어떤 backend import 보다 먼저 덮어쓴다 (외부에서 DATABASE_URL 을 지정해도 무시함).
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""



import pytest as _pytest_wp98


@_pytest_wp98.fixture(autouse=True)
def _no_tiingo_local_seed(monkeypatch):
    """WP98 · Tiingo 장부 씨앗 (docs 실파일) 이 테스트 장부에 섞이지 않게 · 필요한 테스트는 SEED_DIR 을 직접 지정."""
    try:
        from backend.scripts import biotech_h6_collect_prices as _h6
        monkeypatch.setattr(_h6, "SEED_DIR", None)
    except Exception:
        pass


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "real_notifier_send: TelegramNotifier.send 를 stub 하지 않음 (테스트가 httpx 를 직접 가짜로 바꿀 때만 · config 를 직접 넘기는 테스트는 httpx.AsyncClient 를 반드시 가짜로 바꾼다)",
    )


@_pytest_wp98.fixture(autouse=True)
def _no_real_telegram(monkeypatch, request):
    """services/config.py 가 import 때 backend/.env 를 읽어 테스트가 실제 봇으로 발송함 · env 를 비우고 발송 함수를 막는다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")

    import importlib

    async def _false(*args, **kwargs):
        return False

    keep_send = request.node.get_closest_marker("real_notifier_send") is not None
    for mod_name, attr in (
        *(() if keep_send else (("backend.services.notifier", "TelegramNotifier.send"),)),
        ("backend.discovery.meme_watch.alert", "send_message"),
        ("backend.services.telegram_notifier", "send_message"),
    ):
        try:
            mod = importlib.import_module(mod_name)
            if "." in attr:
                cls_name, fn = attr.split(".")
                monkeypatch.setattr(getattr(mod, cls_name), fn, _false)
            else:
                monkeypatch.setattr(mod, attr, _false)
        except ImportError:
            pass
