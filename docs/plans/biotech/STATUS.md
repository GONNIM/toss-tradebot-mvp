# Biotech Catalyst Radar · 상태판 (사용자 진입점)

> **📖 용어집 보기**: [`GLOSSARY.md`](GLOSSARY.md) · 코드 · 가설 · 상태 정의 · 첫 등장 시 (뜻) 병기
> **🚀 배포 절차**: [`DEPLOY.md`](DEPLOY.md) · 운영 구조 · 배포 명령 · 롤백
> **⚙️ 자동 갱신**: 본 상태판은 `biotech_h57b_status_gen.py` 가 매일 자동 생성 · '가능성 지도 (수동)' 절만 손 편집

## 오늘 알아낸 것 (5줄 · 쉬운 말 · 자동)

1. **임상 결과 발표 한 달 전에 사면 평균 +1.62%** (H1b (Phase 3 (3상 임상) guidance) · 표본 4611건 · CI (신뢰구간) [+0.73%, +2.61%] · **CI 하한 > 0 = 우연 아님** · 임계 +2% 미달)
2. **발표 직후 한 달은 -0.74%** (H8 검정 3 · CI 상한 -0.07% · sell_supported=True · **뉴스에 팔아라 격언 데이터로 확인**)
3. **소문 채널 신호 유무 (WP54-3 확정 · 채널 4.5/5 (AACT 옵션 미포함 · Form 4 P 병합 · ch1~ch5 실채움) · 2026-11-15 재실행 금지)**: 신호 있음 1940건 mean **+2.47%** [+1.07%, +4.06%] · 신호 없음 2671건 mean **+1.00%** [-0.11%, +2.16%] · **차이 +1.47%p** CI [-0.37%p, +3.38%p] · 판정: **불지지** (차이 CI 하한 < 0) · 단 **신호 있음 집단만 CI > 0 확정**
4. **뉴스 보고 사는 전략 2건은 효과 없음**: H5 (해외→국내) 폐기 · H3 (activist 전체) 폐기
5. **오늘의 순위표 · 소문 확인은 화면 3탭** (`/radar` · `/rumor` · `/map`) · 최신: `radar-v1.3-20260914.md` · `2026-09-14.md` · **소액 실전 규칙 8항 적용**

🟡 WP63-3 F4 견고성: **유보 (pending · 결론 5분류) 확정** · (a) 미해결 (companyfacts dei 부재 · 시총 부재 이벤트 98건 미판정) · (d) 13D 중복 제외 CI 하한 < 0 · **F4 검정 과거 재실행 금지 · 2026-11-15 전향 평가 (WP56) 까지 유보**

**최종 갱신 (자동)**: 2026-09-14 · git_sha (git 커밋 짧은 해시) `add7af7`

**Phase A (검증 단계 · 알파 존재 여부 판정) 종결 (Fable 최종 검수 통과)**: `PHASE-A-FINAL.md` 종결본 참조 (2026-09-14 동결)
**Phase B (UI 배포 단계)** = 3탭 + 용어집 · WP55 최소 FastAPI 뷰어 `biotech_h55_viewer.py` (로컬 :8765)
**Phase C (확장 단계) 진행 중** = 소문 채널 완비 진척 · h57 PubMed 200/307 · h58 Preprint 200/307 · 실채움 채널 4.5/5 (AACT 옵션 미포함 · Form 4 P 병합 · ch1~ch5 실채움)

---

## 가설별 상태 (자동)

| 가설 | 상태 | 핵심 수치 | 다음 액션 | 최신 리포트 |
|---|---|---|---|---|
| **H1a** · FDA (미국 식약처) AdCom (자문위 회의) 사전 공지 | 유보 후보 | 회의일 87% · 매핑 2/26 | Big Pharma 이름 매핑 확장 | `H1a-design.md` |
| **H1b** · Phase 3 (3상 임상) guidance | **완주 풀 유의 · 임계 미달** | n=4611 · mean **+1.62%** · CI [+0.73%, +2.61%] | 임계 통과 아님 · **작지만 실재** | `verification/H8/H8-H1b-full-report-20260914.md` |
| **H2** · 테마 클러스터 확산 | 미착수 | — | 코드 룰 확정 | `README.md §2 H2` |
| **H3** · Activist 신규 13D/13G | 폐기 (관문 2 · alpha_pass=False) | 이벤트 346 · 13D 30d +4.43% CI 하한 <0 | H3b 로 계승 | `verification/H3/H3-report-20260912.md` |
| **H3b** · 소형주 activist 검정 | 부분 관측 · 임계 미달 | 300M-1B/fund/180d · n=42 · mean +2.85% | 표본 확대 · Fable 옵션 승인 | `design/H3b-design.md` |
| **H4** · Reddit 소셜 첫 언급 | 전향 수집 중 (RSS만) | apewisdom 매치 6/300 | 60일 게이트 후 백테스트 | `H4-design.md` |
| **H5** · 해외 촉매 → 국내 연계 | **종결 (폐기)** | pre +0.22% · imm -0.52% · sus -0.67% | 재개 조건 = 촉매 풀 확장 | `verification/H5-report-20260912.md` |
| **H6** · 분야 순위 point-in-time | 관문 3 대기 · dry-run 완결 | 8세트 46분기 · 상위 3분위 2020Q1 · 소속 38 | membership 확장 (WP27-2) | `H6-design.md` |
| **H7** · 초기 매집 후 분할 매도 | 설계 완료 · 대기 | 사전 커밋 13항 | H6·H8 알파 확인 후 실행 | `H7-design.md` |
| **H8** · 소문 지수 선행성 | **부분 풀 지지 (검정 3)** | post -0.74% CI 상한 -0.07% · sell_supported=True | 채널 확장 후 WP54-3 재검 | `verification/H8/H8-signal-presence-full-2026-09-14.md` |
| **H3-F4 v3** · Form 4 매수 추종 (별도 · WP63-3 견고성) | **유보 (pending)** (5분류 · 과거 재실행 금지) | WP63-3 F4 견고성: **유보 (pending · 결론 5분류) 확정** · (a) 미해결 (companyfacts dei 부재 · 시총 부재 이벤트 98건 미판정) · (d) 13D 중복 제외 CI 하한 < 0 · **F4 검정 과거 재실행 금지 · 2026-11-15 전향 평가 (WP56) 까지 유보** | 2026-11-15 전향 평가 (WP56) 재현 시 확인 승격 | `verification/H3/H3-F4-report-v3-*.md` |
| **Security** · 자격증명 가드레일 | WP8 (설정 강제 부트스트랩) | 156/156 (+2 skip) pytest · SEC WP23 헤더 | 신규 스크립트 자동 강제 | `Security-Audit.md` |

---

## Phase C 순서 (배포 후 첫 작업 = 1)

1. **소문 채널 완비 (진행 중)**: h57 PubMed 잔여 107 CIK 재시도 · **Form 4 채널 e 실채움 (WP28-2)** · CT.gov 상태 변경 (AACT 스냅샷 2~4개 · 2.5GB × 4 = 10GB) → **WP54-3 재실행** (규칙 동일)
2. **H6 소속 확장** (CT.gov 스폰서 전체 재매핑) → 재검
3. **반자동 티켓 탭** (실전 기록 화면화 · trades_manual.csv 편집기)
4. **H3b 전향 검정** (2026-09-14 이후 신규 13D · 소형~중형)
5. **파산 종목 가격 복구** (원장 v6 · B60 파산 8건)

---

## 사용자 액션

- [ ] **crontab 등록** (필수 · 로컬 macOS · 사용자 액션):
  ```bash
  crontab -e
  # 매일 KST 07:00 (UTC 22:00 전날) · 파이프 실행
  0 22 * * * /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily.sh >> /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/data/biotech/community_daily/cron.log 2>&1
  # 매월 15일 KST 08:00 (UTC 23:00 14일) · 60일 전향 평가
  0 23 14 * * cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp && backend/venv/bin/python -m backend.scripts.biotech_h56_forward_eval --window 60d >> backend/data/biotech/community_daily/forward.log 2>&1
  ```
  확인: `crontab -l | grep biotech`

- [ ] **로컬 뷰어 실행**: `backend/venv/bin/python -m backend.scripts.biotech_h55_viewer` → 브라우저 `http://127.0.0.1:8765`

- [ ] **실전 기록 (선택)**: `backend/data/biotech/trades/trades_manual.csv` 에 매수/청산 기록 (18열 헤더)

---

## 가능성 지도 (WP35·WP36 · 2026-09-13)

**규칙**: "정답 찾기 아니라 가능성 돌파" · 확증 트랙에서 폐기된 가설도 방향은 여기 유지 · 재도전 경로는 사전 등록 (H3b 예)

---

---

---

---

---

---

---

---

---

---

## 진입 문서 (자동)

- `STATUS.md` (본 문서 · 사용자 진입점 · 자동 갱신)
- `PHASE-A-FINAL.md` (2026-09-14 종결본 · 동결)
- `GLOSSARY.md` (용어집)
- `DEPLOY.md` (배포 절차서)
- `PENDING.md` (미완 지시 원문 보관)
- `INDEX.md` (문서 목록·용도·상태)
- `verification/H8/H8-signal-presence-full-2026-09-14.md` (WP54-2 채널 5/5 리포트)
- `verification/H8/H8-H1b-full-report-20260914.md` (H1b 완주 풀 리포트)
