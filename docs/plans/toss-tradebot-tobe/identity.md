---
title: optimus8 정체성 · Stage 1~4 로드맵
type: identity
status: active
created: 2026-07-29
updated: 2026-07-29
version: 1.0
---

# optimus8 정체성 · Stage 1~4 로드맵

## 정체성 재정의 (2026-07-29)

**optimus8**은 GON이 그동안 섭렵한 주식 관련 가설·이론을 실시간 판정 가능한 형태로 메뉴화한, **경제적 자유 실현을 위한 개인 전문 정보의 창구**다.

- **사이트**: https://optimus8.cafe24.com
- **자매 프로젝트**: [[../../../../GON-LLM-Wiki/Works/Trading/Upbit-Tradebot-MVP/_INDEX|orionhunter7 (upbit-tradebot-mvp)]] · EMA/MACD 크립토 자동매매 · **완전 분리 유지**
- **상위 SSOT**: [[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/_INDEX|2026-1억 Sprint]] · 12개월 1억 매출 목표의 서브루틴
- **매출 트리 연동**: [[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/Revenue-Tree|Revenue-Tree v2.2]] · T2 (단발 상담·리포트) 채널로 배치 예정 → [[sprint-revenue-integration]]

## Stage 로드맵

성장 원칙: **각 단계에서 합격해야 다음 단계로 이동/확장** (사용자 확정 2026-07-29).

### Stage 1 · 개인 판단 도구 (현재)

- **소비자**: GON 혼자 · 외부 공개 없음
- **법적 스탠스**: 순수 개인 도구 · 규제 무관
- **성공 기준**: 판정 정확도 baseline 확립 · 매일 아침·마감후 사용 정착
- **가장 큰 함정**: Selection bias 자기 과신 · "내 도구는 나에게 맞다" 착각 (리뷰 A 지적)

### Stage 2 · 지식 자산화

- **소비자**: GON + Sprint T2 컨설팅 예약자 (Cal.com 슬롯 유료 전환)
- **법적 스탠스**: 정보 제공만 (투자 권유 아님 헤더 표준화)
- **상품 후보** (근접도 순):
  - Weekly Report (4주 준비 · Obsidian sync 훅 완결 시 자동 초안)
  - Monthly Deep-Dive (8~12주 준비 · 산업/테마 크로스링크 필요)
  - 강의·교재 (6개월+ · identity·역설계 근거 초석)
  - 1:1 컨설팅 (즉시 가능 · **Cal.com 슬롯 재정의만 하면 오픈**)
- **진입 자격 KPI**: Judgment Journal 30건+ · rejection criteria 100% · Obsidian sync 3경로 · T2 유료 예약 1건

### Stage 3 · 하이브리드

- **소비자**: 관심 유입 무료 사용자 + 심화 유료 사용자
- **법적 스탠스**: 유사투자자문업 신고 여부 재평가 (금융위 상담 예정)
- **아키텍처 요구**: user_id 격리 · httpOnly 쿠키 · /admin vs /read vs /insights URL 분리 · Postgres 전환
- **재작업 규모**: Stage 1에서 아키텍처 결정 안 하면 **6~8주 재작업 강제** (리뷰 D 지적) → [[stage2-architecture]]로 사전 대비

### Stage 4 · 외부 유료 구독 (SaaS)

- **소비자**: 정기 구독자 · 기업 라이선스
- **법적 스탠스**: 정식 유사투자자문업 or 콘텐츠 발행 (규제 재평가)
- **인프라**: Stripe/Toss Payments · SLA · 관측성 · 다중 서버
- **매출 목표**: Revenue-Tree T1 (반복 매출) 축 주력

## 핵심 원칙 (Stage 1~4 공통)

1. **자동매매 절대 연결 금지** — 반자동 1클릭 티켓까지만. identity.md v2.0 [[../powderkeg-screener/identity]] 원칙 계승.
2. **판정→결과 폐루프 강제** — 판정 시 rejection criteria·target·horizon·mood 필수. T+7·T+30 outcome 자동 계산.
3. **가설별 검증 상태 라벨** — hypothesis / observing / validated / rejected. 상태 없이 표시 금지.
4. **재현성 = git_sha 필수** — 모든 판정에 배포 SHA 각인. v1.55.1에서 완결.
5. **자산화 준비 = 매 판정 자동 문서화** — Obsidian sync 3경로 (Runs · Weekly · Tickers).
6. **Sprint 서브루틴 자각** — 프로젝트 자체가 목표 아님. 12개월 1억 매출 실현에 기여해야 존재 가치.

## 폐기된 정체성 · 워딩

- "절대 실현 손실 0" 슬로건 (기존 홈 워딩) — 리스크 관리 원칙과 상충 · 폐기
- "카지노 자금" 워딩 (moonshot 페이지) — 감정 매매 유도 · 폐기 or 페이지 자체 삭제
- Toss API 기반 자동매매 → 개인 판단 정보 창구로 정체성 이동

## 정체성 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-06-16 | v0.1 | 초기 · "Toss API 기반 주식 자동매매 봇 MVP" (CLAUDE.md) |
| 2026-07-11 | v1.0 | 사용자 재정의 · "급등주 사전 예측 봇" ([[../../memory/project_true_identity]]) |
| 2026-07-13 | v2.0 | Strategic pivot · pre-market ([[../../memory/project_strategic_pivot_pre_market]]) |
| 2026-07-24 | v2.0 (powderkeg 특화) | [[../powderkeg-screener/identity]] · "2026 하반기 한국주식 투자 이익 창출" |
| 2026-07-29 | v3.0 | **"경제적 자유 실현 개인 전문 정보 창구"** · Sprint 서브루틴 자각 · Stage 로드맵 |
