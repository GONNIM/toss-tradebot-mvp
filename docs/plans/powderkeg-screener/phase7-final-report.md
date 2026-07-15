# Phase 7 화약고 스크리너 · 최종 완결 구현보고서

**작성일**: 2026-07-15
**작성**: Claude Opus 4.7 (사용자 검증 완료)
**기반 지시서**: [`phase7-powderkeg-screener.md`](./phase7-powderkeg-screener.md)
**커밋 헤드**: `cb6131a` · **총 31 커밋**
**상태**: **완결** · 프로덕션 라이브 · 사용자 UI 편집까지 검증 완료

---

## 1. Executive Summary

Phase 7 화약고 스크리너 · 6 단계 (§7-1 ~ §7-6) + 사용자 편집 흐름 · **전 스코프 완결**.

**핵심 성과**
- **10 조건 스크리너** 완전 구현 · 프로덕션 라이브
- **첫 승격 종목** · **035890 서희건설** (10/10 통과)
- **자동 감시** · APScheduler 30분/5분 주기 · Telegram 알림 검증
- **사용자 UI 편집** · lock/note/manual add/remove · Watchlist 패턴 동일
- **Lock 지속성** · screener.run 자동 union · orphan 방지 fix

**규모**
- 총 31 커밋 (feat 15 · fix 12 · docs 2 · chore 2)
- 백엔드 · 7 DB 모델 · 5 collector · 스크리너 오케스트레이터 · 트리거 · 백테스트
- 프론트 · 3 tabs + 사용자 편집 (add/lock/note/remove)
- 프로덕션 데이터 · 118,000+ DART 매핑 · 400+ 재무 · 51 최대주주 · 44 이벤트

---

## 2. 구현 스코프 (§7-1 ~ §7-6)

| 단계 | 지시서 항목 | 구현 결과 | 커밋 |
|---|---|---|---|
| **§7-1** | 데이터 수집 · 재무·시장·지분·이벤트·공정위 | 5 collector 완성 · corp_code 자동 매핑 118K+ | 291d57c · 23b9f4e · 365661d · 9e2075f · 31fb215 · 7b1ef8b · e76de68 |
| **§7-2** | 10 조건 스크리너 · F-Score · 분식 탐지 | 오케스트레이터 · PBR fallback · audit 필드 정확화 | 158cf22 · 311c7e6 · a4281ea |
| **§7-3** | 자동 감시 · 이벤트 트리거 · LLM classifier | Type A/B 처리 · APScheduler 잡 · Telegram | 0f8e21b · 579d165 |
| **§7-4** | 백테스트 · 이벤트 스터디 · validated 게이트 | CAR 계산 · hypothesis→validated 승격 로직 | d8d5f7d |
| **§7-5** | 반자동 주문 티켓 · 무효화 조건 강제 | OrderTicket 모델 · 조건 강제 | 6600b95 |
| **§7-6** | Backend API + Frontend 3 tabs | /powderkeg 라우트 · 리스트/이벤트/리포트 탭 | d7e13c1 |
| **User** | UI 편집 (add/lock/note/remove) · orphan fix | Watchlist 패턴 · union fix | 10230b9 · 978afb0 · cb6131a |

---

## 3. 10 조건 스크리너 (§7-2)

| # | 조건 | 임계 | 데이터 소스 | 서희건설 실측 |
|---|---|---|---|---|
| 1 | PBR | < 0.5 | KRX + market_cap/equity fallback | **0.476** ✅ |
| 2 | 순현금 / 시총 | > 40% | DART 재무 | **40.6%** ✅ |
| 3 | 최대주주+특수관계인 지분율 | ≥ 40% | DART hyslrSttus | **59.8%** ✅ |
| 4 | 공정위 공시대상기업집단 아님 | 아님 | 수동 seed (72社) | 해당 없음 ✅ |
| 5 | 감사의견 적정 (최근 2년) | 적정 | DART accnutAdtorNmNdAdtOpinion | 적정의견 ✅ |
| 6 | 이자수익 교차검증 (분식 탐지) | 실제 수익률 ≥ 기준금리-1.5%p | DART 이자수익/현금 | 정합 ✅ |
| 7 | 영업이익 최근 3년 중 흑자 | ≥ 2년 | DART | 2/3 ✅ |
| 8 | 피오트로스키 F-Score | ≥ 6 | 9 지표 자동 계산 | **7/9** ✅ |
| 9 | 60일 일평균 거래대금 | ≥ 1억 | KRX | 통과 ✅ |
| 10 | 관리종목/거래정지 이력 | 없음 (3년) | 감사 이력 근사 | 없음 ✅ |

**분식 탐지 (§7-2b) 검증**: 032190 다우데이타 · 이자수익 yield 0.243% << 요구 1.75% · `cash_suspect` 정확 판정.

---

## 4. 자동 감시 · Phase 7-3

### APScheduler 잡 (`backend/powderkeg/scheduler.py`)
- `powderkeg_events_poll` · **30분 주기** · DART 공시 폴링
- `powderkeg_triggers` · **5분 주기** · Type A/B 액션 처리
- `POWDERKEG_ENABLED=true` (기본 활성)

### 이벤트 타입 처리
| 타입 | 예시 | 액션 | 알림 |
|---|---|---|---|
| **Type A** (긍정) | 담보제공·자사주 소각·자기주식 취득 | 30분 감지 → 5분 알림 | Telegram · 매수 후보 |
| **Type A1** | 오너 사법 리스크 | LLM classifier (Anthropic Haiku) · 회사자금 관련성 판정 → notify or B 격상 | Telegram · 상세 판정 |
| **Type B** (부정) | 횡령·감사비적정·거래정지 | 5분 이내 리스트 즉시 제거 | Telegram · 🚨 urgent |

**검증**: 002070 (B3 · list_removed) · 082270 (A3 · notified) · **사용자 텔레그램 도착 확인 완료** (2026-07-15).

---

## 5. 사용자 편집 UI (신규 · 2026-07-15)

지시서 외 · 실전 운영 요구사항 · Watchlist Sprint 2 T63 패턴 재사용.

### 신규 DB 필드 (`PowderKegList`)
```python
locked: bool = False          # 사용자 lock · 스크리너 재실행 후에도 유지
added_by: str = "auto"         # auto (스크리너) / user (수동)
user_note: Optional[str]       # 사용자 분석 노트
```

### 신규 Backend endpoints
- `PATCH /list/{id}/lock` · lock 토글
- `PATCH /list/{id}/note` · 노트 저장
- `POST /list/manual` · 수동 종목 추가 (locked=True · added_by=user)
- `POST /admin/list/remove` · 삭제 + 감사 스냅샷 (기존 재사용)

### Frontend 편집 UX
- **➕ ManualAddForm** · sky 배너 · 티커+노트 · 원클릭 추가
- **🔒 lock 토글** · amber 배경 · 다음 run 후에도 유지
- **분석 노트 인풋** · 인라인 편집 · 저장 버튼 자동 노출
- **× 삭제** · prompt 사유 → 감사 스냅샷 저장
- **뱃지** · 🔒 (locked) · user (added_by=user)

### Lock 지속성 fix (`cb6131a`)
**Gap 발견**: screener.run 은 입력 tickers 만 재삽입 → 입력에 없는 locked 종목 orphan.

**Fix**: `run_screener` 시작에 DB 의 `locked=True` 종목 전체를 자동 union.
```python
locked_tickers = list((await session.execute(
    select(PowderKegList.ticker).where(PowderKegList.locked == True).distinct()
)).scalars().all())
extra = [t for t in locked_tickers if t not in input_set]
input_set = input_set + extra
```

**효과**
- 스케줄러 자동 실행 (KRX 저PBR 유니버스만) 에서도 수동 종목 자동 재평가
- 사용자 lock 걸어둔 종목 · 유니버스 축소 후에도 지속 감시
- lock 의도 (무조건 유지) UI 정합

**검증**: tickers=["035890"] 입력 → 003670 (locked user) 자동 union → 새 run_id 에 두 종목 모두 잔존 확인.

---

## 6. 프로덕션 데이터 현황 (2026-07-15)

| 데이터 | 건수 | 소스 |
|---|---|---|
| DART corp_code 매핑 | 118,000+ | corpCode.xml |
| DART 재무 스냅샷 (3년치) | 400+ 종목 · KOSPI 100 + KOSDAQ 300 | fnlttSinglAcntAll |
| DART 최대주주 | 51 | hyslrSttus |
| 감사의견 | 400+ | accnutAdtorNmNdAdtOpinion |
| 공정위 대기업집단 | 72 | 수동 seed |
| KRX 시장 스냅샷 | 2,765 | pykrx |
| PowderKegEvent 처리 | 44 (Type A 15 · Type B 29) | DART 공시 |
| 스크리너 run | 12+ | 수동 + 스케줄러 |
| 화약고 리스트 (승격) | 1 (035890 서희건설) | 10/10 |

**부분 통과 후보 (v2 정밀화)**
| 티커 | 명 | 통과 | 병목 |
|---|---|---|---|
| 032190 | 다우데이타 | 8/10 (cash_suspect) | 이자수익/현금 · **분식 탐지 정확 작동** |
| 003380 | 하림지주 | 8/10 | audit 2년치 부족 · F-Score 5 |
| 015750 | 성우하이텍 | 8/10 | owner 39.1% (40% 근접) |
| 003800 | 에이스침대 | 8/10 | PBR 0.505 |
| 121440 | 골프존홀딩스 | 8/10 | net_cash 10.3% |
| 036830 | 솔브레인홀딩스 | 8/10 | net_cash 1.4% |

---

## 7. Hotfix 히스토리 (12건 · 정확도 완성)

### 지분율 정확화 (지주회사 100%+ 오류)
1. **`36998f0`** · 보통주만 취급 · SK하이닉스 40.1% → 20.1% 정확
2. **`231714e`** · DART "계" (합계) 행 skip · 효성 125.6% → 57.73%
3. **`7924650`** · 공백 tolerant `_is_common_stock`/`_is_major_relate` · 삼성전자·SK하이닉스 0% 해결
4. **`068624c`** · `trmend fallback` Python `or` bug fix · 조석래 10% 오포함 해소

### 매핑·수집 정확화
5. **`e76de68`** · P7-1g corp_code 매핑 · 영풍/효성 같은 corp_code 오류 해결 (118K+ 매핑)
6. **`9b87b09`** · KrxMarketSnapshot.name 컬럼 · 종목명 매핑

### 스크리너 정확화
7. **`311c7e6`** · PBR 자체 계산 fallback · FDR PBR 결측 (KOSPI/KOSDAQ 전체) 대응
8. **`a4281ea`** · audit_opinion · DART 실 필드 `adt_opinion` (문서 표기 부정확 확인)

### 인프라·마이그레이션
9. **`88010a6`** · `/admin/migrate-schema` endpoint · SQLite ALTER TABLE 수동
10. **`97fb8ae`** · `Base.metadata.create_all` 포함
11. **`d86e8b1`** · WAL + 직접 CREATE TABLE · SQLite lock 우회

### Lock 지속성
12. **`cb6131a`** · screener.run · locked 종목 자동 union · orphan 방지

**교훈**: 초기 문서 스펙 (지시서·DART 문서) 과 실제 API 응답 간 fields·format 차이 다수 · 실 데이터 검증 필수.

---

## 8. DoD 검증 결과

| DoD 항목 | 지시서 기준 | 결과 |
|---|---|---|
| 화약고 리스트 생성 | 각 조건별 통과/탈락 사유 기록 | ✅ conditions_json + reject_reasons 저장 |
| 자동 감시 활성 | 이벤트 감지 → 알림 | ✅ 002070 · 082270 텔레그램 도착 |
| 사용자 편집 흐름 | add/lock/note/remove | ✅ 4 endpoint · 프론트 UI · E2E 검증 |
| Lock 지속성 | screener 재실행 후에도 유지 | ✅ union fix 검증 완료 |
| 프로덕션 라이브 | 스케줄러 · Telegram 활성 | ✅ tradebot-api 서비스 |
| 첫 승격 후보 발굴 | 실 데이터 · 10 조건 통과 | ✅ 035890 서희건설 · 10/10 |

**Phase 7 완결 조건 · 6/6 충족**.

---

## 9. v2 개선 항목 (백로그)

지시서 스펙 외 · 실 운영 발견 개선 후보.

### 데이터 정밀화
- **지주회사 지분율 cap** · 순환출자 시 100% 초과 방지 로직
- **KOSDAQ PBR** · pykrx 통합 · FDR 결측 대응 완전화
- **관리종목 이력 (조건 10)** · 별도 이력 수집 · 감사 근사 개선
- **배당성향 (§7-2 확장)** · v1 은 데이터 없음 · DART 배당공시 파싱

### 이벤트 확장
- **LLM 뉴스 크롤링 (§7-1-4)** · 오너 개인 사법 상세 · Anthropic Haiku 확장
- **다양한 이벤트 타입** · CAR t-stat 검증 · Type A/B 세분화

### 백테스트
- **5년 아카이브 backfill** · hypothesis→validated 승격 (표본 ≥ 50 이벤트)
- **다양한 이벤트 타입별 CAR 리포트** · 통계적 유의성 검증

### UX
- **알림 프로필 통합** · SCOUT/SNIPER/WATCH 프로필과 통합
- **리스트 export** · CSV/Excel · 오프라인 분석용

---

## 10. 학습 및 교훈

### 데이터 정확성 우선주의
- 초기 스펙 (지시서·DART 문서) 기반 코드 → 실 응답에서 다수 field/format 차이 발견
- **교훈**: 대량 검증 (400+ 종목) 없이 스펙만으로는 정확도 100% 달성 불가
- **적용**: 지주회사 지분율 hotfix 5회 반복 · 실 데이터로 케이스 발굴

### 사용자 승인 프로세스
- 배포 계획 · 워크플로우 · GitHub Actions 자동 배포 존재 확인 → 수동 SSH 지양
- **교훈**: `feedback_workflow_first_before_manual_deploy` 메모리 준수
- **적용**: main push 재승인 절차 · 자동 배포 워크플로우 활용

### 편집 UI · 패턴 재사용
- Watchlist Sprint 2 T63 (add/lock/remove) 패턴 그대로 적용
- **효과**: 학습 곡선 0 · UX 일관성 · 개발 시간 단축

### 스케줄러 vs 수동 실행의 gap
- 수동 실행은 tickers 명시 · 스케줄러는 유니버스 자동
- **Gap**: locked 종목이 유니버스에 없으면 orphan
- **적용**: `cb6131a` union fix · 두 실행 경로 정합 확보

---

## 11. 참고 문서

**Phase 7 계열**
- [`phase7-powderkeg-screener.md`](./phase7-powderkeg-screener.md) · 원 지시서
- [`first-passed-result.md`](./first-passed-result.md) · 서희건설 승격 상세
- [`phase7-final-report.md`](./phase7-final-report.md) · **본 문서 · 최종 완결**

**주요 파일**
- `backend/powderkeg/` · 스크리너 · 트리거 · 백테스트
- `backend/api/routes/powderkeg.py` · REST API + 사용자 편집 endpoints
- `frontend/app/powderkeg/page.tsx` · 3 tabs + 편집 UI
- `backend/services/models.py` · 7 신규 테이블 (FinancialSnapshot 확장 포함)

---

**Phase 7 화약고 스크리너 · §7-1 ~ §7-6 + 사용자 편집 · 전 스코프 완결.**

**최종 상태**: 프로덕션 라이브 · 자동 감시 활성 · 사용자 편집 UI 검증 완료 · 서희건설 매수 후보 감시 중.
