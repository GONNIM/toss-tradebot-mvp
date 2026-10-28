# Toss Tradebot MVP

**Toss API 기반 주식 자동매매 봇 (MVP)**

> 본 프로젝트는 자매 프로젝트 `upbit-tradebot-mvp`의 노하우를 주식 시장(Toss API)에
> 이식하기 위해 시작되었다. 보편 자산(워크플로우·가드레일·메모리 규약)은 이전했고,
> 코인 특화 자산(EMA/MACD·pyupbit·BACKFILL 등)은 본 프로젝트에서 재검토 후 도입.

---

## WHY (목적)

**핵심 미션**: Toss Open API를 활용한 주식 자동매매 MVP 구축

**사이트 목표** (2026-10-23 사용자): "사용자에게 최적의 정보를 쉽고 자세하게 알려주는게 목표이다." — 알림·화면 문구는 이 기준으로 판단한다.

### 기획 단계 (현 상태 — 2026-06-16)
- Toss Open API 가용 범위 조사 (시세·잔고·주문)
- 주식 시장 특성 반영 (장 운영시간·휴장일·가격 호가 단위·단주 거래 등)
- 코인 vs 주식 전략 적용 가능성 평가 (EMA/MACD 등 지표 → 일·분봉)
- 리스크/규제 검토 (자동매매 약관·테스트모드 가용성)

→ **WHY 섹션은 기획 완료 후 확정·갱신**

### 비기획 사항 (TBD — 다음 단계에서 결정)
- 지원 종목 범위 (KOSPI·KOSDAQ·해외 ETF 등)
- 전략 후보 (지표 기반 / 패턴 / 펀더멘털)
- 매매 모드 (시장가 / 지정가 / 예약주문)
- 운영 환경 (개인 단말 / 서버 상주)

---

## WHAT (구조)

본 프로젝트의 구조는 기획·설계 단계 진행에 따라 본 섹션에 채워 넣는다.

### 초기 스캐폴딩 (현 시점 — 메타 자산만)
```
toss-tradebot-mvp/
├── CLAUDE.md                       ← 본 문서 (작업 계약)
├── README.md                       ← 프로젝트 소개
├── .gitignore                      ← Python + 자격증명 표준
└── .claude/
    └── context/
        └── project-rules.md        ← 보편 워크플로우·금지 사항
```

### 예정 구조 (참고 — `upbit-tradebot-mvp` 패턴 차용 후보)
```
core/        # 전략·필터·포지션 상태
engine/      # 실행 루프 (주식 장 시간 고려)
services/    # Toss API 래퍼, DB, 알림, 에러 매핑
pages/       # Streamlit Dashboard (선택)
docs/        # 분석·운영·계획 문서
scripts/     # 운영 유틸
tests/       # 단위/통합 테스트
```

→ **WHAT 섹션은 설계 단계 완료 후 확정**

---

## HOW (작업 방법)

### 워크플로우 (`upbit-tradebot-mvp`에서 이전한 보편 규칙)

**순차 진행 필수**:

1. **로컬 구현** → 코드 작성
2. **로컬 테스트** → 단위·통합 테스트
3. **완료 보고** → 사용자 승인 대기 ⚠️
4. **GitHub 커밋 준비** → 변경 내용 명시 + 버전 갱신 (해당 시)
5. **GitHub 커밋** → 변경 내용 + 버전 포함
6. **서버 배포 전 승인** → 사용자 확인 ⚠️
7. **서버 배포** → 운영 환경 반영
8. **서버 테스트** → 실시간 로그 확인
9. **완료 보고** → 검증 결과 보고

**⚠️ 사용자 승인 없이 다음 단계 진행 금지**

### 배포 규칙 — 자동화 선확인 (2026-07-08~)

**서버 배포·재시작 계획 수립 시 최초 확인**:

```bash
ls .github/workflows/               # workflow 파일 존재 여부
grep -l "push:\|workflow_dispatch:" .github/workflows/*.yml  # 트리거 파악
```

**본 프로젝트 자동 배포 실체** — `.github/workflows/deploy.yml`:
- 트리거: `push: branches: [main]` (자동) + `workflow_dispatch` (수동)
- 절차: validate (backend 문법·frontend json) → deploy (ssh git reset --hard + build + systemctl/pm2) → verify (health curl 3회 재시도)
- 소요: 약 2m 20s
- 검증: `gh run list --workflow=deploy.yml --limit 3` / `gh run watch`

**배포 판단 흐름**:
1. `.github/workflows/` 존재 + push 트리거 있음 → `git push origin main` 만으로 배포 완료. SSH 접속 불필요.
2. workflow 없거나 실패 시에만 → 수동 SSH 배포 (메모리 `reference_tossbot_deploy` fallback)
3. auto-mode classifier 가 prod SSH 를 차단하면 → 자동화 존재 조사 먼저

**메모리 시점 편향 주의**: `reference_*deploy` 형태의 메모리는 몇 주 전 관측이라 자동화가 나중에 추가됐을 수 있음. 반드시 workflow 파일과 대조.

참조: `.claude/lessons-learned.md` 교훈 #1, 메모리 `feedback_workflow_first_before_manual_deploy`

### 멀티 Phase 작업 배포 규칙

- 모든 Phase 로컬 완성 후 **단일 배포** (Phase별 부분 배포 금지)
- 사용자가 명시적으로 "이번 Phase만 먼저 배포" 지시한 경우만 예외
- 참조: 메모리 `feedback-deploy-only-when-complete`

### 기획/구현계획서 작성 규칙

- 기획안·구현계획서는 채팅으로 먼저 요약 보고 → 사용자 승인 → 문서 저장
- 무단 문서 생성 금지
- 참조: 메모리 `feedback-plan-doc-protocol`

### 버전 갱신 정책

- 런타임 소스 변경 시에만 버전 갱신 (예: dashboard.py 같은 진입점 파일이 향후 생기면 그 파일에)
- 문서·.gitignore·README 같은 비런타임 변경엔 갱신 생략
- 참조: 메모리 `feedback-version-bump-scope`

### 자격증명 가드레일

- 평문 자격증명 작성·커밋 절대 금지 (Toss API key·OAuth 토큰·계좌번호 등)
- `.env` 또는 Secret Manager만 사용, 코드에는 `${VAR}` 참조
- `.gitignore` `.env` 항상 포함
- 참조: 글로벌 `~/.claude-profiles/naver/CLAUDE.md` §1

---

## ⚠️ CRITICAL - 작업 원칙 및 금지 사항

### 보편 금지 사항 (Upbit 프로젝트 이전)

1. **사용자 승인 없이 서버 배포 금지** (Issue #16 교훈)
2. **편협적 수정 금지** — 변수·API 수정 시 `grep -r "이름"` 으로 전체 영향 범위 확인
3. **교훈 문서 선행 작성 금지** — 사용자 요청 시에만 작성
4. **dashboard.py 등 버전 미업데이트 시 커밋 금지** (런타임 코드 변경 시)
5. **부분 배포 금지** (멀티 Phase 작업)

### 본 프로젝트 신규 금지 사항 (Toss API)
- TBD — 기획·설계 단계에서 채울 영역

### 트러블슈팅 우선순위
- TBD — 첫 Issue 발생 시부터 누적

### 상세 문서 (TBD)
- `.claude/context/project-rules.md` — 워크플로우·금지·체크리스트 (생성됨)
- `docs/architecture/` — 시스템 설계 (예정)
- `docs/issues/` — Issue별 트러블슈팅 (예정)
- `docs/work-orders/` — 작업 지시서 (예정)
- `docs/plans/` — 기획안·구현계획서 (예정)

---

## 에이전트 운용

작업은 po가 받아 아래 표대로 나눕니다. 되돌리기 어려운 동작은 사용자 승인 후에 실행합니다.
역할·공용 규칙·두 프로필(thetak·naver) 운용은 `.claude/PROJECT_PROFILE.md` 를 먼저 읽습니다.

| 이런 일 | 맡는 역할 | 완료 확인 |
|---|---|---|
| 단계 계획 | po (planner 겸임) | `docs/plans/<주제>/` 문서 (승인 후 저장) |
| 서버·API·마이그레이션 | backend | 단위 테스트 통과 |
| 화면 | frontend | `tsc --noEmit` + 브라우저 렌더 확인 |
| 검증 | tester | 수용 기준 대응표 |
| 리뷰 | reviewer | 지적 목록 |
| biotech 판정·봉인·병합 승인 | fable | 판정 표 + "병합 승인됨 · PR #번호" |

## 축적된 규칙
<!-- po가 작업을 마칠 때마다 1~3줄 추가합니다. 형식: - (YYYY-MM-DD) 규칙 — 이유 -->
- (2026-10-21) 이 프로젝트는 thetak·naver 두 프로필에서 공용으로 연다. 오래 지킬 규칙은 메모리가 아니라 이 절이나 `.claude/PROJECT_PROFILE.md` 에 남긴다 — 메모리는 프로필마다 따로 쌓여 갈라진다.
- (2026-10-21) 전체 pytest 는 기존 실패 21건이 있어 커밋 hook 에 걸지 않는다. hook 은 biotech 묶음·compileall·tsc 만 — 실패하는 검사를 걸면 모든 커밋이 막힌다.
- (2026-10-22) main 병합은 자동 모드 분류기가 막으므로 사용자가 `! gh pr merge N --merge` 로 한 건씩 실행하고, 각 배포 run 이 끝난 뒤 다음 건을 병합한다 — deploy.yml 에 concurrency 가 없어 배포가 겹칠 수 있다.
- (2026-10-22) "배포일" 이 기준인 상수는 병합 직전에 KST 날짜를 다시 확인한다 — 병합 사이에 날짜가 넘어가 START_ET 를 두 번 고쳤다.
- (2026-10-22) 테스트는 루트 `backend/tests/conftest.py` 맨 위에서 DATABASE_URL 을 메모리로, 텔레그램 토큰을 빈 값으로 강제한다 — `.env` 가 먼저 로드되면 테스트가 실 DB 를 지운 것으로 보이고 실 봇으로 발송했다.
- (2026-10-22) 버전 번호는 `frontend/package.json` (화면 변경) · `backend/api/main.py` (서버 변경) 둘 다 쓴다 — 사용자 결정 · 그전에는 기준 파일이 정해지지 않아 0.1.0 그대로였다.
- (2026-10-22) 화면 기준은 gonnim.dev /dominance · /sangsik 방식으로 바꾼다 (`docs/design-rules.md` 개정 예정 · `docs/plans/ui-ux-optimization/`) — 사용자 결정.
- (2026-10-23) 요청받지 않은 새 조사·작업은 지금 하던 일 바로 뒤에 넣고 이유를 함께 알린다 — 알림 설정 페이지(1022-09) 진행 중 아침 알림 조사를 설명 없이 먼저 해 일정 관리를 의심받았다.
- (2026-10-23) 예상 수익률·목표가 표시 금지 규칙은 폐지한다 — 사용자 결정. 숫자는 「통계 추정가…보장 아님」처럼 추정임을 밝혀 보여 준다. 남은 문서 정리는 PROJECT_PROFILE 1023-06.
- (2026-10-23) LLM 은 Anthropic 이 1순위, 키가 없거나 오류면 Z.ai 로 넘어간다 (모델은 코드 기본값 · env 에 적지 않음) — 사용자 결정 · PR #109.
- (2026-10-25) Anthropic 기본 모델은 Claude Opus 5.5 · effort medium — Z.ai 보다 정확한 핵심 판단이 우선 (사용자 결정 · PR #113). 비용은 콘솔 월 한도로 막는다.

---

## 자매 프로젝트 참조

`upbit-tradebot-mvp` (`/Users/gonnim/Project-MVP/Source/upbit-tradebot-mvp`) 의
다음 자산을 참고용으로 활용:

| 영역 | 참고 위치 | 활용 |
|---|---|---|
| 알림 시스템 | `services/notifier.py`, `services/error_messages.py` | Telegram 발송 패턴 + 한국어 에러 매핑 구조 |
| 운영 매뉴얼 | `docs/operations/notifications.md` | 알림 인벤토리 문서화 패턴 |
| 서버 watchdog | `scripts/server/watchdog_*.sh` | 정체 감지·dedupe 패턴 |
| 디지스트 | `scripts/server/{daily,weekly}_digest_*.sh` | KPI 요약 패턴 |
| 백업·롤백 | `scripts/{backup,rollback}.sh` | 변경 안전망 |

→ **복사가 아닌 학습**. Toss API·주식 시장 특성에 맞춰 재설계 후 도입.

---

**마지막 업데이트**: 2026-10-23
**버전**: 0.3 (에이전트 운용 · 축적된 규칙 절 추가 — 두 프로필 공용)

## 디자인 기준
- 화면 작업(UI·스타일·부품)은 저장소 루트 `DESIGN.md` 의 색·글꼴·간격·부품 규칙을 기준으로 한다. 다르게 정한 값은 이유를 적는다. 로고·상표·고유 그림은 따라 쓰지 않는다. <!-- design-md: 1028-03 -->
- (2026-10-28 · 1022-10) DESIGN.md 는 coinbase 판을 기본으로 쓴다 (4곳 비교: light · 강조색 하나 · 상승·하락 색 · 숫자 고정폭 · 종목 목록 · 터치 44px). 이 프로젝트에서 다르게 정한 값: 반경 8·14·알약 · 그림자 없음 (10/22 결정 · 알약 버튼·24px 카드·마우스 올림 그림자 안 씀) · 본문 17px (한국어 가독) · 숫자 칸은 `tabular-nums` (stripe 규칙) · 홍보용 어두운 큰 화면·섹션 96px 안 씀 · 표·차트 규칙은 이 프로젝트에서 따로 정함 (DESIGN.md 에 거래 화면 없음). 상승·하락 색은 한국식: 상승 빨강 · 하락 파랑 · 강조색은 틸 (coinbase 파랑 #0052ff 는 하락 파랑과 겹쳐 안 씀) — 사용자 결정 10/28. 기획: `docs/plans/ui-ux-optimization/2026-10-28-information-architecture.md`.
