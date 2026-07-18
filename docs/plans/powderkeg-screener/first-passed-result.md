# Phase 7 화약고 스크리너 · 첫 승격 결과

**날짜**: 2026-07-15 (최초) · **2026-07-18 v1.1 정정**
**커밋 헤드**: `579d165` (최초) · `3b90573` (P2-4e 완결 후 정정 실측)
**Run ID**: `20260715-063915` (최초) · `20260718-141834K` (정정 재평가)

---

## 🚨 v1.1 정정 경고 (2026-07-18)

**서희건설의 최초 승격은 DART 재무 파싱 오류에 기반한 부풀린 값이었음** — 3차 리뷰 P2-4b hotfix (`ea40f4b`) 로 확증. 상세는 `3rd-review-response.md` §12 참조.

### 요약
- 최초 (v1.0): `net_cash_ratio 40.6%` · **10/10 · Tier 1 · passed**
- 실측 (v1.1): `net_cash_ratio 16.3%` · **9/10 · Tier 2 (경계) · rejected**
- 원인: `_DEBT_KEYWORDS`가 서희 표기(`차입금등(유동)`·`차입금등(비유동)`·`리스부채`)를 substring 매칭 못해 `total_debt = NULL` · 순현금이 차입금 1,128억을 차감 못하고 부풀림

### 정정 후 실측 (P2-4e 완결 후 `20260718-141834K` 재평가)
```
tier          : tier_2_near
status        : rejected
passed        : 9/10
net_cash_ratio: 0.163  (16.3%)
reject_reasons: net_cash_adj<0.4(0.163) · raw=0.163 · contract_liab=0 · sector=건설
```

---

## 최초 승격 (v1.0 · 2026-07-15 · 파싱 오류 상태 · 역사적 기록)

### 035890 · 서희건설 · ~~**status = "passed"** (10/10)~~ · **정정 · rejected (9/10)**

지시서 `phase7-powderkeg-screener.md` §7-2 · **10 조건 전부 통과 · 화약고 리스트 승격**.

| # | 조건 | 임계 | 서희건설 실측 | 판정 |
|---|---|---|---|---|
| 1 | PBR | < 0.5 | **0.476** | ✅ |
| 2 | 순현금(현금+단기금융-총차입금) / 시총 | > 40% | ~~40.6%~~ · **실 16.3%** (v1.1 정정) | ❌ 실 판정 |
| 3 | 최대주주+특수관계인 지분율 | ≥ 40% | **59.8%** | ✅ |
| 4 | 공정위 공시대상기업집단 소속 | 아님 | 아님 | ✅ |
| 5 | 감사의견 (최근 2년) | 적정 | 적정의견 | ✅ |
| 6 | 이자수익 / 평균 현금성자산 vs (기준금리-1.5%p) | ≥ | 정합 | ✅ |
| 7 | 영업이익 최근 3년 중 흑자 | ≥ 2년 | 2/3 | ✅ |
| 8 | 피오트로스키 F-Score | ≥ 6 | **7/9** | ✅ |
| 9 | 60일 일평균 거래대금 | ≥ 1억 | 통과 | ✅ |
| 10 | 관리종목/거래정지/감사비적정 이력 (3년) | 없음 | 없음 | ✅ |

지시서 완료 기준 · **화약고 리스트가 생성되고 각 조건별 통과/탈락 사유가 기록된다** · 완결 (단, 조건 2 파싱 오류는 3차 리뷰까지 미발견 → v1.1 정정).

---

## v1.1 정정 실측 (2026-07-18 · P2-4b·c·d·e 완결 후)

`_DEBT_KEYWORDS` 확장 (커밋 `ea40f4b`, `a59494a`) 후 서희 재파싱:

### DB 재파싱 결과 (`powderkeg_financial_snapshot`)
| 필드 | 최초 v1.0 | v1.1 정정 |
|---|---|---|
| `cash_and_equivalents` | 188,130,985,813 (1,881억) | 188,130,985,813 (동일) |
| `total_debt` | **NULL** (파싱 실패) | **112,780,285,630** (1,128억) |
| `contract_liabilities` | (컬럼 없음) | NULL (서희 CFS 응답에 계정 부재) |
| `net_cash` | 1,881억 (부풀림) | 753억 |
| `market_cap` (역산) | 4,629억 | 4,629억 |
| `net_cash_ratio` | 0.406 (부풀림) | **0.163** |

### 원 계정 실측 (raw_json.diag_bs_liab_items · 16 items)
서희 2024 사업보고서 CFS · 부채 관련 원 계정 (P2-4b 이후 진단 저장):
- 차입금등(유동) · 774억
- 차입금등(비유동) · 206억
- 유동 리스부채 · 84억
- 비유동 리스부채 · 63억
- **합 · 1,128억** ← v1.0 에서 파싱 실패로 total_debt=NULL 이었음

### 재평가 결과 (Run ID `20260718-141834K`)
```
tier          : tier_2_near         (Tier 2 · 경계)
status        : rejected            (10/10 아님 · 매수 후보 아님)
passed        : 9/10                (조건 2 만 실패)
net_cash_ratio: 0.163               (16.3% · 조건 2 임계 40% 미달)
reject_reasons: net_cash_adj<0.4(0.163) · raw=0.163 · contract_liab=0 · sector=건설
```

### 승격 취소 결정
- 서희건설의 status = "passed" · Tier 1 승격은 **파싱 오류 기반 부풀림**
- 정정 후 실 판정: **rejected · Tier 2 (경계) · 조건 2 net_cash 실패**
- Type A 이벤트 감시 대상에서 제외 (rejected 종목은 자동 리스트 제거 대상)
- 사용자 판단으로 lock 하고 관찰만 유지 가능 (locked=True + rejected)

### 관련 문서
- `3rd-review-response.md` §12 · 서희 재판정 실측 (반박문 §6·§9 및 재재반박 §6 오예측 정정)
- `3rd-review-response.md` §12 · P2-4c·d·e · 26/26 total_debt 매칭 · 계약부채 3층 판별

---

## 부분 통과 후보 (v2 정밀화 대상)

| 티커 | 명 | 조건 통과 | 병목 |
|---|---|---|---|
| 032190 | 다우데이타 | 8/10 (cash_suspect) | 이자수익/현금 미달 (**분식 탐지 정확 작동**) · F-Score 5 |
| 003380 | 하림지주 | 8/10 | audit 2년치 부족 · F-Score 5 |
| 015750 | 성우하이텍 | 8/10 | owner 39.1% (40% 근접) · F-Score 4 |
| 003800 | 에이스침대 | 8/10 | PBR 0.505 (0.5 근접) · net_cash 14.1% |
| 121440 | 골프존홀딩스 | 8/10 | net_cash 10.3% |
| 036830 | 솔브레인홀딩스 | 8/10 | net_cash 1.4% |

---

## 파이프라인 데이터 통계 (2026-07-15 기준)

| 데이터 | 건수 |
|---|---|
| DART corp_code 매핑 | 118,000+ |
| DART 재무 (3년치) | 400+ 종목 · KOSPI 100 + KOSDAQ 300 |
| DART 최대주주 | 51 |
| DART 이벤트 (44건 처리) | Type A 15 (notified) · Type B 29 (list_removed) |
| 공정위 대기업집단 | 72 |
| KRX 스냅샷 | 2,765 |
| 스크리너 run | 11회 |

---

## 실행 세션 하이라이트 (2026-07-15)

**연속 hotfix 20+ 커밋** · 정확도 완성 흐름:
1. `P7-1g corp_code` · DART 공식 매핑 · 영풍/효성 매핑 오류 해결
2. `보통주만` · 우선주 배제 · SK하이닉스 40.1% → 20.1% 정확화
3. `"계" 행 skip` · DART 합계 중복 카운트 방지 · 효성 125.6% → 57.73%
4. `공백 tolerant` · relate="최대주주 본인" · stock_knd="의결권 있는 주식" 대응
5. `trmend fix` · Python `or` bug · 조석래 0% → 정확
6. `PBR fallback` · market_cap / total_equity · FDR PBR 결측 해결
7. `audit_opinion` · DART 실 필드 `adt_opinion` (문서 표기 부정확 확인)
8. `WAL + direct CREATE` · SQLite lock · migrate-schema
9. `Phase 7-3 자동 감시` · APScheduler 잡 등록 · 30분/5분 주기

---

## Phase 7-3 자동 감시 활성

- `powderkeg_events_poll` · 30분 주기 · DART 공시 폴링
- `powderkeg_triggers` · 5분 주기 · Type A/B 액션 처리
- POWDERKEG_ENABLED=true (default)

**서희건설 특수 이벤트 시나리오**
- Type A (담보제공·자사주 소각 등) · 30분 감지 + 5분 알림 · **매수 후보 텔레그램 알림**
- Type B (횡령·감사비적정·거래정지) · **5분 이내 리스트 즉시 제거** · 🚨 urgent 알림
- Type A1 (오너 사법 리스크) · LLM classifier · 회사자금 관련성 판정 → notify or B 격상

---

## v2 개선 항목

- 지주회사 관계인 지분율 · 순환출자 시 100% cap 검토
- KOSDAQ PBR 데이터 · pykrx 통합 (FDR 결측 대응)
- LLM 뉴스 크롤링 (§7-1-4 · 오너 개인 사법)
- 5년 아카이브 backfill · 백테스트 validated 승격 (표본 ≥ 50)
- 다양한 이벤트 타입별 CAR 리포트 t-stat 검증

---

**Phase 7 지시서 §7-1 ~ §7-6 6 단계 완결 · ~~첫 승격 후보 서희건설 확인~~ · 자동 감시 라이브.**

**v1.1 정정** (2026-07-18): 첫 승격 서희건설은 파싱 오류 기반 부풀림 값 · 실 판정 tier_2_near · rejected · 3차 리뷰 P2-4b hotfix 로 확증. 상세 · [`3rd-review-response.md`](./3rd-review-response.md#12-서희건설-재판정-실측-p2-4p2-4b--2026-07-18) §12.

---

## 개정 이력

| 날짜 | 버전 | 변경 | 커밋 |
|---|---|---|---|
| 2026-07-15 | v1.0 | 최초 승격 · 서희건설 10/10 · Tier 1 · passed | `579d165` |
| 2026-07-18 | v1.1 | 서희 승격 정정 · net_cash 40.6% → 16.3% · Tier 1 → Tier 2 (경계) · passed → rejected · 원인 `_DEBT_KEYWORDS` 파싱 실패 · P2-4b hotfix (`ea40f4b`) 후 실측 반영 | (pending) |
