---
title: Sprint 2026-1억 Revenue-Tree 연동
type: business-integration
status: active
created: 2026-07-29
updated: 2026-07-29
sprint_ssot: [[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/Kickoff]]
revenue_tree: [[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/Revenue-Tree]]
critical_finding: "Revenue-Tree v2.2에 optimus8 배치 0건 → Q1 미달 시 폐기 1순위 (리뷰 C 지적)"
---

# Sprint 2026-1억 Revenue-Tree 연동

## 0. 진단 (리뷰 C 근본 지적)

**Revenue-Tree v2.2** (T1 반복 17% / T2 단발 83% / T3 lump-sum 0% 유예)에 **optimus8 배치 0건**.

즉 현재 optimus8은 Sprint 매출 트리에서 존재감 없음. Sprint 원칙 "프로젝트는 서브루틴 · 프로젝트 그 자체가 목표 아님"에 정면 위배. **Q1 미달 시 폐기 1순위** (리뷰 C 리스크 C1).

본 문서는 optimus8을 Sprint 매출 트리에 명시 배치하는 방법을 정의.

## 1. 즉시 배치 · T2 컨설팅 상품 신설

### 1.1 상품 정의

- **명칭**: "optimus8 판정 근거 조회 컨설팅"
- **채널**: Cal.com 슬롯 재정의 ([[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/gonnim-landing/Cal.com-Setup]] 기 완결)
- **형식**: 30분 유료 1:1 세션
- **콘텐츠**:
  - 사용자가 관심 있는 종목 조회 → optimus8 판정 이력 열람
  - 화약고 조건별 근거 · Activist 신호 여부 · Meme 반응 여부
  - 반증 조건 · 유사 사례 이력
  - 판정 재현 (run_id·git_sha)

### 1.2 즉시 오픈 가능성

**리뷰 C 판정**: "**즉시 가능** · 그러나 T2에 배치 안 되어 있음"

즉 프로덕트는 이미 있고, 상품 페이지·결제만 붙이면 오픈. Sprint 3주차 (D-7 홍보) 이후 첫 유료 예약 목표.

### 1.3 준비 항목

- [ ] Cal.com 슬롯 이름 "optimus8 판정 조회 (30분)" 등록
- [ ] 랜딩 페이지 상품 카드 추가 (`gonnim.dev/consulting`)
- [ ] 예약 시 대상 종목 (max 3) 수집 폼
- [ ] 세션 전 판정 이력 자동 pull (판정 permalink 활용)
- [ ] 세션 후 요약 문서 자동 생성 · Obsidian `Consulting/{date}-{client}.md`
- [ ] 결제: 우선 계좌 이체 → Stage 3 이후 Stripe/Toss Payments

### 1.4 법적 방어선

- 상품 설명에 "**투자 권유 아님 · 정보 제공만**" 명시
- "구체 매수·매도 시점 조언 불가" 사전 고지
- 세션 후 문서에도 동일 헤더 표준화

## 2. 4주 준비 · Weekly Report 자동 초안

### 2.1 상품 정의

- **명칭**: "optimus8 Weekly Insights"
- **주기**: 매주 일 08:00
- **콘텐츠**:
  - 이번 주 화약고 신 승격·강등 diff
  - 이번 주 Activist 이벤트 (13D 신규·13G→13D 전환)
  - Tier 1 lock 종목 현황
  - 반자동 티켓 결과 (있는 경우)
- **채널**: 무료 (Stage 2 관심 유입) → 심화 파티션 유료 (Stage 3)

### 2.2 자동 초안 생성 트리거

- [[stage2-architecture#4-5-obsidian-sync-3경로-자동화]]의 매주 일 08:00 훅으로 자동 생성
- 사람 편집 최소화 (오탈자·문맥 마무리만)

### 2.3 4주 준비 로드맵

- W1: 판정 4요소 컬럼 · powderkeg_tier_history 신설
- W2: Obsidian sync Runs/Weekly 훅 완결
- W3: Weekly 초안 생성 자동화 · Wiki 저장
- W4: 첫 발행 · Dry-run 1주 관찰

## 3. 8~12주 준비 · Monthly Deep-Dive

### 3.1 상품 정의

- **명칭**: "optimus8 Monthly Theme Deep-Dive"
- **주기**: 매월 1일
- **콘텐츠**: 특정 산업·테마별 판정 이력 종합
- **가격**: 유료 리포트 (10~30만원 · Sprint T2 lump-sum 축)

### 3.2 준비 조건

- `powderkeg_krx_snapshot`에 **섹터·테마 필드 확장** 필요
- 판정 이력 간 크로스링크 (활동가 신호 종목이 화약고 승격 시 자동 링크 · [[stage2-architecture#4-5-obsidian-sync-3경로-자동화]])
- 최소 3개월 판정 축적 후 첫 발행 가능

## 4. 6개월+ · 강의·교재

### 4.1 상품 정의

- **명칭**: "화약고 스크리너 v2 조건 왜 이 6개인가"
- **형식**: 온라인 클래스 or PDF 교재
- **가격**: 온라인 5~20만원 · PDF 3~10만원

### 4.2 준비 초석

이미 있는 자산:
- [[../powderkeg-screener/identity]] v2.0 · 정체성 명시
- [[../powderkeg-screener/p2-2c-reverse-engineer-features]] · 역설계 근거
- [[../powderkeg-screener/first-passed-result]] · 첫 승격 사례
- [[../powderkeg-screener/3rd-review-response]] · 4th-review-response · 자기 검토 이력

부족한 자산:
- "왜 F-Score 6→4로 완화했는가" 결정 이력이 세션 1건 (P2-2d)에 갇힘 → **판정 이력 자산화 시 자동 축적**

## 5. Sprint Radar 연동 훅

### 5.1 판정 이력 → 사업 아이템 스코어링 근거

- [[../../../../GON-LLM-Wiki/Goals/2026-1억-Sprint/Sprint-Radar/Sprint-Radar-Spec]] 참조
- Sprint Radar가 사업 아이템 스코어링 시 optimus8 판정 이력을 흡수 가능
- API: `/api/v1/read/judgments?ticker={ticker}` (public read)

### 5.2 접점

- Sprint Radar가 특정 산업·테마 아이템을 발견 → 관련 종목의 optimus8 판정 근거 자동 pull
- Weekly Ops 회고 시 "이번 주 optimus8 판정 정확도" 자동 집계

## 6. 매출 목표 배치 (Revenue-Tree 갱신 제안)

**현재** (v2.2, 2026-07-29):
- T1 반복: 17%
- T2 단발: 83%
- T3 lump-sum: 0% (유예)

**제안 갱신** (optimus8 배치):

| 축 | 상품 | 예상 매출 |
|---|---|---|
| T1 | Weekly Insights 심화 파티션 유료 (Stage 3 이후) | (Stage 2 검증 후 확정) |
| T2 | optimus8 판정 조회 컨설팅 (30분) · Cal.com | 5~10만원/건 |
| T2 | Monthly Theme Deep-Dive PDF | 10~30만원/건 |
| T2 | 강의·교재 (6개월+) | 5~20만원/건 |

**Revenue-Tree v2.3 반영 필요** — Sprint Kickoff와 병렬 갱신.

## 7. Stage 이행 KPI 연동

- Stage 1 합격 · **T2 Cal.com 슬롯에 첫 유료 예약 1건** → [[identity#stage-2-지식-자산화]] 진입
- Stage 2 합격 · Weekly Report 유료 구독자 5명+ · 첫 Monthly Deep-Dive 판매 → Stage 3 진입
- Stage 3~4 · SaaS 인프라 · [[stage2-architecture#5-3-결제-훅-스텁]] 활성화

## 8. 위임 · 다음 문서

- **자산화 훅 (Obsidian sync)**: [[stage2-architecture#4-자산화-훅]]
- **판정 이력 저장 · Judgment Journal**: [[stage1-optimization#1-judgment-journal-신설]]
- **리스크 · 자매 봇 크로스 오염 방지**: [[risks-and-guardrails]]
