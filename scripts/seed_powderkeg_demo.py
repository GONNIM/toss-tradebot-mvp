"""Powder Keg UI 시연용 sample 데이터 시딩.

3 종목 리스트 + 5 이벤트 (Type A/B 혼합) + 1 티켓.
실행:
    cd toss-tradebot-mvp && source backend/venv/bin/activate
    python -m scripts.seed_powderkeg_demo
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from backend.services.db import get_session, init_db
from backend.services.models import (
    PowderKegEvent,
    PowderKegList,
    PowderKegOrderTicket,
)


RUN_ID = "20260715-100000"


async def seed():
    await init_db()

    async with get_session() as session:
        # 기존 데모 클린
        await session.execute(delete(PowderKegList).where(PowderKegList.run_id == RUN_ID))
        await session.execute(delete(PowderKegEvent).where(PowderKegEvent.source_id.like("demo-%")))
        await session.execute(delete(PowderKegOrderTicket).where(PowderKegOrderTicket.invalidation_logic.like("[DEMO]%")))

        # ─── 화약고 리스트 (5 종목: 2 passed · 2 rejected · 1 cash_suspect) ─
        session.add(PowderKegList(
            run_id=RUN_ID, ticker="000670", name="영풍",
            status="passed",
            net_cash_ratio=0.55, piotroski_f_score=7,
            owner_pct=0.42, treasury_pct=0.03, pbr=0.35,
            conditions_json=json.dumps({f"{i}": True for i in range(1, 11)}),
        ))
        session.add(PowderKegList(
            run_id=RUN_ID, ticker="004800", name="효성",
            status="passed",
            net_cash_ratio=0.48, piotroski_f_score=6,
            owner_pct=0.47, treasury_pct=0.05, pbr=0.30,
        ))
        session.add(PowderKegList(
            run_id=RUN_ID, ticker="005930", name="삼성전자",
            status="rejected",
            net_cash_ratio=0.15, piotroski_f_score=8,
            owner_pct=0.35, pbr=0.45,
            reject_reasons="big_biz_group,owner<0.4",
        ))
        session.add(PowderKegList(
            run_id=RUN_ID, ticker="000660", name="SK하이닉스",
            status="rejected",
            net_cash_ratio=0.10, piotroski_f_score=7,
            owner_pct=0.30, pbr=1.20,
            reject_reasons="pbr>=0.5,net_cash<0.4,big_biz_group,owner<0.4",
        ))
        session.add(PowderKegList(
            run_id=RUN_ID, ticker="900110", name="이스트아시아",   # 가상
            status="cash_suspect",
            net_cash_ratio=0.62, piotroski_f_score=5,
            owner_pct=0.48, pbr=0.20,
            reject_reasons="cash_suspect:no_interest_income",
        ))

        # ─── 이벤트 (5건 · A 3 + B 2) ─
        now = datetime.now(tz=timezone.utc)
        events = [
            ("004800", "A3", "최대주주 주식담보제공 계약 체결", "https://dart.fss.or.kr/x1", now - timedelta(hours=2)),
            ("000670", "A5", "자기주식 소각 결정", "https://dart.fss.or.kr/x2", now - timedelta(hours=6)),
            ("900110", "A1", "회장 개인 폭행 혐의 뉴스", "https://news.example/x3", now - timedelta(hours=8)),
            ("005930", "B1", "횡령·배임 혐의발생 (금액 미확정)", "https://dart.fss.or.kr/x4", now - timedelta(hours=12)),
            ("000660", "B2", "감사보고서 제출 지연 공시", "https://dart.fss.or.kr/x5", now - timedelta(hours=24)),
        ]
        for ticker, event_type, title, url, dt in events:
            session.add(PowderKegEvent(
                ticker=ticker, event_type=event_type, source="dart",
                source_id=f"demo-{event_type}-{ticker}",
                title=title, url=url, detected_at=dt, release_date=dt,
                confidence=(0.85 if event_type == "A1" else None),
                needs_human_review=(event_type == "A1"),
                action_taken=("list_removed" if event_type.startswith("B") else "notified"),
                validated=(event_type in ("A3", "A5")),   # 예시: A3/A5 만 backtest 통과 가정
            ))

        # ─── 티켓 (2건 · pending + approved) ─
        session.add(PowderKegOrderTicket(
            event_id=1, ticker="004800", proposed_qty=100,
            proposed_price=52000.0, invalidation_price=44000.0,
            invalidation_logic="[DEMO] 진입가 -15% 또는 담보 해제 공시",
            holding_days_max=365, status="pending",
        ))
        session.add(PowderKegOrderTicket(
            event_id=2, ticker="000670", proposed_qty=50,
            proposed_price=850000.0, invalidation_price=720000.0,
            invalidation_logic="[DEMO] 진입가 -15% 또는 자사주 소각 취소",
            holding_days_max=365, status="approved",
            approver="demo_user",
            approved_at=datetime.now(tz=timezone.utc),
        ))

    print(f"[seed] run_id={RUN_ID}")
    print("[seed] list=5 · events=5 · tickets=2")


if __name__ == "__main__":
    asyncio.run(seed())
