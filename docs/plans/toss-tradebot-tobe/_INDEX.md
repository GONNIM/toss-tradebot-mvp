---
title: toss-tradebot-tobe · MOC
type: fact-table
status: active
created: 2026-07-29
updated: 2026-07-29
sprint_link: [[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/_INDEX]]
supersedes: docs/plans/tradebot-tobe/ (폐기)
---

# toss-tradebot-tobe · MOC

> **작성일**: 2026-07-29 · **채택 근거**: 4관점 병렬 리뷰 (퀀트·UX·자산화·아키텍처) 통합
>
> **정체성 재정의**: optimus8 = "경제적 자유 실현을 위한 개인 전문 정보 창구" · 2026-1억-Sprint 서브루틴
>
> **폐기**: 기존 `docs/plans/tradebot-tobe/` (범용 6 Phase 백테스트 인프라 지시서) · Phase 6 보안 5항만 [[phase6-security-salvage]]로 흡수

## 로드맵 요약

Stage 1 (개인 판단 도구, 현재) → Stage 2 (지식 자산화) → Stage 3 (하이브리드) → Stage 4 (외부 유료 구독)

**각 단계 합격 후 진입** · Stage 1 진입 자격 60% 미달 (리뷰 C 판정)

## 문서 인덱스

### SSOT (핵심 문서 · 순독 순서)
1. [[identity]] — 정체성 · Stage 1~4 로드맵 · 원칙
2. [[stage1-optimization]] — Stage 1 즉시 최적화 (Judgment Journal · 통계 규율 이식 · 3계층 재편 · 폐기)
3. [[stage2-architecture]] — Stage 1→2 이행 아키텍처 (user_id · URL 이원화 · 인증 · 자산화 훅 · 관측성)
4. [[sprint-revenue-integration]] — Sprint 2026-1억 Revenue-Tree 연동 (T2 배치 · Cal.com · Weekly Report)
5. [[risks-and-guardrails]] — 크로스컷 리스크 12 (A×3 + B×3 + C×3 + D×3) · 방어선
6. [[roadmap-12week]] — 12주 실행 로드맵 · Stage 이행 KPI
7. [[phase6-security-salvage]] — 폐기된 tradebot-tobe에서 살린 Phase 6 보안 5항

### 리뷰 원본 아카이브 (재현성 · 근거)
- [[reviews/perspective-a-quant-psychology]] — 퀀트·투자심리 관점
- [[reviews/perspective-b-ux-information-architecture]] — 정보설계·UX·사용자 여정 관점
- [[reviews/perspective-c-knowledge-assetization]] — 지식자산화·에디토리얼 관점
- [[reviews/perspective-d-architecture-business]] — SaaS·사업모델·아키텍처 관점

## 원칙

1. **판정 우선 · 실행 후행** — 자동매매 절대 연결 금지. 반자동 티켓까지만.
2. **판정→결과 폐루프 강제** — 모든 판정에 rejection criteria·outcome·mood 필수. Judgment Journal에 병치 (self-page 편애 방지).
3. **가설별 검증 상태 라벨** — hypothesis / observing / validated / rejected. 상태 없이 표시 금지.
4. **소비자는 나 혼자 (현 Stage 1)** — 관리자 인증 100% · 무인증 실 종목 노출 0. `/admin/*` 이관.
5. **재현성 = git_sha 필수** — 모든 판정 결과에 배포 SHA 각인 (v1.55.1 완결).
6. **문서화 = 자산화 준비** — 매 판정·관찰이 GON-LLM-Wiki로 자동 sync (Obsidian 그래프 편입).
7. **Sprint 서브루틴** — optimus8이 Sprint T2 매출에 실제 배치 (Cal.com 컨설팅 슬롯).

## Obsidian 동기화

**Wiki 미러**: `/Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/toss-tradebot-tobe/`
- 본 리포지토리 `docs/plans/toss-tradebot-tobe/`가 **SSOT**
- Wiki 사본은 읽기 뷰 · 편집 시 SSOT 먼저 갱신 후 재복제
- 향후 [[stage2-architecture#자산화-훅]]의 자동 sync 훅으로 대체 예정

## 상태

| 단계 | 상태 | 근거 |
|---|---|---|
| 통합안 채택 | ✅ 2026-07-29 | 사용자 승인 |
| SSOT 문서화 | ✅ 2026-07-29 | 본 폴더 |
| 기존 tradebot-tobe 폐기 | ⏳ 대기 | git rm 예정 |
| Wiki 미러 | ⏳ 대기 | 문서화 직후 복제 |
| 실행 착수 (주 1) | ⏳ 사용자 판단 | [[roadmap-12week]] 참조 |
