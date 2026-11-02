"""1101-03: 진입가 상태 문구에 권유 낱말이 없고 머리 이모지는 그대로인지."""
from discovery.sector_leaders.entry_price import NEAR_ENTRY_TOLERANCE_PCT, compute_entry_price

BANNED = ("매수", "매도", "추천", "진입")


def _flat(n, high, low, close):
    return [(high, low, close)] * n


def _cases():
    return {
        "⚠️": compute_entry_price(current_price=0, ohlc=[]),
        "🔴": compute_entry_price(current_price=200_000, ohlc=_flat(252, 101_000.0, 99_000.0, 100_000.0)),
        "🟢": compute_entry_price(current_price=100_000, ohlc=_flat(252, 100_100.0, 99_900.0, 100_000.0)),
        "🟡": compute_entry_price(current_price=100_000, ohlc=_flat(252, 103_000.0, 97_000.0, 100_000.0)),
    }


def test_prefix_emoji_kept():
    for emoji, r in _cases().items():
        assert r.entry_status.startswith(emoji), r.entry_status


def test_no_banned_words():
    for r in _cases().values():
        assert not any(w in r.entry_status for w in BANNED), r.entry_status


def test_new_wording():
    c = _cases()
    assert c["🟢"].entry_status == "🟢 참고선 근처 (차이 0.5% 안)"
    assert f"{NEAR_ENTRY_TOLERANCE_PCT:g}%" in c["🟢"].entry_status   # 1102-02: 문구가 상수를 따름
    assert c["🟡"].entry_status.startswith("🟡 참고선이 ") and c["🟡"].entry_status.endswith("% 아래")
