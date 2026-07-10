# Toss Tradebot MVP v2 — 고도화 로드맵

**상태**: 🟢 트랙 C 확정 (2026-07-10) · 로드맵 승인 · **Phase 0 대부분 완료 (Toss Open API 채택)** · Phase 1 착수 대기
**목표**: 시그널 발굴에 머물던 MVP에 **실제 매매 실행 레이어 + 자금 관리 수학 + 실시간성 + KR/US 통합 + 조건주문 자동화**를 결합해 실전 운용 가능한 자동매매 봇으로 승격

---

## 📄 문서 인덱스

| # | 문서 | 상태 | 요약 |
|---|---|---|---|
| 00 | [`00-critic-review-2026-07-10.md`](./00-critic-review-2026-07-10.md) | 🟢 완료 | 외부 크리틱(실전 투자자 관점 5% 갈증) 팩트 체크 및 트랙 C 확정 |
| 01 | [`01-track-c-roadmap.md`](./01-track-c-roadmap.md) | 🟢 승인 · Toss 반영 | 트랙 C 정식 구현계획서 (Phase 0~5, 아키텍처, DoD, 리스크 매트릭스) |
| 02 | [`02-omi-interface-spec.md`](./02-omi-interface-spec.md) | 🟢 v2 · Toss 반영 | Order Manager Interface 상세 스펙 (Enum·데이터 모델·예외·어댑터 계약·감사 로그) |
| 03 | [`03-toss-openapi-integration.md`](./03-toss-openapi-integration.md) | 🟢 스펙 확정 | 토스증권 Open API v1.2.2 원문 정독 · 27개 엔드포인트 · 에러 매핑 · Phase 2 검증 프로토콜 |

---

## 🧭 핵심 결정

- **트랙 C** — 트랙 A(실행 채널) + 트랙 B(내실화) 결합, 단계별 릴리즈
- **Broker Adapter Pattern** — 시그널 엔진은 브로커 중립 (향후 확장 대비)
- **Toss Open API v1.2.2 전격 채택** (2026-07-10 사용자 API 키 확보) — KR/US 통합 + 조건주문 SINGLE/OCO/OTO 표준 지원 + REST 전용 (기존 스택 정합)
- **선(先) 안전장치** — Phase 1에서 Paper 어댑터 + 리스크 예산 + Kill Switch 먼저 배포
- **실 자본 최소 노출** — Phase 2 실계좌 검증 시 소액 상한 10만 원 하드코딩

---

## 🚦 진행 상태

- [x] 크리틱 검토 및 트랙 확정
- [x] 구현계획서 초안
- [x] 사용자 승인 (`01-track-c-roadmap.md`, 2026-07-10)
- [x] Phase 0 착수 — env 스키마 확장 · OMI 스펙 문서화
- [x] **KIS→Toss 전격 전환** (2026-07-10) — Toss Open API 원문 정독 · 문서 3개 재편 · 프로젝트 메모리 등록
- [x] 토스 API 클라이언트 등록 완료 (사용자 · 2026-07-10)
- [ ] Phase 0 완료 — `.env` 실 값 저장 · 허용 IP 등록 · `accountSeq` 확보 (사용자 액션)
- [ ] Phase 1~5 순차 진행

---

## 🔗 관련 메모리
`reference_toss_open_api` · `project_sector_leaders_progress` · `project_meme_stock_discovery` · `project_wen_vip_watch` · `project_activist_radar` · `reference_tossbot_deploy`
