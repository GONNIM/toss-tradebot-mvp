---
title: Rulebook 신설 · 강의 원칙 통합 결정 로그
type: decision-log
status: approved
decided_at: 2026-08-02
decided_menu: "📏 Rulebook (/rulebook)"
decided_position: L2
created: 2026-08-02
supersedes: null
depends_on:
  - docs/operations/principles/johnma-8-fundamentals.md
  - docs/plans/toss-tradebot-tobe/roadmap-12week.md
sync_target: /Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Rulebook/rulebook-integration.md
---

# Rulebook 신설 · 강의 원칙 통합 결정 로그

## 배경

Phase E 사용 정착기 진입 후, 외부 강의(존마 주식 기초 강의 #08)의 3원칙을 검토.
원칙 2·3(손익비·물타기 금지)이 Toss Tradebot 정체성에 완전 부합 · 원칙 1(우량주 5단계)은 정체성 불일치.

**사용자 결정 (2026-08-02)**:
1. 기존 메뉴에 통합하지 않고 **새 메뉴** 신설
2. 원칙 문서화 + Obsidian sync 필수 적용

---

## 결정 · 새 메뉴 신설 (사용자 확정 · 2026-08-02)

- **이름**: 📏 **Rulebook** (`/rulebook`)
- **위치**: **L2 첫 항목** (Powderkeg 앞) · 매일 아침 원칙 훑고 실 판단은 다른 페이지에서

**미채택안 (참고)**: B 🎓 Discipline · C 📐 Playbook

---

## 구성 계획

### 상단 · 3원칙 요약 카드
- 손익비 > 승률 · -5% 손절 · R:R ≥ 2 목표
- 물타기 금지 · invalidation 이탈 즉시 청산
- 5단계 필터는 참조 링크만 (`/lab/blue-chip-filter` 예정)
- 출처 · [[../operations/principles/johnma-8-fundamentals]]

### 위젯 1 · R:R 계산기
- 입력: entry · invalidation · target (수동 또는 현재가 API)
- 출력: R:R 실시간 · 색상 (≥2 초록 · <2 노랑 · <1 빨강)
- 도움말: 각 값의 의미 · 강의 사례 (-5%/+30% = R:R 6)

### 위젯 2 · 물타기 감지 로그
- 데이터 소스: `GET /api/v1/judgments?filter=invalidation_hit=true` (신규 필터)
- 컬럼: ticker · invalidation · invalidation_hit_ts · outcome · 물타기 여부(bool)
- 요약 KPI: 최근 30일 물타기율 · Journal baseline과 연동

### 위젯 3 · 우량주 벤치마크 (Phase 2 · `/lab` 이관 검토)
- 존마 원칙 1의 5단계 필터 결과
- Powderkeg (딥밸류) 결과와 병치 · 판정 벤치마크

### 하단 · 원칙별 참조 노트 (Obsidian 링크)
- 강의별 요약 문서 링크 (Obsidian Wiki `Rulebook/`)
- 향후 다른 원칙 소스 추가 시 여기에 append

---

## 관련 백엔드/DB 변경

### Alembic (Phase F 착수 시)
- `user_judgments.invalidation_hit_ts DateTime nullable`
- `user_judgments.invalidation_hit_low Float nullable`
- outcome 크론 확장 · 기간 내 저가 검사

### 신규 API
- `GET /api/v1/rulebook/rr-stats` — 최근 N일 R:R 분포 · baseline 확장
- `GET /api/v1/rulebook/invalidation-hits` — 물타기 감지 판정 목록
- `GET /api/v1/judgments/baseline` 응답에 `avg_rr_ratio` · `invalidation_hit_rate` 추가

### 신규 프론트
- `frontend/app/rulebook/page.tsx` (혹은 승인된 route)
- `frontend/components/rulebook/RRCalculator.tsx`
- `frontend/components/rulebook/InvalidationHitLog.tsx`
- `frontend/components/rulebook/PrincipleCard.tsx`

---

## Obsidian Sync 대상

**Wiki 위치**: `/Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Rulebook/`

**동기화 파일**:
1. `Rulebook/johnma-8.md` — 강의 3원칙 요약 (SSOT = `docs/operations/principles/johnma-8-fundamentals.md`)
2. `Rulebook/rulebook-integration.md` — 본 결정 로그 미러
3. `Rulebook/_INDEX.md` — 원칙별 소스 인덱스 (향후 추가되면 append)

**Sync 방식**:
- 초기 · 수동 복사 (본 세션에서 실행)
- 이후 · `scripts/sync_wiki.py` 에 `--target rulebook` 서브명령 추가 (Phase F 착수 시)

---

## 다음 단계 (사용자 승인 대기)

1. 메뉴 이름 A/B/C 선택 + 위치 L1/L2 선택
2. 승인 후 코드 착수 순서:
   - Tier 1-A (R:R baseline API) → 30분
   - Tier 1-C (R:R 계산기 위젯 + `/rulebook` 페이지 skeleton) → 1시간
   - Tier 1-B (invalidation 이탈 감지 + Alembic + 물타기 로그) → 1.5시간
   - Tier 2 (우량주 벤치마크) → 반나절 · 사용 정착 후

3. 원칙 문서화 · Obsidian sync는 **본 세션에서 완료** (SSOT + Wiki 미러 + 결정 로그)
