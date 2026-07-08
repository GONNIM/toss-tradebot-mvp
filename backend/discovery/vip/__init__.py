"""VIP 개별 종목 심층 감시 채널 (기획: docs/plans/meme-stock-discovery/05-wen-vip-watch.md).

P-A 범위:
- 정규장 30초 폴링 / AH·PM 300초
- 매수가 기반 알림 (TP1 / TP2 / STOP_APPROACH / TRAIL_ARMED / TRAIL_GIVEBACK)
- Activist(SEC 필링) 트래커 — env 활성 (선택), JSON override 로 UI 편집 가능
- 기존 밈주 봇 재활용 · `[VIP-{TAG} · <이벤트>]` 태그

종목은 env `VIP_*` 로 파라미터화. 다른 종목으로 전환 시 `.env` + `data/vip_overrides.json`
만 갱신하면 됨.
"""
