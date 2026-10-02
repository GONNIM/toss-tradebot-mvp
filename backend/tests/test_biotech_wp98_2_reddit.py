"""WP98-2 · 레딧 4곳 묶음 RSS · 429 → 60초 재시도 → biotechplays 단독 · 전부 차단 알림 하루 1회."""
from __future__ import annotations

import json

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


def test_single_first_then_combined_live_when_no_file():
    urls = []
    seq = [_R(200, SINGLE), _R(200, ATOM)]
    posts, st = cf.fetch_reddit(lambda u: urls.append(u) or seq.pop(0), sleep=lambda s: None)
    assert urls[0].startswith("https://www.reddit.com/r/biotechplays/") and "biotechplays+pennystocks" in urls[1]   # 단독 먼저
    assert st["subs_collected"] == 4 and st["mode"] == "single+combined"
    assert cf.REDDIT_HEADERS["User-Agent"] != cf.SEC_UA


def test_combined_read_from_0630_file(tmp_path):
    f = tmp_path / "reddit_combined_20261003.json"
    f.write_text(json.dumps({"ok": True, "attempts": [{"kind": "combined", "http": 200}],
                             "posts": [{"id": "t3_a", "title": "x", "link": "l", "updated": "", "sub": "pennystocks"}]}))
    urls = []
    posts, st = cf.fetch_reddit(lambda u: urls.append(u) or _R(200, SINGLE), sleep=lambda s: None, combined_path=f)
    assert len(urls) == 1 and urls[0].startswith("https://www.reddit.com/r/biotechplays/")                         # 묶음 요청 안 함
    assert st["subs_collected"] == 4 and st["per_sub"] == {"biotechplays": 2, "pennystocks": 1}


def test_no_retry_on_429():
    urls, slept = [], []
    posts, st = cf.fetch_reddit(lambda u: urls.append(u) or _R(429), sleep=slept.append)
    assert len(urls) == 2 and 60 not in slept and [a["kind"] for a in st["attempts"]] == ["single", "combined"]
    assert st["subs_collected"] == 0


def test_duplicate_post_ids_removed():
    seq = [_R(200, SINGLE), _R(200, ATOM)]
    posts, st = cf.fetch_reddit(lambda u: seq.pop(0), sleep=lambda s: None)
    assert sorted(p["id"] for p in posts) == ["t3_a", "t3_b", "t3_c", "t3_d"]     # t3_b 는 두 번 받았지만 한 번만


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


def test_403_stops_further_requests():
    urls = []
    _, st = cf.fetch_reddit(lambda u: urls.append(u) or _R(403), sleep=lambda s: None)
    assert len(urls) == 1 and st["mode"] == "none"


def test_server_shell_has_step_options():
    from pathlib import Path
    sh = (Path(__file__).resolve().parents[1] / "scripts" / "biotech_h48v3_daily_server.sh").read_text()
    for name in ("mcap)", "radar)", "status_gen)", "reddit-probe)", "reddit-combined)", "auto_category)"):
        assert name in sh
    assert sh.index("--step=*)") < sh.index("STARTED=$(date")              # 단계 옵션은 전체 실행 전에 끝남 (exit)
