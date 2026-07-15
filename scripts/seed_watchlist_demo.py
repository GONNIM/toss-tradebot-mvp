"""Watchlist UI 시연용 sample 데이터 시딩 · 로컬 검증용.

- 오늘 trade_date 기준 · Watchlist 5 종목 삽입 (자동)
- 각 종목 signal 3~5건 배포 (news · board · youtube · assembly)
- 완결 SniperSignal 5건 (Report DoD 데모용)

실행:
    cd toss-tradebot-mvp && source backend/venv/bin/activate
    python -m scripts.seed_watchlist_demo
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from backend.discovery.watchlist.store import upsert_signal
from backend.services.db import get_session, init_db
from backend.services.models import (
    LiveTapeUniverse,
    SniperSignal,
    Watchlist,
    WatchlistSignal,
)


_KST = timezone(timedelta(hours=9))
TRADE_DATE = datetime.now(tz=_KST).date().isoformat()


TICKERS = [
    ("005930", "삼성전자", 72700.0),
    ("373220", "LG에너지솔루션", 385000.0),
    ("000660", "SK하이닉스", 195000.0),
    ("035420", "NAVER", 218500.0),
    ("068270", "셀트리온", 195500.0),
]


async def seed():
    await init_db()

    async with get_session() as session:
        # 기존 데모 데이터 클린 (오늘 것만)
        await session.execute(delete(Watchlist).where(Watchlist.trade_date == TRADE_DATE))
        await session.execute(delete(WatchlistSignal).where(WatchlistSignal.trade_date == TRADE_DATE))
        # 유니버스 · 이미 있으면 유지, 없으면 추가
        for code, name, close in TICKERS:
            existing = await session.execute(
                LiveTapeUniverse.__table__.select().where(LiveTapeUniverse.ticker == code)
            )
            if existing.first():
                continue
            session.add(LiveTapeUniverse(
                ticker=code, name=name, market="KOSDAQ",
                dept=None, close_price=close, market_cap_krw=1_000_000_000_000,
                shares=10_000_000, amount_today=50_000_000_000,
                amount_20d_avg=None, is_squeeze_candidate=False,
                refreshed_at=datetime.now(tz=timezone.utc),
            ))

    # signal 시딩 (각 종목별 분포 다르게)
    sample_signals = [
        # ticker, source, signal_type, intensity, payload
        ("005930", "news_yhap", "headline", 1.0, {"title": "삼성전자 2Q 영업이익 서프라이즈", "url": "https://ex.com/1"}),
        ("005930", "news_edaily", "headline", 1.0, {"title": "삼성전자 HBM3E 양산 개시", "url": "https://ex.com/2"}),
        ("005930", "news_fnnews", "headline", 1.0, {"title": "반도체 슈퍼사이클 재진입 · 삼성전자 반등", "url": "https://ex.com/3"}),
        ("005930", "board_naver", "board_post_velocity", 2.5, {"recent_count": 12}),
        ("005930", "youtube_shuka", "video_upload", 1.0, {"title": "삼성전자 지금이 매수 타이밍인가", "video_id": "abc"}),

        ("373220", "news_edaily", "headline", 1.0, {"title": "LG에너지솔루션 GM 수주 대박", "url": "https://ex.com/4"}),
        ("373220", "news_hankyung", "headline", 1.0, {"title": "2차전지 세제 지원 확대 · LG엔솔 수혜", "url": "https://ex.com/5"}),
        ("373220", "moef_rss", "press_release", 0.5, {"title": "2차전지 산업 세제 지원안 발표"}),
        ("373220", "board_naver", "board_post_velocity", 2.0, {"recent_count": 10}),

        ("000660", "news_yhap", "headline", 1.0, {"title": "SK하이닉스 HBM3E 엔비디아 공급 확대", "url": "https://ex.com/6"}),
        ("000660", "news_yonhap", "headline", 1.0, {"title": "SK하이닉스 실적 개선", "url": "https://ex.com/7"}),
        ("000660", "assembly", "bill_registered", 0.5, {"bill_no": "2200001", "title": "반도체 산업 지원 특별법"}),

        ("035420", "news_hankyung", "headline", 1.0, {"title": "NAVER 클라우드 AI 서비스 확대", "url": "https://ex.com/8"}),
        ("035420", "youtube_sampro", "video_upload", 1.0, {"title": "NAVER 언제까지 오를까", "video_id": "def"}),

        ("068270", "news_fnnews", "headline", 1.0, {"title": "셀트리온 FDA 승인 임박", "url": "https://ex.com/9"}),
    ]
    now = datetime.now(tz=timezone.utc)
    for i, (ticker, source, sig_type, intensity, payload) in enumerate(sample_signals):
        await upsert_signal(
            ticker=ticker, source=source, signal_type=sig_type,
            intensity=intensity, payload=payload,
            trade_date=TRADE_DATE,
            detected_at=now - timedelta(minutes=i * 3),
        )

    # Watchlist 직접 삽입 (finalize 없이도 UI 확인)
    from backend.discovery.watchlist.scoring import score_signals
    from backend.discovery.watchlist.store import signals_for_date

    signals = await signals_for_date(TRADE_DATE)
    scores = score_signals(signals)
    universe_names = {t: name for t, name, _ in TICKERS}
    async with get_session() as session:
        for rank, score in enumerate(scores, start=1):
            session.add(Watchlist(
                trade_date=TRADE_DATE, ticker=score.ticker,
                name=universe_names.get(score.ticker),
                rank=rank, composite_score=score.composite_score,
                news_score=score.news_score, board_score=score.board_score,
                youtube_score=score.youtube_score, event_score=score.event_score,
                prev_day_score=score.prev_day_score,
                source_breakdown=json.dumps(score.source_breakdown, ensure_ascii=False),
                locked=False, added_by="auto",
            ))

    # SniperSignal 완결 5건 (Report DoD 데모용 · 최근 7일 이내)
    async with get_session() as session:
        await session.execute(
            delete(SniperSignal).where(SniperSignal.entry_order_uuid.like("demo-%"))
        )
        completed = [
            ("005930", 72000, 74500, "trailing_target", -2),
            ("373220", 380000, 395000, "trailing_target", -3),
            ("000660", 195000, 198000, "trailing_target", -4),
            ("035420", 218000, 213000, "hard_sl", -5),
            ("068270", 195500, 190500, "hard_sl", -6),
        ]
        for i, (t, e, x, reason, days_ago) in enumerate(completed):
            session.add(SniperSignal(
                ticker=t,
                detected_at=now - timedelta(days=abs(days_ago)),
                tape_score=1.5,
                rank_velocity=0, trades_intensity=0, orderbook_imbalance=0,
                entry_order_uuid=f"demo-entry-{i}",
                entry_price=e,
                exit_order_uuid=f"demo-exit-{i}",
                exit_price=x,
                peak_price=max(e, x) * 1.02,
                reason=reason,
            ))

    print(f"[seed] trade_date={TRADE_DATE}")
    print(f"[seed] signals inserted: {len(sample_signals)}")
    print(f"[seed] watchlist rows: {len(scores)}")
    print(f"[seed] closed sniper signals: {len(completed)}")


if __name__ == "__main__":
    asyncio.run(seed())
