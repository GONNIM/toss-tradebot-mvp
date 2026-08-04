# Serenity Hunter · 급등 잠재 발굴 페이지 (Phase L14 · 재설계본)

**작성일**: 2026-08-03 · 재설계 2026-08-03
**작성자**: Claude Opus 4.7 · 사용자 승인 후 저장
**상태**: 기획 재설계 완료 · Fable 5 2차 리뷰 대기
**참조 리뷰**:
- 1차 · `docs/reviews/serenity-tracker-2026-08-03.md` (Claude Agent · 기존 페이지)
- 2차 · Fable 5 · 원안 (v1) 반박 (2026-08-03 · 순서 재설계 지시)

---

## 0. 재설계 이유 (Fable 5 반박 반영)

**원안 v1 폐기 사유**:
- **순서 역전**: UI 파라미터 (7d · spike 2× · confidence 0.7) 를 데이터 검증 이전에 확정 → 백테스트 결과 나오면 재작업 확실
- **SIVE 1건 = 생존 편향**: 히트율 미검증 상태로 "모든 첫 언급 노출" = 실패 N건도 함께 노출 · 시드 100만원 손실 유발 가능
- **인플루언서 1인 소스 알파 미증명**: Serenity 팔로워 900K+ · 사용자 정보 우위 0 · 알파 존재 여부가 페이지 이전에 확인할 유일한 질문
- **섹션 중복**: 신규 첫 언급 = spike (mentions_28d 분모가 신규 종목에서 0 근방 → spike 자동 통과)
- **YAGNI 필터**: 1인 사용자에 다중선택 슬라이더 · confidence 하한 · thesis/evidence 다중 = 개발 시간만 먹고 방치
- **신호 품질 DoD 부재**: 원안 DoD = "typecheck 통과 · pytest 커버" · 코드가 도는 것과 신호가 돈이 되는 것은 무관

**재설계 원칙**:
1. UI 를 만들기 전에 **알파 존재 여부 자체를 데이터로 답하는 페이지** 를 먼저 만든다
2. 검증 결과가 무의미하면 그 사실이 프로젝트 최고 산출물 (100만원 지킴)
3. 필터·슬라이더·다중선택 등 파라미터 UI 는 **검증이 파라미터를 정한 뒤** L15+ 로 이관
4. 신규+spike 는 **단일 리스트에 배지로 병합** · 중복 노출 제거
5. 헬스는 배너가 아닌 **경고 시만 1줄** · 정상 시 UI 표시 없음

---

## 1. 페이지 정보

- **경로**: `/influencer/serenity-hunter`
- **제목**: 🎯 Serenity Hunter · 알파 검증 + 발굴
- **타깃 사용자 워크플로우**:
  1. 아침 개장 전 접속
  2. 최상단 · 검증 테이블 요약 (오늘도 유효한가?)
  3. 통합 발굴 리스트 훑기 (`⚠ 인플루언서 경고 신규` 배지 있으면 회피)
  4. 관심 티커 클릭 → 상세 (기존 페이지 활용)

**기존 `/influencer/serenity` 무영향** · 두 페이지 병존.

---

## 2. 페이지 섹션 구성 (상단 → 하단)

### 2.1 🚨 헬스 경고 1줄 (조건부)
- **표시 조건**: 크론 24h+ 미실행 OR signals 24h+ 신규 없음 OR 알려진 z.ai 잔액 소진
- **정상 시**: 아예 렌더링 안 함 (별도 컴포넌트 없이 조건부)
- **표시 형태**: 얇은 상단 배너 (경고 1줄 · 자세히 링크는 상세 API 로 이동)
- API: `GET /api/v1/serenity/health` (경고 boolean + 상세)

### 2.2 🔬 검증 테이블 (최상단 · 이 페이지의 존재 이유)
**목적**: 과거 signals 4,194건 전수 first_mention 이벤트 사후 성과 = "이 페이지가 만약 지난 90일 존재했다면 뭘 보여줬고 그걸 샀으면 어떻게 됐나"

**계산 대상**:
- 각 티커의 first_mention 이벤트 (signal 최초 발생 시점) 만 추출
- signal 시점 종가 · 익일 시가 · +1d/+3d/+5d/+10d/+30d 종가 → forward return
- gap_next_open_pct = (익일 시가 - signal 시점 종가) / signal 시점 종가 × 100

**표시 (요약 상단 + 분해 표)**:
1. **요약 카드 (Hero)**:
   - 전체 first_mention 이벤트 N건 · 성공적으로 backtest 계산된 M건
   - 히트율 (+5d 기준 ≥ +5% 상승) · 예 `27% (68/253 · 사후 5거래일)`
   - 평균 forward return · +1d/+3d/+5d/+10d/+30d 각각
   - 평균 gap up % (익일 시가 vs signal 종가)
   - **결과가 무의미 (예 히트율 20% 미만)** → 이 카드에 빨간 경고 텍스트

2. **Bucket 분해 표** (3개 이상):
   - By sentiment · bullish / bearish / neutral / calibration
   - By seed 유무 · seed 있음 (검증된 tier) vs 없음 (신규 발굴)
   - By 시총 · 마이크로 (<1B) / 스몰 (1B~10B) / 미드 이상
   - 각 bucket 별 · 이벤트 수 · 히트율 · 평균 return · gap up

**Backend API**: `GET /api/v1/serenity/verification`

### 2.3 📋 통합 발굴 리스트 (Hunter Table · 신규+spike 병합)

**목적**: 오늘 나의 매수 후보 shortlist

**포함 조건**:
- signals 최근 90일 언급된 티커 union
- 정렬: default 는 `mentions_today desc` · 컬럼 헤더 클릭 정렬 지원

**컬럼**:
| 컬럼 | 값 | 특이사항 |
|---|---|---|
| Ticker | 티커 · 상세 링크 | `⚠ 인플루언서 경고 신규` 배지 (auto_avoid + first_mention ≤ 7d) · `NEW` 배지 (first_mention ≤ 7d) |
| Industry | yfinance industry | 기존 로직 유지 |
| First mention | KST 초까지 | 정렬 |
| Latest | KST 초까지 | 정렬 |
| Mentions | today (7d/28d/90d) | 정렬 (기간 select · 상단 컨트롤) |
| Confidence | 최근 signal confidence 평균 · 소수 2자리 | **표시만** · 필터 아님 |
| Thesis | 최근 signal thesis_type 배지 (reaffirmation/new_conviction 등) | 표시만 |
| Bull% | 90d bullish 비율 | 정렬 |
| Market Cap | yfinance marketCap · 조/억 단위 | 신규 · 시총 노출 (Fable 5 놓친 요소) · 정렬 |
| vs Prior | 어제 종가 대비 오늘 | 정렬 |
| Gain | 최초 언급일 대비 | 정렬 |
| Stance | ▲/▼/◆/● | · |

**필터 UI 없음** (Fable 5 YAGNI 지적 반영) · 정렬·검색만.

**Backend API**: `GET /api/v1/serenity/hunter`

---

## 3. 백엔드 확장

### 3.1 Schema · SerenityBacktest 확장
```python
# 기존
return_5d · return_10d · return_30d · return_60d · return_180d
# 신규 (Alembic)
return_1d · return_3d
gap_next_open_pct  # (익일 시가 - signal 종가) / signal 종가 × 100
```

### 3.2 refresh_backtests 개선 (`backend/discovery/serenity/backtest.py`)
- `RETURN_WINDOWS = (1, 3, 5, 10, 30, 60, 180)` 확장
- gap_next_open_pct 계산 · yfinance `Open` 컬럼 활용
- 배치 크기 · 200 → 500 상향
- 스케줄 · 주 1회 → **매일 01:00 KST** (Fable 5 · 4194 signals × 200/주 = 21주 소요 지적)

### 3.3 SerenityTickerPrice 확장 · marketCap
- 컬럼 `market_cap: Optional[float]` (Alembic)
- price_snapshot 배치 시 `info.get("marketCap")` 병합

### 3.4 신규 API
- `GET /api/v1/serenity/verification`
  - 요약 · 전체 first_mention 이벤트 · 히트율 · 평균 return · gap up
  - buckets · sentiment · seed 유무 · 시총
- `GET /api/v1/serenity/hunter`
  - 통합 발굴 리스트 (컬럼 위 표 참조)
  - `is_new` (first_mention ≤ 7d) · `is_avoid_new` (auto_avoid + is_new) 필드
  - avg_confidence · latest_thesis · market_cap 포함
- `GET /api/v1/serenity/health`
  - 경고 조건 boolean + 상세

---

## 4. 프론트 UI 컴포넌트 트리

```
frontend/app/influencer/serenity-hunter/page.tsx
├── HealthWarningLine           (신규 · 조건부 렌더)
├── VerificationHero            (신규 · 요약 카드)
├── VerificationBucketTable     (신규 · sentiment/seed/시총 breakdown)
└── HunterTable                 (신규 · 통합 발굴 리스트 · TickerTable 확장)
```

**컴포넌트 재사용**: 기존 `TickerTable` 은 크게 리팩터하지 않고 `HunterTable` 을 별도 신설 · confidence/thesis/marketCap/배지 로직 포함.

---

## 5. 완료 기준 (DoD)

### 5.1 신호 품질 DoD (필수 · Fable 5 신설 지적)
- [ ] 검증 테이블 · signals 4,194 전수 first_mention 이벤트 커버 · missing 티커 사유 리포트 (yfinance 실패 등)
- [ ] return_1d/3d · 갭 계산 정확도 검증 (yfinance 휴일·상장폐지 · 상장전 처리)
- [ ] 히트율 최소 3개 buckets · 각각 명시
- [ ] 히트율 저조 시 (전체 +5d ≥ +5% 20% 미만) 페이지 상단 경고 표시
- [ ] 실제 100만원 매매 시나리오 · 초저시총 슬리피지 경고 (시총 컬럼 노출)

### 5.2 기술 DoD
- [ ] 백엔드 API 3개 (`/health`, `/verification`, `/hunter`) · pytest 커버
- [ ] Alembic migration (return_1d/3d/gap · market_cap)
- [ ] refresh_backtests 확장 계산 · 로컬 dry-run 검증
- [ ] 프론트 페이지 typecheck 통과
- [ ] 기존 `/influencer/serenity` 페이지 무영향
- [ ] 배포 성공 · 사용자 브라우저 확증

---

## 6. 스코프 밖 (Phase L15+ 이관 · 순서 재설계 결과)

- **확정 이관 (L15)** · confidence 슬라이더 · thesis/evidence 다중선택 · auto_avoid 토글 · 별도 Spike 섹션 → 검증 결과가 파라미터를 정한 후 필요 시 도입
- **확정 이관 (L15+)** · Telegram 알림 (신규 첫 언급 · spike 감지) · 개인 watchlist · 실시간 갱신 (SSE/WebSocket) · z.ai 프롬프트 개선

---

## 7. 열린 질문 · 리스크

- **인플루언서 알파 부재 시나리오**: 검증 테이블 히트율이 매우 저조하면 이 페이지 자체가 폐기 후보. 그 경우 결과 자체가 100만원 지킴 (Fable 5 명시). 사용자 판단 필요.
- **yfinance marketCap 필드 신뢰성**: 소형주·해외주 (SEK/TW/JP) 에서 결측 다수 예상. 대안: `sharesOutstanding × close` 계산.
- **첫 언급 정의**: SerenitySignal.extracted_at (z.ai 추출일) vs SerenityTweet.posted_at (트윗 발행일). 이미 rolling window 는 posted_at 기준으로 통일 · 검증 테이블도 posted_at 기준 사용.
- **갭업 정의**: 익일 시가 vs signal 시점 종가 · 언급이 장 마감 후면 익일 시가 gap 이 실제 매수 가능 지점. 언급이 장중이면 gap 개념 애매 · 최소 다음 거래일 시가 사용.
- **배치 매일 실행 부하**: refresh_backtests 매일 500건 · yfinance rate limit 위험 상승. 처음 몇 회 관찰 후 재조정.

---

## 8. 작업 순서 (구현 시)

1. Alembic · SerenityBacktest return_1d/3d/gap · SerenityTickerPrice market_cap
2. backtest.py · RETURN_WINDOWS 확장 · gap 계산 · 스케줄 매일
3. price_snapshot.py · market_cap 병합
4. API · /health · /verification · /hunter
5. pytest 커버
6. 프론트 · HealthWarningLine · VerificationHero · VerificationBucketTable · HunterTable
7. 단일 배포
8. 서버 backtest 매일 첫 실행 관찰 (rate limit)
9. 사용자 브라우저 확증 · 히트율 정직 노출
