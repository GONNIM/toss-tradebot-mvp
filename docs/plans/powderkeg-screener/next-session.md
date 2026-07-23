# Phase 7 화약고 스크리너 · 다음 세션 재개 가이드

**작성일**: 2026-07-22 (세션 종료 시점)
**대상**: 다음 세션 재개 시 · Claude 및 사용자
**현 라이브**: v1.37 · `6ac02fb`

---

## 0. 즉시 확인 (재개 30초)

```bash
# 1. 라이브 SHA 확증
curl -sS https://optimus8.cafe24.com/powderkeg | grep -oE 'build [a-f0-9]{7}'
# 기대: build 6ac02fb

# 2. 서버 상태
ssh root@optimus8.cafe24.com "systemctl is-active tradebot-api tradebot-cron"

# 3. Tier 1 종목 확증 (11개 · locked)
curl -sS "https://optimus8.cafe24.com/api/v1/powderkeg/list?limit=50" | \
  python3 -c "import sys,json,collections; d=json.load(sys.stdin); t1=[i for i in d['items'] if i.get('tier')=='tier_1_passed']; print(f'Tier 1: {len(t1)}');[print(f\"  {i['ticker']} {i.get('name')}\") for i in t1]"
```

---

## 1. 현 상태 (Where We Are)

### 완결된 것 (세션 커밋 24개)
- **P0** 배포 갭 종결 (SHA 인라인·캐시 하향) — `5fadff6`
- **P1** 실체 결함 정정 (티어 3상태·screener None·태광 재판정) — `b562ded` ~ `fcc55c4`
- **P2** 재무·조정식·hotfix (컬럼·수집·조정식·차입금 매핑·계약부채 3층 판별) — `6314ec0` ~ `3b90573`
- **P2 백필** (재무 386→2,406 · 최대주주 122→2,406 · 다년재무·감사·adv60) — 11+5+multi 배치
- **P4** 4차 리뷰 대응 (big_biz seed·금융업 배제·가드레일 ①②B④·hotfix) — `b64b0e4` ~ `0a34fbf`
- **P5** 자동 분석 노트 + 종목 상세 팝업 — `9171b1a`
- **UX** 정체성 문서 + 가이드 접기 + 4단계 플로차트 + 컬럼 폭 — `6ac02fb`
- **Tier 1 관찰**: 11 종목 lock (세원물산·경동도시가스·오리콤·경인전자·SNT홀딩스·SJM·신라교역·비츠로테크·경동인베스트·삼양케이씨아이·넵튠)

### 데이터 무결성
- total_debt 파싱 100% 매칭
- 잘못된 tier_1 승격 0건
- 파싱·매핑 hotfix 5회 (P2-4b·d·e + P4-3 hotfix + `_compute_tier` hotfix)

---

## 2. 남은 백로그 (Priority 순)

### 🥇 우선순위 1 · UX·기능 후속 (사용자 관점 즉시 체감)
- ~~**[P4-1] 서희 provenance UI + Run diff 로그** (task #30)~~ ✅ **로컬 완료 (2026-07-22)** · 배포 대기
  - Backend: `PowderKegRun` + `PowderKegRunDiff` 모델, screener 훅, 3종 API (`/ticker/{ticker}/provenance`, `/run-diff/latest`, `/run-diff/summary`)
  - Frontend: 리스트 "🆕 변동/⇄ 티어이동" 뱃지, 상단 요약 카드, 상세 팝업 "🔄 변동 이력 + Provenance" 섹션
  - Tests: 신규 9건 + 회귀 22건 pass · 계획서 `docs/plans/powderkeg-screener/p4-1-provenance-run-diff.md`
- ~~**[P4-6] 조건 ① 발굴 조건 별도 표기** (task #35)~~ ✅ **로컬 완료 (2026-07-22)** · 배포 대기
  - `DISCOVERY_CONDITIONS = {"1_pbr"}` 상수 · 퍼널 카드 발굴/정보량 2그룹 분리 · 상세 팝업 발굴 조건 회색톤 + "🔎 · 발굴" 태그

### 🥈 우선순위 2 · 실데이터화 (Type B 방어선 강화)
- ~~**[P4-5] 조건 ⑩ KRX 관리종목 실데이터 (대안 A)** (task #34)~~ ✅ **로컬 완료 (2026-07-23)** · 배포 대기
  - data.krx.co.kr JSON API가 2026 로그인 봉쇄 → **KIND 3-엔드포인트 조합** (adminissue.do + tradinghaltissue.do + corpList.do) 채택
  - 신규 collector `krx_admin_issue.py` · admin 93.7% · halt 98.4% 매칭 실측 (미매칭은 ETF/우선주 · 스크리너 대상 아님)
  - 신규 모델 `PowderKegKrxIssue` (append-only 스냅샷)
  - 신규 API `POST /collectors/krx-admin-refresh`
  - screener 조건 ⑩ 감사 근사 → 실 데이터 (스냅샷 미수집 시 c10=None 3상태 유지)
  - Tests: 신규 12건 + 회귀 8건 pass · 계획서 `docs/plans/powderkeg-screener/p4-5-krx-admin-issue.md`

### 🥉 우선순위 3 · 파이프라인 심화 (v2 성격)
- **[P2-1] 상폐 재무 백필** ✅ **로컬 완료 (2026-07-23)** · 배포 대기
  - 원 계획(DartCorpCodeMap stock_code IS NULL) 실측 파괴 → KIND `delcompany.do` 크롤링 채택
  - 5년 실측: 전체 393건 · Powderkeg 대상 311건 · 이관성 제외 후 236건
  - 신규 collector `krx_delisted.py` · 재무 수집기 확장 · 배치 API + Progress 재개
  - Tests: 신규 6건 + 회귀 48 pass · 계획서 `docs/plans/powderkeg-screener/p2-1-delisted-financials-backfill.md`
  - 예상 백필 시간: 반나절 이내 (원 2~3일에서 KIND 실측으로 단축)
- **[P2-2] PIT 층화 백테스트 재설계** (task #17) · P2-1 백필 완료 후 착수
  - `backtest.py:run_stratified_backtest` · as-of 재무 조회 · 이벤트 시점 10조건 재평가
  - 뼈대 완성 (Phase 7-4) · as-of 함수만 추가 필요
  - 소요: 5~7시간 (P2-1 백필 후)
- **[v2 인증 아키텍처]** (task #20~#23)
  - localStorage → httpOnly 쿠키
  - JWT + 24h 만료 + refresh + jti blacklist
  - role-based access · sniper_api_access 감사 테이블
  - 총 소요: 12~16시간 (4 서브태스크)

### 후속 세션 신규 검토 항목
- **자동 재평가 옵션 A** (일 1회 · 현재 리스트 종목만 · identity.md §6 참조)
  - 사용자 재검토 후 결정
- **Tier 2 near 20 종목 개별 분석**
- **P4-2b 조건 ④ 정의 재검토** (상호출자제한 vs 공시대상 세분화)
- **P2-3b dart_financials CFS/OFS fallback** (서희 계약부채 별도 확인)

---

## 3. 재개 시 즉시 사용할 스킬·명령

### 관련 파일 (Quick Reference)
| 목적 | 경로 |
|---|---|
| 배포 스킬 | `.claude/skills/deploy-optimus8/SKILL.md` |
| 정체성 · 자동 vs 수동 | `docs/plans/powderkeg-screener/identity.md` |
| 3차 리뷰 대응 (v1.8 · 15섹션) | `docs/plans/powderkeg-screener/3rd-review-response.md` |
| 4차 리뷰 대응 (v1.0) | `docs/plans/powderkeg-screener/4th-review-response.md` |
| 첫 승격 결과 (v2 경인전자) | `docs/plans/powderkeg-screener/first-passed-result.md` |
| **본 문서** · 재개 가이드 | `docs/plans/powderkeg-screener/next-session.md` |

### 자주 쓴 명령
```bash
# 스크리너 재평가 (수동 트리거 · 사용자 판단 시)
ssh root@optimus8.cafe24.com bash -c '
TOKEN=$(grep ^SNIPER_API_TOKEN= /root/toss-tradebot-mvp/backend/.env | cut -d= -f2- | tr -d "\"'"'"'")
curl -sS -X POST http://127.0.0.1:8000/api/v1/powderkeg/screener/run \
  -H "X-API-Token: $TOKEN" -H "Content-Type: application/json" \
  -d "{\"tickers\":[\"024830\"],\"year\":2026}"
'

# 리스트 tier 확증
curl -sS "https://optimus8.cafe24.com/api/v1/powderkeg/list?limit=50"

# 종목 상세 (팝업 API)
curl -sS "https://optimus8.cafe24.com/api/v1/powderkeg/ticker/024830/detail"
```

### 로컬 dev server (라이브 API 프록시)
```bash
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/frontend && \
  NEXT_PUBLIC_API_BASE_URL=https://optimus8.cafe24.com npm run dev -- --port 4000
# → http://localhost:4000/powderkeg
```

---

## 4. 진행 원칙 (반복 방지)

### 지시서 원칙 · 지속 준수
- "hypothesis 유지 · **자동매매 절대 연결 금지**" (CLAUDE.md)
- 예측 없음 · 사용자 판단 근거 제공만
- 스크리너 자동 재평가 없음 (설계) · 이벤트만 자동 감지

### 세션 관리
- SSH 감시 background는 SSH timeout(exit 255) 흔함 · 서버 nohup은 무관
- 완료 확인은 다시 SSH tail로 · 로컬 timeout 무시
- 토큰 노출: `ps -o cmd` 대신 `ps -o pid,etime` 사용
- 대화 로그·shell history에 절대 노출 X (§1.3 절차)

### 커밋 후 배포
- push → GitHub Actions 자동 (deploy.yml · paths-ignore: docs/**)
- 문서만 커밋은 배포 skip (정상)
- 배포 감시: `gh run watch $(gh run list --workflow=deploy.yml --limit=1 --json databaseId --jq '.[0].databaseId')`

### 검증 3중
- SSR 마커 → **커밋 해시 SSR 푸터**로 대체 (P0 완결)
- API 응답 → curl + Python 파싱
- DB → sqlite3 직접 확증

---

## 5. Tier 1 종목 관찰 노트 (11 종목)

| 티커 | 종목 | net_cash | pbr | owner | robustness |
|---|---|---|---|---|---|
| 024830 | **세원물산** ⭐ | 245.8% | 0.192 | 78.4% | at_risk |
| 267290 | 경동도시가스 | 174.8% | 0.259 | 51.6% | at_risk |
| 010470 | 오리콤 | 155.6% | 0.462 | 64.8% | at_risk |
| 009140 | 경인전자 | 136.7% | 0.432 | 49.6% | at_risk |
| 036530 | SNT홀딩스 | 103.4% | 0.397 | 64.1% | at_risk |
| 123700 | SJM | — | — | — | (확인 필요) |
| 004970 | 신라교역 | — | — | — | (확인 필요) |
| 042370 | 비츠로테크 | — | — | — | (확인 필요) |
| 012320 | 경동인베스트 | — | — | — | (확인 필요) |
| 036670 | 삼양케이씨아이 | — | — | — | (확인 필요) |
| 217270 | 넵튠 | — | — | — | (확인 필요) |

**모두 locked=True + added_by=user** · 사용자가 이전에 수동 추가하고 최근 재평가에서 Tier 1 판정.

**공통 특성**: F-Score 6/9 턱걸이 · robustness at_risk · Type A 이벤트 대기 상태

---

## 6. 다음 세션 시작 시 첫 지시 제안

**Option A**: 우선순위 1 진행 · 서희 provenance UI (5~6시간)
**Option B**: 우선순위 2 · KRX 관리종목 크롤링 (3~4시간)
**Option C**: Tier 2 near 20 종목 개별 분석 (2~3시간 · 관찰 후보 확대)
**Option D**: Tier 1 11 종목 상세 검증 · 6개 미검증 종목 실측 (2시간)
**Option E**: 사용자 판단 · 목록 확인 후 결정

---

## 7. 문서 인덱스 (재개 시 참조 순서)

1. **본 문서** → 전체 맥락 재확인
2. `identity.md` → 자동 vs 수동 범위 · 오해 없이 진행
3. `first-passed-result.md` → Tier 1 승격 종목 상세
4. `4th-review-response.md` → 최근 리뷰 대응 이력
5. `3rd-review-response.md` → 파싱·hotfix 이력
6. `phase7-final-report.md` → 원 완결 보고서 (전 히스토리)
7. `phase7-powderkeg-screener.md` → 원 지시서

---

## 8. 개정 이력

| 날짜 | 버전 | 변경 | 커밋 |
|---|---|---|---|
| 2026-07-22 | v1.0 | 신규 · 다음 세션 재개 가이드 · 백로그 우선순위 · 자주 쓴 명령·문서 인덱스·Tier 1 노트 | (pending) |
