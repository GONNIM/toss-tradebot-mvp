

import pytest as _pytest_wp98


@_pytest_wp98.fixture(autouse=True)
def _no_tiingo_local_seed(monkeypatch):
    """WP98 · Tiingo 장부 씨앗 (docs 실파일) 이 테스트 장부에 섞이지 않게 · 필요한 테스트는 SEED_DIR 을 직접 지정."""
    try:
        from backend.scripts import biotech_h6_collect_prices as _h6
        monkeypatch.setattr(_h6, "SEED_DIR", None)
    except Exception:
        pass
