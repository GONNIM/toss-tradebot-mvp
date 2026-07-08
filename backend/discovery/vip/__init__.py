"""WEN VIP 감시 채널 — 개별 종목 심층 감시 (기획: docs/plans/meme-stock-discovery/05-wen-vip-watch.md).

P-A 범위:
- 30초 폴링 (미국 정규장 시간대) + 300초 (AH/PM)
- 매수가 기반 알림 (TP1 / TP2 / STOP_APPROACH / TRAIL_ARMED / TRAIL_GIVEBACK)
- Trian Fund Management 필링 트래커 (SEC EDGAR data.sec.gov)
- 기존 밈주 봇 재활용 · `[VIP-WEN · <이벤트>]` 태그
"""
