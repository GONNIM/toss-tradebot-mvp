# Principles Gate 설계 v1 (2026-08-23)

> **본 문서는 설계안 · 구현 착수는 별건 세션 · 사용자 승인 후.**
> 관련 charter: [`backend/principles/charter.json`](../../../backend/principles/charter.json) v1.0.8

## 0. 개념 정리 · PASS = 매수 후보 리스트

- **PASS ≠ 매수 신호**. 저평가 우량주 5원칙 (PER · shareholder_return · dividend_continuity · debt · sector_diversification) 통과는 **매수 후보** (candidate list) 를 의미할 뿐이다.
- 실제 매수 판단은 (a) 시점 (시황·차트) · (b) 트랑셰·분산 (섹터 상한 · 포지션 크기) · (c) 실체 검증 (TTM 급증/급감·일회성 이익) 을 별도 층으로 통과해야 한다.
- **PrinciplesGate = fail-closed 화이트리스트** 관문. 신호가 매수 실행에 도달하기 전 · PASS 리스트 소속 여부를 강제.

## 1. 게이트 3층 구조

```
[신호 원천 layer]  Serenity · SuperSignal · Sniper · VIP · MemeWatch · Radar (수동 판정 포함)
       │
       ▼
[게이트 3-1 · PrinciplesGate]  PASS 리스트 소속 여부 · fail-closed 화이트리스트
       │
       ├─ 매수 신호가 PASS 소속 → 3-2 진입
       └─ PASS 아님 → 자동 매수 차단 + 사유 로그 (관리 화면 병치)
       ▼
[게이트 3-2 · 섹터 분산]  편입 시점 포트폴리오 섹터 30% 상한 검증
       │
       ├─ 편입 시 30% 이하 예상 → 3-3 진입
       └─ 초과 → 매수 차단 + 사유 (섹터 코드 · 현재 비중 · 편입 후 예상)
       ▼
[게이트 3-3 · 실체 검증 태깅]  TTM 구성 분기 이상 패턴 자동 태깅
       │
       ├─ 태깅 없음 → 자동 매수 허용
       └─ 태깅 있음 ("실체 검증 필요") → 자동 매수 보류 + 사용자 확인 요구
```

## 적용 범위 · 매수 (BUY) 전용

**게이트는 매수 (BUY) 신호에만 적용 · 매도는 우회** (포지션 청산 방해 금지).
- 매도는 리스크 축소 · 관문 통과 요구 없음
- 구현: `signal_router.py::route()` 안 `if req.side == OrderSide.BUY:` 조건부 삽입
- 근거: 이미 PASS 통과해 진입한 종목이 후에 PASS 리스트에서 빠져도 청산 자유

## 3-1 PrinciplesGate

**목적**: 매수 신호가 PrinciplesRun 의 최신 PASS 리스트에 포함된 종목만 실행 진입 가능.

**설계**:
- 위치: `backend/execution/signal_router.py` 안 · 신규 `class PrinciplesGate(Gate)` 게이트
- 로직:
  ```python
  latest_run = SELECT * FROM principles_runs ORDER BY id DESC LIMIT 1
  pass_tickers = SELECT ticker FROM principles_results
                 WHERE run_id = latest_run.id AND verdict = 'PASS'
  if signal.ticker not in pass_tickers and not is_whitelisted(signal.source):
      return GateResult(allowed=False, reason='principles_fail_closed',
                         detail=f"ticker {signal.ticker} not in PASS list of run {latest_run.id}")
  ```
- **fail-closed**: PrinciplesRun 자체가 없거나 (cache_empty_skip) · 최근 run 이 26시간 이상 stale → **차단** (신호 소스 무관 · charter 원안). 예외 화이트리스트만 통과.
- **화이트리스트**: `sniper` 소스 (사용자 명시 대안 · 짧은 스캘핑 목적 · PASS 무관). 화이트리스트 소스는 게이트 우회 · 하지만 사유 로그에 `whitelist_bypass=sniper` 명기.

**차단 사유 로그** (관리 화면 병치):
- `principles_fail_closed` · PASS 아님
- `principles_run_stale` · 최근 run > 26h 경과
- `principles_run_missing` · principles_runs 비어있음
- `sector_over_limit` (3-2 에서)
- `verification_required` (3-3 에서 · 자동 차단 아니라 사용자 확인 요구 상태)

**관리 화면 병치**: 
- `/principles/screener` 페이지에 최근 차단 이력 (최근 20건) 표 표시
- 각 사유별 카운트 (지난 26h) · 이상 급증 시 알림 (예: `sector_over_limit` 시간당 10건 이상 → 게이트 로직 재검토)

**구현 지점**:
- `backend/execution/signal_router.py::PrinciplesGate` (신규 클래스 · 예상 60~80 라인)
- `backend/api/routes/principles.py` · `/principles/gate/blocked-recent` 신규 endpoint (예상 30 라인)
- `frontend/app/principles/gate-history/page.tsx` (신규 · 예상 120 라인)

**예상 규모**: 백엔드 100 라인 + 프론트 120 라인 + 단위 테스트 4~6 케이스 (60 라인) = **총 ~280 라인**

## 3-2 섹터 분산

**목적**: 편입 시점 포트폴리오 섹터 30% 상한 검증. 특정 섹터 (반도체·자동차 등) 편중 방지.

**설계**:
- 위치: `backend/execution/signal_router.py` 안 · 신규 `class SectorDiversificationGate(Gate)`
- 로직:
  ```python
  current_positions = SELECT ticker, shares × latest_price AS value
                      FROM broker_positions WHERE broker='toss'
  # 티커 → 섹터 (induty_code) 매핑 · principles_financial_cache 또는
  #   serenity_ticker_prices.sector · manual_overrides 참조
  sector_map = build_sector_map(current_positions.tickers)
  total_value = sum(current_positions.values)
  # 편입 시 예상 · signal.value_krw (매수 예정 금액)
  signal_sector = sector_map.get(signal.ticker) or resolve_sector(signal.ticker)
  current_sector_value = sum(p.value for p in current_positions if sector_map.get(p.ticker) == signal_sector)
  new_ratio = (current_sector_value + signal.value_krw) / (total_value + signal.value_krw)
  if new_ratio > 0.30:
      return GateResult(allowed=False, reason='sector_over_limit',
                         detail={'sector': signal_sector, 'current_ratio': current_sector_value/total_value,
                                 'projected_ratio': new_ratio, 'limit': 0.30})
  ```
- **induty_code 기반**: `principles_financial_cache.industry_code` (a7d2b5c9e3f1 마이그레이션 · 이슈 B) 또는 `serenity_ticker_prices.sector` 사용
- **포트폴리오 현재 비중 조회 경로**: 
  - 토스증권 대시보드 캐시 (`backend/api/routes/dashboard.py::get_toss_account`) 에서 실 보유 종목·평가액 조회
  - 대안: `user_judgments` (Journal · 판정 저장) 의 open positions
  - 자동 매수 로직이 어느 broker 를 사용하는지에 따라 결정 (현재는 토스증권 미러링 우선)

**구현 지점**:
- `backend/execution/signal_router.py::SectorDiversificationGate` (신규 · 예상 100 라인 · sector resolver 포함)
- `backend/execution/sector_resolver.py` (신규 · industry_code → sector 매핑 · manual_overrides 병행 · 예상 60 라인)
- 단위 테스트 (섹터 계산 · manual_overrides · 경계값 · 예상 80 라인)

**예상 규모**: **총 ~240 라인**

## 3-3 실체 검증 태깅 (신규 · 세션 B 구현 완료 2026-08-23)

**확인 스코프 (2026-08-23 최종 확정)**: `(ticker, tags_hash)` **이중키** · run_id 감사 필드로만.
- 이유: recompute 마다 실효 시 재확인 피로 → 기계적 승인 유도 (보호 장치 자기 무력화)
- 태그 구성 동일 → 확인 유지 · 구성 변경 → hash 불일치 자동 실효

## 3-3 실체 검증 태깅 (원문 · 참고)

**목적**: PASS 종목이라도 TTM 구성 분기의 이상 패턴 (단분기 급감/급증 · 일회성 의심) 을 자동 태깅해 게이트가 자동 매수를 보류하고 사용자 확인 요구.

**근거 (실측)**:
- **SJG세종 (033530)** · PER 1.88 · TTM 963억 · 2025 Q4 단독 +6.9억 (Q1~Q3 평균 227억 대비 3%) · 2026 Q1 +384억 급증 · 저평가 무늬
- **두올 (016740)** · PER 4.23 · TTM 211억 · 2025 Q4 단독 -13.8억 (Q1~Q3 흑자 대비 음전환) · Q4 이례

**태깅 규칙 초안** (charter v1.0.9 후보 · 임계값은 사용자 최종 결정):

**(a) 단분기 이례**
- 최근 8개 단독 분기 (`_standalone_series` 결과) 시리즈에서
- `|q_standalone − q_prev_4q_avg| > q_prev_4q_avg × 1.0` (직전 4Q 평균의 100% 초과 · 급증·급감·음전환 감지)
- 예 (실증): SJG세종 Q4'25 +6.9억 vs 직전 4Q 평균 227억 · 편차 220억 > 227억 · 태깅
- 예 (실증): 두올 Q4'25 -13.8억 vs 직전 4Q 평균 100억 · 편차 113억 > 100억 · 태깅

**(b) TTM 의 특정 분기 의존**
- `max(recent_4q_standalone) / TTM > 0.50` (단일 분기가 TTM 의 50% 초과 · 지속성 결함 의심)
- 예: SJG세종 TTM 963억 · Q1'26 384억 = 40% (경계) · Q2'26 336억 = 35% · 태깅 대상 아니지만 (b) 는 border

**(c) 태깅 종목 처리**
- verdict 는 PASS 유지 (5원칙 자체는 통과)
- `principles_results.verification_tags: JSON list` 추가 (예: `["single_quarter_outlier", "ttm_concentration"]`)
- 게이트 3-3: 태깅 있으면 `GateResult(allowed=False, reason='verification_required', detail=tags)` 반환
- 자동 매수 보류 · 사용자 확인 응답 (판정 API `/principles/verification/confirm/{ticker}`) 후 통과
- 스크리너 화면 (`/principles/screener` PASS 리스트) 에 태그 라벨 표시 (⚠ "실체 검증 필요")

**구현 지점**:
- `backend/principles/verification_tagger.py` (신규 · 태깅 규칙 · 예상 100 라인)
- `backend/services/models.py::PrinciplesResult.verification_tags` 컬럼 추가 (Alembic 마이그레이션)
- `backend/principles/scheduler.py::daily_recompute` · 태깅 로직 호출·저장 (예상 20 라인 추가)
- `backend/execution/signal_router.py::VerificationRequiredGate` (신규 · 예상 60 라인)
- `backend/api/routes/principles.py` · 확인 endpoint 2개 (verification/confirm · verification/pending list) (예상 60 라인)
- `frontend/app/principles/screener/page.tsx` · 태그 라벨 렌더링 (예상 40 라인 수정)
- 단위 테스트 (태깅 규칙 · 실측 SJG세종·두올 픽스처 · 예상 120 라인)

**예상 규모**: **총 ~400 라인** (백엔드 200 + 마이그레이션 20 + 프론트 40 + 테스트 120 + endpoint 60 근사)

## 총 구현 예산 (설계안)

| 항목 | 예상 라인 |
|---|---|
| 3-1 PrinciplesGate | ~280 |
| 3-2 섹터 분산 | ~240 |
| 3-3 실체 검증 태깅 | ~400 |
| **합계** | **~920 라인** |

**세션 분할 권고**:
- **세션 A**: 3-1 (fail-closed · 화이트리스트 · 관리 화면) · 예상 1일
- **세션 B**: 3-2 (섹터 분산 · sector resolver) · 예상 1일 (broker positions 연동 준비 필요)
- **세션 C**: 3-3 (실체 검증 태깅 · charter v1.0.9 등재 · 임계값 사용자 최종 결정) · 예상 1.5일

**우선순위 권고**: 3-1 → 3-3 → 3-2
- 3-1 은 charter 원안 · 가장 시급 (현재 게이트 없음 · 매수 로직이 PASS 무관하게 실행 가능)
- 3-3 은 SJG세종·두올 사례로 실 필요성 확진 · 이월 판정 부담 없이 태깅만 · 자동 매수 로직 확장 전 도입 이상적
- 3-2 는 자동 매수 활성 후 · 여러 포지션 누적 상황에서 발동 · 후순위 가능

## 리스크·미결 항목

- **PrinciplesRun 최신성 판단**: "26시간 이내" 임계값 사용자 검토 필요 (daily_recompute 는 매일 23:00 · 26h 이상 stale 은 배치 실패 신호)
- **화이트리스트 소스 확정**: 사용자 언급 `sniper` 외 추가 후보 (VIP · MemeWatch 등) 은 별도 검토
- **broker_positions 데이터 소스**: 자동 매수 broker 확정 후 3-2 구현 착수
- **verification_tags 표시 UX**: 스크리너 리스트에서 태그 라벨 위치·색상·클릭 시 상세 뷰 별도 디자인 필요
- **charter v1.0.9 임계값 (100%·50%)**: SJG세종·두올 2건 실증 근거 · 표본 확대 후 재검증 (반도체 초호황 종목 등 정상 급증도 태깅되지 않도록 조정 필요)

## 관련 문서

- [`backend/principles/charter.json`](../../../backend/principles/charter.json) v1.0.8
- [Session · 파서·verify 자기 채점 사고 회고](../../../../GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Sessions/2026-08-21-parser-verify-self-scoring-postmortem.md) (5차 결함 · TTM 110.60/PER 13.15 취소 · 실체 검증 필요성 근거)
