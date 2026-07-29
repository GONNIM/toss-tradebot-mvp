---
title: Perspective A · 퀀트·투자심리 리뷰 (원본 아카이브)
type: review-archive
status: reference
created: 2026-07-29
reviewer_persona: "20년 경력 퀀트 리서처 겸 행동재무학 전문가 · 헤지펀드 개인 트레이더 대시보드 자문"
scope: 각 메뉴의 통계적 유의성 · 확증편향 유발 요소 · Stage 1 성패 진짜 기준
word_limit: 600
---

# Perspective A · 퀀트·투자심리 리뷰 (원본)

## 1. 핵심 판단

optimus8은 **정보 밀도는 높으나 "판정→결과" 폐루프가 없는, 확증편향 유발 구조**다. Powderkeg에는 t-stat·표본 n·`decision.validated` 게이트라는 진짜 통계 규율이 있고([powderkeg/page.tsx:1892-1914](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/powderkeg/page.tsx)), Watchlist에는 승률·R:R·MDD DoD 리포트가 붙어있다([watchlist/page.tsx:93-107](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/watchlist/page.tsx))— 여기까진 시니어급이다. 그러나 근본 결함 3가지: (a) `CrazyPick.perf_1w`/`perf_1m` 필드가 DB에는 있는데([services/models.py:70 인근](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/services/models.py)) API/UI 어디에도 노출 안 됨 — 즉 "매일 10건 Pick 던지고 결과는 안 본다"는 selection bias 그 자체. (b) Moonshot·Meme·VIP·Activist·Super-Signals는 아예 사후 outcome 필드조차 없음 — grep `perf_1w` = 프론트 0건. (c) 18개 페이지 중 5개(Crazy·Moonshot·Meme·Super-Signals·Activist)가 서로 다른 "Top N 정보"를 병렬 발신 — 사용자가 매일 자기 이론에 유리한 페이지를 골라 볼 자유가 무제한. Stage 1 목적("개인 판단 도구")은 정보 공급이 아니라 **자기 판단의 오류율을 측정·감소**시키는 것인데, 지금 사이트는 전자만 하고 후자를 안 한다.

## 2. Stage 1 최적화 · 6개 권고

1. **[Judgment Journal 신설] 화면 하나에 "오늘 나는 어느 종목에 어떤 판단을 했나 + 그 근거 + rejection 조건" 을 강제 기록** — 근거: 현재 powderkeg lock/manual add([powderkeg/page.tsx:563](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/powderkeg/page.tsx))·watchlist 편입([watchlist/page.tsx:538](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/watchlist/page.tsx))에 사용자 판단 이력이 흩어져 있어 pre-registration이 불가능. **실행**: `user_judgments` 테이블 신설(ticker·pick_date·thesis·invalidation_price·target_price·source_page) + `/judgments` 페이지 1개. 판정 시 rejection criteria 필수 입력.

2. **[Crazy·Moonshot에 perf_1w/1m 컬럼 즉시 노출]** — 근거: DB 컬럼은 이미 있음([services/models.py:70~ CrazyPick "T+7일 수익률" 주석 확증](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/services/models.py)), `api/routes/crazy.py`만 손대면 됨. **실행**: 히스토리 탭에 "예측 시점 vs T+7·T+30 실제" 컬럼 2개 추가 + Selection bias 방지 위해 **모든 Pick의 결과를 무조건 표시**(cherry-pick 금지). Moonshot도 동일.

3. **[Meme·VIP·Activist "사후 반응 시그널" 라벨 강제 부착]** — 근거: `components/meme-watch/UsageGuide.tsx:93` "밈주 워치는 사후 반응 시그널이라 forecast 아님"이 코드 주석에만 있고 UI 헤더엔 없음. 사용자가 이걸 "예측"으로 오독하면 앵커링 발생. **실행**: 각 페이지 header 배지에 `[LEADING]` / `[LAGGING]` / `[COINCIDENT]` 타입 명시 · 색상 구분(사후 반응은 회색 톤).

4. **[Powderkeg의 통계 규율을 다른 페이지에도 이식 · 표본 부족 종목 강제 회색화]** — 근거: powderkeg는 `표본 < 50 → 표본부족 배지`([powderkeg/page.tsx:1984](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/powderkeg/page.tsx))·`|t| < 2 → 결론 어려움`([1957·2020](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/powderkeg/page.tsx)) 규율 있음. Crazy/Moonshot/Super-Signals는 이 게이트 없이 "score 90.5" 같은 숫자만 던져 pseudo-precision 유발. **실행**: 모든 스코어 옆에 "표본 n · 통계 유의성 + 95% 신뢰구간" 부착 · n < 임계면 카드 회색+회의 아이콘.

5. **[감정·시장 상황 프리셋 강제 표시]** — 근거: 현재 판정 UI 어디에도 사용자 상태(수면·손실 후 복구심리·시장 VIX·전일 손익)를 기록하는 필드 없음. Kahneman이 말한 "hot state에서 만든 판단은 cold state 판정과 다르다". **실행**: judgment journal에 `mood: cool|neutral|revenge|fomo` + 전일 자체 손익 자동 pull → 나중에 mood별 승률 분포 리포트.

6. **[Backtest 페이지의 "sources" 체크박스 default 변경]** — 근거: `backtest/page.tsx:16-20`에서 meme/vip/activist 모두 `true` 디폴트. 사용자가 자기 가설 유리하게 선택 조합을 계속 바꿔가며 승률 좋은 조합만 남기는 **datamining bias** 발생 경로. **실행**: 최초 실행 시 모든 조합 강제 실행 + 결과 통합 표시 · "임의 선택은 datamining"이란 경고 배너.

## 3. Stage 2 이행 준비 · 4개 아키텍처 결정

1. **`user_judgments` 스키마를 지금 확정** — Stage 2 지식 자산화의 원자단위는 "판정+근거+결과"의 삼각. 나중에 스키마 바꾸면 과거 판정 소급 재기록 불가. 최소 필드: `id, ts, ticker, page_source, thesis_md, invalidation, target, horizon_days, result_at_horizon, mood, market_regime`.

2. **Page-level `emitted_at` + `snapshot_url` 을 모든 Top-N 응답에 강제** — 지금 crazy history는 pick_date만 있고 스코어 계산 당시의 원본 데이터 snapshot 링크가 없음. Stage 2에서 "이 판단은 왜 그때 옳았나/틀렸나"를 사후 감사하려면 **입력 데이터 immutable snapshot** 필수. powderkeg의 provenance([powderkeg/page.tsx:1051](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/powderkeg/page.tsx))가 유일한 모범 — 다른 페이지에도 강제.

3. **"페이지 정체성" 태그 필수화 (Leading/Lagging/Coincident + Universe scope + Refresh cadence)** — 지금 crazy(US·시총≥$1B) vs powderkeg(KRX·소형주) vs meme(사후반응) vs vip(전문가 관측) 특성이 헤더 카피에만 있고 metadata로 분리 안 됨. Stage 2 유료 구독 시 "이 사용자에게 어떤 페이지가 실제 도움 됐나"를 pageflag 기준으로 집계해야 함.

4. **성과 리포트를 페이지 밖 별도 `/journal` 로 물리 분리** — 각 페이지 안에 성과 붙이면 사용자가 자기 자랑 지표만 보게 됨(자기 페이지 편애). 통합 저널에서 **모든 페이지 판정을 한 화면에 병치**해야 selection bias 방지. Stage 2에서 이걸 마케팅 자산으로 전환 가능.

## 4. 폐기·비판 · 삭제/재구성 대상

- **`/dashboard`**: Phase K(Toss API) 미가동 상태에서 "총 자산 USD" 카드 4개만 뜸([dashboard/page.tsx:22-40](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/dashboard/page.tsx)). Toss API 방향 자체가 [tradebot-tobe-prompt.md 폐기 대상]으로 지정된 상황에서 유령 페이지. **삭제 or "Judgment Journal 대시보드"로 완전 재구성**.
- **`/positions`**: 69 lines · 동일하게 Phase K 대기 · "보유 포지션 없음" 상태 방치([positions/page.tsx:24-27](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/positions/page.tsx)). **삭제**.
- **`/execution` (896 lines)**: kill-switch·paper·threshold 편집 UI. Stage 1 "자동매매 절대 연결 금지"([identity.md:16-17](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/docs/plans/powderkeg-screener/identity.md))와 정면 충돌. 존재만으로 사용자 유혹. **관리자 전용으로 숨김 or Stage 3까지 폐기**.
- **`/moonshot` (Top 3 · 미국장 · 100만원 카지노 자금)**: [moonshot/page.tsx:37 "카지노 자금·수동 매수"] · Stage 1 "개인 판단 도구" 정체성과 프레이밍 상충. "카지노" 워딩이 감정적 매매 유도. **삭제 or "US High-Beta Watch"로 리네이밍 + outcome 강제**.
- **`/sector-leaders`**: 산업부 월간 수출입 ↔ KRX 매핑([sector-leaders/page.tsx:1-15](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/sector-leaders/page.tsx))은 매크로 lagging 지표라 개별 종목 매수 판단으론 신호대잡음비 낮음. **유지하되 "매크로 참고" 라벨 강제 + Top N 카드 UI 폐기(테이블만)**.
- **`/super-signals` "2+ 소스 승격"** — meme·vip·activist 병합이라지만([super-signals/page.tsx:19-22](/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend/app/super-signals/page.tsx)) 세 원천 모두 lagging/reflex 성격 · 병합이 신호를 증폭 못하고 **공통 시점 편향만 증폭**. 통계적 근거(t-stat·표본) 없이 rule-based 병합. **폐기 or powderkeg validated 게이트 이식 후 재승인**.

## 5. 리스크 3개

1. **Selection bias 누적으로 사용자가 자기 예측력을 과신 → 실전 배팅 확대 → 큰 손실** — 지금 Crazy/Moonshot은 매일 10~13건 Pick 방출, outcome 자동 계산 필드는 DB에만 존재하고 UI 미노출. 사용자가 자연히 "맞춘 것만 기억"하는 사후해석편향 100% 노출. Stage 2 자산화 전에 **판정 오류율 정직한 baseline** 없으면 지식자산 자체가 오염된 데이터가 됨.
2. **"내 도구가 나에게 맞다"는 착각의 물리적 증거 부재** — CLAUDE.md·identity.md 어디에도 "GON 본인의 실 매매 vs optimus8 판정 상관계수" 측정 계획 없음. Sprint 목표 1억(Revenue-Tree)이 optimus8 판정 정확도와 무관한 채 진행되면 Stage 4 유료 구독 진입 시 **"실제 수익 근거 무" → 규제·환불·평판 리스크**.
3. **18개 페이지 UI 부하가 판단 피로 유발 → 결정적 순간에 오히려 잘못된 페이지에 앵커링** — powderkeg 하나가 2176 lines·11개 세부 섹션. 하루에 18개 페이지를 한 사람이 순회 불가능. Stage 1 "개인 판단 도구"의 진짜 KPI는 "매일 얼마나 확신 있는 판단을 몇 개 내렸나"인데, 지금은 페이지 순회 자체가 시간을 다 씀. **핵심 3~4 페이지로 축약 + 나머지는 archived 라벨**이 Stage 1 합격의 전제조건.
