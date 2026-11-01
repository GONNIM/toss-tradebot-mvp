"""1028-02 · 상장폐지·티커 변경 4종목이 감시 목록에서 빠졌는지."""
from backend.scheduler import cron


def test_delisted_removed():
    for t in ("ZAPP", "HCDI", "NUKK", "BREA"):
        assert t not in cron.WATCHLIST
    assert len(cron.WATCHLIST) == 55
    assert len(set(cron.WATCHLIST)) == len(cron.WATCHLIST)
