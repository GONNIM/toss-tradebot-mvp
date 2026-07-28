# P2-5 · activist-radar 이슈 A/B 근본 수정

**작성일**: 2026-07-28
**우선순위**: 🚨 긴급 · 라이브 허위 데이터 노출

## 실측 이슈
### A · "회사명 미확인" · SC 13G XML 파싱 실패
- `_NS = "schedule13D"` (대문자) · SC 13G URI `"schedule13g"` (소문자) 미매칭
### B · Wolf Pack 요약(0) vs 이벤트 필드(10명 허위)
- `target_desc` substring 매칭 · empty-string `"" in x == True` · 이슈 A 연쇄

## 수정
- Phase 1 · URI-agnostic XPath `.//{{*}}elementName`
- Phase 2 · `events_by_ticker` (target_ticker · ACTIVIST) · empty 가드 · detect_wolf_pack 재작성
- Phase 3 · `POST /meme-watch/activist/recompute-wolf-pack` (마이그레이션 API)
- Phase 4 · pytest 7건
- Phase 5 · v1.53 배포 · recompute 트리거

## 개정
| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-28 | v1.0 | 신규 · Phase 1~4 완료 |
