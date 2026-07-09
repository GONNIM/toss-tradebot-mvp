# 02. 데이터 소스 설계

**목표**: 무료 공식 소스만으로 Phase A~C 커버. SEC EDGAR + DART 통합.

## 1. 미국 — SEC EDGAR

### 1.1 사용 엔드포인트

| 엔드포인트 | 용도 | 실측 상태 |
|-----------|------|-----------|
| `data.sec.gov/submissions/CIK{cik}.json` | Activist 별 recent 필링 | ✅ VIP watch 에서 이미 검증 · UA 정책 준수 |
| `efts.sec.gov/LATEST/search-index?q=X&forms=SC+13D%2FA` | Full-text 검색 · CIK 확보 | ✅ Trian CIK 확보에 사용 |
| `data.sec.gov/api/xbrl/frames/us-gaap/...` | Form 13F XBRL · 분기 지연 | Phase E+ (이번 스코프 X) |

### 1.2 폴링 설계

- **주기**: 5분 (SEC 초당 10 요청 정책 · 45 CIK × 12회/시간 = 540 요청/시간 = 0.15 req/sec · 여유)
- **UA**: `Suauncle-Research suauncle-contact@gmail.com` ([[reference_sops_age_workflow]] 등록 값 재활용)
- **엔드포인트별 판정**: `filings.recent.form[i]` 에서 새 accession 감지 → 이벤트 생성
- **관심 폼**: `SC 13D`, `SC 13D/A`, `SC 13G`, `SC 13G/A`, `SCHEDULE 13D`, `SCHEDULE 13D/A`

### 1.3 대상 회사 판정 (오검출 방지)

- `primaryDocDescription` 에 회사명 매치 → 신뢰도 상
- desc 비어있으면 filing 상세 페이지 (`archives.sec.gov/Archives/edgar/data/{cik}/{accession}/...`) 재조회 · subject company CIK 추출 필요 (Phase A+β 개선)
- **최소 필터**: `filings.recent.filingDate` 가 최근 30일 이내

### 1.4 신규 필링 dedup

- `data/activist_state.json` — filer CIK 별 last_seen_accession 배열 (최근 10개)
- 신규 accession 만 이벤트 생성 · 24h cooldown 없음 (SEC 필링은 재발생 자체가 사건)

---

## 2. 한국 — DART Open API

### 2.1 사용 엔드포인트

| 엔드포인트 | 용도 | 실측 상태 |
|-----------|------|-----------|
| `opendart.fss.or.kr/api/list.json?pblntf_ty=F&bgn_de=&end_de=` | 대량보유 공시 목록 (최근) | ✅ DART_API_KEY 등록됨 · 별건에서 활용 중 |
| `opendart.fss.or.kr/api/document.json?rcept_no=` | 공시 상세 · 목적·지분율 파싱 | 신규 · 실측 필요 |
| `opendart.fss.or.kr/api/company.json?corp_code=` | 회사 · filer 코드 조회 | 신규 |
| `opendart.fss.or.kr/api/majorstock.json?corp_code=` | 대량보유·변동 API | 실측 필요 (선택) |

### 2.2 폴링 설계

- **주기**: 5분 (DART 는 초당 20 요청 정책 · 여유)
- **API key**: 환경변수 `DART_API_KEY` (SOPS 파일 관리)
- **pblntf_ty**: `F` (대량보유상황보고서) · 최근 5일 (신규만 감지)
- **활동주주 매칭**: 응답의 `flr_nm` (제출인) 필드 · Universe([[01-universe]]) 리스트 매칭 (`유사도 검사 · 정규화` — 로마자·한글·법인 접미어 정리)

### 2.3 목적 필터 (필수)

DART `document.json` 응답에서 `보유목적` 필드 추출:

- `경영권에 영향을 주기 위한 것` ⭐⭐⭐⭐⭐ 최상 신호
- `경영권에 영향을 주기 위한 것 · 임원의 선임/해임 목적` ⭐⭐⭐⭐⭐
- `단순투자` ⭐ 노이즈 · 필터 제외
- 기재 목적 없음 · 파싱 실패 → 사용자 확인용 UI 표시 (자동 알림 X)

### 2.4 dedup · 오검출 방지

- `data/activist_state.json` 한국 섹션 · `rcept_no` (접수번호) 유일 키
- filer 이름 정규화 사전 (예: "얼라인 파트너스" ≈ "얼라인파트너스" ≈ "Align Partners") · Phase B 첫 스텝에서 20개 정도 확정
- 특수관계인 다수 등장 시 대표 filer 만

---

## 3. 재활용 지점 (기존 시스템 통합)

| 기존 파일 | 재활용 방식 |
|-----------|-------------|
| `backend/discovery/vip/activist_tracker.py` | 함수 `fetch_recent(cik, ua)` 그대로 사용 · 반복 호출로 multi-CIK 지원 |
| `backend/discovery/vip/config.py` | `SEC_EDGAR_UA` 값 공유 |
| `backend/services/notifier.py` | Telegram 알림 인프라 재활용 · `[ACTIVIST-US · <fund> · <ticker>]` 태그 |
| `backend/scheduler/cron.py` | `IntervalTrigger(seconds=300)` 로 activist job 추가 (기존 8개 job + 신규) |
| `backend/services/dart.py` 또는 유사 | 이미 있으면 확장 · 없으면 신규 (`services/dart_client.py`) |
| `.env.sops.yaml` | 추가 env 없음 (DART_API_KEY 재활용) |

---

## 4. 폴링 주기 결정 근거

| 주기 | 서비스 부담 | 감지 지연 | 채택 |
|------|-------------|-----------|------|
| 1분 | 높음 (SEC 정책 여유 O · 오히려 노이즈 알림) | < 1분 | X |
| **5분** | 낮음 · 정책 여유 충분 | < 5분 · 대량보유공시 지연(수분) 감안 여유 | ✅ |
| 15분 | 낮음 | < 15분 · SC 13D 는 신속 대응 어려움 | X |

---

## 5. 신호 파이프라인 흐름

```
[스케줄러 5분 tick]
      ↓
[미국 트랙]                             [한국 트랙]
CIK 45개 loop                          DART list.json 최근 5일
  → data.sec.gov 폴링                    → filer 이름 매칭 (Universe)
  → last_seen_accession 비교              → rcept_no dedup
  → 신규 필링 감지                        → document.json 상세 파싱
  → 관심 폼 필터                         → 보유목적 필터 (경영참여만)
  → 강도 스코어링 (Phase C)               → 강도 스코어링 (Phase C)
      ↓                                    ↓
[통합 이벤트]
  → Wolf Pack 판정 (30일 window)
  → Telegram 발송
  → state 저장
  → UI /vip 임시 통합 카드 (Phase F 에서 전용 페이지)
```

---

## 6. 알려진 한계 · 후속 개선

- **primaryDocDescription 비어있는 SEC 필링** — VIP watch 에서 이미 확인. Phase A+β 에서 archives 상세 크롤링 or 별도 subject-company 추출 로직 (SEC 필링 header parser)
- **DART 응답 지연** — 실제 공시 후 API 반영까지 수분 소요. 5분 폴링 이면 최악 10분 감지 지연
- **filer 이름 매칭 노이즈** — 특수관계인 · 유사 이름 다른 fund · 로마자/한글 표기 차이. Phase B 첫 스텝에서 정규화 사전 20개 확정
- **한국 특수관계인 여러 명 등장** — 대표 filer 만 노출 · Phase C 이후 특수관계인 관계도 UI 시각화 (선택)
