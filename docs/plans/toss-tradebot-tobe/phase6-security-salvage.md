---
title: 폐기된 tradebot-tobe에서 살린 것 · Phase 6 보안 5항
type: salvage-note
status: active
created: 2026-07-29
updated: 2026-07-29
supersedes: docs/plans/tradebot-tobe/tradebot-tobe-prompt.md (전량 폐기)
salvage_source: 위 문서의 Phase 6 부분만
---

# 폐기된 tradebot-tobe에서 살린 것 · Phase 6 보안 5항

## 0. 폐기 배경

**기존 문서**: `docs/plans/tradebot-tobe/tradebot-tobe-prompt.md` (Phase 0~6 · 6개 Phase 백테스트 인프라 지시서)

**폐기 근거** (4관점 만장일치 · 2026-07-29):
- Phase 0 (백테스트 인프라) — 이미 powderkeg 스크리너에서 실현됨. 재수집 불필요.
- Phase 1~5 (Activist·Sniper·Sector·Meme·VIP 고도화) — 정체성 재정의 (개인 판단 도구 · 정보 창구)와 방향 불일치. [[stage1-optimization]]의 3계층 재편 + Judgment Journal이 상위 대안.
- Phase 6 (보안·운영 하드닝) — **5항 중 대부분 유효** · 본 문서로 승계.

**사용자 지시**: "git rm 후 새 SSOT에 Phase 6 보안 5항만 살림" (2026-07-29).

## 1. 살린 항목 · Phase 6 보안 5항

### 6.1 공개 페이지 내부 설정 노출 제거

**원 지시**: "스나이퍼 설정 가이드(터미널 명령·`/Users/...`·env 키명) 공개 페이지에서 제거 → `docs/ops.md` 내부화"

**본 프로젝트 상태**:
- 현 사이트가 아직 무인증 접근 가능 · Stage 2 이관 전 반드시 완료
- 확인 대상: `/settings` · `/sniper` 페이지의 설명 문구

**실행 위치**: [[roadmap-12week#주-2·라우트-재편]] (주 2)

**방어 대상 리스크**: B3 (관리자/외부 분리 지연 → 무인증 실 종목 노출)

### 6.2 관리/실행 엔드포인트 인증 미들웨어 + rate limit + 감사 로그

**원 지시**: "관리/실행 계열 엔드포인트: 인증 미들웨어 필수 + rate limit + 실패 시 지수 백오프 + 감사 로그(누가·언제·무엇을)"

**본 프로젝트 상태**:
- `require_sniper_token` 데코레이터 이미 존재 (관리 엔드포인트에 적용)
- rate limit **미구현** (slowapi 등)
- **감사 로그 `sniper_api_access` 테이블 주석에만 존재** · 실체 없음 (리뷰 D 확증)

**실행 위치**:
- Rate limit: [[roadmap-12week#주-8·관측성]] (주 8 · Sentry와 병렬)
- 감사 로그: [[roadmap-12week#주-7·인증-이관]] (주 7)
- `slowapi` 도입 · `@limiter.limit("5/minute")` 관리 엔드포인트 적용

**방어 대상 리스크**: D1 (XSS 토큰 탈취) · A2 (실증 부재)

### 6.3 localStorage 토큰 → httpOnly 쿠키 + 회전

**원 지시**: "토큰: localStorage 대신 httpOnly 쿠키 세션 또는 최소한 만료 시간이 있는 토큰으로 교체. 토큰 회전(rotation) 절차 문서화."

**본 프로젝트 상태**:
- **localStorage 저장 3곳 확증** (리뷰 D): `sniper/page.tsx` · `watchlist/page.tsx` · `powderkeg/page.tsx`
- XSS 1건 → 실주문 토큰 유출 · 리스크 D1 (Critical)

**실행 위치**: [[roadmap-12week#주-7·인증-이관]] (주 7)

**세부**:
- httpOnly 쿠키 이관 · `lib/auth.ts` 통일
- Role 3단계 (admin/subscriber/anon)
- 토큰 회전 절차:
  - 관리자 매뉴얼 문서 (`docs/operations/token-rotation.md`)
  - 로테이션 트리거 · CLI 스크립트

**방어 대상 리스크**: D1 (Critical)

### 6.4 홈 화면 문구 · 투자 권유 방지

**원 지시**: '홈 화면 문구 수정: "절대 실현 손실 0" 제거 → "규칙 기반 손실 관리 · 검증된 시그널만 자동화" 로 교체. 목표 문구 "1,000만원 → 1억원"은 "위험 대비 수익(MDD 대비 CAGR) 극대화"로 교체.'

**본 프로젝트 상태**:
- 현 정체성이 이미 v3.0 "경제적 자유 실현 개인 전문 정보 창구"로 재정의됨 → [[identity#정체성-이력]]
- "절대 실현 손실 0" 슬로건 폐기 확정
- "카지노 자금" (moonshot) 워딩 폐기 확정

**실행 위치**:
- Home 재작성: [[roadmap-12week#주-2·라우트-재편]] (주 2)
- 유혹 요소 정화: [[stage1-optimization#4-3-유혹-요소-정화]]

**방어 대상 리스크**: A1 (자기 과신) · A2 (실증 부재) · C2 (v1.x 판정 무효화 · 정체성 이력 명시)

### 6.5 공개 페이지 투자 권유 아님 고지 · 일관 적용

**원 지시**: "공개 페이지 전체에 투자 권유 아님 고지 일관 적용(밈주 워치 수준의 고지를 전 모듈로 확대)"

**본 프로젝트 상태**:
- meme-watch 페이지에 자체 disclaimer 존재 (`components/meme-watch/UsageGuide.tsx`)
- 다른 페이지에는 명시 부재
- Stage 2 진입 시 자동 생성 문서 헤더 표준화 필요 (컨설팅·리포트)

**실행 위치**:
- Stage 1 완결 전: 각 페이지 하단 footer에 "정보 제공만 · 투자 권유 아님" 고지 배치
- Stage 2 이후: Weekly Report · Monthly Deep-Dive · 컨설팅 문서 헤더 자동 삽입 · [[sprint-revenue-integration#1-4-법적-방어선]]

**방어 대상 리스크**: A2 (실증 부재 → 규제) · C1 (T2 매출) · Stage 3 유사투자자문업 재평가 대비

## 2. 폐기 확정 항목 · 살리지 않은 것

원 문서 Phase 6 이외 항목 (Phase 0~5):

| 항목 | 폐기 근거 |
|---|---|
| Phase 0 · backend/backtest/ (engine·costs·asof·report) | 이미 `backend/powderkeg/backtest.py` 등에서 실현됨. 재수집 불필요. |
| Phase 1 · Activist Radar CAR 백테스트 · 승격 게이트 | Powderkeg의 통계 규율을 이식하는 것으로 대체 → [[stage1-optimization#2-powderkeg-통계-규율을-다른-페이지로-이식-a]] |
| Phase 2 · Sniper 페이퍼 모드 · 그리드 서치 | 자동매매 방향 재검토 후 착수. Stage 1 "자동매매 절대 연결 금지" 원칙 재확인. |
| Phase 3 · Sector-Leaders 관세청 잠정치 | 매크로 lagging 지표. Top N 카드 폐기 + 테이블만 유지 → [[stage1-optimization#4-3-유혹-요소-정화]] |
| Phase 4 · Meme Watch 역할 재정의 | 이미 사후 반응 시그널로 인식. [LAGGING] 배지 강제로 대체 → [[stage1-optimization#2-3-정보-유형-배지-강제]] |
| Phase 5 · VIP 매수가 앵커 제거 | Judgment Journal에 통합 (mood·invalidation·target). VIP 페이지는 개별 종목 딥다이브로 유지 → [[stage1-optimization#3-2-l2-·-심층-주말-리서치]] |

## 3. 이관 완결 확증

**폐기 실행**:
```bash
git rm docs/plans/tradebot-tobe/tradebot-tobe-prompt.md
git rm docs/plans/tradebot-tobe/tradebot-tobe-prompt.md.pdf
git rmdir docs/plans/tradebot-tobe/  # 폴더 비어 있음 확증
```

**Wiki 미러 동기화**:
`/Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/toss-tradebot-tobe/` 하위에 SSOT 사본.

**커밋 메시지 예**:
```
docs(planning): toss-tradebot-tobe SSOT 신설 · 기존 tradebot-tobe 폐기

- 4관점 병렬 리뷰 통합 (퀀트·UX·자산화·아키텍처)
- Stage 1~4 로드맵 · 12주 실행 계획
- 기존 tradebot-tobe/ 폐기 · Phase 6 보안 5항만 phase6-security-salvage.md로 승계
- Wiki 미러: GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/toss-tradebot-tobe/
```

## 4. 위임 · 다음 문서

- **폐기 후 신규 방향**: [[_INDEX]]
- **Phase 6 5항 실행 상세**: [[roadmap-12week]] (주 2·7·8)
- **리스크 매트릭스**: [[risks-and-guardrails]]
