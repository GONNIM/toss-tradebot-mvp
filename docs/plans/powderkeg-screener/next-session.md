# Phase 7 화약고 스크리너 · 다음 세션 재개 가이드

**작성일**: 2026-07-22 · **개정 2026-07-23** (v1.43 세션 종료 시점)
**대상**: 다음 세션 재개 시 · Claude 및 사용자
**현 라이브**: **v1.43 · `1e37134`** (7개 배포 · P4-1 + P4-6 + P4-5 + P2-1 + P2-2 + P2-1b 완결)

---

## 0. 즉시 확인 (재개 30초)

```bash
# 1. 라이브 SHA 확증
curl -sS https://optimus8.cafe24.com/powderkeg | grep -oE 'build [a-f0-9]{7}'
# 기대: build 1e37134 (or 이후 커밋)

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

### ✅ 완결 · 배포 완료 (2026-07-22~23 세션)
- **P4-1** provenance UI + Run diff (v1.38 · `3f7edb2`) · `p4-1-provenance-run-diff.md`
- **P4-6** 발굴 조건 분리 표기 (v1.38 동시)
- **P4-5** KRX 관리종목 실데이터 (v1.39 · `49d0922`) · `p4-5-krx-admin-issue.md`
- **P2-1** 상폐 재무 백필 (v1.40 · `6b22962`) · `p2-1-delisted-financials-backfill.md` · **322 rows / 185 tickers 실측 완결**
- **P2-2** PIT 층화 백테스트 (v1.41 · `3c62d20`) + `/backtest/stratified` 라우트 (v1.42 · `8314688`) · `p2-2-pit-stratified-backtest.md`
- **P2-1b** 활성 종목 재무 백필 (v1.43 · `1e37134`) · **+4,232 rows (2020-2022 재무 확충)**

### ⚠️ 주요 발견 (다음 세션 참고 필수)
- **PIT 재실측 결과 pit_passed=0** (A3·B3 이벤트) — 시스템 무결이나 **화약고 6조건 자체가 매우 tight** · 이벤트 발생 종목 대부분이 화약고 아님 → **화약고 가설 재검토 필요** (Phase 2 성격 · 별건 논의)
- 백필 후 흐름 변화: A3 excluded_no_financial 72%→19% · excluded_failed_pit 28%→81% · 재무 확보는 정상 · 6조건 판정에서 탈락
- Tier 1 lock 11 종목 유지 · KRX 실데이터로도 c10=True 확증 (감사 근사 판정 정확도 100%)

### 🥇 남은 우선순위 (다음 세션)

**우선순위 1 · 화약고 가설 재검토 (신설 · P2-2 결과 근거)**
- 6조건 relax 실측 (F-Score 4+·owner 30%+ grid search) · 3~4h
- 또는 이벤트 시점 조건 완화 · 화약고 정의 자체를 이벤트 반응 종목 관찰로 역설계

**우선순위 2 · v2 인증 아키텍처** (task #20~#23) · 12~14h Phase 1 MVP
- localStorage → httpOnly 쿠키
- JWT + 24h 만료 · pyjwt 이미 설치 (신규 라이브러리 불요)
- role-based access · sniper_api_access 감사 테이블
- Grace period 2~4주 · 하위 호환

**우선순위 3 · Phase 2 완전 PIT** · 3~6개월 대기 (자연 축적)
- KrxMarketSnapshot 매일 append 스케줄러 (현재 2일치만) · 3~4h
- PowderKegKrxIssue 매일 append (P4-5 스케줄러화) · 이미 크롤링 API 있음
- 축적 완료 후 pit_evaluate에서 시장·관리 조건도 as-of 평가

**우선순위 4 · 소소한 개선**
- git_sha env 주입 (PowderKegRun.git_sha=null 해소) · 30분
- Tier 2 near 39 종목 개별 분석 (계획서 20 → 실측 39) · 2~3h
- P4-2b 조건 ④ 정의 재검토 (상호출자제한 vs 공시대상 세분화)
- P2-3b dart_financials CFS/OFS fallback

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

**Option A**: 화약고 가설 재검토 · 6조건 relax grid search (3~4h · PIT 결과 후속)
**Option B**: v2 인증 Phase 1 MVP (12~14h · 보안 심화 · pyjwt 준비 완료)
**Option C**: Phase 2 완전 PIT 준비 · 시장·관리 데이터 매일 append 스케줄러 (3~4h + 3개월 대기)
**Option D**: Tier 2 near **39** 종목 개별 분석 (2~3h · 관찰 후보 확대)
**Option E**: 사용자 판단 · Tier 1 관찰 지속 · 다음 요청 대기

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
| 2026-07-22 | v1.0 | 신규 · 다음 세션 재개 가이드 · 백로그 우선순위 · 자주 쓴 명령·문서 인덱스·Tier 1 노트 | f32624d |
| 2026-07-23 | v2.0 | 7개 배포 완결 반영 (v1.38~v1.43) · P4-1/P4-6/P4-5/P2-1/P2-2/P2-1b 완료 표시 · 화약고 가설 재검토 신규 우선순위 1 · 남은 백로그 재정렬 | (pending) |
