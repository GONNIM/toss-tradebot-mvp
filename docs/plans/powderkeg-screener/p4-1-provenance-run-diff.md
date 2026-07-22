# P4-1 · 서희 provenance UI + Run diff 로그 · 구현 계획서

**작성일**: 2026-07-22
**우선순위**: 🥇 우선순위 1 · UX·기능 후속 (next-session.md §2)
**예상 소요**: 5~6h
**의존/후속**: 완료 후 P4-6 발굴 조건 표기 분리 → 단일 배포 v1.38

---

## 1. 목적

- **Run diff**: 스크리너 run 간 조건값·상태 변화 원인을 로그로 축적하여 "언제·왜 값이 바뀌었나"를 UI에서 즉시 확인
- **Provenance**: 종목 상세에서 조건별 값의 원천 컬렉터·수집 시각을 노출하여 데이터 신뢰도 정착
- **배경**: 서희 케이스처럼 파싱/집계 hotfix가 반복될 때, 사용자가 티어 이동·값 변화 원인을 스크리너 로그 없이도 판단 가능하게 함

---

## 2. 설계

### 2.1 DB 스키마 신규 (`backend/services/models.py`)

**PowderKegRun** — 스크리너 run 자체 기록
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | INTEGER PK | |
| started_at | DATETIME | UTC |
| ended_at | DATETIME | UTC · nullable |
| ticker_count | INTEGER | 이번 run 대상 티커 수 |
| trigger | VARCHAR(16) | `auto` / `manual` |
| git_sha | VARCHAR(40) | 배포 SHA (SSR 푸터와 일치) |

**PowderKegRunDiff** — 조건 단위 변화만 저장 (동일값 skip)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | INTEGER PK | |
| run_id | INTEGER FK | PowderKegRun.id |
| ticker | VARCHAR(16) | |
| condition_key | VARCHAR(64) | 예: `cond_2_debt`, `tier` |
| prev_value | TEXT | JSON 인코딩 (숫자/문자열 모두 수용) |
| curr_value | TEXT | |
| prev_status | VARCHAR(16) | `pass`/`fail`/`na`/`skip`/`null` |
| curr_status | VARCHAR(16) | |
| changed_at | DATETIME | UTC · 인덱스 |
| reason_hint | VARCHAR(255) | 선택 · 원인 힌트 |

**인덱스**: `(ticker, changed_at DESC)`, `(run_id)`, `(condition_key, changed_at DESC)`

### 2.2 screener.py 훅 · diff 삽입 (`backend/powderkeg/screener.py`)

- Run 시작 시 `PowderKegRun` 삽입 → `run_id` 획득
- `_evaluate_ticker` 결과 저장 직전에:
  1. 이전 스냅샷(마지막 pass 결과) 조회
  2. 조건별 값/상태 비교 → **변경된 조건만** RunDiff에 삽입
  3. 값 동일 skip · 신규 조건 등장 시 prev=null
- 조건 티어 이동(예: `tier_3_watch` → `tier_1_passed`)도 `condition_key='tier'`로 기록
- Run 종료 시 `ended_at` 업데이트

### 2.3 API 3종 신규 (`backend/api/routes/powderkeg.py`)

**GET `/api/v1/powderkeg/ticker/{ticker}/provenance`**
- 응답: 조건별 최근 값 + 출처(collector 이름) + 수집 시각 (dart_financials/krx_snapshot/adv60/ftc/big_biz 등)
- 활용: 상세 팝업 "변동 이력" 탭 상단

**GET `/api/v1/powderkeg/run-diff/latest?ticker={ticker}&limit=20`**
- 응답: 종목별 최근 N개 diff (내림차순)
- 활용: 상세 팝업 "변동 이력" 탭 목록

**GET `/api/v1/powderkeg/run-diff/summary?run_id=latest`**
- 응답: 최근 run에서 티어 이동/조건 변화 종목 목록
- 활용: 리스트 상단 요약 카드 · 뱃지 소스

### 2.4 Frontend UI (`frontend/app/powderkeg/page.tsx` + 상세 팝업)

- **리스트 뱃지**: 최근 24h 내 diff 있는 종목에 `🆕 변동` 표시
- **상세 팝업 확장** · "변동 이력" 탭 신설
  - 각 조건별 최근 N run 값·상태 타임라인
  - 조건별 provenance (원천 컬렉터 + 최종 수집일)
- **페이지 상단 요약 카드** (선택): `/run-diff/summary` 응답에서 티어 이동 종목 수 노출

### 2.5 테스트 (`backend/tests/`)

- `test_powderkeg_run_diff.py` 신규
  - PowderKegRun/PowderKegRunDiff 모델 CRUD
  - diff 계산 로직 단위 테스트 (동일값 skip · 상태 변화 · 신규 조건)
  - 3종 API 응답 스키마 검증
- `test_powderkeg_screener.py` 확장
  - 스크리너 run이 RunDiff를 실제로 삽입하는지 assertion

### 2.6 마이그레이션

- `POST /api/v1/powderkeg/admin/migrate-schema` 확장 (기존 패턴 유지)
- 새 테이블 2종을 idempotent 하게 생성
- 백필: 최초 배포 후 첫 run에서 자동 baseline 삽입 (prev=null)

---

## 3. 배포 전략

- P4-1 완료 → P4-6 (조건 ① 발굴 표기 분리) 완료 → **단일 배포 v1.38**
  - 근거: `feedback_deploy_only_when_complete` — 멀티 Phase는 통합 배포
- 배포 후 3중 실측 (`feedback_measure_not_declare`)
  - SSR SHA 확증 (footer)
  - Tier 1 목록 (기존 11 종목 유지)
  - 신규 API 3종 응답 스키마

---

## 4. 리스크 · 완화

| 리스크 | 완화 |
|---|---|
| RunDiff 폭증 (조건 20개 × 100 종목 × 매 run) | 변경분만 저장 · 동일값 skip · 인덱스 정합 |
| 마이그레이션 실패 시 스크리너 중단 | migrate-schema는 idempotent · 실패 시 diff 저장만 skip |
| 이전 스냅샷 없음 (최초 run) | prev=null baseline · 다음 run부터 정상 diff |
| Frontend 팝업 무거워짐 | 변동 이력은 클릭 시 lazy fetch |

---

## 5. 완결 정의 (Done Criteria)

- [ ] `PowderKegRun`, `PowderKegRunDiff` 모델 + 마이그레이션 idempotent
- [ ] screener run 시 자동으로 diff 삽입 (동일값 skip · 상태 변화 기록)
- [ ] 3종 API 정상 응답 · pytest 통과
- [ ] 리스트 뱃지 + 상세 팝업 "변동 이력" 탭 정상 렌더 (dev server 확증)
- [ ] 단일 배포 v1.38 · SSR SHA + Tier 1 + 신규 API 3중 실측 통과
- [ ] `next-session.md` P4-1 완료 표시 · 본 계획서 개정 이력 업데이트

---

## 6. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-22 | v1.0 | 신규 · 사용자 승인 후 저장 |
| 2026-07-22 | v1.1 | 로컬 구현 완료 · Backend 3종 API + Frontend UI + pytest 9/9 · 회귀 22/22 통과 · 배포 대기 |
