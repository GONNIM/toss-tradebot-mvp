"""Powder Keg Screener · Phase 7.

전략: 딥밸류 (그레이엄 net-net + 피오트로스키) × 지배구조 카탈리스트 (그린블라트 특수상황).
목표: 현금 많고 싸고 오너 지분 높은데 오너에게 현금이 필요해지는 사건 발생 종목 탐지.

원칙:
- 백테스트 검증 전까지 hypothesis 상태 · 자동매매 절대 연결 금지
- as-of 정렬 (reference_date vs release_date 분리)
- 출력 = 관찰 후보 + 이벤트 알림 (매수 추천 아님)
- Sniper/Watchlist 와 완전 분리

지시서: docs/plans/powderkeg-screener/phase7-powderkeg-screener.md
"""
