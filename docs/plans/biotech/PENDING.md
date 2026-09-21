# PENDING · Biotech Catalyst Radar 미완 지시 원문 보관

**용도**: 세션 간 지시 유실 방지. 세션 시작 시 이 파일을 **가장 먼저 읽고**, 완료된 지시는 완료일과 함께 `## DONE` 섹션으로 이동한다.

**등재 규칙**:
- 새 지시 발행 시 원문 전문을 즉시 이 파일 `## PENDING` 상단에 append
- 완료 시 지시 헤더에 `→ DONE YYYY-MM-DD` 표기 후 `## DONE` 섹션으로 이동
- 중단·철회 시 `→ CANCELLED YYYY-MM-DD (사유)` 표기 후 DONE 섹션 이동

---

## PENDING

### [Biotech Catalyst Radar · WP69-3g · report/radar/status/form4 개조] · 2026-09-21 발행 · dry-run 2/6 → 3/6 실패 후속

**진전 (2026-09-21 KST 13:32 · main = `6ac3ee3` · PR #13 병합)**:

WP69-3e-α + WP69-3f 배포 성공 · 서버 dry-run 재시도 결과:

- ✅ **[1/6] candidates 성공** — `var/biotech/candidates/biotech_candidates_20260921.csv` 생성 · final=80 · sources a_readout 80 · **h3_prices_merged 없음 → mcap_distribution: unknown=80 (미산정 · 사용자 조건 통과)**
- ✅ **[2/6] confirm 성공** — `var/biotech/community_daily/community_confirm_20260921.csv` 생성 · apewisdom 300 tickers OK · **Reddit 3/4 sub 429 (pennystocks·wallstreetbets·stocks) · biotechplays 만 OK · 소스별 중단 규칙 정상** · stage_dist: collecting 79 (baseline < 7 · 첫 실행)
- ✅ **텔레그램 env source 작동** — Notifier "미설정" 오류 사라짐
- ❌ **[3/6] report 실패** — `biotech_h48v3_report.py:47` `backend/data/biotech/candidates/biotech_candidates_20260921.csv` 하드코딩 경로 · 서버는 var/biotech/candidates/ 에 저장 · report 는 backend/data 만 조회 → FileNotFoundError
- 4/6 radar · 5/6 form4 · 6/6 status_gen 미실행 (즉시 중단)

**crontab 등록 금지** (규칙 준수 · 서버 무변경)

**다음 세션 첫 지시 (재개 시 실행)**:

1. **h48v3_report.py 개조** — `_find/_find_glob` 로 candidates·confirm CSV 조회 (RUNTIME > docs > backend/data)
2. **h46v3_radar.py 개조** — candidates·confirm 파일 조회 + 산출 경로 (RUNTIME/watchlist)
3. **h65_form4_daily.py 개조** — candidates 조회 + 산출 경로 (RUNTIME 최상위)
4. **h57b_status_gen.py 개조** — 각 리포트 조회 + STATUS.md 산출 경로 (docs 유지 · git 추적)
5. **dry-run 재시도** — 6단계 모두 성공 시 KPI/rows 오늘 갱신 확인
6. **crontab** (성공 시에만) — `0 7 * * *` daily + `0 6 * * 1 --aact-weekly-only`

**보조 개선 (선택)**:
- h3_prices_merged 대체 Tiingo fallback 로직 (사용자 조건 α · 후보 ≤100 심볼) — 현재 시총 unknown=80 · 서비스는 mcap_bucket 필터 skip 상태
- Reddit 3 sub 429 는 IP rate limit · 서버가 매일 반복 실행하면 rate 완화 관측 필요 (biotechplays 만으로도 파이프 진행 가능)

**서버 상태 (변경 없음)**:
- crontab -l: 여전히 비어 있음
- 런타임 폴더: `var/biotech/{candidates, community_daily, logs, ctgov_snapshot.json}` (2/6 산출)
- systemd env: BIOTECH_RUNTIME_DIR 유지
- .env source: 작동 확증

---

### [Biotech Catalyst Radar · WP69-3e · 상위 파이프 산출물 서버 이식] · 2026-09-20 발행 · dry-run 1/6 실패 후속

**dry-run 결과 (2026-09-20 KST 14:57 · main = `cc8c899`)**:
- 1/6 candidates 단계 실패 · `FileNotFoundError`
- 요구 파일: `/root/toss-tradebot-mvp/backend/data/h3_targets_v2_<sha>.csv` (sha = 현재 git rev-parse)
- 원인: `biotech_h48v3_candidates.py:57` 이 `h3_targets_v2_<sha>.csv` 를 로드 · 이 파일은 상위 파이프 (`h3_targets_census` · `h3_efts_sc13d` 등) 가 만듬 · 서버에는 없음 (로컬 mac 만 존재)
- 부작용: 텔레그램 알림 무시 (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 서버 .env 미설정)
- **crontab 등록 금지** (사용자 규칙 · dry-run 실패 시 중단·보고 준수)
- **서버 무변경** (systemd env · 런타임 폴더 유지 · 이 실행은 파일 하나만 시도 실패)

**다음 세션 첫 지시 (사용자 결정 필요)**:

Fable 검수 관점 · 상위 파이프 산출물 이식 방안 3가지 · 하나 승인 필요:

1. **α (권장 · 커밋 이식)**: `h3_targets_v2_<sha>.csv` (그리고 downstream `h1a_events_v2` · `h39_readouts_checkpoint.json` · `h3_prices_merged`) 를 `docs/plans/biotech/data/` 로 커밋 (git 추적 · 소용량 확인) · `biotech_h48v3_candidates.py` 도 `_search_dirs` 를 쓰도록 개조 (RUNTIME > docs > backend/data). 서버 무권한 · 배포 시 자동 반영.
   - 리스크: sha 붙은 파일명이 배포 커밋마다 바뀜 → git_sha 로직을 anchor 파일 (mtime 최신) 로 교체 필요. `_biotech_bootstrap.data_sha()` 이미 이 방식 지원.

2. **β (rsync 이식)**: 로컬 mac 에서 서버 `/root/toss-tradebot-mvp/var/biotech/upstream/` 로 rsync (git 추적 밖). daily.sh 첫 단계에서 파일 존재 확인 후 실행. 사용자 mac 이 켜져 있어야 한 번 이식.

3. **γ (파이프 완전 이식)**: 상위 스크립트 (`h3_targets_census`, `h3_efts_sc13d`, `h39_readouts`, `h1a_v3` 등) 도 daily 파이프에 포함 · 서버가 스스로 h3_targets 생성. 크론 소요 시간 증가 (몇 분 → 30분+).

**보조 처리**:
- 서버 `.env` 에 `TELEGRAM_BOT_TOKEN` · `TELEGRAM_CHAT_ID` 확인 (SOPS decrypt 상태) · 알림 활성화 여부 별도 승인 요청
- `git_sha()` 를 `data_sha()` 로 대체 (파이프 sha 불일치 fix · WP108 기존 사례 정합)

**PR #11 배포 결과 (성공)**:
- main = `cc8c899` (WP69-3d 병합)
- pytest 14/14 · /health 200 · 8 admin 라우트 401 (미회귀)
- kpi/rows 값 유지 (기존 docs/plans/biotech/data/ CSV 참조 · 신 로직도 무회귀 계약)
- ⚠️ dry-run 실패로 데이터 갱신 없음 · KPI 는 여전히 candidates_v3 = 79 (2026-09-14 자)

---

### [Biotech Catalyst Radar · WP69-3 서버 파이프 이식 · in-progress] · 2026-09-20 발행

**현재 상태 (2026-09-20 세션 종료 시점)**:

- **배포 커밋**: `main` 이 `7ffd260` (WP69-3c hotfix) · 이전 상위 커밋 `bac7166`(AACT 스크립트) · `b1ed936`(BIOTECH_RUNTIME_DIR 지원) · `5378710`(WP72 정보 구조)
- **systemd 수동 변경 완료** (자동 배포 범위 밖 · 승인 포함 실행):
  - `/etc/systemd/system/tradebot-api.service` 에 `Environment="BIOTECH_RUNTIME_DIR=/root/toss-tradebot-mvp/var/biotech"` 라인 1개 추가 (백업 파일 `*.bak.20260920_*` 있음)
  - `systemctl daemon-reload && systemctl restart tradebot-api` 완료 · `/health` 200
- **런타임 폴더**: `/root/toss-tradebot-mvp/var/biotech/{logs}` (git 추적 밖 · reset --hard 무영향)
- **crontab -l**: 여전히 비어 있음 (등록 안 함 · (c) 조건부 승인 대기)
- **접근 확정 (서버 IP · biotech_sec_common 상수)**:
  - SEC EDGAR = **200 OK** ✅
  - CT.gov v2 = **403 BLOCKED** ⚠️ → AACT 대안
  - StockTwits = **403 BLOCKED** ⚠️ → γ+α 대안 (사용자 결정)
  - apewisdom = **200 OK** ✅
  - Reddit RSS (r/biotechplays) = **200 OK** ✅

- **AACT 스크립트 완주 (WP69-3c · 2026-09-20 14:32 KST)**:
  - `biotech_h69_aact_weekly.py` 신규 · 서버 배포 완료
  - PR #8 (`bac7166`) → PR #9 hotfix (`7ffd260`) 병합 · main = `6c1a211`
  - **hotfix**: `unzip` 바이너리 부재 → `zipfile.testzip()` fallback · CRC 전수 통과 확증
  - 서버 다운 · 파싱 완주:
    - 스냅샷 = 2026-09-20 (오늘) · zip 2,405 MB · 2m 30s 다운
    - sponsors.txt = 962,048 행 · 후보 스폰서 매칭 733 nct
    - studies.txt = 603,488 행 · 매칭 study 733
    - **JSON 저장** = `/root/toss-tradebot-mvp/var/biotech/ctgov_snapshot.json` · 226 KB
    - **55 unique ticker** (79 후보 v3 중 · 70% 매칭)
    - zip 삭제 · 2.4 GB 회수
    - 예정 top5 (D-10 · 2026-09-30): CCCC · RGNX · **AVIR** · SLN · EWTX (AVIR = rumor 표1 최상단 종목과 정합)
  - **아직 파이프에 연결 안 됨** — h50/h49 가 이 JSON 을 참조하도록 개조 필요 (다음 세션 첫 작업)

**다음 세션 첫 지시 (사용자 발행 원문)**:

> "CT.gov = AACT 주간 스냅샷(서버 · 실측 경로 · studies만 추출 · JSON 저장 · zip 삭제 · 실패 시 로컬 주간 JSON 커밋 예비). 스톡트윗 = γ(apewisdom+레딧 RSS로 열기·단계 산정 · 기준선 재축적)+α(로컬 가용 시 보조 열). β·δ 제외. (b)(c) 조건부 승인: 구현·소스 점검 통과 → dry-run 성공 시에만 crontab 0 7 등록 · 실패 시 중단·보고."
>
> "WP69-3c · AACT 주간 잡 (서버): URL 실측 (실측 확증: `daily/YYYY-MM-DD_daily-clinical-trials.zip` · 2.35 GB). biotech_h69_aact_weekly.py: 최신 스냅샷 다운 (재시도 3 · unzip -t → zipfile.testzip fallback 이미 반영) → studies.txt 스트리밍 파싱 (nct_id · lead_sponsor · phase · overall_status · primary_completion_date · study_first_posted) → 후보 우주 스폰서 매칭 → var/biotech/ctgov_snapshot.json → zip 삭제 · 로그 · 실패 시 텔레그램. 매일 파이프 A 상태 = JSON 읽기 (CT.gov API 호출 제거) · JSON 7일 초과 시 '예정일 자료 오래됨' 경고. cron 0 6 * * 1. 예비: 실패 3회 시 로컬 주간 JSON."
>
> "WP69-3d · 대중 열기 v1.5 (γ+α): 서버 채널 = apewisdom + Reddit RSS · 24h 집계 · 30일 기준선 재축적 (서버) · 7일 미만 '수집 중' · 임계 사전 고정 후 h_radar_params v1.5 changelog 기재 · 가중치 동일. 스톡트윗 = 로컬 보조 (있으면 st_24h CSV 저장소 data 커밋 선택 · 없으면 '미수집'). 표 3·KPI 급등 경보 = 서버 채널 기준 재정의 (apewisdom 24h 5배 or RSS 급증) · 문서 반영."
>
> "(b) dry-run · 서버 수동 1회 · biotech_h48v3_daily_server.sh → 6단계 성공 · 런타임 폴더 산출 · KPI/rows 갱신 (오늘 날짜) · 화면 /biotech 소문 탭 날짜 = 오늘. (c) crontab · dry-run 성공 시에만 · 0 7 daily + 0 6 * * 1 aact · crontab -l · 24h 관측."

**다음 세션 실행 순서 (조건부)**:

1. AACT 스크립트 재실행 (서버 SSH · 기존 zip 재사용 · `_download_zip()` 이 `if zip_path.exists(): LOG.info("기존 zip 재사용")` 로 skip) → `ctgov_snapshot.json` 생성 · study_matches · unique_tickers 확인
2. `biotech_h50_ct_upcoming.py` · `biotech_h49_time_state.py` 를 `ctgov_snapshot.json` 참조하도록 개조 (CT.gov API 콜 제거)
3. `biotech_h48v3_confirm.py` γ 재작성: `fetch_stocktwits_paged()` 제거 · apewisdom + Reddit RSS 만 · 30일 기준선 폴더는 `$BIOTECH_RUNTIME_DIR/st_baseline/` (서버) 로 재축적 시작 (7일 미만 "수집 중") · 임계 재검토 후 `h_radar_params.v1.5.md` changelog 기재
4. 표3/KPI "급등 경보" 재정의: apewisdom 24h 5배 or Reddit RSS 매치 급증
5. **문서**: STATUS.md 상단 안내 문구에 "서버 파이프 (일별 07:00 KST · 주간 AACT 월요일 06:00)" 반영
6. **(b) dry-run**: 서버 SSH · `bash biotech_h48v3_daily_server.sh` 수동 1회 · 6단계 성공 여부 확인 · `/api/v1/biotech/kpi.json` 값 갱신 확인 (화면 소문 탭 날짜 = 오늘)
7. **(c) crontab** (dry-run 성공 시에만): 서버 crontab -e 로 2줄 추가 · 24h 관측 · 실패 시 등록 취소·보고

**다음 세션 보안 규칙 (변경 없음)**:
- biotech_sec_common.{SEC_UA, SEC_FROM, SEC_ACCEPT_ENCODING} 상수 참조 · 하드코딩 금지
- 403/429 즉시 중단·기록 (소스별 · 전체 중단 아님)
- 우회 금지 (사용자 결정 β·δ 제외)
- 자격증명 스캔 커밋 전 필수
- SSH 는 사용자 승인 시에만

---

### [Biotech Catalyst Radar · 배포 승인 (조건 2건) · 9/20 단일 배포 · Phase C 진입] · 2026-09-14 발행

**Fable 최종 검수**: 완주 풀 재검 통과 · Phase A (검증 단계) 종결 승인.

**배포 조건 (5분 작업 · 완료)**:
1. STATUS.md 상단 5줄 쉬운 말 교체 → **완료** (임상 발표 1M 전 +1.62% 등 · 코드 괄호 표기)
2. DEPLOY.md 운영 구조 확정 → **완료** ((a) 로컬 cron→push→뷰어 파일 읽기 (b) .env 키 목록 daily.sh 는 무인증 (c) 서버 변경 사용자 승인 + revert 롤백)

**배포 실행 (사용자 승인 후)**: DEPLOY.md 절차대로 · 배포 후 /radar · /rumor · /map 3 라우트 200 확인 · 첫 자동 실행 로그 확인 · crontab 등록 명령 재안내

**WP56 · 60일 전향 평가 준비 (완료 · 실행은 60일 뒤 자동)**:
- `backend/scripts/biotech_h56_forward_eval.py` 신설
- 매주 저장된 레이더 CSV 의 A 상태 종목 "저장일+1 매수 · 예정일 전날 청산" 가상 규칙 · XBI 대비 · 비용 1% · 날짜 클러스터 CI
- trades_manual.csv 실전 기록 대조 · 창 내 CLOSED 거래 집계
- 60일·6개월 리포트 자동 (`verification/forward/forward-{60d|180d}-YYYY-MM-DD.md`)
- 앵커: 2026-09-14 · 60d cutoff = 2026-11-13 · 180d = 2027-03-13
- 오늘 dry-run: A 상태 32건 · virtual_n=0 (창 미도달 정상)

**Phase C 순서 (배포 후 첫 작업 = 1)**:
1. **소문 채널 완비**: 회사별 PubMed · bioRxiv 게재 증가율 · CT.gov 상태 변경 (AACT 스냅샷) → WP54-2 신호 유무 재검 (규칙 동일 · +1.0%p AND CI 하한 > 0)
2. **H6 소속 확장** (CT.gov 스폰서 전체 재매핑) → 재검
3. **반자동 티켓 탭** (실전 기록 화면화)
4. **H3b 전향 검정** (2026-09-14 이후 신규 13D · 소형~중형)
5. **파산 종목 가격 복구** (원장 v6)

---

### [Biotech Catalyst Radar · 9/20 배포 전 완주 풀 재검 (옵션 2) + 신호 유무 검정 사전 등록 + 최소 열람 페이지] · 2026-09-14 발행

**발행**: 2026-09-14 (세션 21 · WP39 (임상 결과 발표일 목록 만들기) 완주 340/340 · 7351 events)

**Fable 결정**: 옵션 2 (배포 보류 · 즉시 재검 · 9/20 유지). 코드 옆 뜻 표기 규칙 유지.

**WP43-4 · 완주 풀 재검 (오늘)**:
- 입력 = WP39 완주 7,351건 · 결과 발표 필터·방향 태그 v2 적용 · 가격 매치 후 표본 n 보고 (커버율 병기)
- H8 검정 3 (뉴스에 팔기): pre D-30~D-1 · post D+1~D+30 · 날짜 클러스터 CI (신뢰구간) · 부호·지지 여부
- H1b (발표 전 D-30 진입 · D-1 청산): 순초과수익 · CI · 임계 +2% · alpha_pass · 폐기 조건 (CI 하한 ≤ 0) 판정 (예상: 통과 아님 · 폐기도 아님 = "작지만 실재")
- H8 검정 1 v2 (소문 지수 상/하 절반 · 채널 2종 부분): 재계산 · "채널 부분 · 결론 불가" 표기 유지
- 봉인 JSON 갱신 (기존 부분 풀 봉인은 이력 보존) · H8·H1b 리포트 갱신 (쉬운 말 5줄 · 부분 풀 → 완주 풀 수치 변화 표)

**WP54 · 신호 유무 검정 (사전 등록 · 실행 전 규칙 고정)**:
- 가설: 발표 전 D-180~D-31 에 소문 채널 (13D · Form4 P · 테마 소속 증가 · 가능 시 CT.gov 상태 변경) 신호가 1개 이상인 이벤트는 신호 없는 이벤트보다 D-30~D-1 순초과수익이 높다.
- 규칙: 두 집단 평균 차이 · 날짜 클러스터 CI 하한 > 0 이면 지지 · 임계 차이 ≥ +1.0%p (사전 고정) · 채널 부분이면 "채널 n종" 명시
- 완주 풀로 1회 실행 · 봉인 · 리포트 (`docs/plans/biotech/verification/H8/H8-signal-presence-20260914.md`) · 이 검정이 WP53 관찰 (신호 있음 861건 +3~4% vs 전체 +1.4%) 의 정식 판정임을 명시

**WP55 · 최소 열람 페이지 (9/20 전 · biotech 이름공간 · 기존 메뉴 무수정)**:
- 3탭: 레이더 순위표 (radar-v1.3 md 최신) · 소문 확인 (rumor-daily 최신 md · 날짜 선택) · 가능성 지도 (STATUS.md) · md 를 그대로 렌더 · 상단에 용어집 링크 · 하단 고정 문구 (알파 미확정 · 소액 전향용 · 자동매매 없음)
- 반자동 티켓 탭은 Phase C 1순위 (보류함) 유지 · 임시 기록 CSV 안내
- 로컬 실행 방법 1줄 · 스크린샷 첨부 · DEPLOY.md 에 페이지 포함

**배포 준비**:
- STATUS · PHASE-A-FINAL 에 완주 풀 수치 반영 (부분 → 완주 변화 한 줄) · "소문 신호 유무" 결과 반영 · 코드 옆 뜻 표기 유지
- DEPLOY.md 절차대로 사용자 승인 대기 · cron 등록 명령 유지

**보고 (쉬운 말 · 뜻 표기)**: [WP43-4] 완주 풀 표본 n · 검정 3 · H1b · 검정 1 표 (부분→완주 변화) [WP54] 신호 있음/없음 n · 평균 · 차이 · CI · 판정 [WP55] 스크린샷 · 실행 방법 [배포] STATUS 상단 5줄 첨부 · 가능성 지도 3줄

---

### B115~B117·B127·B128·B129·B130 · H8 P1 수정 + H5 정의 복원 + §2 H5·H6·H7 편입 → DONE 2026-09-06 (review-log 완료 확인)

**발행**: 2026-09-06

**전제**: Fable 검수 · H8 P1 2건 (창 겹침 미래참조 · 규모 편향 미정규화) · H5 이전 확정 (B116) 복원 · 순서 정정: B115~B117 (README §2 H5·H6·H7) 최우선. 결제 금지 · 독립 이름공간 · 팁 금지. 봇 감지 페이지 우회 금지 (대안 공식 소스). 탐침 충족 시 실행 · 200 이면 SEC 우선.

**작업 규칙**: TodoWrite. 순차. 서버 조회 전용. 와일드카드 금지.

**작업 1 · B115~B117 README §2 정의 (직전 지시 전문 PENDING 참조)**:
> H5 (해외 촉매→국내 연계 · 유형 4분류 · 창 D-5~D-1/D+1~D+5/D+1~D+20 · KOSDAQ150 · 비용 0.5%) · H6 (point-in-time 분야 순위 · 테마 사전 v1 + 대조군) · H7 (초기 매집 바스켓 · 분포 지표 · 청산 사다리) · §2 정식 편입 · gap flag 제거.

**작업 2 · B127 H8-design v2**:
> 2-1. §1·§3 지수 창 D-180~D-31 · 기준선 D-360~D-181 · 지수 = (신호 - 기준선) / max(기준선, 1) 또는 z-점수 중 하나 커밋 (초안: 증가율) · 채널 ≥2 유효조건 유지.
> 2-2. §2 채널 1 소스 AACT 스냅샷 (point-in-time 재구성) 교체 · CT.gov API 현재 상태만.
> 2-3. §2 채널 5 ADCOM 일정 연방관보 API 공고 교체 (공고일=사전 공지 시각) · FDA 캘린더 스크레이핑 폐기.
> 2-4. 사전 커밋 항목 재번호 · review-log.

**작업 3 · B128 H5-design 복원**:
> placeholder → B116 정의 전면 재작성 (연계 4분류 · 식약처+DART · 비만약 20 케이스 · 현대약품 · FDA 촉매 · B8 대립가설 · 사전 커밋 표) · 조회공시 절 "H8 국내 채널" 이관 링크만.

**작업 4 · B129 조회공시 실측 (DART 실키)**:
> 4-1. list.json 실키 1회 정상 응답 (status 000).
> 4-2. pblntf_ty=I · 기간 2025-01~2026-09 · report_nm "조회공시" 포함 10건 · 바이오 corp_code 필터 · 답변 본문 요구일 파싱 · `h8_kr_inquiry_sample_{sha}.csv`.

**작업 5 · B130 연방관보 실측**:
> federalregister.gov API · "Advisory Committee" + FDA · 2021~2026 공고 건수 · 표본 10건 필드 충족률 · SOURCES.md 행 신설.

**완료 보고 (수치만)**: §2 H5·H6·H7 편입 · H8 v2 변경 항목 · H5 복원 · DART 실키 status · 조회공시 표본 n·파싱 성공률 · 연방관보 건수·충족률 · 탐침 이력.

---

### B123·B124·B125·B126 · "소문에 사서 뉴스에 팔아라" 시간축 편입 · H8 소문 지수 신설

**발행**: 2026-09-06

**전제**: 사용자 이론 (전문가 채널이 공개 뉴스보다 먼저 언급 → 소문 층 수집·검증하고 H7 진입·청산에 결합). Fable 종합: H8 "소문 지수 선행성" 신설 · 단일 소스 금지 (L14) · 채널 ≥2 합류 · 소매 소셜 (H4) 과 분리 · 국내는 조회공시 편입. SEC 불요. 결제 금지 · 독립 이름공간 · 팁 금지.

**작업 규칙**: TodoWrite. 순차. 서버 조회 전용. 와일드카드 금지. 탐침 간격 충족 시 실행 · 200 이면 SEC 세션 우선.

**작업 1 · B123 README 편입**:
> §0 깔때기에 시간축 층 추가 ("소문 → 뉴스 → 뉴스 이후" · 격언 분해표) · H8 을 가설 목록에 추가 · H7 진입 규칙 "H6 분야 ∧ H8 소문 지수 상승" · 청산 규칙 "뉴스 전 50%" 근거 가설로 H8 명시 · 기존 Influencer 메뉴는 L14 폐기 유지 · H8 은 별개 (전문가 채널). review-log.

**작업 2 · B124 H8 설계서 (실행 없음)**:
> `docs/plans/biotech/H8-design.md` 사전 커밋 표: 소문 채널 6종 신호 정의 (CT.gov · 프리프린트 · PubMed · 학회 초록 · FDA/EMA · Form 4/13D · KR 조회공시) · 소문 지수 = D-180~D-1 채널별 신호 수 가중 합 · 채널 ≥2 합류만 유효 · 검정 1 (선행성 · 상/하 절반 · D-30~D-1 CI) · 검정 2 (시차 분포) · 검정 3 (뉴스 팔기 · D+1~D+30 CI 상한 ≤0) · 폐기 조건 · 이벤트 풀 H1a·FDA 승인·H5.

**작업 3 · B125 채널 6종 실측 (호출 최소 · 각 5~10건)**:
> CT.gov API 변경 이력 · bioRxiv/medRxiv/PubMed 게재일 검색 · FDA ADCOM 캘린더·EMA CHMP·학회 초록 페이지 접근 · KIND/DART 조회공시 검색 (표본 10) · SOURCES.md 행 신설 (접근성 · 이력 깊이 · 시각 필드).

**작업 4 · B126 H5 v2 수정**:
> H5-design.md 조회공시 편입 · "조회공시 → 답변" 소문→뉴스 쌍 정의 · 표본 10건.

**완료 보고 (수치만)**: README 편입 · H8 설계서 경로 · 사전 커밋 항목 수 · 채널별 실측 (접근/이력/시각) · 조회공시 10건 · SOURCES 신설 행 수 · 탐침 이력.

---

### B108 · H4 준비 병행 + 탐침 즉시 실행

**발행**: 2026-09-06

**전제**: Fable 정정 · "대기" 는 SEC 차단 해제 확인 1건 (명령 1줄) · 그 외 시간은 H4 준비 (SEC 불요). 결제 금지 · 독립 이름공간 · 키 마스킹.

**작업 규칙**: TodoWrite. 순차. 서버 조회 전용. 와일드카드 금지.

**작업 1 · 탐침 즉시 실행**:
> `python -m backend.scripts.biotech_sec_probe`
> - 200 → 작업 2 건너뛰고 PENDING 최상단 SEC 세션 6작업 실행
> - 403 / SKIPPED_INTERVAL → 이력 기록 후 작업 2 진행 · 작업 2 종료 시점 간격 충족이면 재탐침 1회

**작업 2 · B108 H4 준비 (SEC 호출 0회)**:
> 2-1. 기존 자산 인벤토리 (읽기 전용): meme-stock-discovery 파이프 데이터 파일 · 기간 · 티커 수 · 백테스트 스크립트 경로 · 03-backtest-report.md HOT 임계·히트율 정의 · 재사용 가능 범위와 biotech 격리 방식 표.
> 2-2. 바이오 서브셋 필터 (SEC 불요): (a) H3 targets 286 (SIC 2834/2836 확인분) + (b) XBI 구성 CSV (운용사 공개 · 출처 URL 기록) 합집합 → biotech_ticker_set_{sha}.csv · 출처 컬럼 필수.
> 2-3. H4 검증 설계서 초안 docs/plans/biotech/H4-design.md: §2 H4 정의 그대로 (첫 언급 후 D+1~D+10 · HOT 위양성률 · 진성 히트율) · §2-0 판정식 · 가격 h3_prices_merged 재사용 + 부족분 yfinance · 사전 커밋 항목 (HOT 임계 · 위양성 정의 · 비용 모형) 명시 · 실행 없음.
> 2-4. 기존 밈주 백테스트 바이오 필터 dry-run (호출 없이 데이터 존재·기간·표본 n 추정만).

**완료 보고 (수치만)**: 탐침 결과·시각 · (200 시) SEC 세션 완료 보고 · (그 외) 인벤토리 표 · 바이오 티커 집합 n·출처 분포 · H4 설계서 경로 · 예상 표본 n.

---

### B107 · Item 2.01 120d 게이트 · 실전 전 정밀화 1건

**발행**: 2026-09-06

**전제**: Fable 검수 · B103~B106 통과 (29/29). 오프라인 · 호출 0회. 결제 금지.

**작업 규칙**: TodoWrite. 서버 조회 전용. 와일드카드 금지.

**작업 1 · B107 (오프라인 · 호출 0회)**:
> label_from_filings 의 8-K Item 2.01 ACQUIRED 증거에 조건 추가: `|filing_date - form25_date| ≤ 120d` 인 경우만 인정 (매수측 자산 인수 8-K 오분류 차단). form25_date 는 함수 인자. DEFM14A · SC 14D9 · Item 1.03 규칙 무조건 유지. fixture 테스트 1건 추가 (폐지 3년 전 Item 2.01 → OTHER_DELISTED). 30/30 통과 보고.

**작업 2 · 탐침 운용**:
> 09:32 UTC 이후 python -m backend.scripts.biotech_sec_probe 실행. --force 금지. 403 → 다음 간격 대기 · 이력 기록. 200 → PENDING 최상단 SEC 세션 전문 (B98 · B55+ · B95+B103 · B60 · companyfacts · dry-run 사전 점검) 그대로 순차 실행 · 기존 완료 보고 양식 사용.

**완료 보고 (수치만)**: B107 테스트 결과 · 탐침 이력 · (200 시) SEC 세션 완료 보고 전체.

---

### B104·B105·B103·B106 · SEC 차단 대기 프로토콜 확정 · 오프라인 준비 전환

**발행**: 2026-09-06

**전제**: Fable 판정 · 중단 승인 (규정 준수 확인). 차단은 IP 수준 · 대기로만 해소. 결제 금지.

**작업 규칙**: TodoWrite. 순차. 서버 조회 전용. 와일드카드 금지.

**작업 1 · B104 탐침 프로토콜**:
> 재개 확인 = data.sec.gov 단일 요청 1건 (동일 신원 선언 UA) · 간격 최소 2시간 (권장 +2h → +6h → +24h) · 403 이면 즉시 종료 · 각 탐침을 review-log 1줄 기록. 200 확인 시에만 SEC 세션 6작업 개시 (직전 세션 프롬프트 전문이 PENDING.md 에 보존).

**작업 2 · B105 우회 금지 명문화**:
> README §3 보안 상시 규칙에 1줄: "IP 차단 시 서버 실행·네트워크 변경 등 IP 교체로 접근하지 않는다 (우회 금지 · 대기와 탐침만)."

**작업 3 · B103 §8 현행화 (오프라인)**:
> 생존 편향 수치 = 92 (kept 50 + simfin_kept 42) / 48 (B60_pending 35 + unrecoverable 13) · "라벨링(B95) 후 재산출 예정" 유지.

**작업 4 · B106 SEC 세션 코드 사전 작성 (오프라인 · fixture 기반)**:
> 4-1. B98 이벤트 추출기: submissions JSON fixture (합성 2기관 · 13D/13D-A/13G 혼합) 로 신규만 추출·subject 매핑 검증 pytest.
> 4-2. B95 라벨 분류기: filing 목록 fixture 로 Item 1.03 / DEFM14A / SC 14D9 규칙 분류 pytest.
> 4-3. companyfacts 파서: companyfacts JSON fixture 로 이벤트일 최근접 분기 shares 선택 로직 pytest.
> 4-4. 전 코드에 진행률 체크포인트·403 즉시 중단 공통 처리.
> 목표: 탐침 200 후 SEC 세션이 수신·저장만으로 완료되게 준비.

**완료 보고 (수치만)**: B103 갱신 확인 · B106 pytest 결과 (신규 n건) · 탐침 이력 (시각·상태). SEC 200 확인 시: PENDING 세션 전문대로 진행.

---

### B98·B55+·B95·B103·B60·companyfacts · SEC 세션 일괄 실행 · 이벤트 완성 → 백테스트 준비 완료

**발행**: 2026-09-06

**전제**: 엔진 동결 (B99~B102 통과 · 7/7). SEC 쿨다운 해제 확인 후 실행. 첫 요청 1건으로 403 여부 확인 · 403 즉시 중단·보고 (UA 순환 절대 금지). PENDING.md 등재 후 착수. 신 UA (TossTradebot-BiotechRadar/1.0) · 0.5s 간격 · 키 마스킹 · 결제 금지 · biotech 독립 이름공간.

**작업 규칙**: TodoWrite. 작업 1개씩 순차. 서버 조회 전용. 와일드카드 패턴 금지. 진행률 체크포인트.

**작업 1 · B98 h3_events (13D/13G 신규)**:
> 기관 55 CIK submissions 에서 기간 내 SC 13D · SC 13G 신규(/A 제외) 이벤트 산출. 행: event_id · target_cik · ticker · event_type(13D_new/13G_new) · event_date(제출일) · accession · institution. subject CIK 는 filing 메타로 확정 (B24 filer/subject 일치). 대사: 유형별 합계 vs census (신규 13D 50 · 신규 13G 296).

**작업 2 · B55+ Form 4 매수**:
> 55 CIK Form 4 XML issuerCik·transactionCode 파싱 · P만 F4_buy 이벤트로 h3_events 추가. 파싱 실패·비매수 분해 카운트.

**작업 3 · B95 라벨링 + B103**:
> 140 target 기계 라벨 (8-K Item 1.03 → BANKRUPT · DEFM14A/SC 14D9/합병 8-K → ACQUIRED · 그 외 OTHER_DELISTED). h3_bias_analysis 재산출 (가격 92 vs 미가격 48 구성 비교 · 편향 방향 1줄). README §8 수치 현행화.

**작업 4 · B60 표지 파싱 (미가격 48)**:
> 각 target 신규 13D/13G 표지에서 당시 티커 파싱 → Tiingo/SimFin 재시도 (B74 · adj_close) → 원장 v6 · 통합기 재실행.

**작업 5 · companyfacts 발행주식수**:
> 140+194 target filing 시점 근접 분기 발행주식수 → h3_mcap_{sha}.csv (cik · asof · shares · 산출 mcap 방식). 엔진 mcap_lookup 배선 (이벤트 시점 최근접 분기).

**작업 6 · 사전 점검 보고 (백테스트 미실행)**:
> h3_events 를 엔진 --dry-run + 적격 검사만 · 예상 표본 n (horizon 별) · 제외 분해. 실행은 Fable 최종 검수 후.

**완료 보고 (수치만)**: h3_events 행 수·유형별 분해·census 대사 · F4 파싱 분해 · 라벨 분포 · bias 비교 표 · B60 회수 n/48 · 원장 v6 분해 (합계 140) · mcap 확보 n · 예상 표본 n · CSV 경로. 해석 서술 금지.

---

### B99·B100·B101·B102 · 엔진 수정 4건 · 실데이터 투입 전 필수

**발행**: 2026-09-06

**전제**: Fable · P1-1 폐지 창 단축 이벤트 no_exit 제외 → 인수 프리미엄(H3 성공 결말) 180d 체계적 탈락 · 하방 왜곡 · P1-2 임계 (2%/30%) ≠ H3 커밋값 (+5/+15% · 35%). 호출 0회.

**작업 1 · B99 창 단축 청산**:
> compute_return: exit 목표일 이후 바 부재 · 마지막 바 < 목표일 → 마지막 바 청산 · `window_shortened=True` · `actual_days` · 요약에 shortened 카운트. entry 부재는 제외 유지.

**작업 2 · B100 임계 dict (H3 커밋값)**:
> `H3 = {30d: mean≥+5.0, 180d: mean≥+15.0, hit≥35.0, ci_lo>0}` · §2-0 서열 (1차 mean · 2차 hit) · README §3-5 반영.

**작업 3 · B101 보완 3건**:
> 3-1. entry_lag: entry_date > event+7d 제외 · excluded["entry_lag"]
> 3-2. exit overshoot: exit_date > 목표일+15d flag · 카운트만
> 3-3. SIC 배선: h3_targets_v2 로 cik→sic · 버킷 subsector 축

**작업 4 · B102 pytest 2건 추가**:
> (f) 인수 60일 후 +40% 종료 → 180d 포함·shortened=1·net excess 양수
> (g) 임계 정합: +6%/40%/CI>0 → alpha=True · +4% → False
> 기존 5 + 신규 2 = 7건 통과

**작업 5 · SEC 세션 예약 (쿨다운 후)**:
> B98·B55+·B95·B60·companyfacts · 신 UA · 0.5s · 403 즉시 중단

---

### B97 · 백테스트 사양 커밋 + 엔진 오프라인 구축 · SEC 대기 활용

**발행**: 2026-09-06

**전제**: Fable · B94·B96 대사 통과 (92/140 가격) · SEC 쿨다운 대기 중 오프라인 엔진 구축.

**작업 1 · 사양 커밋 (README §3 백테스트 사양 v1)**:
> 진입 D+1 종가 (adj_close) · 창 D+1~D+30/D+1~D+180 · benchmark XBI (IWM 병기) · net = 왕복 비용 1.0% · 민감도 0.5/2.0/5.0% · §2-0 판정식 · bootstrap 이벤트 단위 10,000회 · seed 고정 · 종목 클러스터 재추출 · 버킷 mcap [50M,300M)/[300M,1B)/[1B,5B] × subsector · mcap = companyfacts 발행주식수 × 원시 종가 · 이벤트 적격 [D-30,D+180] 실존 · 사후 조정 금지

**작업 2 · B97 엔진 구축**:
> `backend/scripts/biotech_h3_backtest.py` · 입력 h3_events + h3_prices_merged + benchmarks + 원장 · 출력 이벤트별 수익률 + 요약 + alpha_confirmed ("Fable 검수 대기") · git_sha 각인

**작업 3 · 합성 데이터 pytest 5건**:
> (a) 알파 심음 CI>0 검출 (b) 무알파 비검출 (c) 비용 차감 (d) D+1 미래 참조 부재 (e) 창 단축 카운트

**작업 4 · SEC 세션 예약 (쿨다운 후)**:
> B98 h3_events · B55+ Form 4 코드 P · B95 라벨링 · B60 표지 파싱 · companyfacts

---

### B94·B96·B95 · 9건 재시도 + 벤치마크 + unrecoverable 분류 정정

**발행**: 2026-09-04

**전제**: Fable · hold_similar 9건의 "unrecoverable" 자기모순 (원 티커 존재) · 수집기가 final_symbol 공백 참조로 건너뜀 추정.

**작업 1 · B94 9건 재시도**:
> 1-1. 건너뛴 원인 1줄 (코드 라인)
> 1-2. 9 티커 Tiingo → SimFin · CLVRW→CLVR
> 1-3. 성공 kept/simfin_kept · 실패 B60_pending · unrecoverable = 22건 (티커 자체 부재)만 · v5 · 합계 140
> 1-4. 통합기 재실행

**작업 2 · B96 XBI·IWM 벤치마크**:
> yfinance 2020-01-01~ · adj_close · `benchmarks_{sha}.csv` (h3_prices 분리)

**작업 3 · B95 예약 (SEC 쿨다운 후 · B60 병합)**:
> 140 target submissions 기계 라벨링 (Item 1.03/DEFM14A/SC 14D9) · h3_bias_analysis 재산출 · README §8 갱신

**작업 4 · 예약 유지 (SEC 쿨다운 후 · 신 UA · 0.5s)**:
> B60 표지 파싱 · B55+ Form 4 코드 P

---

### B90·B91·B92·B93 · SimFin 파서 P0 수정 + 편향 정량화 + 정리

**발행**: 2026-09-04

**전제**: Fable · run2 simfin 42,798행 전량 close=0 · 컬럼 매핑 결함. adj_close 정체 미확인. Tiingo 정상 (CDTX 1:20 조정 확인).

**작업 1 · B90 SimFin 파서 수정**:
> 1-1. compact 응답 1건 columns 원문 확인 (스키마 추정 금지)
> 1-2. simfin_kept 41건 재수집 (run3)
> 1-3. 교차 검증 5종목 · adj_close 상대오차 ≤1% · 초과 시 중단·보고
> 1-4. 통합기 재실행 · close>0 재확인

**작업 2 · B91 편향 정량화 (호출 0회)**:
> 2-1. 원장 v3에 event_type 복원 · v4
> 2-2. 가격 87 vs 미가격 53 · event_type 분포 · README §8 수치

**작업 3 · B92 정리 (호출 0회)**:
> 3-1. hold_similar 9 최종 상태 표
> 3-2. 통합기 eodhd 제외 · 재통합 · eodhd 0

**작업 4 · B93 문서**:
> README §3 · "이벤트별 [D-30, D+180] 가격 실존 검사 · 미충족 표본 제외 + 제외 수 리포트" 1줄

**작업 5 · 예약 유지 (SEC 쿨다운 후 · 신 UA)**:
> B60 · B55+ Form 4

---

### B87·B88·B89 · B83 승인 (5건 수정) · 반영 즉시 수집 실행

**발행**: 2026-09-04

**전제**: Fable · v2.1 재판정 확정 · Tiingo 18/20 · 합집합 20/20 · 바 밀도 250± 확인. 사전 검수 불요.

**작업 1 · B87 계획 수정 5건 (B83-collection-plan.md + 수집기 반영)**:
> 1-1. 수집 창: `2020-01-01 ~ form25_date+30d` (event-365~event 사용 금지 · D-30~D+180 창 보전)
> 1-2. adj_close 컬럼 (Tiingo adjClose · SimFin 조정가 확인 후 · 수익률 계산 기준)
> 1-3. 대상 140 전량 · kept 5 (깊이 통일 재수집) + data_lost 13 + queued_v3 74 + hold_similar 9 + B60_pending 39
> 1-4. B74 유지 · bar_density 컬럼 기록만 (자동 격리 없음 · LIPO 식별용)
> 1-5. tiingo_unique_symbols_used 누계 (월 500)

**작업 2 · B88 활성 194 수정주가 재수집**:
> yfinance auto_adjust=True · adj_close 포함 · 실행별 run 파일

**작업 3 · B89 폐지 140 수집 (1 완료 즉시)**:
> Tiingo 140 → SimFin 폴백 → 잔여 B60_pending · 6분류+bar_density · 원장 갱신 (kept/simfin_kept/B60_pending/unrecoverable) · 합계 140

**작업 4 · 통합·보고**:
> 통합기 + 소스 분포 + review-log 1줄

---

### B84·B85·B86·B83 · 판정식 v2.1 커밋 → 오프라인 재판정 · 호출 0회

**발행**: 2026-09-04

**전제**: Fable · 실패 8건 중 6건 창 시작일 = 비거래일 경계 오판 (XLRN 일요일 · first +1d) · AKUS 인수 거래정지→Form25 지연 (last −21d) · **데이터가 아니라 판정식 결함**. AV 응답 본문 미보관 → FAIL 판정 불가 → "미측정". 결제 금지.

**작업 1 · B84 판정식 v2.1 사전 커밋 (재판정 실행 전)**:
> README §4 + SOURCES B80 블록: "판정식 v2.1 (2026-09-04): 창 커버 = first_bar ≤ 창시작+7일 AND last_bar ≥ 이벤트일−30일. 근거: (1) 창시작 주말/연휴 → 첫 거래일 최대 수일 뒤 (7일 = 최장 연휴 여유) (2) 인수 종목 거래 정지→Form25 지연 (B74 절단 +30d 동일). 결과 관찰 후 조정/소스별 차등 금지 · 3소스 동일."

**작업 2 · B85 오프라인 재판정 (test3 CSV first/last 만)**:
> 2-1. v2.1 로 3소스 재산출 · PASS/FAIL (18/20)
> 2-2. 합집합 (Tiingo ∪ SimFin) 재산출 · 잔여 미커버 사유
> 2-3. 집단별 (인수/파산/해산) 분해
> 2-4. `biotech_coverage_test3_rejudge_{git_sha}.csv` · SOURCES 3소스 행 갱신 (v2.1 + 구수치 병기)

**작업 3 · B86 AV 재분류 · 본문 보관**:
> SOURCES AV = "미측정 (응답 본문 미보관)" 정정. test3 스크립트 비정상 응답 본문 200자 컬럼 (키 마스킹). AV 재측정 후순위.

**작업 4 · B83 재작성 (B85 결과 기준)**:
> PASS 시: "축소 검증안" → "수집 재편성 계획" (Tiingo 1차 · SimFin 폴백 · 폐지 140 · Tiingo 500 심볼/월 · 활성 194 yfinance 유지 · 미커버 편향 방향 정량화)
> FAIL 시: 축소 유지 + 유료 후보 목록 제거 (사용자 무료 전용 결정)

---

### B82·B78·B58 · 키 3개 등록 · 실측 실행

**발행**: 2026-09-04

**전제**: 사용자 통보 · TIINGO/AV/SIMFIN 키 backend/.env 등록 완료. 이번 세션 실측 완주. 결제·유료 제안 금지. 키 원문 금지.

**작업 1 · B82 SimFin 사전 확인**:
> 공식 문서 · API 버전 (v2/v3) · 인증 방식 (query vs header) · test_simfin 수정. 무료 티어 벌크 다운로드 포함 여부 · 포함 시 "벌크 1파일 → 오프라인 창 커버 판정" 교체 (크레딧 0). SOURCES 기재.

**작업 2 · B78 EODHD 탐침 (최대 3회)**:
> v4 2022~2023 폐지 2~3건 · from/to 명시 (event-365 ~ event) · 반환 창 기록 · SOURCES "공식 확인".

**작업 3 · B58 3소스 실측**:
> 3-1. dry-run · 3키 SET · 표본 20 · 호출 계획
> 3-2. SimFin (벌크 우선) → Tiingo → AV · B80 창 커버 · FETCH_ERROR · 집단별 분리 · AV 재시도 금지
> 3-3. PASS/FAIL 18/20 · SOURCES · review-log

**작업 4 · 분기**:
> PASS 존재: B83 단일 큐 재편성 1페이지 계획서 (실행 Fable 검수 후)
> 전 FAIL: 축소 검증안 초안 (실행 없이)

**작업 5 · 병행 (SEC 쿨다운 · 신 UA)**:
> B60 · B55+ Form 4 · 403 재발 즉시 중단

---

### B80·B81·B58 · EODHD PASS 철회 · B58 핵심 경로 전환

**발행**: 2026-09-04

**전제**: Fable · EODHD 20/20 PASS 공식 철회 (창 커버 0/20 · 1년 제한 강력 지지). kept 13 = data_lost_overwrite (덮어쓰기 유실 · 부적격 아님). B58 핵심 경로 · 사용자 Tiingo·AV 키 .env 추가 예정. **결제·유료 제안 금지**.

**작업 1 · B80 기준 재정의 사전 커밋 (호출 0회 · 오늘)**:
> README §4 · SOURCES.md · 통과 기준 v2 (2026-09-04): "표본 20 각각 응답 시계열이 (event_date-365 ~ event_date) 창 실제 커버 → 커버 인정. 창 커버 18/20 이상 = PASS. 응답 존재만으로는 커버 불인정." SOURCES EODHD 행 "PASS 철회 (2026-09-04 · B77 재감사 · 창 커버 0/20 · 1년 제한)".

**작업 2 · B81 덮어쓰기 결함 수정 (호출 0회 · 오늘)**:
> 2-1. `h3_prices_{sha}_{date}_{run}.csv` 실행별 + 통합기 (중복 dedupe · 최신 우선)
> 2-2. 원장 13건 `data_ineligible` → `data_lost_overwrite` + 사유
> 2-3. 09-02 파일 yfinance 194 무결성 (티커 수 · 행 수)

**작업 3 · B58 실측 준비 (호출 0회 · 오늘)**:
> 3-1. coverage_test 3소스 확장 (Tiingo · Alpha Vantage · SimFin) · 신 기준 · FETCH_ERROR · dry-run
> 3-2. SimFin 무료 티어·데이터 깊이 조사 (가입 필요 시 사용자 액션)
> 3-3. 호출 계획 (AV 25/day 유의)

**작업 4 · B78 EODHD 탐침 (내일 quota 리셋 후 · 3회)**:
> v4 2022~2023 폐지 2~3건 · from/to 명시 · SOURCES 실측 기재 (기록용)

**작업 5 · 키 수령 후**:
> Tiingo → AV 순서 · v4 20 실측 (신 기준) · 집단별 커버율 · PASS/FAIL

**작업 6 · 병행 (SEC 쿨다운 후)**:
> B60 3차 복구 · B55+ Form 4

---

### B77·B78·B79 · EODHD 이력 깊이 의혹 결판 · 대량 수집 중단

**발행**: 2026-09-03

**전제**: Fable · 격리 원본 실측 · HOOK·APTOF 시계열 요청일 기준 정확 1년 창 (2025-09-03~) 잘림 → 무료 티어 이력 깊이 제한 의혹. 사실이면 kept 18 · 최초 20/20 PASS 재검토. 잔여 74 대량 수집 중단. **결제 금지 · 유료 전환 제안 금지 (사용자 결정)**.

**작업 1 · B77 소급 감사 (호출 0회 · 오늘)**:
> 1-1. kept 18 재판정 · h3_prices CSV 티커별 first/last · form25 대조 · B74 기준 통과 여부 · 불통과 = 원장 `data_ineligible` 신설
> 1-2. 최초 20/20 재감사 · coverage_test2 CSV eodhd_range 파싱 · 창 커버 vs 행 존재 결론
> 1-3. "무료 티어 1년 제한" 가설 판정 (지지/기각/불확정) · first=요청일-365 패턴 빈도 포함

**작업 2 · B79 parse fail 규명 (호출 0회)**:
> quarantined_raw rows=1 · 날짜 공백 7건 원인 코드 역추적 · collect_eodhd dict 오류 응답 행 변환 분기 · `fetch_error` 분류 신설 (empty 구분) · 체크포인트 스키마 추가

**작업 3 · B78 정밀 탐침 (내일 quota 리셋 후 · 최대 3회)**:
> v4 표본 2022~2023 폐지 2~3개 · from/to 명시 (event-365 ~ event) · 반환 범위 vs 요청 창 · SOURCES.md EODHD 행 실측 기재

**작업 4 · 분기 준비**:
> 제한 확정 시: B58 (Tiingo/Alpha Vantage) 승격 준비 · 동일 v4 표본 실측 스크립트
> 제한 기각 시: 호출 파라미터 원인 규명 · 74건 수집 재개안

---

### B74·B75·B76 · 격리 규칙 교체 · 오늘 잔여 한도로 8건 재수신

**발행**: 2026-09-03

**전제**: Fable · 3일차 격리 8건은 B65 순환 재격리 (EODHD 폐지일 필드 부재로 기준일 form25 회귀 · OTC 지속 종목 영구 격리 루프 · HOOK 재격리 증거). 규칙 교체.

**작업 1 · B74 규칙 교체**:
> 1-1. validate_last_date 격리 로직 제거 → 신 규칙:
>   (a) 적격: `first_bar ≤ form25_date − 90d` (폐지 이전 커버) · 미커버 = 재활용 심볼 · quarantine
>   (b) 절단 저장: 통과 시 `form25_date + 30d` 초과 바 제거 · 제거 수 `truncated_bars` 체크포인트
>   (c) form25_date 부재 = held (호출 전 큐 분리)
> 1-2. 격리 원본 보존 · `h3_prices_quarantined_raw_{git_sha}.csv` (재판정 시 재호출 불필요)
> 1-3. validate_event_window (프로브) 유지
> 1-4. docstring 갱신

**작업 2 · B75 오늘 8건 재수신 (잔여 10 quota 내)**:
> 3일차 격리 8건 (HOOK·APTOF·ITOS·ALPN·OTIC·RGLS·PRDS·INBX_old) 신 규칙 재수신 · 6분류 누계 · 원장 갱신 · 격리 유지 시 B60_pending 전환.

**작업 3 · B76 문서**:
> README §8 · 1줄: "폐지 종목 시계열 form25+30d 절단 · 재활용 심볼 오염 차단 · 창 단축 종목 수 리포트 명시". review-log 1줄.

**작업 4 · 4일차 이후**:
> 잔여 큐 신 규칙 · 수율 중단선 유지.

**작업 5 · 예약 유지 (SEC 쿨다운 후 · 신 UA)**:
> B60 · B55+ Form 4.

---

### B71·B72·B73 · 소규모 3건 수정 후 3일차 실행 (같은 세션 진행 가능)

**발행**: 2026-09-03

**전제**: Fable · 배선 실질 통과. 3건 고치고 dry-run 재확인 후 같은 세션 3일차 실행 승인 (사후 검수).

**작업 1 · B71 수율 중단선 위치 수정**:
> 중단선 판정 (fetched≥10 && kept/fetched<0.5) 이 empty·quarantine continue 우회하지 못하도록 매 반복 종료 시 공통 판정 위치로 이동.

**작업 2 · B72 빈 플래그 제거**:
> `--with-yfinance` 플래그·도움말·로그 전량 제거 (기능 부재 · 혼선 방지). 재도입은 별도 티켓.

**작업 3 · B73 HOOK 정합 확인**:
> h3_prices CSV 들 grep · 존재 시 원장 HOOK kept 정정 (사유: B65 복권 · 가격 반영) · 부재 시 큐 유지 + 원장 사유 기재. 매치 행 수 보고.

**작업 4 · dry-run 재확인 후 3일차 실행 (quota 리셋 후)**:
> dry-run 3항 (잔여 큐·kept skip·상위 20 HOOK 반영) → 이상 없으면 본 실행 · 6분류·수율·원장 갱신 보고.

**작업 5 · 예약 유지 (SEC 쿨다운 후 · 신 UA)**:
> B60 (B60_pending 31 + hold_similar 9) · B55+ Form 4 (진행률 체크포인트 · 403 즉시 중단).

---

### B69 · 수집기 배선 완료 (3일차 선행 조건)

**발행**: 2026-09-03

**전제**: Fable 코드 검수 · 헬퍼 3개 (load_ledger_kept_ciks · is_warrant_unit_rights · validate_event_window) main() 미연결. **이 상태 3일차 실행 금지.** 배선 완료 + dry-run 확인 후에만 3일차.

**작업 1 · B69 배선 체크리스트 (7항)**:
> 1-1. 큐 경로 → `queue_eodhd_v3_{git_sha}.csv` · yfinance skip 플래그 (194 재호출 금지).
> 1-2. 시작 시 `load_ledger_kept_ciks()` · 큐 kept 제거 · skip 건수 로그.
> 1-3. 수집 루프: 수신 → `validate_last_date` (form25/eodhd_delist 전달) → 프로브 대상 `validate_event_window` 추가 → 통과분 write · 실패 quarantine 직행 + 사유.
> 1-4. 체크포인트 6분류 스키마 (fetched/rows_gt_0/validated_kept/quarantined/empty/held) + sum_check · 원장 즉시 갱신.
> 1-5. 수율 중단선: kept/fetched < 0.5 시 루프 중단 + 잔여 보존.
> 1-6. Docstring 현행 (v3 85건 · 원장 skip · 즉시 검증 · 6분류) 갱신.
> 1-7. `is_warrant_unit_rights` 조건부: 기저 심볼(접미 제거형)이 동일 회사명 후보에 존재할 때만 적용. VERU 류 단독 오탐 금지.

**작업 2 · dry-run 검증**:
> (a) 로드 큐 v3 85건 (b) kept skip 수 (c) 상위 20 (d) 검증 함수 연결.

**작업 3 · 3일차 수집 (1·2 완료 + quota 리셋 후)**:
> 상위 20 (정규 우선 · 잔여 프로브) · 6분류 · 수율 보고.

**작업 4 · 예약 유지 (SEC 쿨다운 후 · 신 UA)**:
> B60 (B60_pending 31 + hold_similar 9 표지 파싱) · B55+ Form 4 (진행률 체크포인트 · 403 즉시 중단).

---

### B67·B68 · 원장 정정 (3일차 전 필수) + 프로브 절차

**발행**: 2026-09-03

**전제**: Fable · 원장 kept=4 vs 체크포인트 (day1 4 + day2 11 = 15) 모순. 2일차 kept 11 (CLXPF·MDNA·OPT·CDTX·DICE_old·ETNB·STSA·FMTX·ICVX·ACHL_old·PNT) 오배정. HOOK 복권도 큐 편입 오처리. **3일차는 B67 완료 후에만.** 오늘 호출 0회.

**작업 1 · B67 원장 재작성**:
> 1-1. 체크포인트 v2 kept 15건 각 target_cik 역매핑 → 원장 kept 정정. HOOK 복권 kept (h3_prices 적재 확인 후).
> 1-2. queued_v3 / B60_pending 재배정 · 합계 대사 (140 = kept + queued_v3 + hold_similar + B60_pending).
> 1-3. queue v3 에서 kept 제거 · 갱신 건수 · 분할 일수.
> 1-4. 수집기 중복 방지: 호출 전 원장 조회 · kept skip + 로그.

**작업 2 · B68 프로브 절차**:
> 2-1. `_old` 우선 (재활용 티커 옛 시계열).
> 2-2. 프로브: HOLD 9 + 다중 후보 · 1건씩 호출 → 즉시 검증 (last_date + first_date 이벤트 창) → 실패 시 격리 + 다음 후보 자동 편입 · 소진 시 B60_pending.
> 2-3. B64 확정 5건도 즉시 검증 (INNT 류 오선택 자동 교정).
> 2-4. 프로브 = 정규 큐 처리 후 잔여 호출.

**작업 3 · 3일차 수집 (B67 완료 후 · quota 리셋 후)**:
> 갱신 큐 상위 20 (정규 우선 · 잔여 프로브) · 즉시 검증 · 6분류 · 수율 <50% 중단 · 원장 즉시 갱신.

**작업 4 · 예약 유지 (SEC 쿨다운 후 · 신 UA)**:
> B60 3차 복구 (B60_pending 전량 · 13D/G 표지 파싱) · B55+ Form 4 (진행률 체크포인트 · 403 즉시 중단).

---

### B64·B65·B66 · Fable 판정 회신 · 유사 14건 편입 + 격리 규칙 수정

**발행**: 2026-09-03

**전제**: Fable · 유사 14건 전원 큐 편입 승인 (기계 규칙). 격리 규칙 결함 (form25 = 거래소 폐지 · OTC 지속 오격리 사례 APTOF/Ayala). 오늘 EODHD 호출 없이 오프라인만.

**작업 1 · B64 유사 14건 심볼 확정 (로컬 JSON)**:
> (1) W/WS/U/R 접미 제외 (기저 심볼 존재 시 탈락 · CLVRW→CLVR)
> (2) EODHD 폐지일 form25_date 최근접 (≤60d)
> (3) 잔여 복수 시 이벤트 창(first-1y ~ form25+30d) 시계열 겹침
> (4) 미확정 HOLD (호출 금지 · 사유 기록)
> 확정분 queue v3 추가 · 분할 재산출.

**작업 2 · B65 격리 재판정 (로컬 JSON)**:
> 2-1. 기준 수정: `last_date ≤ max(form25_date, eodhd_delist_date) + 30d`. 수집기 반영.
> 2-2. 격리 24건 재판정:
>   - 회사명 완전 일치 + 신 기준 통과 → 복권 (OTC 지속)
>   - 불일치 (INO·IMVT 활성 오매칭) → 격리 유지 · B60 편입
> 2-3. 복권/유지 분해.

**작업 3 · B66 단일 원장**:
> `h3_delisted_ledger_{git_sha}.csv` · 폐지 바이오 전 대상 1행 · 컬럼: target_cik · target_name · 확정 심볼 · 상태 (kept/queued_v3/B60_pending/unrecoverable) · 상태 근거 · form25_date · eodhd_delist_date. 총계 = 폐지 대상 수 (합계 대사 필수). 이후 생존 편향 수치는 이 원장 기준.

**작업 4 · 3일차 수집 (내일 · 갱신 큐)**:
> 상위 20 · 신 기준 검증 · 6분류 · 수율 <50% 즉시 중단.

**작업 5 · B60 예약 (SEC 쿨다운 후 · 신 UA)**:
> 대상 46건 (기존 25 + eodhd_absent 21) + B64 HOLD. 13D/G 표지 티커 파싱 → EODHD 재대조 → 큐 편입.

---

### B61·B62·B63·B60·B55+ · EODHD 수집 중단 + 오프라인 사전 검증 · 큐 재구성

**발행**: 2026-09-03

**전제**: Fable · 39호출 중 유효 6 (수율 15%). 원인 = 회사명 유사 일치가 활성 기업 심볼(INO·IMVT·IRON 등) 오매칭. **사전 검증 완료 전 EODHD 호출 중단.** 오늘 한도 이미 소진 · 내일 호출 전 반드시 완료. 결제 금지.

**작업 1 · B61 오프라인 사전 검증 · queue v3 (API 0회)**:
> 1-1. 로컬 eodhd_us_delisted_symbols.json (59,925) 기준 잔여 큐 + 격리 재시도 + 미매칭 13 재검증.
> 1-2. 통과 규칙 (모두 충족만 큐 편입):
>   (a) 정규화 회사명 완전일치 (유사 자동 편입 금지 · 별도 후보 CSV Fable 검수용)
>   (b) JSON 폐지일 있으면 |폐지일 - form25_date| ≤ 60d
>   (c) B63: form25_date 부재 시 JSON 폐지일 기준 대체 · 둘 다 부재 시 HOLD (호출 금지)
> 1-3. queue_eodhd_v3.csv · 예상 유효수 · 제외 사유 분해.
> 1-4. kept 6건 재검증 제외.

**작업 2 · B62 장부 정의 통일**:
> 2-1. 체크포인트 스키마 6분류: fetched · rows>0 · validated_kept · quarantined · empty · held. 매일 합계 대사 필수.
> 2-2. 2일차 "성공 19 vs 데이터 있음 10" 9건 규명 · 재분류.
> 2-3. 1~2일차 체크포인트 신 스키마로 소급 재작성.

**작업 3 · 3일차 수집 (B61 완료 후만)**:
> queue v3 상위 20 실행 · 수신 즉시 검증 · 6분류 장부. 수율 (kept/fetched) 리포트. **수율 < 50% 시 즉시 중단.**

**작업 4 · 다음 세션 예약 (SEC 쿨다운 후 · 신 UA)**:
> B60 3차 복구 (13D/G 표지 티커 파싱 · 25건 + B61 HOLD 추가). B55+ Form 4 파싱 재개 (진행률 체크포인트). 403 재발 즉시 중단.

---

### B59·B57+·B60·B55+ · 격리 상시화 + SEC UA 규정 준수 · 우회 금지 재확인

**발행**: 2026-09-03

**전제**: Fable · B57 격리가 대형 오염(1일차 16/20) 정확 캐치. 격리 상시화 + SEC 차단 근본 원인(UA) 고침. **경고: 차단 후 "전 UA 조합 시도" 는 금지된 우회 · 재발 금지 · 차단 시 올바른 행동 = 중단·원인 보고·수정 후 재개.**

**작업 1 · B59 SEC 접근 규정 준수 (다른 SEC 작업보다 선행)**:
> 1-1. biotech 스크립트 전체 UA → "TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)". Mozilla 위장 제거. From 유지.
> 1-2. 요청 간격 0.15s → 0.5s (2 req/s).
> 1-3. 403 재발 시 즉시 중단 · UA 변경 재시도 금지 · 보고만.
> 1-4. SOURCES.md SEC 행 UA 갱신 · Security-Audit.md 위반 사례 1행 등재.
> 1-5. Archives 접근 = 세션 최후순위.

**작업 2 · B57+ 격리 상시화**:
> 2-1. 수집기 수신 즉시 검증 · 통과분만 h3_prices · 위반은 quarantine 직행.
> 2-2. 2일차 19건 소급 검증.
> 2-3. 격리 시 회사명 재매칭 후보 자동 익일 큐 편입.

**작업 3 · B37 수집 계속**:
> 3일차부터 일 20건 · 상시 검증 · 체크포인트. 잔여 92 + 격리 재시도 · 5일 예상.

**작업 4 · B60 3차 복구 (작업 1 완료 + 쿨다운 후)**:
> 미해결 25건 (격리 잔여 12 + 미매칭 13) · 신규 13D/13G 표지에서 발행사 티커 파싱. 최종 미복구 = "생존 편향 잔존" 리포트 확정.

**작업 5 · B55+ Form 4 재실행 (작업 1 완료 + 쿨다운 후 · 최후순위)**:
> 선언 UA 로 재개 · issuerCik·transactionCode · 코드 P 만 form4_buy · 대사 · first_event_date 재계산 · 진행률 체크포인트.

---

### B56·B57·B55+·B58 · 생존편향 재유입 차단 + Form 4 경로 교체

**발행**: 2026-09-03

**전제**: Fable 검수 · 1일차 수집 정상 · 티커 미복구 113 탈락 = 생존 편향 재유입 P0. 결제 금지 · biotech 독립 · 키 마스킹.

**작업 1 · B56 티커 복구 2차**:
> 1-1. EODHD exchange-symbol-list API (delisted 포함) 1회 호출 → US 폐지 심볼 명단 로컬 저장 (일 한도 20 중 1건 차감).
> 1-2. 미복구 113건 target_name 정규화 (대소문자·Inc/Corp/Ltd/plc·구두점) 매칭. 완전일치 우선 · 유사 별도.
> 1-3. queue_eodhd 갱신 · 분할 일수 재산출. 최종 미복구는 사유 + 방향 불명 명시.

**작업 2 · B57 오염 검증**:
> 2-1. EODHD 시계열 last_date ≤ form25_date + 30d 검증. 위반 시 quarantine CSV.
> 2-2. 1일차 20건 소급 적용 · 격리 n 보고.
> 2-3. 격리 종목 회사명 재매칭.

**작업 3 · B55+ Form 4 경로 교체**:
> 55 CIK submissions Form 4 → XML issuerCik·issuerTradingSymbol·transactionCode 파싱. 코드 P 만 이벤트 (B51). h3_targets form4 컬럼 → form4_buy. 대사 (기관 census 도 통일).

**작업 4 · 수집 계속 (EODHD 2일차)**:
> 잔여 7 → B56 복구 → B57 재시도. 20/day 한도 내.

**작업 5 · B58 예약 (후순위)**:
> Tiingo · Alpha Vantage 가입 필요 여부만. 실측은 H3 수집 완료 후.

---

### B37 · EODHD 2일차 (익일 7건 재개 · 자동 예약)
**미완**: 1일차 EODHD 20건 (한도 소진) · 2일차 큐 = 27-20 = **7건** 남음. 익일 재실행 시 `biotech_h3_collect_prices.py` 는 이미 처리된 티커 스킵 로직 없음 → 수동 큐 조정 or 스크립트 개선 필요.

### B55+ · Form 4 XML 파싱 재실행 (다음 세션 · SEC Archives IP 차단 해제 후)
**상황**: 2026-09-03 12:07 실행 결과 1694 accession 처리 · 파싱 0건. 원인 = `www.sec.gov/Archives/*` 엔드포인트에서 전 UA 조합 403 반환 (rate limit 트리거 · undeclared automated tool 판정). data.sec.gov (submissions API) 는 정상 접근 유지.
**재개 조건**: IP 차단 자동 해제 (통상 수시간~24시간) 대기 · 재실행 시 요청 간격 늘리고(0.5s+) UA 헤더에 email 만 포함 (SEC 공식 권고 형식).
**스크립트**: `backend/scripts/biotech_h3_form4_parse.py`

### B52 · Form 4 종목 count 정확화 (별건 · B55+ 성공 후 자동 해소 예상)
**필요성**: 이번 B52 수정으로 SC 13D (60/50 · 초과 정상) · SC 13G (298/296 · 거의 일치) 는 대사 성공 · 그러나 **Form 4: 523/1694 (-1171 부족)** · 원인 = EFTS company name search는 Form 4 filer(fund) 이름으로 색인 안 됨 (Form 4 는 issuer 관점). 정확화 방안: filer submissions API 로 Form 4 accession 확보 → 각 accession-index.json 에서 issuer CIK 추출 (55 CIK × Form 4 avg 30 = ~1650 API calls). 우선순위 판단 대기.

---

### B52~B55 · P0 2건 수정 후 수집 개시 → DONE 2026-09-02

**발행**: 2026-09-02 (이번 세션)

**전제**: Fable P0 지적 2건 (h3_targets 이벤트 컬럼 전면 0 · DELISTED 티커 공백). 수집 개시는 P0 해소 후. 결제 금지 · biotech 독립.

**작업 1 · B52 이벤트 분류 수정**:
> 1-1. 원인 진단 (form type 매칭 오류·Form 4 issuer 매핑 실패·코드 라인 인용)
> 1-2. h3_targets 재산출 (v2)
> 1-3. 통과 조건 = 합계 대사: sc13d_new 합 50 · sc13g_new 합 296 · form4_all 합 1,694 (± unmapped 별도)
> 1-4. first_event_date · accession_first_event 전 행 채움

**작업 2 · B53 폐지 티커 복구**:
> 각 DELISTED 행의 form25_accession 으로 25-NSE 문서 파싱 → 티커. 실패 시 마지막 10-K/10-Q 표지 fallback. 그래도 실패 = "미복구 · 사유" + EODHD 큐 제외.

**작업 3 · B54 대조표 정리**:
> K2 Ascent 제외 (제3자 재간접). Perceptive Credit · Farallon 부동산/크레딧 "비주식 전략" 비고. 55 vs 56 · 303 vs 302 규명.

**작업 4 · 가격 큐 확정**:
> 4-1. 시총 필터는 백테스트 단계 (문서 명시)
> 4-2. queue_yfinance (활성) · queue_eodhd (폐지 · 20건/일)
> 4-3. yfinance 빈 응답 → queue_eodhd 자동 재배정 + 사유

**작업 5 · B37 수집 개시 (작업 1~4 완료 즉시 · 승인 불요)**:
> queue_yfinance 전량 + queue_eodhd 1일차 20건 · 체크포인트 · EODHD 한도 도달 자동 중단.

**작업 6 · B55 예약 (다음 세션 가능)**:
> Form 4 XML transaction code P 필터 백테스트 전처리 추가. B51 정의 없이 백테스트 착수 금지.

---

### B55 · Form 4 transaction code P 파싱 필터 (예약 · 다음 세션 실행 가능)
**전문**: Form 4 XML 본문에서 transaction code 를 파싱해 매수(P 계열)만 이벤트로 남기는 필터를 백테스트 전처리에 추가한다. **백테스트는 이 필터 없이 착수 금지 (B51 정의).**

---

### B50 · 3-2/3-3 후속 절 (원문 잘림 · 사용자 재확인 대기)
**상황**: 작업 3 원문이 "3-1. 각 target 의 SIC 를 submissions 로 확인 · 2834/2836 외 제외." 에서 끝남. 후속 절(3-2·3-3 등 · 예: 가격 큐 파일 산출·EODHD 분할 스케줄·CSV 필터링 실행 여부) 여부 미확인. **본 지시(B52~B55) 로 대체됨 · 종료 처리 후보** (사용자 확인 필요).

---

### B49~B51 · census 종목화 + 자격 검사 + 이벤트 정의 고정 → DONE 2026-09-02

**발행**: 2026-09-02 (이번 세션)

**완료 산출물**:
- B51 · README §2 H3 이벤트 정의 고정 (신규 SC 13D + 신규 SC 13G + Form 4 매수 3종)
- B49-1 · `backend/data/h3_activist_cik_registry_add7af7.csv` (56 rows)
- B49-2 · `backend/data/h3_targets_add7af7.csv` (391 rows · sic_biotech 컬럼)
- B50-1 · SIC 2834/2836 자격 정보 columns (필터 실행은 후속 대기)

**전제**: B36 census 방향 승인 · B40 국내 3소스 제외 확정. 가격 수집 전 아래 3건 선행.

**작업 규칙**: TodoWrite · 순차 · 서버 조회 전용 · 와일드카드 금지 · SEC rate limit · 비밀값 원문 금지 · biotech 독립 이름공간.

**작업 1 · B51 이벤트 정의 고정**:
> README §2 H3 정의에 추가: "백테스트 이벤트 = 신규 SC 13D · 신규 SC 13G · Form 4 취득 거래 (transaction code P 등 매수 계열) 의 3종만. 13D/A·13G/A 정정과 Form 4 매도·기타 코드는 이벤트 제외 (census 집계에는 포함되나 신호로 쓰지 않음)." review-log 1줄.

**작업 2 · B49 종목 단위 census**:
> 2-1. CIK 등록명 대조표: 55개 기관 CIK 각각에 대해 submissions API 의 등록명을 붙인 표 산출 (backend/data/h3_activist_cik_registry_{git_sha}.csv · 컬럼: institution · cik · registrant_name · 비고).
> 2-2. 종목 단위 census: filing 대상 종목별 1행 (backend/data/h3_targets_{git_sha}.csv · 컬럼: ticker · target_cik · target_name · 관련 기관 · 이벤트 유형별 건수 (신규13D/신규13G/Form4매수 · B51 정의 적용) · 최초 이벤트 일자 · 상장 상태 · 폐지 시 Form25 accession·일자). 상장 상태 판정 근거 없는 추정 기재 금지.

**작업 3 · B50 바이오 자격 검사 · 가격 큐 확정**:
> 3-1. 각 target 의 SIC 를 submissions 로 확인 · 2834/2836 외 제외.
> ⚠ **원문 잘림**: 3-2·3-3 등 후속 절 여부 불명. 3-1 만 실행하고 실행 후 사용자에게 원문 재확인 요청.


---

## DONE

### B40 · 네이버·카카오·토스 US 폐지 커버율 실측 → DONE 2026-09-02
**완료 산출물**: 실측 결과 SOURCES.md 반영 · 3 소스 전건 FAIL (naver 0/20 · daum 0/20 · toss 0/20)

### B36 · H3 filing 실집계 (재발행 · 최우선) → DONE 2026-09-02
**완료 산출물**: `backend/data/h3_filing_census_add7af7.csv` · 총 3,115 filing · 391 고유 target · 172 폐지 · EODHD 분할 9일 · biotech 독립 스크립트 `biotech_h3_filing_census.py`

**발행**: 2026-09-02

**전문**:
> 4-1. 7개 기관 (RA Capital · Baker Bros · Perceptive · Deep Track ·
>      Farallon · OrbiMed · Redmile) 의 CIK 를 확정한다. EDGAR 회사
>      검색 사용 · 기관당 복수 CIK 가능성 확인 · 출처를 기록한다.
>      기존 sec_poller.py SEED_ACTIVISTS 에 이미 있는 기관은 그
>      CIK 를 재사용하고 출처에 "기존 seed" 라 적는다.
> 4-2. 지난 5년 (2021-09-01~2026-09-01) 의 SC 13D/13G (신규 ·
>      amendment 구분) 와 Form 4 매수 filing 을 기관 CIK 기준으로
>      전수 집계한다. filer CIK 일치 규칙 (B24 확립) 적용.
> 4-3. filing 대상 종목의 고유 티커 목록을 만들고, 각 종목의 상장
>      상태를 SEC submissions 로 확인한다 (최근 filing 존재 + Form 25
>      유무 기준 · 추정 기재 금지).
> 4-4. 산출 수치: 기관별 filing 건수 · 고유 티커 수 · 그중 폐지
>      종목 수 · EODHD 분할 수신 필요 일수 = ceil(폐지 종목 수/20).
> 산출물: backend/data/h3_filing_census_{git_sha}.csv · biotech 독립
> 모듈 경로 사용 (기존 activist 코드 수정 금지 · 읽기 참조만).
> review-log 1줄.

### B33 · FMP 403 병기 → DONE 2026-09-02

**발행**: 2026-09-02

**전문**:
> SOURCES.md 와 README §4 의 FMP 행에 "403 = 접근 제한 · 커버리지
> 자체는 미측정" 을 병기.
