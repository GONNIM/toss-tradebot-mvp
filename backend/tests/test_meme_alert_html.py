"""meme 알림 → TelegramNotifier(HTML) 통합 (1022-09 Task 5)."""
from __future__ import annotations

import html
import re
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.discovery.meme_watch import alert as alert_mod


def _score(ticker, s):
    return SimpleNamespace(ticker=ticker, score=s, emoji="🔥🔥", label="BLAZING")


def _intensity(v):
    return SimpleNamespace(intensity=v, emoji="🌋", label="ERUPTING")


def _meta(name, market="US"):
    return SimpleNamespace(name=name, market=market)


def _plain_md(text: str) -> str:
    return re.sub(r"[*_`]", "", text)


def _plain_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def test_html_escapes_name_and_keeps_text():
    md = alert_mod._format_alert("BLAZING", _score("ABCD", 1.2), None, _meta("A&B <X> Corp"), None)
    title, body = alert_mod._to_title_body(md)
    assert "A&amp;B &lt;X&gt;" in title
    assert "<" not in title.replace("&lt;", "")  # 제목은 태그 없이 (notifier 가 <b> 로 감쌈)
    # 변환 전후 글자 내용이 같음 (태그·Markdown 기호 제거 후)
    assert _plain_md(md) == _plain_html(title + "\n" + body)


def test_markdown_marks_become_html_tags():
    _, body = alert_mod._to_title_body("제목\n*굵게* `CODE` _기울임_")
    assert body == "<b>굵게</b> <code>CODE</code> <i>기울임</i>"


@pytest_asyncio.fixture
async def meme_env(monkeypatch):
    from backend.services.db import get_session, init_db
    from backend.services.models import MemeAlertHistory

    await init_db()
    async with get_session() as session:
        await session.execute(delete(MemeAlertHistory))

    sent: list[dict] = []
    results_box: dict = {"result": "sent"}

    class _FakeNotifier:
        def __init__(self, *a, **kw):
            self.config = SimpleNamespace(bot_token="t", chat_id="c")
            self.last_result = None

        async def send(self, level, title, body, force=False, category=None, dedupe_id=None, gate=True):
            sent.append({"title": title, "body": body, "category": category, "dedupe_id": dedupe_id, "force": force})
            self.last_result = results_box["result"]
            return self.last_result == "sent"

    monkeypatch.setattr(alert_mod, "TelegramNotifier", _FakeNotifier)
    yield sent, results_box


async def _run_with(monkeypatch, results):
    async def _top(top_n=50):
        return results

    import backend.discovery.meme_watch.top as top_mod

    monkeypatch.setattr(top_mod, "compute_top_memes", _top)
    return await alert_mod.check_and_send_alerts()


@pytest.mark.asyncio
async def test_categories_by_alert_type(monkeypatch, meme_env):
    sent, _ = meme_env
    stats = await _run_with(monkeypatch, [
        {"score": _score("GME", 0.5), "intensity": _intensity(9.0), "meta": _meta("GameStop"), "volume": None},
        {"score": _score("AMC", 1.5), "intensity": None, "meta": _meta("AMC"), "volume": None},
    ])
    assert [s["category"] for s in sent] == ["meme_erupting", "meme_blazing"]
    assert [s["dedupe_id"] for s in sent] == ["GME", "AMC"]
    # 예전처럼 TELEGRAM_PROFILE 을 우회 (배포만으로 받는 알림이 바뀌지 않게) · 알림 설정 거름은 그대로
    assert all(s["force"] is True for s in sent)
    assert stats["sent_new"] == 2


@pytest.mark.asyncio
async def test_queued_counts_as_handled_no_repeat(monkeypatch, meme_env):
    """하루 요약 대기(queued)도 이력에 남겨 다음 회차에 다시 넣지 않음."""
    from backend.services.db import get_session
    from backend.services.models import MemeAlertHistory

    sent, box = meme_env
    box["result"] = "queued"
    rows = [{"score": _score("AMC", 1.5), "intensity": None, "meta": _meta("AMC"), "volume": None}]
    await _run_with(monkeypatch, rows)
    await _run_with(monkeypatch, rows)
    assert len(sent) == 1
    async with get_session() as session:
        assert len((await session.execute(select(MemeAlertHistory))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_failed_send_not_recorded(monkeypatch, meme_env):
    sent, box = meme_env
    box["result"] = "failed"
    rows = [{"score": _score("AMC", 1.5), "intensity": None, "meta": _meta("AMC"), "volume": None}]
    await _run_with(monkeypatch, rows)
    await _run_with(monkeypatch, rows)
    assert len(sent) == 2  # 실패는 이력에 안 남겨 다음 회차에 다시 시도
