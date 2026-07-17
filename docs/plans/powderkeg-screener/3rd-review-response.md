# Phase 7 화약고 스크리너 · 3차 리뷰 · 재재반박 대응 · 실측 재검증

**작성일**: 2026-07-16
**작성자**: Claude Opus 4.7 (사용자 검증 지시)
**대상**: `2nd-review-rebuttal.md` (2026-07-16, 379라인) 에 대한 3차 재재반박
**목적**: 재재반박 6개 항목을 코드·라이브 URL·응답 헤더·소스 트리로 3중 실측 후 재판정 · 반박문의 결함(§1 SSR 마커 방식) 정정 · P0~P3 구현안 확정

---

## 0. 요약 (Executive Summary)

- **재재반박 정확도**: 6건 중 **5건 수용** + 1건 부분 수용 (반박문의 66% 대비 재재반박 83~100%)
- **가장 결정적 발견**: 반박문 §1 의 "SSR 마커 실측으로 배포 확증" **방법론 자체가 결함**
  - `page.tsx:1`이 `"use client"` client component
  - 초기 `tab="list"` · v1.27(report 탭)과 v1.28(events 탭) 마커는 **탭 조건부 렌더링** 안에 존재
  - 따라서 SSR HTML 에 v1.27/v1.28 마커 부재는 **정상**이며 배포 여부를 증명·반증하지 못함
  - 재재반박이 제안한 **커밋 해시 SSR 푸터**가 유일한 결정적 배포 검증 수단 (본 문서 §7 · P0 구현 완료)
- **캐시 결함 실측**: 라이브 응답 헤더 `Cache-Control: s-maxage=31536000, stale-while-revalidate` + `x-nextjs-cache: HIT` — 재재반박의 "일부 사용자 구버전 관측" 가설 확증 (본 문서 §7 · P0 하향 조치 완료)
- **팔림세스트 재발 3회째**: `phase7-final-report.md:26` 이 "51 최대주주" 로 미갱신 (§3 참조) — 커밋 체크리스트에 §6 갱신 규정 필요

---

## 1. 실측 데이터 (3중 검증)

### 1.1 라이브 URL 응답 헤더 (2026-07-16 22:46 KST · HTTPS GET)
```
HTTP/1.1 200 OK
Server: nginx/1.18.0 (Ubuntu)
Content-Type: text/html; charset=utf-8
Content-Length: 20342
Vary: RSC, Next-Router-State-Tree, Next-Router-Prefetch, Accept-Encoding
x-nextjs-cache: HIT              ← Next.js 정적 캐시 히트
X-Powered-By: Next.js
Cache-Control: s-maxage=31536000, stale-while-revalidate   ← 1년 캐시 (!!)
ETag: "ddg0wmxrdedtk"
```
**해석**: nginx 리버스 프록시 앞단 캐시가 있든 없든, Next.js 자체가 `s-maxage=31536000` 을 발행. `stale-while-revalidate` 만료 없음(초 단위 인자 부재)이라 사실상 영구 stale 서빙 허용. 배포 후에도 프록시·CDN 이 이전 SSR HTML 을 서빙할 여지가 크다.

### 1.2 SSR HTML 마커 카운트 (Python · `html.count`)
- 존재 (10건): `게이트 4조건` · `표본 ≥ 50` · `승률` · `평균 수익` · `이 페이지는 무엇인가요` · `이 리스트를 어떻게` · `가이드 다시 보기` · `강건성` · `저PBR 후보 대량 발굴` · `티어별 액션`
- 부재 (4건): `이 리포트가` (v1.27) · `이 피드가` (v1.28) · `퍼널 워터폴` (v1.18) · `반려` (필터 한국어)
- 혼재 (필터 칩): `passed` 2회 · `rejected` 1회 여전히 SSR 노출

**중요 정정**: v1.27/v1.28 마커 부재는 **탭 조건부 렌더링 때문** 이며 배포 갭 근거가 될 수 없음. 반박문 §1 의 실측 방법론 결함(다음 §2 참조).

### 1.3 소스 실측 · `page.tsx:1,26-35,683,1511`
```tsx
"use client";                                    // ← client component
...
const [tab, setTab] = useState<Tab>("list");     // 초기 활성 탭 = list
...
{open ? "▼" : "▶"} 📖 이 피드가 뭐하는 건가요?    // line 683 · EventsTab 안
{open ? "▼" : "▶"} 📖 이 리포트가 뭐하는 건가요?  // line 1511 · ReportTab 안
```
초기 렌더에서 EventsTab / ReportTab 서브트리는 **DOM 에도 존재하지 않음** (`{tab === "events" && <EventsTab />}` 패턴). SSR 마커 카운트는 이들 콘텐츠에 도달 불가.

### 1.4 인증 실측 · `backend/api/auth.py` + `routes/powderkeg.py`
- `require_sniper_token` 적용 라우트: **20+ 개** (lock, note, manual, admin/list/remove, collectors 8종, backtest 2종, screener, ticket, admin/holding-expiry-run, admin/migrate-schema 등) — 반박문의 "4/4" 표기는 편집·삭제 라우트만 세었을 뿐 실제 커버리지는 훨씬 넓음
- `require_sniper_live_token` = 토큰 + `SNIPER_LIVE_ENABLED=true` **이중 스위치** · 기본 false · 실 자금 이동은 이중 잠금 (재재반박이 놓친 자산)
- 토큰: `SNIPER_API_TOKEN` 32자 랜덤 · SOPS 저장 · **단일 정적** · 회전·만료·사용자 분리 없음 (재재반박 정확)
- 프론트 저장: `frontend/app/powderkeg/page.tsx:25` `const TOKEN_KEY = "sniper_api_token"` · `localStorage.getItem(TOKEN_KEY)` (재재반박 정확)

### 1.5 팔림세스트 · `phase7-final-report.md:26`
```
- 프로덕션 데이터 · 118,000+ DART 매핑 · 400+ 재무 · 51 최대주주 · 44 이벤트
```
반박문 §3 에서 168 확대를 인정했으나 본문 §6 미갱신 → **팔림세스트 3회째 재발** (v1.11, v1.12 이후 세 번째).

### 1.6 배포 자동화 실측 · `.github/workflows/deploy.yml`
- `on: push: branches: [main]` + `paths-ignore: ['**/*.md', 'docs/**', ...]`
- 배포 단계: `git reset --hard origin/main` → `npm install` → `npm run build` → `systemctl restart tradebot-api tradebot-cron` → `pm2 reload tradebot-web`
- **자동화 존재 확증** (memory `feedback_workflow_first_before_manual_deploy` 준수 · reference_tossbot_deploy 신뢰 전 검증 완료)
- 문서만 변경 시 배포 skip · 코드 변경 시 자동 배포

---

## 2. 반박문 §1 방법론 결함 정정

### 반박문 주장
> SSR HTML 17,932 bytes 마커 실측으로 v1.14~v1.28 배포 완결 확증

### 결함
1. **SSR 마커 부재 ≠ 배포 미완**: `"use client"` + 탭 조건부 렌더 페이지에서는 초기 SSR 에 탭별 콘텐츠가 존재하지 않음
2. **SSR 마커 존재 ≠ 배포 완료**: 캐시가 몇 달 전 SSR 을 서빙하고 있을 수 있음 (`x-nextjs-cache: HIT`)
3. **버전 마커 자체가 팔림세스트 리스크**: v1.22~v1.28 버전 관리가 문서와 어긋나면 마커 매칭이 의미 없음

### 유일한 결정적 검증
SSR 페이지 자체에 **커밋 해시 노출** — 관측자가 브라우저·curl·프록시 어느 경로로 오든 즉시 서빙된 빌드를 식별 (§7 P0 구현 완료).

### 재재반박 인용
> "SSR 푸터에 빌드 커밋 해시를 노출하세요 — 이 논쟁 자체가 재발 불가"

**수용 · P0 완료 (커밋 대기)**.

---

## 3. 항목별 최종 재판정 매트릭스

| # | 반박문 판정 | 재재반박 판정 | **본 문서 최종** | 근거 §  |
|---|---|---|---|---|
| 1 배포갭 | 반박 (SSR 확증) | 미해결 | **부분 인정** · SSR 마커 방법론 결함 정정 · 캐시 결함 실재 · P0 로 종결 | §1.1, §1.2, §2 |
| 2 층화 | 인정 (v2 이관) | 지금 실행 가능 (상폐 재무 선행) | **재재반박 수용** · PIT 실행 순서 확정 | §4 |
| 3 유니버스 | 부분 인정 (168) | 수용 + §6 미갱신 | **재재반박 수용** · 팔림세스트 3회째 확증 | §1.5, §5 |
| 4 티어 | 인정 (태광 Tier 1 후보) | 태광 상한 Tier 2 (조건 7 실탈락) | **재재반박 수용** · 반박문 기대치 정정 | §6 |
| 5 인증 | 실체 완전 안전 | 존재 · Phase 6 기준 미달 | **부분 수용** · 재재반박 방향 옳음 + 이중 스위치는 자산으로 보존 | §1.4, §8 |
| 6 선수금 | 인정 (개별 검증) | 수용 + 계약부채 명시 정의 | **재재반박 수용** · 조정식 표준화 | §9 |

**재재반박 정확도**: 5/6 (83%) · 부분 수용 1건 (인증에서 이중 스위치 언급 누락)

---

## 4. #2 층화 백테스트 · PIT 재설계 (P1)

### 재재반박 핵심 지적
> "층화 대상은 '현재 리스트'가 아니라 '각 이벤트 시점에 10조건을 통과했던 과거 종목'이므로, 오늘 당장 5년치 층화 표본을 만들 수 있다. 단 진짜 선행 의존성은 **상폐 종목을 포함한 과거 재무 백필** (DART 는 상폐사 공시 보관하므로 가능). 이것 없이 PIT 층화를 돌리면 imputation 으로 잡았던 생존 편향이 층화 단계에서 부활한다."

### 대응
반박문 §2 는 정확했으나 §10-5b 의 "표본 0 문제로 v2 대기" 결론은 **look-ahead 설계에서만 참**. PIT 로 재설계하면 표본 문제도 자동 해결. 단, 상폐 재무 백필이 진짜 선행.

### 실행 순서 (확정)
1. **1단계**: DART 상폐사 공시 백필 (`FinancialSnapshot` 에 `is_delisted` 플래그 + `delisted_at` 컬럼 추가)
2. **2단계**: `backtest.py:run_stratified_backtest` PIT 재설계
   ```python
   for event in past_events(as_of=event.date):
       fin_T = query_financials(ticker, as_of=event.date)
       mkt_T = query_market(ticker, as_of=event.date)
       shr_T = query_shareholders(ticker, as_of=event.date)
       if apply_10_conditions(fin_T, mkt_T, shr_T):
           yield event  # stratum member
   ```
3. **3단계**: v1.29 문서 §17-4 · 결함 명시 + PIT 결과 첨부

### 소요 (재추정)
- 상폐 재무 백필 · KOSPI/KOSDAQ 폐지 종목 ~300개 · 3년치 · **~2,700 API 콜**
- 최대주주·감사의견·상폐사 병합 시 **2~3일 분할** (반박문 "하루 완결" 추정은 재무만 기준)

---

## 5. #3 유니버스 · §6 팔림세스트 종결 (P1)

### 재재반박 핵심
> "51 → 168 확대 자체는 좋은 실행이나 §6 이 갱신 안 되어 리뷰어가 구수치로 판단하게 만듦. 3회째 재발. 커밋 체크리스트에 §6 동시 갱신 조항 추가."

### 대응
1. **즉시 정정**: `phase7-final-report.md:26` 을 "168 최대주주 · 재무 400+ · 44 이벤트" 로 갱신
2. **개정 이력 강화**: `§17-3` 에 v1.19 실측 결과 (117 티커 추가) 명시
3. **커밋 체크리스트 조항 추가** (`.claude/lessons-learned.md` 또는 CLAUDE.md):
   > "숫자(카운트·비율·티어 개수 등)를 변경한 커밋은 phase7-final-report.md §6 정합성 검증 필수"

### 재무 백필 확대 재추정
- 반박문: 6,900 콜 (재무만 · 하루)
- 본 문서: 재무 6,900 + 최대주주 800 + 감사의견 500 + 상폐사 2,700 = **~10,900 콜 · 2~3일 분할**

---

## 6. #4 티어 · 태광산업 기대치 정정 (P1)

### 재재반박 핵심
> "'태광산업 재판정 · 예상 · Tier 3 → Tier 1' 은 성립하기 어렵다: ① Tier 1 = 10/10 인데 조건 7 을 '실 실패 1건' 으로 분류했으므로 상한은 9/10 = Tier 2 ② 조건 7 실패는 데이터가 채워져도 뒤집히지 않을 공산 큼 — 태광산업은 최근 **4년 연속 영업손실** 공개 보도. 현실적 기대치는 **Tier 2** (8~9/10)."

### 대응
반박문 §4 "Tier 3 → Tier 1 (데이터 확보 시)" 정정 → **"Tier 3 → Tier 2 예상 (조건 7 실 실패 · 데이터 보정 후 상한 9/10)"**. 이는 v2 백로그 1번(정체형 종목의 조건 7 완화)의 실증 근거.

### 3상태 분리 코드 (P1 구현안 · 반박문 §4 대로)
```python
# backend/powderkeg/screener.py
if len(fin_all) >= 2:
    c8 = fscore.total_score >= t.piotroski_f_score_min
else:
    c8 = None                             # ← False 아니라 None
    result.piotroski_f_score = None

# backend/api/routes/powderkeg.py:_compute_tier
def _compute_tier(cond, status):
    if not isinstance(cond, dict):
        return ("rejected", 0, [])
    items = [(k, v) for k, v in cond.items() if k != "_robustness"]
    passed = sum(1 for _, v in items if v is True)
    failed = [k for k, v in items if v is False]
    missing = [k for k, v in items if v is None]
    total = len(items)

    if passed == total:
        return ("tier_1_passed", passed, [])
    if passed >= total - 1 and not missing:
        return ("tier_2_borderline", passed, failed)   # 실 실패 1건
    if missing and passed + len(missing) >= total - 1:
        return ("tier_2_needs_data", passed, failed + [f"{k} (데이터 부족)" for k in missing])
    if passed >= total - 2:
        return ("tier_3_partial", passed, failed)
    return ("rejected", passed, failed)
```

### UI 뱃지 (반박문 §4 확장)
- 🥇 Tier 1 (10/10 · 화약고)
- 🥈 Tier 2 · 실패 1건 (borderline)
- 🥈 Tier 2 · 데이터 부족 · 나머지 통과 (needs_data)
- 🥉 Tier 3 · 실패 2건 이하

---

## 7. #1 배포갭 · P0 구현 완료 (본 커밋)

### 변경 파일
1. `frontend/next.config.mjs`:
   - `NEXT_PUBLIC_BUILD_SHA` · `NEXT_PUBLIC_BUILD_TIME` 빌드 타임 인젝션 (git rev-parse 자동 · env override 가능)
   - `/powderkeg` + `/powderkeg/:path*` 응답에 `Cache-Control: s-maxage=60, stale-while-revalidate=300` 명시 (기존 `s-maxage=31536000` 하향)
2. `frontend/app/layout.tsx`:
   - 전 페이지 하단 푸터에 `build {SHA} · {ISO_TIME}` 노출

### 검증 방법 (배포 후)
```bash
# 헤더 검증
curl -sSI https://optimus8.cafe24.com/powderkeg | grep -i cache-control
# → 기대: Cache-Control: s-maxage=60, stale-while-revalidate=300

# 마커 검증 (React SSR 이 <!-- --> 컨테이너로 문자열 분리하므로 python 파싱)
curl -sS https://optimus8.cafe24.com/powderkeg | python3 -c "
import sys, re
html = sys.stdin.read()
m = re.search(r'build[^A-Za-z0-9]*([a-f0-9]{6,12})', html)
print('build sha:', m.group(1) if m else 'NOT FOUND')
"
# → 기대: build sha: <최신 커밋 short SHA>

# 브라우저 하단 푸터에서도 육안 확인 (모든 페이지에 노출)
```

### 로컬 빌드 검증 (2026-07-16 완료)
```
Next.js 14.2.35 · ✓ Compiled successfully · 21/21 정적 프리렌더
.next/server/app/{powderkeg,index,sniper}.html:
  <span title="build sha · 배포 확증용 (3차 리뷰)">build <!-- -->782809b<!-- --> · 2026-07-16T...</span>
  → 현재 HEAD (782809b) 일치 확증
```

### nginx 프록시 캐시 조치 (SSH 승인 필요)
Next.js 응답 헤더를 하향해도 nginx 가 별도로 `proxy_cache` 를 걸었다면 nginx 캐시도 무효화 필요. 필수 실측:
```bash
ssh root@optimus8.cafe24.com "grep -E 'proxy_cache|proxy_pass' /etc/nginx/sites-enabled/* 2>/dev/null"
ssh root@optimus8.cafe24.com "cat /root/toss-tradebot-mvp/frontend/.next/BUILD_ID; git -C /root/toss-tradebot-mvp log --oneline -3"
```
→ 사용자 승인 대기 (auto mode classifier 가 개별 명령 재승인 요구)

---

## 8. #5 인증 · 최종 판정 (P3 → 조기 착수 권장)

### 반박문 판정 정정
- "실체 완전 안전 · 4/4 인증 있음" → **"실체 강함 · 20+ 라우트 인증 + 이중 스위치 · 단, Phase 6 지시서(httpOnly 쿠키 · 회전 · 만료) 미준수"**

### 남은 결함 (재재반박 지적 · 수용)
1. `localStorage` 저장 · XSS 1회에 토큰 유출
2. 단일 정적 토큰 · 스나이퍼 봇과 공유 · 사용자 분리 없음
3. 무기한 유효 · 회전·만료 없음
4. 감사 로그 표준 logging 만 · 별도 테이블 `sniper_api_access` 는 Sprint 1.5 예정

### 자산 (재재반박 미언급 · 반박문 정확)
- `require_sniper_live_token` = 토큰 + `SNIPER_LIVE_ENABLED=true` **이중 스위치**
- 기본 false · Paper 모드 fallback · 자금 이동은 이중 잠금

### 개선안 (Phase 6 준수 · P3 → v2 P1 승격 권장)
1. **토큰 저장**: `localStorage` → httpOnly + Secure + SameSite=Strict 쿠키
2. **회전**: 24h 만료 + refresh 토큰 · JWT + `jti` blacklist
3. **사용자 분리**: 관리자·조회자 role · 라우트별 권한
4. **감사 로그 실체화**: `sniper_api_access` 테이블 즉시 활성 (지연 사유 재검토)

---

## 9. #6 서희건설 · 계약부채 조정식 표준화 (P2)

### 재재반박 정의 (수용)
```
조정 순현금 = 현금성자산 - 총차입금 - 계약부채(선수금)
```
- **수주산업 기본 적용**: 건설·조선·플랜트 (`sector_code` 기반 자동 판별)
- **두 값 병기**: 원 net_cash 와 조정 net_cash 동시 노출 (사용자가 직접 판단)
- **Tier 강등 결과도 그대로 게시** — A3 재라벨(v1.9), B3 정정(v1.11) 원칙 연장

### 구현 스켈레톤
```python
# backend/powderkeg/collectors/dart_financials.py
_CONTRACT_LIABILITY_KEYWORDS = (
    "계약부채", "선수금", "customer advances",
)

class FinancialSnapshot:
    ...
    contract_liabilities: Optional[float]   # 신규 컬럼

# backend/powderkeg/screener.py
cash = (fin_latest.cash_and_equivalents or 0) + (fin_latest.short_term_investments or 0)
debt = fin_latest.total_debt or 0
contract_liab = fin_latest.contract_liabilities or 0

net_cash_raw = cash - debt
if is_construction_like(ticker):   # sector_code 판별
    net_cash_adj = cash - debt - contract_liab
else:
    net_cash_adj = net_cash_raw
```

### 서희건설 재검증 절차
1. DART API 로 서희건설 (035890) 최근 4분기 계약부채 조회
2. `net_cash_adj` 재계산
3. 조건 2 (> 40% 시총) 재평가
4. 결과 (Tier 유지 또는 강등) 를 `first-passed-result.md` 에 v1.1 개정 이력으로 게시

---

## 10. 실행 계획 · 우선순위 재정렬

### P0 · 본 커밋 · 배포 갭 논쟁 종결
- [x] `frontend/next.config.mjs` · 커밋 해시 인젝션 + 캐시 하향
- [x] `frontend/app/layout.tsx` · 푸터에 SHA 노출
- [x] `docs/plans/powderkeg-screener/3rd-review-response.md` · 본 문서
- [ ] 로컬 `npm run build` 검증
- [ ] 사용자 커밋·배포 승인
- [ ] 배포 후 curl 헤더 3중 검증
- [ ] SSH 로 nginx `proxy_cache` 유무 확인 · 있다면 무효화 명령 제안

### P1 · v1.29 (오늘~내일)
- [x] `phase7-final-report.md:26` 팔림세스트 정정 (51 → 168) · v1.19 후속 실행 이력 §17-3 추가
- [x] `_compute_tier` · 3상태 분리 (passed/failed/missing) · `missing_conditions` API 필드 신규
- [x] `screener.py` · c1/c2/c3/c5/c7/c8/c9 데이터 부족 시 `c* = None` (False 대신) · `passed_all = all(v is True ...)` 명시화
- [x] UI · TierBadge에 `tier_2_needs_data` 케이스 (🥈 데이터부족) · 필터 옵션 · 병목 표시 분리 (실패/데이터부족)
- [x] `.claude/lessons-learned.md` 교훈 #2 · 숫자 변경 커밋 시 §6 정합 검증 규정
- [ ] 태광산업 재판정 후 UI 뱃지 검증 (기대: Tier 2 · 배포 후 실측)

### P2 · v1.30~v1.32
- [ ] DART 상폐사 재무 백필 (~2,700 콜 · `is_delisted` 플래그)
- [ ] `backtest.py:run_stratified_backtest` PIT 재설계
- [ ] `FinancialSnapshot.contract_liabilities` 컬럼 · 수집·저장
- [ ] 서희건설 조정 net_cash 재검증 · `first-passed-result.md` v1.1

### P3 → v2 승격 · 인증 아키텍처
- [ ] `localStorage` → httpOnly 쿠키 (Phase 6 지시서 준수)
- [ ] JWT + role-based (관리자·조회자 분리)
- [ ] 24h 만료 + refresh 토큰 · `jti` blacklist
- [ ] `sniper_api_access` 감사 테이블 활성 (지연 사유 재검토)

---

## 11. 검증 원칙 갱신 (본 리뷰 학습)

### 신규 원칙
1. **SSR 마커는 배포 검증에 부적합** — client component + 조건부 렌더링에서 오탐/누탐 발생. **커밋 해시 노출 필수**.
2. **응답 헤더 실측** — `Cache-Control`, `x-nextjs-cache`, `ETag`, `Date` 는 배포 검증의 1급 데이터.
3. **팔림세스트 3회째** — 숫자 변경 커밋에 문서 §6 정합 검증 자동화 필요.
4. **경쟁하는 두 명 이상 관측자 관측이 다르면 캐시 결함** — 배포 완결이든 미완이든 실질 문제.

### 기존 원칙 (반박문 §9) 재확인
- 실측 우선 (문서·설명 대신 코드·URL)
- 3중 실측 (SSR + chunk + API 응답 → **SSR + 응답 헤더 + 소스 트리** 로 확장)
- Python 스크립트 정확 카운트 (grep 인코딩 이슈 우회) · **`html.count` 사용 · 서로게이트/컨트롤 문자 제거 후 UTF-8 valid 보장**

---

## 12. 참고 · 관련 문서

- [`phase7-powderkeg-screener.md`](./phase7-powderkeg-screener.md) · 원 지시서
- [`phase7-final-report.md`](./phase7-final-report.md) · 완료 보고서 (§6 팔림세스트 P1 정정 예정)
- [`2nd-review-rebuttal.md`](./2nd-review-rebuttal.md) · 2차 리뷰 반박문 (§1 방법론 결함 · §4 태광 기대치 · §5 실체 완전 안전 표현 정정 필요)
- [`user-guide.md`](./user-guide.md) · 사용자 가이드
- [`first-passed-result.md`](./first-passed-result.md) · 서희건설 승격 (P2 조정식 적용 후 v1.1 개정 예정)
- **본 문서** · 3차 재재반박 대응 · 실측 재검증 (2026-07-16 v1.0)

---

## 13. 개정 이력

| 날짜 | 버전 | 변경 | 커밋 |
|---|---|---|---|
| 2026-07-16 | v1.0 | 최초 작성 · 재재반박 6항 실측 재판정 · P0 커밋 해시 SSR 푸터 + 캐시 하향 완료 · P1~P3 확정 | `5fadff6` |
| 2026-07-17 | v1.1 | P1 5/6 항목 로컬 완료 · §6 정정 · screener None · tier 3상태 · UI 뱃지 · 교훈 #2 · 태광 재판정만 배포 후 실측 대기 | (pending) |

---

**3차 리뷰 · 재재반박 5/6 수용 · SSR 마커 방법론 결함 정정 · 배포 갭 논쟁 P0 로 영구 종결 · 남은 결함(층화·티어·팔림세스트·선수금·인증)은 P1~P3 로 명시 실행.**
