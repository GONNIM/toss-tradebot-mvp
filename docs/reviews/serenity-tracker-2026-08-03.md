# Serenity Stock Tracker · 시니어 전문가 리뷰 (2026-08-03)

> 대상: `frontend/app/influencer/serenity/**` + `backend/discovery/serenity/**` + `backend/api/routes/serenity.py`
> 리뷰어 관점: 시니어 프로덕트 & 퀀트 리서치
> 목적: "SIVE 같은 급등 잠재 종목 사전 발굴" 이라는 사용자 실 투자 목표 부합성 검증
> 기준일: 2026-08-03 · signals 4,194 · tweets 6,223 · tickers 251 · seed 7 · backtests 0 · z.ai 잔액 소진

---

## TL;DR

1. **현 페이지는 "SIVE 를 사전에 발견"할 수 있는 UX 가 아니다.** Top Picks 는 seed 7개에서만 나오고, 급등 조기 신호를 잡을 첫 도구인 "신규 첫 언급" 알림·필터가 없다. `frontend/app/influencer/serenity/page.tsx:38-43` 의 Top Picks 조건은 이미 시장이 다 아는 종목만 걸러낸다.
2. **데이터 파이프라인은 견고하나 검증축(backtest)이 0건.** `backend/discovery/serenity/scheduler.py:114-125` 는 주 1회 (월 00:00 KST) 만 실행되므로 최소 다음 주 월요일까지 판정 근거가 없다. 이 상태에서 사용자에게 "Top Picks" 라벨을 붙이는 것은 위험.
3. **15원칙 자동 판정 15개 중 실제 채워지는 것은 4개 (#1·#8·#13·#14 부분).** 나머지 11개는 seed 없으면 전부 skip → `ChecklistCard` 는 사실상 seed 등록 여부 뷰어. 사용자는 "9 pass" 를 보고 conviction 있다고 오독하기 쉬움.
4. **Momentum 정의가 조기 발굴에 부적합.** `mentions_7d/(mentions_90d/90*7) >= 2` 는 이미 90일간 5회 이상 언급된 종목만 대상 (page.tsx:49) — 첫 언급 급등 시나리오(SIVE 원형)는 원천 제외된다.
5. **z.ai 잔액 소진 상태에서 UI 는 아무 경고도 하지 않는다.** 사용자는 오늘 새 signal 이 없다는 사실 자체를 알 수 없음 (summary 카드의 `last_signal_at` 만 살펴야 감지 가능). 이는 "발굴 놓침" 을 유발하는 조용한 실패.

**한 줄 결론**: 인프라 8/10, UX 5/10, 사전 발굴 적합성 3/10. Phase L14 는 "새 티커 첫 언급 알림 + confidence·mentions_today 기반 Momentum 재정의 + z.ai 상태 배너" 를 P0 로 처리해야 한다.

---

## 1. 목적 적합성 검증

### 1.1 SIVE 같은 종목을 "미리" 발견 가능한가 · 답: 부분적으로만 가능

SIVE 원형 시나리오는 "Serenity 가 이차전지/optical CPO 소형주 를 초기에 언급 → 사용자가 그 첫 언급 시점에 인지 → 급등 전 매수" 이다. 현재 페이지에서 이 여정을 밟으려면:

| 발견 경로 | 현 상태 | 실 사용자 손해 |
|---|---|---|
| Top Picks 에서 발견 | ❌ seed 7 개 외 표시 불가 · `page.tsx:88-91`이 `isTopPick` 필터에 `serenity_tier in {S, A}` 강제 · seed 없으면 tier null → 자동 배제 | 신규 종목은 반드시 놓친다 |
| Momentum 에서 발견 | ⚠️ `mention_count_90d >= 5` 필터 (`page.tsx:49`) · 첫 언급~4회 언급 사이 종목은 완전 배제 | SIVE 원형(초기 급등) 완전 배제 |
| 90일 테이블에서 발견 | ⚠️ 기본 정렬 `mentions_90d desc` (`TickerTable.tsx:73`) · 251 종목 중 상위에 나오려면 이미 다수 언급된 상태여야 함 | 첫 언급 1~3회 티커는 251번째 근처에 파묻힘 |
| Signal Feed 에서 발견 | ⚠️ 접힘 default (`page.tsx:64`) · 사용자가 능동적으로 펼쳐야 표시 · 기간 최대 90일 · 티커별 필터 UI 없음 | 하단으로 밀려 접근성 떨어짐 |

**결론**: 4개 발견 경로 모두 "이미 여러 번 언급된 종목" 을 전제로 설계됨 → **SIVE 처럼 첫 언급~수일 내 급등** 시나리오는 원천 배제. 이것이 프로젝트 정체성 "급등주 사전 예측 봇" 과 정면 충돌.

### 1.2 랜딩 배치 (Top Picks · Momentum · 테이블 · 카드 · Avoid · Feed) 의 부합성

배치 자체는 "결정 지원 시스템" 관점에서 합리적 (Ben Shneiderman 의 Overview → Zoom → Filter → Details on demand 원칙 준수).

문제는 각 섹션의 **큐레이션 로직** 이 사전 발굴이 아니라 **사후 확인** 에 맞춰져 있다는 것.

- Top Picks (`page.tsx:167-187`): "이미 확신 있는 종목 재확인" 용 — 정답이지만 seed 7 개 한계
- Momentum (`page.tsx:190-209`): "이미 반복 언급된 종목 중 최근 가속" 용 — 조기 발굴엔 부적합
- 테이블 (`TickerTable.tsx`): 정보 밀도 높음 (12 컬럼), 정렬·검색 강력. **가장 실용적인 도구인데 페이지 중반 위치**.
- 카드 그리드 (`page.tsx:216-268`): tier 별 분류 UX 훌륭하나 seed 없는 티커는 "미분류" 로 뭉쳐서 표시 → 사실상 노이즈
- Avoid (`page.tsx:271-296`): 접힘 default 적절
- Signal Feed (`page.tsx:298-357`): 접힘 default 적절 · 하지만 티커별 필터 UI 부재

**개선 제안**: 최상단에 "🆕 새 첫 언급 (지난 3일 first_mention_at)" 섹션을 추가해야 정체성과 부합.

### 1.3 여정에서 빠진/방해되는 요소

**빠진 요소**:
- 신규 티커 첫 언급 알림 (조기 발견 핵심)
- z.ai extractor 상태 배너 (오늘 몇 트윗 처리됐는지)
- 관심 종목 저장 (watchlist bridge)
- confidence 임계 필터 (현재 confidence 0.2 signal 도 mentions 로 카운트됨 · aggregators.py:100)
- 트윗 원문 감정 극성 · thesis_type 필터 (Signal Feed 에는 sentiment 만)
- 시장구분 (KRX/US/TW/JP) 필터 · 사용자는 한국 시드로 100만원 운용 · 실 매수 가능 시장 판단 필수

**방해되는 요소**:
- 카드 그리드의 "미분류 · 언급 순" 섹션 (page.tsx:254-264): 저 confidence 노이즈 티커 대량 포함
- Top Picks 조건 `bullish_pct_90d >= 60` (`page.tsx:42`): 새로 언급된 종목이 bullish 100% 여도 mentions 표본 부족으로 통계적 의미 낮음. 반대로 이미 60% 넘긴 성숙 종목만 노출.
- Signal Feed 의 `sentiment=""` default: 4194 signal 중 상당수는 neutral/calibration · 이를 포함해 표시하면 판단 방해.

### 1.4 15원칙 skip 항목의 발굴 정확도 손해

`ChecklistCard.tsx:15-116` 을 정독한 결과, 15개 중:

| # | 원칙 | 자동 판정 | 판정 로직 | 손해 |
|---|---|---|---|---|
| 1 | Bottleneck hunting | 부분 | serenity_tier ∈ {S,A} → pass | seed 없으면 skip · 신규 발굴 불가 |
| 2 | Multi-hop BOM | 부분 | domain_tags 존재 → pass | 태그 부여도 수동 seed |
| 3 | Contract ARR | ❌ skip 강제 | - | 크리티컬 (Serenity 원본 3원칙) |
| 4 | Mag7 노출 | ❌ skip 강제 | - | 크리티컬 |
| 5 | GAAP margin > 60 | ❌ skip 강제 | - | 필요 (SIVE 판정 핵심) |
| 6 | Pre-ramp qualification | ❌ skip 강제 | - | **가장 아쉬움** · 급등 조기 신호 |
| 7 | Dilution / ATM | 부분 | anti_pattern_flags 텍스트 매치 | seed 없으면 pass 로 오판 |
| 8 | Financing tier | 부분 | seed 값 그대로 | 자동 판정 아님 |
| 9 | Short squeeze | ❌ skip 강제 | - | 필요 |
| 10 | Tariff-Buy | ❌ skip 강제 | - | 매크로 이벤트 감지 필요 |
| 11 | Institutional lag | ❌ skip 강제 | - | 필요 |
| 12 | Vega/IV | ❌ skip 강제 | - | 낮은 우선순위 (options) |
| 13 | Serenity Conviction | 부분 | seed tier | 자동 판정 아님 |
| 14 | Anti-patterns | 부분 | flags 개수 | seed 없으면 자동 pass |
| 15 | 14점 체크리스트 | ❌ skip 강제 | - | 종합 판정 |

**결정적 손해**: 원칙 3 (Contract ARR), 4 (Mag7), 6 (Pre-ramp), 11 (Institutional lag) 이 자동 판정 불가 → 이 4개가 Serenity 원본에서 "확신 상승 시그널" 로 작동하는 축인데 UI 는 전부 회색(skip). 사용자는 육안으로 트윗 원문을 뒤져야 판단 가능 → 자동화 이점 소실.

**단, 재판정 자체가 어려운 것은 인정**. Contract ARR·Mag7 은 최소 quarterly earnings 파싱 · Mag7 은 customer list 데이터 소스가 필요. **차선책**: z.ai extractor 가 signal 추출 시 `thesis_type=new_bottleneck && evidence_type=contract` 조합을 뽑아내면 원칙 3 근사 가능 → 현재 프롬프트 (`system.md:63-65`) 는 이 필드를 이미 요구하고 있으나 UI 에서 활용하지 않음.

---

## 2. 데이터 계층 검증

### 2.1 Rolling window · first_mention · gain 계산의 조기 발굴 적합성

- **posted_at 기준 window** (`aggregators.py:82-91`): 옳은 결정. extracted_at 은 배치 처리 시각 · 시계열 왜곡. 이는 잘 설계됨.
- **first_mention_at = min(posted_at)** (`aggregators.py:93-97`): 개념적으로 맞음. 다만 seed submodule 로부터 매일 auto-pull → 과거에 이미 언급됐던 트윗이 뒤늦게 archive 에 들어오면 `first_mention_at` 이 앞으로 이동함. 실 사용자 관점에선 "언제부터 봤어야 했는지" 지표라 문제 없지만, **"내가 언제 알았어야 하는가"** 관점에선 archive 유입 시각 (`ingested_at`) 이 더 맞다. 이건 UX 결정.
- **gain_since_first_mention_pct** (`price_snapshot.py:106-115`): first_mention_date 이상 첫 거래일 종가 사용. **문제**: 트윗이 장중 실시간 언급이면 그날 종가는 이미 급등 후일 수 있음. Serenity 는 종종 pre-market 언급 · 개장 후 갭업 → gain 은 이미 반영된 상태 표시. 실 진입 가능 가격은 다음날 시가여야 함. **손해**: gain 이 실제 사용자가 잡을 수 있었던 수익보다 과대 표시됨.

### 2.2 confidence · thesis_type · evidence_type 의 UI 반영

| 필드 | 백엔드 수집 | UI 반영 |
|---|---|---|
| confidence | float 0~1 (`extractor.py:83-86`) | SignalFeedCard 만 표시 (`SignalFeedCard.tsx:44`) · 카드/테이블 미반영 |
| thesis_type | 4 값 (`models.py:1471`) | SignalFeedCard 태그 · 카드에는 `thesis_types` list 로 저장되나 미표시 |
| evidence_type | 9 값 (`models.py:1472-1475`) | SignalFeedCard 태그만 · 집계·필터 없음 |

**손해**: 사용자가 "지난 7일 evidence_type=contract 인 새 종목" 같은 결정적 필터를 걸 수 없음. 이건 Serenity 정체성 (계약 evidence = high conviction) 을 정면으로 무시.

**확실한 문제**: aggregate 통계 (mentions_today 등) 가 **confidence 무관 전량 카운트** (`aggregators.py:100-105`). z.ai 가 confidence 0.15 로 뽑은 애매한 signal 도 mentions 로 1 카운트됨 → mentions 인플레이션.

### 2.3 백테스트 5·10·30·60·180 거래일 윈도우 · 급등주 발굴 검증에 맞나

**부적합**. 급등주 관측 윈도우로는 **1·3·5·10 거래일** 이 표준. 60·180 거래일은 장기 홀드 검증용.

`backtest.py:31` 의 `RETURN_WINDOWS = (5, 10, 30, 60, 180)` 은 Serenity 스타일 (Multi-x 홀드 · 6개월+) 에는 맞지만, 사용자 프로젝트 정체성 (급등 전 매수 · 시드 100만원 · 100% 손실 감내) 과 불일치. 최소 `return_1d`, `return_3d` 추가 필요.

**추가 문제**: `_HISTORY_WINDOW_DAYS = 200` (backtest.py:32) 은 180일 return 산정에 딱 걸림. 주말/휴장일 고려하면 200 캘린더일은 약 137 거래일 · 180 거래일 return 은 종종 None 이 될 것. → `_HISTORY_WINDOW_DAYS = 280` 정도로 확대 권장.

### 2.4 yfinance sector/industry 만으로 Industry 충분한가

- **US 티커**: 대체로 정확 (yfinance info API)
- **KRX/TW/JP**: `TickerTable.tsx:239-243` 은 fallback `sector` → `domain_tags` → "—" 로 처리. 실제로 yfinance info 는 `.KS`, `.TW`, `.T` 심볼에 sector/industry 제공하지만 **한국어가 아니라 영어** ("Semiconductors" 등). UI 는 영어 그대로 표시 → 한국 사용자 인지 부하.
- **Private/브랜드** (`ticker_map.py:108-139`): sector/industry 없음 → "—" 표시. 다만 `is_private_or_brand` 조기 return 으로 yfinance 호출 자체가 skip 됨 → 재분류 여지 없음.

**티커 매핑 sanity 이슈**: `ticker_map.py:130` 의 `"LPK"` skip 은 `_YFINANCE_SYMBOL` 에도 `"LPK": "LPK"` 로 등록됨 (라인 84). 우선순위 (`to_yfinance_symbol:181-189`) 상 skip 리스트가 우선이라 LPK 는 항상 실패 처리 → **버그**: matplotlib 태그 매핑 승격 후 skip 리스트에서 제거 안 됨. 실 사용에는 큰 영향 없으나 코드 위생 문제.

`ticker_map.py:124` 의 `"RIBER".upper() if False else "RIBER_SKIP_PLACEHOLDER"` 는 이미 라인 141 에서 필터하지만 **가독성이 나쁘고** 유지보수 위험. 그냥 삭제하는 게 낫다.

### 2.5 z.ai 추출 프롬프트 (`prompts/system.md`)

**강점**:
- Serenity 도메인 sub-sector 맵 명시 → 심볼 매핑 정확도 높음
- Multi-hop supply chain 논지 명시 (라인 69) → LITE 언급 시 AXTI 도 뽑히도록 유도
- confidence < 0.5 강제 (라인 71) → "no position" 명시 시 저평가
- JSON schema 강제 · sanitize 로직 (`extractor.py:63-99`) 견고

**약점**:
- "급등 임박" 명시적 감지 원칙 없음 · 프롬프트는 "논지 분석" 관점 · "언제까지 매수 가능" 같은 timing evidence 는 프롬프트에서 요구하지 않음
- 트윗 컨텍스트로 posted_at 만 전달 (`extractor.py:236`) · reply chain (부모 트윗) 이나 quoted tweet 은 미전달 → 재확인 트윗(reaffirmation) 문맥 손실
- 프롬프트 튜닝 이력 없음 · 파일 자체가 SSOT 라 하지만 실측 정확도 측정 파이프라인 부재

**개선 여지**: `thesis_type=new_bottleneck` 인 경우 프롬프트에 "이 종목이 아직 시장에 알려지지 않은 초기 단계인가" 를 명시 필드로 추출하도록 요청하면 조기 발굴에 결정적.

---

## 3. 고도화 로드맵

| 우선 | 항목 | 문제 | 해법 | 임팩트 | 난이도 |
|---|---|---|---|---|---|
| **P0** | 신규 첫 언급 섹션 신설 | SIVE 원형(첫 언급 급등) 완전 배제 · 프로젝트 정체성 정면 위배 | `first_mention_at >= now-3d` 티커를 최상단 별도 섹션 · 카드 UI 재사용 · seed 없어도 표시 | ★★★★★ | ★☆ (프론트 1개 섹션 추가 · 백엔드 쿼리 변경 없음) |
| **P0** | z.ai / 크론 상태 배너 | 잔액 소진·크론 실패 시 UI 무경고 · 사용자 판단 왜곡 | Summary API 에 `hours_since_last_signal`, `zai_configured`, `last_cron_success` 필드 · 4시간 이상 갭 있으면 상단 빨간 배너 | ★★★★★ | ★★ |
| **P0** | confidence 임계 필터 | 저 confidence signal 이 mentions 를 인플레이션 | aggregators 에 `min_confidence` 파라미터 · UI 에서 임계 (0.5 default) 조정 슬라이더 · 카드/테이블 실시간 재계산 | ★★★★ | ★★ |
| **P0** | Momentum 정의 재검토 | `mention_count_90d>=5` 필터로 조기 급등 배제 | 3 축 병행 표시: (a) 절대 오늘 mentions>=3 · (b) `mentions_today/mentions_7d avg` 비율 · (c) `first_mention_at within 7d && mentions>=2`. 각 축 별 batch 표시 | ★★★★★ | ★★★ |
| **P1** | evidence_type / thesis_type 필터 | 사용자가 "계약 evidence 최근 7일" 같은 판단 근거 필터 불가 · Serenity 정체성 핵심 무시 | 테이블 상단에 다중 선택 filter chip (evidence_type · thesis_type · sentiment · market) · aggregators 확장 | ★★★★ | ★★★ |
| **P1** | 백테스트 짧은 윈도우 추가 | 5·10·30·60·180 은 장기 · 급등주 검증엔 부족 | `return_1d`, `return_3d` 추가 · DB migration · UI 차트 항목 추가 · `_HISTORY_WINDOW_DAYS` 상향 (200→280) | ★★★★ | ★★ |
| **P1** | Telegram 알림 | 매일 아침 페이지 접속 놓치면 발견 지연 | 새 티커 첫 언급 + mentions_today spike + top_picks 진입 3종 알림 · services/notifier 활용 | ★★★★ | ★★★ |
| **P1** | 백테스트 크론 주 1회 → 매일 | 주 1회 (월요일) 배치는 급등주 검증 주기와 안 맞음 · 새 signal → 최대 6일 대기 | scheduler `day_of_week="mon"` 삭제 · 매일 자정 실행 · 배치 크기 유지 (rate limit 방어) | ★★★ | ★☆ |
| **P2** | Watchlist bridge | 관심 종목 저장 없음 · 세션 간 컨텍스트 유실 | 기존 `/watchlist` 모듈과 연동 · 상세 페이지에 "Watchlist 추가" 버튼 · 사용자 노트 필드 | ★★★ | ★★★ |
| **P2** | 개인 판단 로그 (Journal 연동) | 사용자가 "이 종목 조사했다" 흔적 남길 곳 없음 | 기존 `/journal` 과 딥링크 · 티커별 판단 히스토리 | ★★ | ★★ |
| **P2** | 실시간 auto-refresh | 페이지 열어두면 stale · 사용자 수동 새로고침 | 60초 폴링 (SSE 오버킬) · summary 만 refresh · 새 signal 도착 시 카드 하이라이트 | ★★ | ★★ |
| **P2** | 시장 구분 필터 | 251 티커 중 KRX/TW/JP/EU 혼재 · 한국 시드로 실 매수 가능한 종목만 필터할 수단 없음 | `to_yfinance_symbol` 결과의 접미어로 market 필드 도출 · 테이블 필터 | ★★★ | ★★ |
| **P2** | 프롬프트 튜닝 파이프라인 | system.md 변경 시 정확도 회귀 측정 불가 | 골드 셋 100 트윗 · CI 에서 z.ai 재실행 · 결과 diff | ★★ | ★★★★ |

**우선 실행 순서 권장**: P0 4개를 **단일 Phase L14** 로 묶어 배포. z.ai 잔액 recharge 후 즉시 착수.

---

## 4. User 관점 사용 매뉴얼

### 4.1 매일 아침 (개장 전 08:30~09:00 KST) 3단계 워크플로우

1. **상단 카운터 신뢰도 검사 (10초)**
   - `📡 최근 signal (KST)` 이 **당일 07:00 이후**인지 확인 (crawler 06:00 + extractor 07:00 크론 정상 실행 여부)
   - 24시간 이상 갭이면 z.ai 잔액 or 크론 실패 의심 · 이후 판단 근거 약함
2. **90일 언급 테이블 · today desc 로 즉시 재정렬 (30초)**
   - 상단 컨트롤 `Mentions: today`, `desc` 로 변경 (`TickerTable.tsx:170-194`)
   - Bull% >= 60 & mentions_today >= 2 & AVOID 없음 3조건 티커 3~5개 shortlist
   - 각 티커 클릭 → 상세로 이동
3. **상세 페이지에서 판단 (티커당 2분)**
   - `Anti-pattern` 있으면 즉시 제외
   - `Recent Signals` 최상단 (가장 최근) reasoning 정독 · evidence_type=contract/earnings 우선
   - `Backtest chart` return_30d 양수 확인 (0 이면 아직 판단 근거 없음)
   - 트윗 원문 링크 → X 직접 확인 (Serenity reply chain 이 UI 에 없으므로 필수)

**총 소요**: 10분 (shortlist 5개 기준). 개장 09:00 전 완료 가능.

### 4.2 Top Picks · 언제 신뢰 · 언제 의심

**신뢰 조건 (모두 충족 시)**:
- `mentions_today >= 1` (오늘도 살아있는 논지)
- `bullish_pct_90d >= 70` (60 아니라 70 · 60은 과잉 관대)
- `anti_pattern_flags` 비어있음
- `gain_since_first_mention_pct` 가 -20% ~ +50% 사이 (너무 오르면 뒷북, 너무 빠지면 논지 파괴)

**의심 조건 (하나라도 해당 시)**:
- Top Picks 8개 중 실제 오늘 mentions 있는 종목이 3개 미만 → 큐레이션 stale
- 모든 Top Picks 가 seed 7개 안에 포함됨 → 자동 발견 아님 · 수동 seed 재확인일 뿐
- `last_signal_at` 이 3일 이상 지남 → 논지 냉각

### 4.3 테이블 정렬로 SIVE 급 발견하기

**추천 스캔 순서** (하루 한번):

| 순서 | 정렬 | 필터 | 목적 |
|---|---|---|---|
| 1 | `first_mention_at desc` | (검색 비움) | 최근 첫 언급 신규 종목 · **SIVE 형 발견 유일 경로** |
| 2 | `mentions_today desc` | 검색으로 industry 관심 sector 필터 | 오늘 급 관심 |
| 3 | `gain_since_first_mention_pct asc` | Bull% >= 60 | 강 논지 · 아직 안 오른 종목 |
| 4 | `vs_prior_close_pct desc` | (검색 비움) | 어제 대비 오늘 급등 시작 종목 |
| 5 | `mentions_7d desc` | (검색 비움) | 최근 급 관심 (기본 90d 대신) |

**주의**: 현재 UI 는 default 정렬 `mentions_90d desc` 라 매번 사용자가 순서 1~5를 수동 재설정해야 한다. P0 후속으로 정렬 프리셋 저장 필요.

### 4.4 Avoid 리스트 활용

- **매일 접힘 상태 유지** (default). 판단 시 방해.
- **월 1회 펼침** · 보유 종목이 auto_avoid 리스트에 들어갔는지만 확인 (financing_tier D/F 로 하락 · anti_pattern 새로 추가)
- 신규 종목 조사 시 티커 검색은 테이블에서. Avoid 는 사후 안전망.

### 4.5 상세 페이지 검토 순서

1. **Anti-pattern (2초)**: 있으면 즉시 back
2. **Recent Signals 최상단 (30초)**: 가장 최근 reasoning · evidence_type
3. **15원칙 Checklist (10초)**: pass 개수는 무시 (대부분 skip). fail 만 확인
4. **Backtest chart (10초)**: 5·30·60일 return 방향성. 데이터 부족이면 신중
5. **Recent Signals 나머지 (필요 시)**: 논지 진화 궤적 확인
6. **트윗 원문 링크 (필수)**: reply chain, quoted tweet, 커뮤니티 반응

**요령**: 15원칙 Checklist 는 `passCount` 를 신뢰하지 말 것. 현재 최대 pass 는 5개 · 대부분 seed 여부 뷰어. 실질 판단은 Recent Signals 원문에서.

### 4.6 흔한 오독 · 회피 방법

| 오독 | 원인 | 회피 |
|---|---|---|
| "mentions_today=0 인데 카드에 있음 = 오늘 급등 신호" | 카드는 90d 언급 기준 노출 (page.tsx:113) | today >= 1 확인 필수 |
| "Top Picks 8 개 = 8개 다 매수 후보" | Top Picks 는 seed 재정렬일 뿐 | 오늘 mentions + backtest 있는 것만 후보 |
| "Bull% 80% = 확신 종목" | mentions 표본 5 미만이면 통계적 의미 낮음 | mentions >= 10 + Bull% >= 60 조합 |
| "Gain since first mention +200% = 놓친 기회" | 트윗 posted_at 이후 종가 기준 · 실 매수 가능 다음날 시가와 다름 | 개인 backtest 로 재확인 |
| "15원칙 9 pass" | 대부분 skip → pass 표시 왜곡 | fail 개수 위주로 판단 |
| "z.ai signals 4194 = 활발" | 잔액 소진 상태 (2026-08-03 현재) | last_signal_at 시각으로 실 갱신 확인 |

---

## 5. 리스크 · 열린 질문

### 5.1 즉시 리스크 (다음 배포 전 결정 필요)

1. **z.ai 잔액 미충전 상태에서 사용자에게 판단 근거 제공**: 신규 signal 없이 stale aggregate 만 표시 · UI 는 무경고 → P0 배너 필수.
2. **Top Picks 라벨의 정직성**: 현재 큐레이션은 "seed 재정렬" 인데 사용자는 "AI 가 오늘 뽑은 후보" 로 오독 가능. 라벨 문구 재검토 (예: "Serenity Seed · S/A tier · 활성 언급 종목") 또는 큐레이션 로직 실질 강화.
3. **backtest 0 건 상태 배포 지속**: `page.tsx:107` 은 백테스트가 없어도 카드/테이블 정상 표시하지만, 상세 페이지 (`[ticker]/page.tsx:107`) 는 백테스트 차트가 항상 빈 상태 · 사용자는 "이 종목 백테스트 결과가 원래 없다" 로 오독. 첫 월요일 크론 이후에도 배치 크기 200 이라 4194 / 200 = 21주 소요 → **backtest.py 배치 확대 or 병렬화 필수**.

### 5.2 데이터 신뢰성 리스크

4. **z.ai 응답 정확도 회귀 감지 부재**: 프롬프트 튜닝 시 정확도 지표 없음. Serenity 실 논지 vs 추출 signal 정합성을 골드셋으로 측정하는 파이프라인 필요.
5. **submodule auto-pull 실패 사일런트**: `crawler.py:130-158` 는 실패 시 warning 로그만 · UI 에서는 감지 불가. crawler 크론 후 새 트윗 0 건 지속되면 alert.
6. **first_mention_at 의 시간축 왜곡**: yan-labs submodule 이 과거 트윗 뒤늦게 추가하면 first_mention_at 이 과거로 밀림 → gain_since_first_mention 이 부풀려짐. `ingested_at` 사용 대안 검토 필요.

### 5.3 열린 설계 질문 (사용자 결정 필요)

7. **한국 시장 실 매수 가능성**: Serenity 언급 251 티커 중 KRX 상장 몇 개인가? 사용자 시드 100만원 · 해외 주식 매수 정책 확정 필요 · 미확정 시 UI 에 KRX only 필터 추가.
8. **"급등주" 정의 재확인**: 원 정체성 "밈주 워치" 와 Serenity "AI/반도체 supply-chain bottleneck" 은 사실 다른 카테고리. Serenity 는 fundamental·hold 스타일 · 밈주는 sentiment·flip 스타일. 이 페이지의 실 용도가 "Serenity 논지 참조" 로 축소되는 것 아닌지 재검토.
9. **Watchlist / Journal 통합 수준**: Serenity 는 발견 · 관심 저장은 어디에? 통합 안 하면 사용자는 매번 재조사.
10. **backtest 이후 실 진입 가정**: signal_date 종가로 backtest 하지만 실제로는 다음날 시가 진입이 현실적. Backtest 로직 자체가 실 사용 시나리오와 vestige.

### 5.4 코드 위생 (블로커 아님 · 정리 권장)

- `ticker_map.py:124` `"RIBER".upper() if False else "RIBER_SKIP_PLACEHOLDER"` 삭제
- `ticker_map.py:130` LPK skip 리스트에서 제거 (매핑에 이미 있음)
- `serenity.py:126` `SerenitySummary` schema 에 `hours_since_last_signal` 필드 추가 (P0 배너용 사전 작업)
- `BacktestChart.tsx:44` `data[w.key] ?? 0` 은 null 을 0 으로 렌더 · Cell fill 은 hasData 로 분기하나 실제 bar 높이는 0 (평평) · 사용자는 "0% return" 으로 오독 위험. null 은 아예 bar 를 그리지 않는 것이 정직.

---

**리뷰 종합 등급**:
- 인프라 (crawler·extractor·scorer·backtest·price_snapshot 5 cron): B+ (견고 · backtest 배치 크기만 조정)
- API (routes/serenity.py): B+ (계약 명확 · 상태 필드 부족)
- UI 정보 밀도: B (테이블 훌륭 · 카드 그리드 노이즈)
- UI 사전 발굴 적합성: **D** (첫 언급 발견 경로 부재)
- 15원칙 자동화: C (11/15 skip · 근본적 데이터 한계)
- 사용자 매뉴얼 명확성: C (UI 만으로 오독 위험 · 문서 필요)

**다음 배포 (Phase L14) 권장 스코프**: P0 4개 (신규 첫 언급 · 상태 배너 · confidence 필터 · Momentum 재정의) 를 단일 배포. z.ai recharge 완료 확인 후 착수.
