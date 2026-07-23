# P4-5 · KRX 관리종목 실데이터 (KIND 크롤링) · 구현 계획서

**작성일**: 2026-07-23
**우선순위**: 🥈 우선순위 2 · 실데이터화 (next-session.md §2)
**예상 소요**: 4~5h
**의존/후속**: 완료 후 단일 배포 v1.39 · 다음 screener run에서 실 데이터 반영

---

## 1. 목적

- 조건 ⑩ (관리종목 이력 없음) 판정을 **감사의견 3년 근사 → KIND 실 크롤링 기반**으로 정확화
- 매일 스냅샷 저장 · 종목별 지정 이력 추적
- reject_reasons에 지정 사유·지정일 노출 (판단 근거)

---

## 2. 데이터 소스 (실측 통과)

| 용도 | Method | URL | 응답 | 인코딩 |
|---|---|---|---|---|
| 관리종목 리스트 | POST | `https://kind.krx.co.kr/investwarn/adminissue.do` | HTML fragment · 111건 | UTF-8 |
| 매매거래정지 리스트 | POST | `https://kind.krx.co.kr/investwarn/tradinghaltissue.do` | HTML fragment · 125건 | UTF-8 |
| 회사명↔종목코드 매핑 | GET | `https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13` | HTML 표 · 2,759건 | **EUC-KR** |

**주의사항** (실측 근거):
- Referer 헤더 필수 (없으면 빈 body 200 반환)
- 인코딩 이중화 (adminissue/haltissue는 UTF-8, corpList는 EUC-KR)
- corpList는 1.2MB이므로 하루 1회 캐시 (in-memory or file)
- Rate limit 관측된 사례 없음 · 일 3 요청은 무해

**대안 검토 및 기각**:
- data.krx.co.kr JSON API (`MDCSTAT03301` 등): 2026년부터 로그인 강제화 · 봉쇄됨
- FinanceDataReader krx: KRX_ID/KRX_PW 로그인 필요 · 우회 곤란
- pykrx: 관리종목 카테고리 미지원
- KRX OPEN API (openapi.krx.co.kr): 인증키 신청 리드타임 · 백업으로만 등록 검토

---

## 3. 설계

### 3.1 DB 스키마 · `PowderKegKrxIssue` (신규)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | INTEGER PK | |
| ticker | VARCHAR(10) | 인덱스 |
| name | VARCHAR(200) | |
| kind | VARCHAR(16) | `admin` (관리종목) or `halt` (매매거래정지) |
| reason | VARCHAR(500) | 지정 사유 |
| designation_date | VARCHAR(20) | KIND 원문 · YYYY-MM-DD or 원문 그대로 |
| snapshot_date | VARCHAR(10) | 스냅샷 채집일 (YYYY-MM-DD) · 인덱스 |
| refreshed_at | DATETIME | server_default now |

인덱스: `(ticker, kind, snapshot_date DESC)`, `(snapshot_date)`

**append-only** 정책 · 매일 새 스냅샷을 새 row로 저장 → 이력 유지

### 3.2 Collector · `backend/powderkeg/collectors/krx_admin_issue.py` (신규)

함수:
- `_session()` → requests.Session with common headers (User-Agent)
- `fetch_admin_issues()` → list[dict] · 관리종목 파싱
- `fetch_trading_halt()` → list[dict] · 거래정지 파싱
- `fetch_name_to_ticker()` → dict[str, str] · corpList 파싱 · in-memory 캐시 (하루 1회)
- `refresh_admin_issue_snapshot(snapshot_date=None)` → 3 API 호출 · matched 계산 · PowderKegKrxIssue 삽입 (오늘 날짜 스냅샷)
- Retry: 최대 2회 재시도 (기본 timeout 15s) · 실패 시 stats["errors"] 카운트

### 3.3 API · `POST /powderkeg/collectors/krx-admin-refresh` (인증 필수)
- 응답: `{snapshot_date, total_admin, total_halt, matched, unmatched, sample_unmatched:[...]}`

### 3.4 Screener 조건 ⑩ 개선 (`backend/powderkeg/screener.py`)

- 최근 스냅샷 조회 · 대상 티커가 관리/정지 리스트에 있는지 확인
- 최근 N년 (설정: 3년) 지정 이력 존재 여부도 검사
- 로직:
  - 스냅샷 미수집 → c10 = None (fallback 없음 · 3상태 유지)
  - 대상 티커가 최근 스냅샷 리스트에 있음 → c10 = False · reject_reasons에 사유·kind·지정일
  - 최근 3년 지정 이력 있음 → c10 = False · reject_reasons에 최근 지정일 표시
  - 위 모두 아님 → c10 = True

**호환성**: 현재 v1.35 감사 3년 근사(대안 B)는 P4-5 배포 후 제거.

### 3.5 테스트 · `backend/tests/test_powderkeg_krx_admin.py` (신규)

- HTML 파싱 (fixture 저장 · 실 fetch mocking) · 관리종목 fixture · 정지 fixture · corpList fixture
- name→ticker 매핑 정확도
- Snapshot append + lookup
- Screener 조건 ⑩ 통합 시나리오
  - 스냅샷 없음 → c10=None
  - 관리종목 리스트에 있음 → c10=False, 사유 노출
  - 정상 → c10=True

### 3.6 migrate-schema · 신규 테이블 idempotent CREATE

기존 패턴대로 `direct_creates` 리스트에 CREATE TABLE IF NOT EXISTS 추가 + 인덱스 3~4개.

---

## 4. 커버리지 gap · 알려진 미매칭

- 관리종목 111건 중 7건(ETF/우선주)이 corpList에 없음
- Powderkeg 유니버스는 이미 저PBR 공통주 발굴 파이프라인 통과분이므로 100% 커버 예상
- 만약 미매칭 종목이 유니버스에 등장하면 warning 로그 + unmatched 리스트에 남김

---

## 5. 배포 전략

- Backend + Frontend(선택) 완료 후 **단일 배포 v1.39** (`feedback_deploy_only_when_complete`)
- 배포 후 절차:
  1. `POST /admin/migrate-schema` → 신규 테이블 생성
  2. `POST /collectors/krx-admin-refresh` → 첫 스냅샷 축적
  3. `POST /screener/run` (Tier 1 lock 11 종목) → 조건 ⑩ 실 데이터 반영 확증
- 3중 실측 (`feedback_measure_not_declare`)
  - SSR SHA
  - Tier 1 목록 (회귀 없음)
  - `/collectors/krx-admin-refresh` matched/unmatched 실측
  - screener 결과에서 c10 근거 노출

---

## 6. 리스크 · 완화

| 리스크 | 완화 |
|---|---|
| KIND 응답 포맷 변경 | 파싱 실패 시 stats["errors"]++ · 로그 · 이전 스냅샷 유지 |
| corpList EUC-KR 인코딩 오류 | `r.encoding = "euc-kr"` 명시 · 테스트 fixture 이중화 |
| 커버리지 gap (ETF/우선주) | 스크리너 대상 아님 · 무해 · warning 로그만 |
| KIND IP 차단 | 일 3 요청 · 실측 리스크 낮음 · 필요 시 24h 재시도 |
| Screener 조건 ⑩ 로직 변경으로 회귀 | 기존 v1.35 감사 근사 test 유지 + 신규 통합 test 병행 |

---

## 7. 완결 정의 (Done Criteria)

- [ ] `PowderKegKrxIssue` 모델 + 마이그레이션 idempotent
- [ ] `krx_admin_issue.py` collector · KIND 3 엔드포인트 실측 통과 · matched ≥ 94%
- [ ] `krx-admin-refresh` API 정상 응답 · pytest 통과
- [ ] Screener 조건 ⑩ 실 데이터 반영 · fallback 로직 제거 · 3상태 유지 (None/False/True)
- [ ] pytest 신규 케이스 모두 pass · 회귀 없음
- [ ] 단일 배포 v1.39 · SSR SHA + Tier 1 + refresh matched 3중 실측 통과
- [ ] `next-session.md` P4-5 완료 표시 · 본 계획서 개정 이력 갱신

---

## 8. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-23 | v1.0 | 신규 · 사용자 승인 후 저장 |
| 2026-07-23 | v1.1 | 로컬 구현 완료 · Collector(admin 93.7% · halt 98.4% 매칭 실측) + DB + API + screener 조건 ⑩ 통합 + pytest 12+8/12+8 pass · 배포 대기 |
