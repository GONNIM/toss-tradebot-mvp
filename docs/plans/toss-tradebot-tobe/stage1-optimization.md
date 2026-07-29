---
title: Stage 1 · 즉시 최적화
type: implementation-spec
status: active
created: 2026-07-29
updated: 2026-07-29
depends_on: [[identity]]
implements: 리뷰 A (퀀트) · B (UX) · C (자산화) 통합
---

# Stage 1 · 즉시 최적화 (판정→결과 폐루프 완결)

## 0. 목표

Stage 1 진짜 KPI는 정보 공급이 아니라 **자기 판단 오류율 측정·감소**. 현 optimus8은 전자만 하고 후자를 안 함 (리뷰 A). 본 문서는 폐루프 완결에 필요한 즉시 실행 항목을 명시.

## 1. Judgment Journal 신설 (핵심 · A+C+D 통합)

### 1.1 DB 스키마 · `user_judgments` 테이블

```python
class UserJudgment(Base):
    __tablename__ = "user_judgments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    user_id: Mapped[str] = mapped_column(String(50), default="owner")  # Stage 3 대비
    ticker: Mapped[str] = mapped_column(String(20))
    page_source: Mapped[str] = mapped_column(String(30))  # powderkeg | watchlist | sniper | ...
    hypothesis_id: Mapped[str] = mapped_column(String(50))  # v2.0-powderkeg-6cond 등
    thesis_md: Mapped[str] = mapped_column(Text)  # 판정 근거 (마크다운)
    invalidation_price: Mapped[Optional[float]]
    target_price: Mapped[Optional[float]]
    horizon_days: Mapped[int] = mapped_column(default=7)
    mood: Mapped[str] = mapped_column(String(20))  # cool | neutral | revenge | fomo
    market_regime: Mapped[str] = mapped_column(String(30))  # bull | bear | choppy | crisis
    result_at_horizon: Mapped[Optional[float]] = mapped_column(default=None)  # T+N 실현 수익률
    result_computed_at: Mapped[Optional[datetime]]
    git_sha: Mapped[Optional[str]] = mapped_column(String(40))
```

**인덱스**: `(user_id, ts DESC)` · `(ticker, ts DESC)` · `(hypothesis_id, ts)`

### 1.2 API 라우트

- `POST /api/v1/judgments` — 판정 생성 (rejection criteria 필수)
- `GET /api/v1/judgments?ticker=&horizon=&mood=` — 조회
- `PATCH /api/v1/judgments/{id}/outcome` — T+N 실현 결과 갱신 (cron 자동)
- `GET /api/v1/judgments/baseline` — 승률·평균 수익률·mood별 분포

### 1.3 프론트 · `/journal` 페이지 (L1 최상단)

**필수 표시**:
- 오늘 판정 목록 (source page 병치 · self-page 편애 방지)
- 최근 30일 승률·평균 수익률·mood별 분포
- Rejected hypothesis 아카이브 (실패 자산도 자산)
- 판정 vs 결과 정합성 스코어카드 (Stage 2 진입 근거)

### 1.4 판정 생성 UI (모든 페이지에 삽입)

- Powderkeg lock 시, Watchlist 편입 시, Sniper enable 시 → **판정 폼 팝업 강제**
- 필드: thesis (자유 서술) · invalidation_price (필수) · target · horizon · mood
- 저장 시 자동: page_source · hypothesis_id · git_sha · market_regime (KOSPI 20MA·VKOSPI 자동 태깅)

## 2. Powderkeg 통계 규율을 다른 페이지로 이식 (A)

### 2.1 즉시 노출 · 이미 DB에 있는 outcome 필드

- **`CrazyPick.perf_1w` / `perf_1m`** — DB에는 있는데 UI 노출 0. `api/routes/crazy.py` + 프론트 히스토리 탭에 즉시 추가.
- **모든 Pick의 결과 무조건 표시** (cherry-pick 금지).
- **`MoonshotPick`** 동일 처리.

### 2.2 사후 outcome 신설 · 지금 필드 없는 페이지

Meme·VIP·Activist·Super-Signals: `outcome_at_horizon` 컬럼 신설 · 크론으로 T+7 자동 계산.

### 2.3 정보 유형 배지 강제

각 페이지 헤더에 다음 중 하나:
- `[LEADING]` (선행지표) — powderkeg (미래 잠재)
- `[LAGGING]` (사후반응) — meme-watch · sector-leaders (관세청 lagging)
- `[COINCIDENT]` (동행) — sniper · activist (실시간 이벤트)

**색상**: leading=파랑 · coincident=초록 · **lagging=회색** (앵커링 방지)

### 2.4 통계 유의성 표기 강제

모든 스코어 옆에:
- 표본 n · 95% 신뢰구간 · `|t| < 2` 시 결론 어려움 배지

**n < 임계** (예: 50) 시 카드 회색+회의 아이콘. Powderkeg의 `표본 < 50 → 표본부족` 패턴 이식.

### 2.5 Backtest 데이터마이닝 방지

- 최초 실행 시 **모든 sources 조합 강제 실행 + 결과 통합 표시**
- 임의 선택 UI는 유지하되 "임의 선택은 datamining bias 유발" 경고 배너

## 3. 정보구조 3계층 재편 (B)

### 3.1 L1 · 매일 (개장 여정 시간축)

```
📓 Journal (신설·최상단)
  → 🌙 Watchlist    (마감후 예측)
  → 🚀 Sniper       (개장 진입)
  → 💼 Positions    (보유 관찰)
  → 📊 Dashboard    (성과)
  → 📜 Logs         (감사)
```

**Home 재작성**: "오늘의 컨트롤 타워"
- 실시간 배지 4개: `Watchlist 확정` · `Sniper enabled` · `Tier 1 lock 종목수` · `Kill Switch 상태`
- Judgment Journal 최근 5건 요약
- 장 상태 배지 (정규장/AH/마감) 상시 노출

### 3.2 L2 · 심층 (주말 리서치)

```
🧨 Powderkeg   (딥밸류 스크리너 · LEADING)
🐺 Activist    (13D 감시 · COINCIDENT)
🕵️ VIP         (개별 종목 딥다이브)
🇰🇷 Sector    (수출 매크로 · LAGGING · 매크로 참고 라벨)
```

**dropdown 또는 별도 라인** — L1 아래 배치.

### 3.3 L3 · `/lab` 실험장 (nav 히든)

```
crazy · moonshot · meme-watch · super-signals · backtest · execution
```

**규율**:
- nav에서 완전 제거
- `/lab` 인덱스 페이지 하나로 몰기
- 각 항목에 "마지막 검토일 · 라이브 여부 · outcome baseline" 컬럼 강제
- **6개월 방치 라우트 자동 삭제** (무덤화 방지)

### 3.4 기타 재편

- **Settings** → nav에서 빼고 우측 상단 ⚙️ 아이콘
- **Powderkeg** 상단 "가이드 다시 보기 + 상세 문서" 두 버튼 → 우측 nav ❓ 도움말로 통합
- **Watchlist → Sniper 명시적 화살표 UI** (이미 localStorage 공유가 파이프라인 증거)

## 4. 폐기 · 삭제 · 재구성

### 4.1 즉시 삭제 (dead code · 4관점 만장일치)

- **`docs/plans/tradebot-tobe/`** 전량 (git rm)
- **프론트 nav 제거 + `/lab` 이관**: crazy · moonshot · super-signals · backtest · execution
- **API include 제외** (main.py 라우터 등록에서 제외): crazy · super_signals · moonshot · execution
- **DB 격리**: `accounts` · `orders` · `AuditTrade` 3개 (Phase K "미가동" 주석) → `services/models_legacy.py` 이동 or 삭제

### 4.2 재구성 (Phase K placeholder 페이지)

- **`/dashboard`** · **`/positions`** — Toss API Phase K 미가동 상태에서 유령. **Judgment Journal 대시보드로 재구성**.

### 4.3 유혹 요소 정화

- **`/execution`** (896 lines · kill-switch·threshold 편집 UI) — Stage 1 "자동매매 절대 금지" 원칙과 정면 충돌. 존재만으로 사용자 유혹. **관리자 전용 숨김 or Stage 3까지 폐기**.
- **`/moonshot`** "카지노 자금 · 수동 매수" 워딩 — 감정 매매 유도. **삭제 or "US High-Beta Watch"로 리네이밍 + outcome 강제**.
- **`/sector-leaders`** Top N 카드 UI — 매크로 lagging 지표. **테이블만 남기고 카드 폐기 + "매크로 참고" 라벨 강제**.
- **`/super-signals`** meme+vip+activist 병합 — 세 원천 모두 lagging/reflex · 병합이 신호 증폭 못하고 **공통 시점 편향만 증폭**. **폐기 or powderkeg validated 게이트 이식 후 재승인**.

## 5. Stage 1 합격 KPI (Stage 2 진입 자격)

- [ ] Judgment Journal 판정 30건+ 축적 · rejection criteria 100%
- [ ] 판정 정확도 baseline 확정 (T+7 outcome 자동 · selection bias 제거)
- [ ] Obsidian sync 3경로 자동화 완결 → [[stage2-architecture#자산화-훅]]
- [ ] 관리자 인증 100% · 무인증 실 종목 노출 0
- [ ] 3계층 재편 완결 · L3 archived 라벨 · `/lab` 인덱스
- [ ] **T2 Cal.com 컨설팅 슬롯에 첫 유료 예약 1건** → [[sprint-revenue-integration]]

## 6. 위임 · 다음 문서

- **아키텍처 결정 (user_id · URL 이원화 · 인증 · 자산화 훅 · 관측성)**: [[stage2-architecture]]
- **Sprint 매출 연동 (T2 배치 · Cal.com · Weekly Report)**: [[sprint-revenue-integration]]
- **리스크 12 · 방어선**: [[risks-and-guardrails]]
- **12주 실행 로드맵**: [[roadmap-12week]]
