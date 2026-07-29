---
title: Perspective B · 정보설계·UX 리뷰 (원본 아카이브)
type: review-archive
status: reference
created: 2026-07-29
reviewer_persona: "15년 경력 정보설계·UX 컨설턴트 · Bloomberg Terminal / TradingView / Notion 대시보드 정보구조 설계"
scope: 18개 메뉴 정보구조 · 사용자 여정 3시나리오 · 재편안
word_limit: 600
---

# Perspective B · 정보설계·UX 리뷰 (원본)

## 1. 핵심 판단

현 18개 메뉴는 **flat 단일 nav bar**(layout.tsx L11-31)에 계층 없이 나열돼 있고, 그중 3개(`super-signals`·`backtest`·`execution`)와 2개(`crazy`·`moonshot`)는 이미 정체성 재정의로 nav 숨김+라우트 유지 상태다. 즉 GON 스스로도 "네비게이션과 라우트가 어긋난다"는 문제를 code comment로 인정하고 있다. Home(`page.tsx`)은 3장 카드(sector-leaders·dashboard·positions)만 노출해 nav 순서와 완전히 불일치한다. **정보구조가 이미 붕괴 중이며 Stage 2 이행 전에 재편이 필수**다.

## 2. Stage 1 최적화 · 구체 권고

**L1/L2/L3 3계층 재편안** (18개 → L1 5개 · L2 4개 · L3 히든):

- **L1 · 매일 (개장 여정)**: `🌙 Watchlist` → `🚀 Sniper` → `💼 Positions` → `📊 Dashboard` → `📜 Logs`. 시간축(마감후 예측 → 개장 진입 → 보유 관찰 → 성과 → 감사) 순.
- **L2 · 심층 (주말/리서치 여정)**: `🧨 Powderkeg` (딥밸류 스크리너) · `🐺 Activist Radar` (13D 감시) · `🕵️ VIP` (개별 종목 딥다이브) · `🇰🇷 Sector Leaders` (수출 매크로). "탐색·가설" 그룹으로 묶고 L1 아래 dropdown 또는 별도 라인.
- **L3 · 실험장 (URL 접근만)**: `crazy`·`moonshot`·`meme-watch`·`super-signals`·`backtest`·`execution`. nav 완전 제거, `/lab` 인덱스 페이지 하나로 몰기.

**추가 5개 권고**:
1. `Home`을 진짜 **오늘의 컨트롤 타워**로 재작성 — 최상단에 `Watchlist 확정 상태 + Sniper enabled + 오늘 티어1 lock 종목수 + Kill switch 상태` 4개 라이브 배지. 현 3장 카드는 static placeholder이라 매일 열 이유가 없다.
2. `Settings` → nav에서 빼고 우측 상단 아이콘(⚙️)으로 이동. 매일 열지 않는 페이지가 매일 시야를 차지 중.
3. `Powderkeg` 페이지 상단 `📖 가이드 다시 보기 + 📄 상세 문서` 두 버튼(L58-76)은 우측 nav "❓ 도움말"로 통합, 페이지 상단 정리.
4. `Watchlist`와 `Sniper` 사이 명시적 화살표 UI (`Watchlist 확정 → Sniper 실행`) — 현재는 별개 페이지처럼 보이나 실은 파이프라인. `sniper_api_token` localStorage 공유(watchlist L18, sniper L27)가 이미 그 증거.
5. 페이지 하단 build SHA(layout L62)는 유지 · 대신 nav 옆에 "장 상태 배지"(정규장/AH/마감) 상시 노출 — VIP HeroCard 로직(L70-79) 재활용.

## 3. Stage 2 이행 준비 · 아키텍처 결정

1. **URL 네임스페이스 분리** — 관리자 라우트 전부 `/admin/*` 이동 (settings·logs·execution·backtest). Stage 2 외부 뷰는 `/insights/*` 또는 `/wiki/*`로 별도. 지금 flat 구조는 그대로 두면 롤백 불가.
2. **인증 게이트 위치** — 현재 `sniper_api_token`은 localStorage(sniper L27)라 페이지별 산발. Stage 2 진입 전 **httpOnly 쿠키 + role 3단계(admin/subscriber/anon)** 로 통일. next-session.md 우선순위 2에 이미 명시된 항목, 재편과 동시 진행.
3. **"소비자 뷰"용 컴포넌트 추출** — Powderkeg 상세 팝업·Sector-Leaders AnalysisPanel·VIP HeroCard 3종이 유일하게 외부에 팔릴 만한 UI다. 이들을 `components/public/`로 분리해 향후 SSR 무인증 페이지에서 재사용.
4. **판정 vs 결과 대조 뷰 부재** — Sprint 2 DoD Report(watchlist L53-142)는 있지만 "어제 판정 → 오늘 결과" 일일 대조 화면이 없다. Stage 2의 핵심 판매 포인트("우리는 매일 자기 판정을 검증한다")를 뒷받침할 유일한 근거이므로 Stage 1 말미에 추가 필수.

## 4. 폐기·비판

- **폐기 문서**: `docs/plans/tradebot-tobe/tradebot-tobe-prompt.md`(+ .pdf) — 지시대로 삭제.
- **nav 완전 제거**: `crazy`(미국 시총≥$1B 안전 universe · 한국 전환으로 무의미)·`moonshot`(16:50 KST 미국장 대상 · 정체성과 불일치)·`super-signals`(v2 Phase 3 미완, comment로 백업 명시)·`backtest`·`execution` — 이미 layout에서 주석 처리됐으므로 `/lab` 인덱스에 몰거나 라우트 자체 삭제.
- **`meme-watch` 격하**: 정체성 상징이라 삭제 불가지만 L1에서 L2 실험장으로. 자체 disclaimer(L89-93)가 "카지노 머니로만"이라 매일 여는 도구 아님.
- **Home 카드 3장**: sector-leaders/dashboard/positions만 노출 · 실사용 순서(watchlist·sniper·powderkeg)와 완전 불일치. 폐기 재작성.
- **`Dashboard`+`Positions`**: 둘 다 "Phase K 활성 후 실 데이터" placeholder(dashboard L64-68, positions L26). 실 데이터 붙기 전엔 Home 통합 상태 배지로 대체하고 nav 1칸으로 줄이기.

## 5. 리스크 3개

1. **재편 도중 URL 북마크 파괴** — GON 본인이 크론·Telegram 알림·docs 링크에서 `/powderkeg` 등 절대 경로를 사용 중(next-session.md L26, L33). 라우트 이전 시 301 redirect 유지 없으면 알림 링크가 죽는다.
2. **L3 실험장이 무덤화** — nav 숨김만으로 방치하면 코드가 썩는다. `/lab` 인덱스에 "마지막 검토일 · 라이브 여부" 컬럼 강제. 6개월 방치 라우트는 자동 삭제 룰 설정.
3. **관리자/외부 뷰 분리 지연 시 자격증명 노출** — 현재 Powderkeg/Watchlist가 실 종목 리스트·백테스트 수치를 무인증 URL로 노출. Stage 2 외부 초대 전에 `/admin` 이관 안 하면 "개인 도구" 법적 스탠스가 훼손된다.
