---
title: Perspective C · 지식자산화 리뷰 (원본 아카이브)
type: review-archive
status: reference
created: 2026-07-29
reviewer_persona: "10년 경력 지식 아카이빙·에디토리얼 전문가 · Obsidian/Roam 그래프를 컨설팅·리포트·유료 뉴스레터·강의로 변환 다수"
scope: 판정 자산의 상품화 후보 · Obsidian sync · 에디토리얼 규율
word_limit: 600
---

# Perspective C · 지식자산화 리뷰 (원본)

## 1. 핵심 판단

optimus8은 **판정 로직은 정교하나 판정 자산은 휘발성**이다. `powderkeg_list` 스키마에 `run_id·conditions_json·reject_reasons`는 남지만 **가설(왜 이 6개 조건인가) · 회고(승격 종목 6개월 후 결과) · 시장 컨텍스트(강세장/약세장)** 3요소가 DB에 없다. 그 자산은 `docs/plans/powderkeg-screener/*.md` (17개 파일)와 GON-LLM-Wiki의 단 1건 세션 로그에 산발되어 있고, **자동 sync는 0건**이다 (Radar만 `sync-kickoff.ts`로 Kickoff.md에 동기화). 즉 Stage 1 → Stage 2 이행 시 상품화 가능한 자산은 사실상 `identity.md · first-passed-result.md · 3rd/4th-review-response.md` 4개 뿐이며, 이 상태로 유료 뉴스레터·리포트 발행 시 3주차부터 콘텐츠 고갈이 확정된다. **Stage 2 진입 자격 60% 미달**.

## 2. Stage 1 최적화 · 자산화 준비 5~7개 권고

1. **`powderkeg_list`에 판정 4요소 컬럼 3개 추가** — `hypothesis_id` (어떤 가설 버전으로 판정했는가 · v2.0 등), `market_context` (VKOSPI·KOSPI 20MA 위/아래 등 자동 태깅), `retrospect_url` (승격 후 이벤트 발생·매수·결과 링크). 백필은 필요 없음 — 신 판정부터 축적.
2. **`powderkeg_list.conditions_json`에 margin 값 저장 의무화** — 현재 `{"1":true, ...}` 만 있고 `condition_margins`는 `first-passed-result.md`에는 있으나 DB에 없음. 이후 강등·복귀 추이 분석이 곧 콘텐츠 소재.
3. **승격 종목 매주 스냅샷 자동 로그** — `powderkeg_list` 는 run 단위 · 종목별 시계열 view/table 신설 (`powderkeg_tier_history`). 경인전자 강등(v2 정체성 부적합)처럼 tier 이동 자체가 인용 가능한 이벤트가 된다.
4. **Rejected 이력 아카이브 태그** — 서희건설 v1.0→v1.1 취소 사례는 상품화 가치 최상급 ("파싱 오류 발견·수정 이력"). `reject_reasons`에 원인 카테고리 열거 (parsing_error·threshold_miss·hypothesis_revision) 후 월 1회 집계.
5. **`docs/plans/powderkeg-screener/`의 17개 파일 명명 규칙 강제** — `phase7-*` `p2-*` `p4-*` 접두어가 혼재. 후일 인용·검색이 어렵다. `YYYY-MM-DD-{topic}-{version}.md` 로 통일 or `_INDEX.md` 신설로 최소한의 항해 지도.
6. **매 판정 run 종료 시 훅 1개 추가** — `run_screener` 종료 시 그 run의 신규 승격·강등 diff를 `GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Runs/{run_id}.md` 자동 생성. `sync-kickoff.ts` 패턴 그대로 복제. 이 파일 하나가 없어서 세션 로그가 8일에 1건이다.
7. **UI 판정 팝업에 "판정 근거 인용 가능 URL" 노출** — 현 팝업은 조건별 값만. `optimus8.cafe24.com/powderkeg/decision/{run_id}/{ticker}`  permalink 신설 시 뉴스레터·리포트에서 직접 링크 가능.

## 3. Stage 2 이행 준비 · 3~5개 아키텍처 결정

1. **상품 후보 근접도 순위** (현 자산 기준):
   - Weekly Report (**가장 가깝다 · 4주 준비**) — run diff + 이벤트 로그 + 반자동 티켓 결과. 위 권고 6번 훅만 있으면 자동 초안 생성 가능.
   - Monthly Deep-Dive (**8~12주**) — 산업/테마 크로스링크가 없어 "특정 테마"로 묶을 수 없음. `powderkeg_krx_snapshot`에 섹터 필드 확인·태깅 필요.
   - 강의·교재 (**6개월+**) — `identity.md v2.0`·`p2-2c-reverse-engineer-features.md`가 초석. 다만 "왜 F-Score 6→4로 완화했는가"의 역설계 근거는 세션 1건에 갇힘.
   - 컨설팅 (**즉시 가능 · 그러나 T2에 배치 안 되어 있음**) — Revenue-Tree v2.2에 optimus8 관련 T2 항목 0건. Cal.com 슬롯을 optimus8 판정 조회 상품으로 재정의 가능.

2. **Obsidian sync 최소 3개 경로 신설** — (a) run diff → `Runs/{run_id}.md` (b) 매주 일 08:00 → `Weekly/{YYYY-Www}.md` (c) 승격 종목 상세 → `Tickers/{ticker}.md` (첫 승격 시 생성 · 이후 append). `gonnim-landing/scripts/sync-kickoff.ts`가 이미 존재하는 패턴 참조.

3. **지식 그래프 크로스링크 정책 확정** — activist-radar 신호가 화약고 승격 종목과 겹칠 때 `Tickers/{ticker}.md`에 양방향 링크 자동 삽입. 이게 없으면 "특정 종목 판정 근거 조회 대행" 컨설팅이 사람 노동으로 남는다.

4. **법적 스탠스 명시 헤더 표준화** — 모든 자동 생성 문서에 "개인 도구 · 투자자문 아님 · v2.0 개인 이익 창출 목적" 헤더. Stage 2 유료 진입 전 필수 방어선.

## 4. 폐기·비판 · 자산화 방해 관행

- **`docs/plans/tradebot-tobe/tradebot-tobe-prompt.md` 폐기 확정** — 이미 사용자 명시. 관련 PDF도 같이 삭제. 남겨두면 다음 세션에서 재참조 오염.
- **17개 리뷰 문서의 "3차·4차·2nd-rebuttal" 명명** — 시점 기반이라 재조회 불가. 리뷰 지속 시 20~30개로 팽창 후 붕괴. `_INDEX.md` 없음 = 자산 아님.
- **세션 로그 주기 8일** — 12개 배포·11개 hotfix가 1개 파일에 압축됨. 판정 개별 근거 손실. 배포당 1노트가 정답.
- **`conditions_json`에 boolean만 저장** — margin·컨텍스트·hypothesis version 미기록으로 재현 불가. 이 상태 6개월 지속 시 과거 판정을 "재현할 수 없는 판정"으로 폐기해야 함.
- **로컬 `backend/powderkeg.db`가 빈 파일** — 개발·실 데이터 분리 불명확. Stage 2 상품 초안 생성 시 로컬에서 실 데이터 인용 불가.

## 5. 리스크 3개

1. **Sprint T2 83% 편중 vs optimus8 T2 배치 0** — Revenue-Tree v2.2에 optimus8이 T1/T2/T3 어디에도 매핑 안 됨. 자산화 방향 정의 없이 판정만 축적하면 Q1 미달 시 폐기 1순위.
2. **v2.0 정체성 변경으로 v1.x 판정 무효화 위험** — "예측 없음 · 관찰만" → "매수/매도 판단" 전환. v1.x 판정 이력을 Stage 2 상품에 인용 시 근거 불일치. 판정마다 `hypothesis_id` 없으면 전량 무효.
3. **자매 봇(upbit) 분리 규칙 위반 재발** — CLAUDE.md는 "완전 분리"이나 GON-LLM-Wiki `Works/Trading/`에 둘 다 병렬 배치. 상품화 시 크로스 오염 (예: EMA/MACD 노하우가 optimus8 리포트에 스며듦) 방지 정책 문서 0건.

---

**참조 파일 (절대 경로)**:
- /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/docs/plans/powderkeg-screener/identity.md
- /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/docs/plans/powderkeg-screener/first-passed-result.md
- /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/powderkeg/screener.py
- /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/data/tradebot.db (schema: `powderkeg_list`, `powderkeg_event`, `powderkeg_order_ticket`)
- /Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/_INDEX.md
- /Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Sessions/2026-07-22-to-29-consistency-hardening.md
- /Users/gonnim/GON-LLM-Wiki/Goals/2026-1억-Sprint/Kickoff.md (Radar sync 패턴 참조)
- /Users/gonnim/GON-LLM-Wiki/Goals/2026-1억-Sprint/Revenue-Tree.md (T1/T2/T3에 optimus8 미배치 확증)
