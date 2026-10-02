"""WP98-2 · 레딧 4곳 묶음 RSS · 429 → 60초 재시도 → biotechplays 단독 · 전부 차단 알림 하루 1회."""
from __future__ import annotations

from backend.scripts import biotech_h48v3_confirm as cf

ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>t3_a</id><category term="pennystocks" label="r/pennystocks"/><title>$ENTX phase 3</title><link href="https://r/1"/><updated>2026-10-02T00:00:00+00:00</updated></entry>
<entry><id>t3_b</id><category term="biotechplays" label="r/biotechplays"/><title>KOD readout</title><link href="https://r/2"/><updated>2026-10-02T00:01:00+00:00</updated></entry>
<entry><id>t3_c</id><category term="biotechplays" label="r/biotechplays"/><title>IOVA</title><link href="https://r/3"/><updated>2026-10-02T00:02:00+00:00</updated></entry>
</feed>"""


class _R:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text


SINGLE = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>t3_b</id><category term="biotechplays"/><title>KOD readout</title><link href="https://r/2"/></entry>
<entry><id>t3_d</id><category term="biotechplays"/><title>ABCL news</title><link href="https://r/4"/></entry>
</feed>"""


def test_combined_plus_single_merged():
    urls = []
    seq = [_R(200, ATOM), _R(200, SINGLE)]
    posts, st = cf.fetch_reddit(lambda u: urls.append(u) or seq.pop(0), sleep=lambda s: None)
    assert "biotechplays+pennystocks+wallstreetbets+stocks" in urls[0] and urls[1].startswith("https://www.reddit.com/r/biotechplays/")
    assert st["subs_collected"] == 4 and st["mode"] == "combined+single"
    assert cf.REDDIT_HEADERS["User-Agent"] != cf.SEC_UA          # 레딧 전용 UA


def test_duplicate_post_ids_removed():
    seq = [_R(200, ATOM), _R(200, SINGLE)]
    posts, st = cf.fetch_reddit(lambda u: seq.pop(0), sleep=lambda s: None)
    assert sorted(p["id"] for p in posts) == ["t3_a", "t3_b", "t3_c", "t3_d"]     # t3_b 는 두 번 받았지만 한 번만
    assert st["per_sub"] == {"pennystocks": 1, "biotechplays": 3}


def test_429_retry_each_request():
    seq = [_R(429), _R(429), _R(429), _R(200, SINGLE)]
    slept = []
    posts, st = cf.fetch_reddit(lambda u: seq.pop(0), sleep=slept.append)
    assert [a["kind"] for a in st["attempts"]] == ["combined", "combined_retry", "single", "single_retry"]
    assert slept.count(60) == 2 and st["subs_collected"] == 1 and st["mode"] == "single_retry"


def test_all_blocked_notifies_once(tmp_path, monkeypatch):
    monkeypatch.setattr(cf, "OUT_DIR", tmp_path)
    sent = []

    class _N:
        async def send_warning(self, title, body):
            sent.append(title)
            return True

    import backend.services.notifier as nt
    monkeypatch.setattr(nt, "TelegramNotifier", _N)
    _, st = cf.fetch_reddit(lambda u: _R(429), sleep=lambda s: None)
    assert st["subs_collected"] == 0
    cf._notify_reddit_blocked("20261002", st)
    cf._notify_reddit_blocked("20261002", st)
    assert sent == ["biotech 레딧 입력 없음"]


def test_403_stops_without_fallback():
    urls = []
    _, st = cf.fetch_reddit(lambda u: urls.append(u) or _R(403), sleep=lambda s: None)
    assert len(urls) == 1 and st["mode"] == "none"


def test_server_shell_has_step_options():
    from pathlib import Path
    sh = (Path(__file__).resolve().parents[1] / "scripts" / "biotech_h48v3_daily_server.sh").read_text()
    for name in ("mcap)", "radar)", "status_gen)", "reddit-probe)"):
        assert name in sh
    assert sh.index("--step=*)") < sh.index("STARTED=$(date")              # 단계 옵션은 전체 실행 전에 끝남 (exit)
