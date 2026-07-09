"""Activist Radar — 헤지펀드 경영권 매수 초기 신호 감지.

기획: docs/plans/activist-radar/
Phase A~C 범위:
- Phase A: 미국 SEC EDGAR SC 13D/G 폴러 (30 CIK)
- Phase B: 한국 DART 대량보유공시 폴러 (10 filer)
- Phase C: 강도 스코어링 + Wolf Pack 감지

VIP watch 인프라 재활용: activist_tracker.fetch_recent · TelegramNotifier · SOPS 배포.
"""
