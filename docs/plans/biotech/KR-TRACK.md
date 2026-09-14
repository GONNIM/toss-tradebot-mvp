# KR-TRACK · Biotech Catalyst Radar 국내 트랙 설계 (Phase C 준비 초안)

**작성일**: 2026-09-02 (B46)
**상태**: 초안 · 재사용 원칙 확립 (Fable B43·B44 정정 반영)
**전제**:
- US 검증(H1~H4) 이후 KR 시장 이식은 별도 백테스트(Phase C) 통과 전까지 금지 (README §8 B8)
- 신규 클라이언트/스크래퍼 작성 금지 · 기존 파이프 확장 원칙 (Fable B43)

---

## 1. DART 수집 · 기존 principles 파이프 확장 (신규 클라이언트 금지)

**재사용 대상**:
- `backend/discovery/data_sources/dart/client.py` — `fetch_financial_statement` · `_api_key()` · corp_code 캐시 · 8개 API 엔드포인트(재무·주주·감사·자기주식·회사개요 등) 이미 구현
- `backend/principles/financials.py` — TTM 누적 분해·재무 파싱 헬퍼
- `backend/principles/scheduler.py` — weekly_detect(일 21:00) · daily_recompute(23:00) APScheduler 등록

**KR 바이오 이식 시 확장 방식**:
- 바이오 임상 공시(주요사항보고서·조회공시) 수집은 `client.py` 에 함수 추가 · 별도 클라이언트 파일 신설 금지
- corp_code 매핑은 기존 캐시 재활용 (`backend/data/corp_code.xml` 유사 · principles 도 동일 소스)

**게이트**:
- DART API 호출 로그 마스킹 = `setup_secure_logging` 이미 커버 (2026-08-22 산출물) · 신규 함수도 config import 시 자동 적용
- KR 바이오 스크리너 신설 시 principles/screener.py **패턴만 참고 · principles 코드 수정·결합 금지 · biotech 모듈 독립 구현** (B47 · 2026-09-02 · 독립 운영 원칙)

---

## 2. DART 호출 예산 · 키 단위 합산

**DART 무료 API 한도** (opendart.fss.or.kr 정책):
- 기본 한도 = 20,000 calls/day (키 단위 합산 · 프로젝트 사용 키 = `backend/.env:DART_API_KEY`)

**현재 사용량** (2026-09-02 기준 · 코드 관측):
- `backend/principles/scheduler.py`:
  - `weekly_detect` (매주 일 21:00) = KOSPI ~950 종목 × 회사개요+재무 API ≈ 2건/종목 → **~1,900 calls/wk**
  - `daily_recompute` (매일 23:00) = 캐시 활용 · 재계산 위주 · 실 호출 소수 (~100 calls/day 추정 · 실측 필요)
- `backend/discovery/serenity/*` — DART 사용 없음 (Twitter/tweet 기반)
- `backend/discovery/meme_watch/catalyst_signal.py` — grep 매치 있음 · 실 호출 여부 사용량 카운터 부재로 미확인 (별건 확인 필요)

**KR 바이오 이식 후 예산 (예상)**:
- KOSDAQ 바이오 ~450 종목 × 공시 3~5건/종목 = **1,350~2,250 calls/wk 추가**
- 총 예산 =  기존 principles + 신규 = **~3,300~4,150 calls/wk < 20,000/day** · 여유 있음
- 다만 **실 사용량 카운터가 코드에 없음** (grep confirmed) · KR 이식 전 카운터 도입 필요 (별건 티켓)

**주의**:
- 유료 플랜(API 확장 신청) 필요성 없음 · 무료 한도 안에서 충분
- 실 사용량 카운터 부재 = 폭주 감지 불가 · 초기 이식 시 수동 모니터링 필수

---

## 3. KR 가격 파이프 · 기존 KRX candle 커버 범위 확인

**재사용 대상**:
- `backend/discovery/data_sources/krx_price/loader.py`
  - `fetch_all_meta()` = FinanceDataReader `StockListing('KRX')` · KRX 전 종목 메타
  - `fetch_daily_candles()` = pykrx `stock.get_market_ohlcv` 24M 일봉
  - `ingest_24m_candles()` = 매핑 51종목 × 24M → `KrxDailyCandle` 테이블 적재
- `backend/powderkeg/collectors/krx_market.py` · `krx_delisted.py` · `krx_admin_issue.py` — 시장·폐지·관리종목 별도 파이프 이미 존재

**KR 바이오 이식 시 커버 범위 확인**:
- 활성 KOSDAQ 바이오 커버: **가능** (pykrx `get_market_ohlcv` KOSPI/KOSDAQ 지원)
- 폐지 KOSDAQ 바이오 커버: **미확인** (pykrx 폐지 종목 이력 보유 여부 실측 필요) → US 트랙 B15-2 와 동일 방법으로 20 표본 실측 필요
- 상장전(비상장) 바이오: **부재** (기술특례 상장 대상 임상 이벤트는 IPO 이전 신호 · 별도 소스 필요)

**부족분 대응 후보** (실측 미달 시만 등록):
- 공공데이터포털 KRX 개방 API (금융투자협회 · 상장·폐지 이력 · 무료)
- FinanceDataReader 폐지 종목 부분 지원 확인 필요

---

## 4. SOURCES.md 신설 · DART 행 = "기존 보유 · 발급 불필요"

**신설 경로**: `docs/plans/biotech/SOURCES.md` (별도 파일)

**주요 행 (v0 초안)**:

| 소스 | 상태 | 근거 |
|---|---|---|
| DART (opendart.fss.or.kr) | **기존 보유 · 발급 불필요** | `backend/.env:DART_API_KEY` 존재 · 2026-08 principles 배치 상시 사용 |
| KRX candle (pykrx) | **기존 보유 · 무인증** | `backend/discovery/data_sources/krx_price/loader.py` 상시 사용 |
| 공공데이터포털 KRX 폐지 API | 미확인 | KR 폐지 표본 실측 미달 시만 발급 검토 (Phase C 진입 조건) |
| EODHD (개인 무료) | 발급 완료 (2026-09-02) | 20 calls/day · Phase A US 트랙 완주 후 재검토 |
| FMP (개인 무료) | 발급 완료 (2026-09-02) | 250 calls/day · Phase A US 트랙 03 소스 병렬 검증 |

---

## 5. 다음 액션 (별건 티켓)

- DART 사용량 카운터 코드 도입 (`backend/discovery/data_sources/dart/client.py` 에 `_daily_calls` counter 추가 · principles/meme_watch 배치 커버)
- pykrx 폐지 KOSDAQ 바이오 커버율 실측 (B15-2 US 표본과 동일 방법 · KR 표본 20 준비)
- `SOURCES.md` v1 별도 저장 후 이 문서에서 참조
