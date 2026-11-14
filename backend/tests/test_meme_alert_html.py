"""meme 알림 → TelegramNotifier(HTML) 통합 (1022-09 Task 5)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.discovery.meme_watch import alert as alert_mod
from backend.tests.alert_rules import violations


def _score(ticker, s):
    return SimpleNamespace(ticker=ticker, score=s, emoji="🔥🔥", label="BLAZING")


def _intensity(v):
    return SimpleNamespace(intensity=v, emoji="🌋", label="ERUPTING")


def _meta(name, market="US"):
    return SimpleNamespace(name=name, market=market)


def _volume(close, r1d=None, bar_date=None, snapshot_at=None):
    return SimpleNamespace(close=close, return_1d_pct=r1d, bar_date=bar_date, snapshot_at=snapshot_at)


def test_meme_erupting_wording():
    title, body = alert_mod._format_alert(
        "ERUPTING", _score("GME", 1.214), _intensity(8.7), _meta("GameStop", "NYSE"), _volume(31.4, 18.2),
        prev_score=0.882, prev_intensity=5.1,
    )
    assert title == "🌋 밈 · 급등 진행 · GameStop(GME) · 다시 오름"
    assert "최근 종가 기준 +18.2% · $31.40" in body
    assert "오늘" not in body and "지금" not in body
    assert "상승 강도 8.7/10 (실측 · 직전 5.1)" in body
    assert "급등 전 단계 점수 1.21 (추정 · 직전 0.88" in body
    assert violations(title, body) == []


def test_meme_blazing_wording():
    title, body = alert_mod._format_alert("BLAZING", _score("005930", 1.05), None, _meta("삼성전자", "KRX"), _volume(71000.0, 2.0))
    assert title == "🔥 밈 · 급등 전 단계 · 삼성전자(005930)"
    assert "5가지" not in body and "입력" not in body  # contributions 없으면 수를 쓰지 않음
    assert "최근 종가 기준 +2.0% · 71,000원" in body
    assert violations(title, body) == []


def test_meme_without_previous():
    title, body = alert_mod._format_alert("BLAZING", _score("ABCD", 1.2), None, None, None)
    assert "직전" not in body and "None" not in body
    assert "ABCD" in title
    assert violations(title, body) == []


def test_meme_long_name_keeps_code():
    title, _ = alert_mod._format_alert("ERUPTING", _score("OPEN", 1.2), _intensity(9.0),
                                       _meta("Opendoor Technologies Incorporated"), None, prev_score=1.0)
    assert title.endswith("(OPEN) · 다시 오름")
    assert len(title) <= 40


def test_meme_link_real_path():
    _, body = alert_mod._format_alert("BLAZING", _score("ABCD", 1.2), None, _meta("A&B <X> Corp"), None)
    assert body.endswith("자세히: https://optimus8.cafe24.com/lab/meme-watch")


def test_meme_html_escapes_name():
    title, _ = alert_mod._format_alert("BLAZING", _score("ABCD", 1.2), None, _meta("A&B <X> Corp"), None)
    assert "A&amp;B &lt;X&gt;" in title


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


# ─── 1114-02 문구(기준일·입력 수) ───

from datetime import date, datetime  # noqa: E402


def test_krx_bar_date_wording():
    title, body = alert_mod._format_alert(
        "BLAZING", _score("123456", 1.22), None, _meta("테스트", "KRX"),
        _volume(8120.0, 31.8, bar_date=date(2026, 11, 13)),
    )
    assert "11/13 종가 기준 +31.8% · 8,120원" in body
    assert "오늘" not in body and "지금" not in body
    assert violations(title, body) == []


def test_us_bar_date_wording():
    title, body = alert_mod._format_alert(
        "BLAZING", _score("ABCD", 1.22), None, _meta("Abcd", "NASDAQ"),
        _volume(12.5, -3.2, bar_date=date(2026, 11, 13)),
    )
    assert "11/13 종가 기준 -3.2% · $12.50" in body
    assert violations(title, body) == []


def test_bar_date_estimated_from_saturday_snapshot():
    # 토요일 16:00 KST 스냅샷 → 금요일(11/13) 봉
    _, body = alert_mod._format_alert(
        "BLAZING", _score("123456", 1.1), None, _meta("테스트", "KRX"),
        _volume(1000.0, 1.0, snapshot_at=datetime(2026, 11, 14, 16, 0)),
    )
    assert "11/13 종가 기준" in body


def test_us_snapshot_date_estimate():
    # 월요일 06:05 KST = 일요일 ET → 금요일 11/13
    assert alert_mod._snapshot_base_date(datetime(2026, 11, 16, 6, 5), "NASDAQ") == date(2026, 11, 13)
    # 금요일 06:05 KST = 목요일 16:05 ET → 11/12
    assert alert_mod._snapshot_base_date(datetime(2026, 11, 13, 6, 5), "NASDAQ") == date(2026, 11, 12)


def _contrib(label):
    return SimpleNamespace(label=label)


def test_input_count_follows_contributions():
    sc = _score("ABCD", 1.2)
    sc.contributions = [_contrib("소셜 모멘텀"), _contrib("유동성 폭주"), _contrib("Momentum / Breakout")]
    title, body = alert_mod._format_alert("BLAZING", sc, None, _meta("Abcd"), None)
    assert "입력 3가지: 소셜 모멘텀, 유동성 폭주, 가격 흐름" in body
    assert "5가지" not in body and "Momentum" not in body
    sc.contributions.append(_contrib("공매도 잔고"))
    _, body4 = alert_mod._format_alert("BLAZING", sc, None, _meta("Abcd"), None)
    assert "입력 4가지" in body4 and "5가지" not in body4
    assert violations(title, body) == []


def test_market_open_clock():
    # 2026-11-13(금) 금요일: 11:00 ET = 01:00 KST 11/14 → 장 중
    assert alert_mod._us_market_open(datetime(2026, 11, 14, 1, 0)) is True
    # 같은 날 16:04 KST (= 02:04 ET) → 장 밖
    assert alert_mod._us_market_open(datetime(2026, 11, 13, 16, 4)) is False
    # 토요일 낮 → 장 밖
    assert alert_mod._us_market_open(datetime(2026, 11, 14, 10, 0)) is False


# ─── 1114-02 같은 자료 재알림 막기 ───

_SAT_10 = datetime(2026, 11, 14, 10, 0)
_FRI_1604 = datetime(2026, 11, 13, 16, 4)
_WED_2000 = datetime(2026, 11, 11, 20, 0)
_TUE_1000 = datetime(2026, 11, 10, 10, 0)
_FRI = date(2026, 11, 13)


async def _run_at(monkeypatch, results, now):
    async def _top(top_n=50):
        return results

    import backend.discovery.meme_watch.top as top_mod

    monkeypatch.setattr(top_mod, "compute_top_memes", _top)
    return await alert_mod.check_and_send_alerts(now=now)


def _row(ticker, s, bar_date, market="KRX", name="T"):
    return {"score": _score(ticker, s), "intensity": None, "meta": _meta(name, market),
            "volume": _volume(1000.0, 5.0, bar_date=bar_date)}


async def _seed_history(ticker, at_, score, bar_date=None, alert_type="BLAZING"):
    import json as _json

    from backend.services.db import get_session
    from backend.services.models import MemeAlertHistory

    payload = {"score": score, "intensity": None, "name": "T", "market": "KRX", "retrigger": False}
    if bar_date:
        payload["bar_date"] = bar_date.isoformat()
    async with get_session() as session:
        session.add(MemeAlertHistory(ticker=ticker, alert_type=alert_type, triggered_at=at_,
                                     payload=_json.dumps(payload)))
        await session.commit()


@pytest.mark.asyncio
async def test_krx_same_bar_date_blocked_anytime(monkeypatch, meme_env):
    sent, _ = meme_env
    await _seed_history("111111", _FRI_1604, 1.1, _FRI)
    # 평일 장 중(월요일 10:00)에도 같은 기준일이면 안 보냄 · 점수가 +0.5 올라도
    stats = await _run_at(monkeypatch, [_row("111111", 1.6, _FRI)], datetime(2026, 11, 16, 10, 0))
    assert sent == [] and stats["skipped_same_data"] == 1


@pytest.mark.asyncio
async def test_krx_new_bar_date_sent(monkeypatch, meme_env):
    sent, _ = meme_env
    await _seed_history("111111", _FRI_1604, 1.1, _FRI)
    stats = await _run_at(monkeypatch, [_row("111111", 1.6, date(2026, 11, 16))], datetime(2026, 11, 16, 20, 0))
    assert len(sent) == 1 and stats["skipped_same_data"] == 0


@pytest.mark.asyncio
async def test_krx_saturday_blocked_over_weekend_lookup(monkeypatch, meme_env):
    sent, _ = meme_env
    # 금 16:04 이력 → 토 10:00 (이력 10일 안)
    await _seed_history("111111", _FRI_1604, 1.1, _FRI)
    stats = await _run_at(monkeypatch, [_row("111111", 1.9, _FRI)], _SAT_10)
    assert sent == [] and stats["skipped_same_data"] == 1


@pytest.mark.asyncio
async def test_us_offhours_same_date_blocked_unless_score_up(monkeypatch, meme_env):
    sent, _ = meme_env
    await _seed_history("ABCD", datetime(2026, 11, 10, 6, 30), 1.1, _FRI)
    # 토요일 (장 밖) +0.2 → 막음
    s1 = await _run_at(monkeypatch, [_row("ABCD", 1.3, _FRI, "NASDAQ")], _SAT_10)
    assert sent == [] and s1["skipped_same_data"] == 1
    # +0.3 이상 → 「MM/DD 종가 기준」 문구로 보냄
    s2 = await _run_at(monkeypatch, [_row("ABCD", 1.45, _FRI, "NASDAQ")], _SAT_10)
    assert len(sent) == 1 and "11/13 종가 기준" in sent[0]["body"] and s2["skipped_same_data"] == 0


@pytest.mark.asyncio
async def test_us_market_hours_keeps_existing_behavior(monkeypatch, meme_env):
    sent, _ = meme_env
    # 수요일 11:00 ET = 목 01:00 KST — 같은 기준일 이력이 8시간보다 오래 → 장 중이라 새 알림으로 보냄
    await _seed_history("ABCD", datetime(2026, 11, 11, 6, 30), 1.1, date(2026, 11, 10))
    stats = await _run_at(monkeypatch, [_row("ABCD", 1.15, date(2026, 11, 10), "NASDAQ")], datetime(2026, 11, 12, 1, 0))
    assert len(sent) == 1 and stats["skipped_same_data"] == 0


@pytest.mark.asyncio
async def test_weekday_evening_same_date_blocked_changed_sent(monkeypatch, meme_env):
    sent, _ = meme_env
    await _seed_history("111111", datetime(2026, 11, 11, 11, 0), 1.1, date(2026, 11, 11))  # 8시간 쿨다운 밖
    s1 = await _run_at(monkeypatch, [_row("111111", 1.2, date(2026, 11, 11))], _WED_2000)
    assert sent == [] and s1["skipped_same_data"] == 1
    s2 = await _run_at(monkeypatch, [_row("111111", 1.2, date(2026, 11, 12))], _WED_2000)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_old_history_row_base_date_estimated_from_snapshot(monkeypatch, meme_env):
    from backend.services.db import get_session
    from backend.services.models import MemeVolumeSnapshot

    sent, _ = meme_env
    async with get_session() as session:
        await session.execute(delete(MemeVolumeSnapshot).where(MemeVolumeSnapshot.ticker == "222222"))
        session.add(MemeVolumeSnapshot(ticker="222222", snapshot_at=datetime(2026, 11, 14, 16, 0), volume=1.0,
                                       volume_z_20d=0.0, return_1d_pct=1.0, close=1.0))
        await session.commit()
    # bar_date 없는 옛 이력 (토 16:04 알림) → 마지막 스냅샷(토 16:00 → 금요일 봉)으로 추정
    await _seed_history("222222", datetime(2026, 11, 14, 16, 4), 1.1, None)
    stats = await _run_at(monkeypatch, [_row("222222", 1.2, _FRI)], datetime(2026, 11, 14, 22, 0))
    assert sent == [] and stats["skipped_same_data"] == 1


@pytest.mark.asyncio
async def test_payload_has_bar_date_and_send_result(monkeypatch, meme_env):
    import json as _json

    from backend.services.db import get_session
    from backend.services.models import MemeAlertHistory

    sent, box = meme_env
    box["result"] = "queued"
    await _run_at(monkeypatch, [_row("333333", 1.2, _FRI)], _TUE_1000)
    async with get_session() as session:
        pl = _json.loads((await session.execute(
            select(MemeAlertHistory.payload).where(MemeAlertHistory.ticker == "333333"))).scalar_one())
    assert pl["bar_date"] == "2026-11-13" and pl["send_result"] == "queued"


@pytest.mark.asyncio
async def test_skipped_alert_makes_no_signal_hit_or_router(monkeypatch, meme_env):
    import backend.discovery.super_signal.signal_hit as sh

    calls = []

    async def _rec(**kw):
        calls.append(kw)

    monkeypatch.setattr(sh, "record_hit", _rec)
    sent, _ = meme_env
    await _seed_history("444444", _FRI_1604, 1.1, _FRI)
    await _run_at(monkeypatch, [_row("444444", 1.5, _FRI)], _SAT_10)
    assert sent == [] and calls == []
    # 대조: 새 기준일은 기록됨
    await _run_at(monkeypatch, [_row("555555", 1.5, _FRI)], _SAT_10)
    assert len(calls) == 1


_FRI_1604 = datetime(2026, 11, 13, 16, 4)
