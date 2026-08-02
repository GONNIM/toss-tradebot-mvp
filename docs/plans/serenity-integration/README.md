# Serenity Integration · Toss Tradebot Influencer Track

> **작성 세션**: gon-llm-wiki (2026-08-02 · Content Ingest 파생 · TikTok @ai_dongdon 영상 → Serenity/Capafy 조사 → yan-labs/serenity-aleabitoreddit 로컬 정독 → Toss Tradebot 통합 명세 확정)
>
> **실행 세션**: 본 문서를 Toss Tradebot 세션에서 읽고 Phase L1~L8 순차 실행

## 목적

**Serenity (@aleabitoreddit)** — X 900K+ 팔로워 · AI/반도체 supply-chain 특화 분석가 (2025 검증 실적: AAOI +483% · AXTI +1,057%+ · NBIS Multi-x · LITE +174% · ALAB +283%) — 의 15원칙·per-ticker 논지·dated calls를 Toss Tradebot Discovery 코어에 통합.

**Full 통합 범위**:
- 상단 Nav 에 **Influencer** 메뉴 추가 (Dashboard 좌측)
- Influencer 선택 시 하단 Nav = **Serenity** 만 (기존 L2 hidden)
- 데이터 파이프라인 (crawler + z.ai extractor + scorer + backtest)
- Supabase 스키마 4 테이블
- Cron 4개
- Frontend UI (Signal Feed + Ticker Grid + 15원칙 checklist + Backtest chart)

**예상 시간**: 36h (~4~5일 집중 or 2~3주 저녁·주말)

## 상태

- **Phase L0** · 명세 문서 작성 완료 (본 폴더) · **현재 지점**
- **Phase L1** · 대기 — 사용자 착수 승인 필요

## 파일 구조

| 파일 | 내용 |
|---|---|
| [README.md](./README.md) | 진입점 · 개요 · 상태 (본 문서) |
| [01-ui-spec.md](./01-ui-spec.md) | UI 명세 · Nav 변경 · 페이지 구조 · Next.js 코드 스켈레톤 |
| [02-backend-arch.md](./02-backend-arch.md) | 백엔드 아키텍처 · Supabase 스키마 SQL DDL · z.ai 프롬프트 · 스코어링 함수 · Cron |
| [03-implementation-plan.md](./03-implementation-plan.md) | Phase L1~L8 실행 순서 · 파일 리스트 · 시간 예산 · 승인 게이트 |

## 원천 자료 (참조)

### Serenity 오픈소스 (로컬 clone)
- **경로**: `~/GON-Dev/serenity-tracker/` (yan-labs/serenity-aleabitoreddit)
- **핵심 데이터**:
  - `data/aleabitoreddit_tweets.json` — 6,222 트윗 아카이브 (2025-07-02 ~ 2026-08-01)
  - `data/aleabitoreddit_tweets.csv` — 동일 CSV
  - `data/ticker_stats.txt` — 689 distinct tickers · mention count · first/last seen
- **핵심 문서**:
  - `serenity-aleabitoreddit/references/theses.md` — per-ticker 논지 (1,442 라인 · sub-sector 그룹 · conviction tiers)
  - `serenity-aleabitoreddit/references/methodology.md` — **15원칙 프레임** (346 라인)
  - `serenity-aleabitoreddit/references/track-record.md` — dated calls 검증 데이터 (194 라인)
  - `serenity-aleabitoreddit/references/articles.md` — long-form X Article 요약
  - `serenity-aleabitoreddit/analysis/*.md` — 6 period 분석
- **업데이트 스크립트**:
  - `prep.py` — 트윗 JSON 월별 chunk · ticker stats 재계산
  - `update.py` — 신규 트윗 pull · dedupe · Note Tweet 텍스트 resolve
  - `scripts/xreach_note_text.mjs` — xreach 클라이언트 adapter (인증 필요 · 선택)

### 사전 분석 문서 (GON-LLM-Wiki)
- **관찰 로그**: `~/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Serenity-Signal-Observation-Log.md`
  - §H · methodology 15원칙 요약
  - §I · Toss Tradebot Discovery 스코어링 매핑 (Supabase 스키마 초안)
  - §K · track-record 검증 데이터
  - §L · 실 통합 명세 (본 문서의 원천)
- **심층 분석 v2**: `~/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Influencer-Signal-Applied-Analysis-2026-08-02.md`
  - 5 페르소나 심층 분석 · 4 옵션 결정 프레임
- **원천 노트**: `~/GON-LLM-Wiki/Clippings/summaries/trading/2026-08-02-160639-요즘은-ai가-다-한다구-ai-aitrend.md`

## 실행 원칙 (Toss Tradebot CLAUDE.md 준수)

1. **순차 진행** — Phase L1 → L8 순 · 이전 Phase 완료 및 사용자 승인 없이 다음 진행 금지
2. **로컬 우선** — 로컬 구현 → 로컬 테스트 → 사용자 확인 → 커밋 → 배포
3. **자격증명 X** — 실 API 키·시크릿 본 문서 및 코드에 하드코드 금지 · `.env` (chmod 600) 및 GitHub Secrets 사용
4. **naver 프로필 §1 가드** — GROQ/OPENAI/ANTHROPIC/GitHub PAT 등 시그니처 스캔 커밋 전 필수
5. **개별 파일 add** — 와일드카드 `git add .` 금지 · 파일별 명시 add

## 진입 조건 (사용자 확인 필요)

- [ ] 본 명세 문서 검토·승인
- [ ] `.env` (backend) 에 필요 키 확보 계획: `ZAI_API_KEY`·`SUPABASE_URL`·`SUPABASE_SERVICE_ROLE_KEY`
- [ ] `serenity-tracker` git submodule 추가 (권장) 또는 로컬 참조 방식 확정
- [ ] Phase L1 착수 시점 확정
- [ ] 사용자 실 시드 결정 (Full 통합 후 사용 여부)

## 다음 액션

1. **본 README 검토**
2. `01-ui-spec.md` → UI 요구사항 확인·조정
3. `02-backend-arch.md` → 데이터 모델·스키마 확인·조정
4. `03-implementation-plan.md` → Phase L1 착수 승인
