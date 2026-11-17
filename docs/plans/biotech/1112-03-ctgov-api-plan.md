# 1112-03 계획 — 임상 등록부 주간 사본을 공식 API(ClinicalTrials.gov v2)로 바꿈

- 작성: 2026-11-17 · 상태: 사용자 승인(11/17 「1112-03 계획 승인」) · Fable 1차 조건부 GO 막음 1~4 · 권고 2~7 반영 · 서버 접근 확인 200 · Fable 2차 GO
- 결정 기록: 11/16 원인 확인(AACT 옛 내려받기 주소 410 · 사본은 계정 로그인 뒤로 옮겨 감 · 교훈 #10) → 11/17 사용자 「1112-03 ②」(공식 API로 바꿈) → 11/17 계획 요약 승인
- 관련: 교훈 #8 · #10 · `backend/scripts/biotech_h69_aact_weekly.py`

## 0. 목표와 끝 기준
- 월요일 06:00 주간 잡이 계정 · 비밀값 없이 임상 자료를 다시 만든다.
- 출력 파일(`ctgov_snapshot.json` · 날짜별 사본) 칸과 값 모양은 지금과 같다. 읽는 곳 5곳(api/routes/biotech.py · biotech_h50_ct_upcoming.py · biotech_h6_aact_theme_extract.py · biotech_auto_category.py · biotech_h48v3_daily_server.sh)은 고치지 않는다.
- 끝 기준: 5절 비교 기준 통과 · 6절 시험 통과 · 배포 뒤 첫 실행 로그에 「출처 ctgov_api_v2 · study N · ticker M」 한 줄과 새 날짜별 사본.

## 1. 바꾸는 범위
| 단계 | 지금 (AACT) | 바뀜 (공식 API) |
|---|---|---|
| 1) 주소 확인 | 최근 10일 zip 1바이트 범위 확인 | 없앰. 대신 `GET /api/v2/version` 으로 dataTimestamp 를 읽는다 |
| 2) 내려받기 · 3) 무결성 | 2.4GB zip · unzip 시험 | 없앰 |
| 4) 후보 사전 | 그대로 | 그대로 |
| 5) 파싱 · 맞추기 | 모든 후원사 이름 훑기 → SponsorMatcher | 후보 이름 · 별칭으로 검색 → 받은 후원사 이름에 같은 SponsorMatcher |
| 6) 저장 · 사본 · 자동 분류 · SEC 단계 | 그대로 | 그대로 (`aact_snapshot_date` = API dataTimestamp 날짜 · `source: "ctgov_api_v2"` · `api_data_timestamp` 칸 더함) |

AACT 코드(주소 확인 · zip · 파싱)는 지우지 않고 남기되 주간 잡에서 부르지 않는다(되돌리기용 · 다음 정리 때 지움). `--source aact` 옵션은 만들지 않는다(원본이 막혀 시험할 수 없음).

## 1-1. 먼저 서버 접근 확인 (Fable 1차 막음1)
- 2026-09-20 서버 IP 는 이 API 에서 403 을 받았고, 그래서 AACT 로 바꿨다(PENDING.md 「접근 확정」). 구현 전에 서버에서 `biotech_h69_source_check` 읽기 1회(사용자 승인 · 사용자 명령)로 「CT.gov v2 studies」가 200 인지 본다.
- 결과(11/17 13:08 KST · 사용자 승인 · 사용자 명령 실행): 「CT.gov v2 studies」 HTTP 200. 다만 `pageSize=1` 한 번이므로 배포 뒤 첫 실행 보고에 응답 코드별 개수와 총 요청 수를 적는다.
- 403 이면 이 계획은 서버에서 성립하지 않는다. 우회(IP 교체 · 다른 서버 실행)는 하지 않고 사용자에게 다시 정해 달라고 올린다(README 「우회 금지」).

## 2. 받기
- 검색어(Fable 1차 막음2): 공식 API 검색은 낱말이 모두 들어 있어야 걸린다(11/17 실측: 「Pfizer」 6115건 · 「Pfizer Inc.」 707건 · 「VERTEX PHARMACEUTICALS INC / MA」 0건). 그래서 후보 이름에서 설립 주 표기(`/DE/` · `/ MA` 등)와 법인 접미어를 뗀 이름(`biotech_name_match.normalize_name` 과 같은 규칙)으로 검색한다.
- 질의: 후보마다 정리한 이름 한 번, 그리고 그 후보 티커의 별칭 두 파일(`docs/plans/biotech/data/sponsor_aliases.csv` · `sponsor_aliases_radar.csv` · 지금 `_load_aliases` 가 읽는 그대로)마다 `query.spons=<정리한 이름>` 한 번. 같은 검색어는 한 번만 보낸다.
- 이름별 결과 0건은 따로 세어 로그 · 보고에 낸다(0건도 200 으로 와서 오류가 나지 않는다).
- 받는 칸(`fields=`): NCTId · BriefTitle · OfficialTitle · OverallStatus · Phase · PrimaryCompletionDate(+type) · CompletionDate(+type) · LastUpdatePostDate · EnrollmentCount(+type) · StudyType · LeadSponsor · Collaborator · Condition · ConditionBrowseModule mesh · Intervention(name · type) · DesignAllocation · DesignMasking · PrimaryOutcome(measure · timeFrame). 결과 칸(resultsSection)은 받지 않는다.
- `pageSize=1000` · `nextPageToken` 을 끝까지 따른다. 요청 사이 1.5초. 질의당 쪽 상한 20 — 넘으면 잡 전체를 멈추고 파일을 쓰지 않는다(그 이름만 건너뛰지 않음 · 원인 알림).
- 같은 NCT 가 여러 질의에 걸리면 한 번만 둔다.
- 요청 머리: 지금 쓰는 HEADERS(User-Agent · From) 그대로.
- 분당 한도는 구현 첫날 공식 문서로 확인해 상수에 근거 줄을 단다(지금은 추정).

## 3. 맞추기와 값 옮기기
- 시험마다 lead 후원사 이름 → `SponsorMatcher.match` · 안 맞으면 collaborator 이름들 → 맞으면 role=collaborator. 지금 규칙(lead 우선 · 별칭 · alias_sub)과 같은 순서. 검색에 걸렸어도 규칙에 안 맞으면 버린다.
- 값 모양:
  - phase: 목록 → `/` 로 잇기(`["PHASE2","PHASE3"]` → `PHASE2/PHASE3`) · 빈칸과 `NA` 는 지금 AACT 값과 같게(9/28 로컬 사본: 빈칸 53 · `NA` 4 · 구현 때 11/12 사본으로 다시 확인 · 대응표를 시험에 넣음).
  - overall_status · *_date_type · enrollment_type · study_type · allocation · masking: API 대문자 값 그대로(AACT 와 같은 모양 · allocation `NA` 302건 포함 대응표).
  - 날짜(Fable 1차 막음3): AACT 사본 날짜는 모두 `YYYY-MM-DD` 이고 월만 있는 날짜는 그 달 마지막 날로 들어 있다(9/28 사본 31일 308 · 30일 194). API 의 `YYYY-MM` 은 그 달 마지막 날 `YYYY-MM-DD` 로 바꾼다. 그대로 두면 `/fr6c/confirm` 의 `date.fromisoformat` 이 400 을 내고 days_to 가 최대 30일 당겨진다. 규칙은 구현 때 11/12 사본으로 다시 확인한다. days_to 는 지금 함수로 계산.
  - enrollment: API 는 숫자로 주지만 지금처럼 문자열로 둔다.
  - 질환 · MeSH 목록은 API 순서 그대로 두고, 비교 때 순서까지 대조한다(카드 분류가 첫 항목을 씀 · biotech.py:518-523).
  - 길이 자르기(brief 300 · official 500 · outcome 300/200 · 1차 목표 3개)는 지금과 같게.
- 맞추기 진단(`_write_match_report`)과 Jaccard 검수 표는 받은 후원사 이름 안에서 만든다(진단용 · 판정 영향 없음 · 범위가 줄어든다고 보고서 머리에 적음).

## 4. 실패 처리 (교훈 #10 반영)
- 200 아닌 응답(401 · 403 · 404 · 410 · 429 · 5xx)과 연결 오류는 3회 다시 시도(5xx · 연결 오류만 · 10초 간격) 뒤 멈춘다. 4xx 는 다시 시도하지 않는다.
- 멈추면 새 파일을 쓰지 않는다(반쪽 결과 없음). 지난 사본 그대로. critical 알림 1통에 단계 · 응답 코드 · 마지막 질의 순번을 적는다.
- API dataTimestamp 가 실행 시각보다 7일 넘게 늦으면 warning 알림 1통(파일은 씀).
- 결과가 0 study 이거나 지난 사본보다 study 수가 30% 넘게 줄면 쓰지 않고 critical(이름 검색이 통째로 깨진 경우를 막음).
- 지난 사본에 시험이 있던 종목이 0건이 되면 쓰지 않고 critical 에 그 종목 수를 적는다(한 종목이 통째로 빠지는 것을 막음 · 총수 30% 가드로는 못 잡음).
- 200 인데 JSON 이 아니거나 `studies` 열쇠가 없으면 실패로 다룬다.
- 저장은 임시 파일에 쓴 뒤 바꿔치기(SEC 명부 방식 · aact_weekly.py:628-630)로 한다.

## 5. 배포 전 비교 (이 맥 · 공개 API · 서버 안 건드림)
- 대조 자료 가져오기: 서버의 `var/biotech/ctgov_snapshot_20261112.json` 과 11/12 실행 때 쓴 후보 CSV(`biotech_candidates_v3_*.csv` 가운데 11/12 18시 전 최신)를 사용자 명령 `scp` 로 이 맥 scratchpad 에 받는다(읽기 · 저장소에 넣지 않음).
- 같은 후보 목록으로 새 코드를 돌려 11/12 사본과 대조한다.
- 기준(Fable 1차 막음4 · 판정 칸 기준):
  1. lead 이고 days_to 0 이상인 시험(시간 상태 판정에 쓰이는 시험)은 전부 다시 잡힌다. 빠진 것은 하나씩 까닭을 적는다.
  2. 전체 NCT 가운데 95% 이상이 다시 잡힌다.
  3. 종목 집합이 같다(수만이 아니라 종목이 같음).
  4. 종목별 가장 가까운 예정 시험(NCT · 날짜)과 `sponsor_active_counts` 가 종목별로 같다.
  5. NCT 별 ticker · role 이 같다.
  6. 같은 NCT 의 칸 값이 다르면 칸별 개수와 목록을 낸다. 날짜 · 상태 차이는 `last_update_posted_date` 가 11/12 뒤인 것만 갱신으로 인정하고, 그 밖은 하나씩 설명한다. 질환 · MeSH 는 순서까지 본다.
  7. 새로 더 잡힌 NCT 는 목록으로 낸다(맞추기 규칙 통과분).
- 값 모양이 같다는 결과가 나오면 봉인 설계 6절(「주간 단계의 ctgov_snapshot.json」)은 설계 변경이 아니라 해석 기록으로 처리하고, 병합 승인 질의 때 PENDING.md 영구 규칙 한 줄(「자료 출처를 공식 API 로 받되 파일 · 칸 · 값은 같다」)을 올린다. 값 모양이 달라지면 PRD 10절 절차로 따로 승인받는다.
- 기준에 못 미치면 배포하지 않고 빠진 시험과 까닭을 보고한다.
- 비교 결과 파일은 저장소 밖(scratchpad)에 두고 요약 숫자만 보고 · PR 에 적는다(종목 · 금액 없음 · 공개 저장소).

## 6. 시험 (`backend/tests/test_biotech_ctgov_api.py` 새 파일 · 네트워크 없이 가짜 응답)
1. 값 옮기기: phase 목록 잇기 · 빈칸 · `NA` 대응 · 날짜 종류 · 월 단위 날짜 → 그 달 마지막 날 · enrollment 문자열 · 길이 자르기 · 상세 칸이 지금 출력 칸 이름과 같음.
2. 쪽 넘기기: nextPageToken 3쪽을 끝까지 · 쪽 상한 넘으면 잡 전체 멈춤 · 파일 안 씀.
3. 맞추기 · 검색어: 설립 주 표기 · 법인 접미어 뗀 검색어 · 별칭 두 파일 · lead 맞음 · collaborator 만 맞음 · 검색엔 걸렸지만 규칙 불일치는 버림 · 같은 NCT 한 번 · 0건 이름 세기.
4. 실패: 410 · 429 · 403 즉시 멈춤 · 5xx 3회 뒤 멈춤 · 200 인데 JSON 아님 · `studies` 없음 · 멈추면 파일 안 씀 · 알림 문구에 코드.
5. 줄어듦 가드: 0 study · 30% 넘게 줄면 · 지난 사본에 있던 종목이 0건이면 안 씀 · 임시 파일 바꿔치기.
5-1. 판정 경로: 새 출력으로 `biotech_fr6c.attribute_stage` 가 오류 없이 같은 귀속을 냄 · 월 단위 날짜의 days_to 가 지금과 같음.
6. 출력 모양: 지금 시험(`test_biotech_p3a_aact.py`)이 보는 칸이 새 출력에도 있음 · 읽는 곳 5곳이 쓰는 칸 목록과 대조.
- 커밋 hook(biotech 묶음)에 새 시험이 들어가는지 확인한다.

## 7. 순서와 승인
0. 1-1 서버 접근 확인(사용자 승인 · 사용자 명령). 403 이면 여기서 멈추고 사용자에게 다시 올린다.
1. 이 문서 커밋 · Fable 검토(조건부면 고쳐 한 번 더). 교훈 #10 은 PR #215 에 있으므로 #215 를 먼저 병합한다.
2. 구현 브랜치 · 6절 시험 먼저 → 구현 → 전체 biotech 시험 · compileall.
3. 5절 비교 → 결과 보고 → 사용자 승인.
4. Fable 병합 승인(diff SHA) → 사용자 병합 → 배포(피할 시각 05:55–06:45 · 09:00–09:15 · 16:40–17:15 · 18:00 앞뒤 밖).
5. 첫 실행: 11/23(월) 06:00 정기 실행을 기다리거나, 사용자 승인으로 수동 1회 — 배포 보고 때 정해 주십시오.
6. 버전: 서버 변경이므로 `backend/api/main.py` 버전을 올린다.

## 8. 하지 않는 것
- 후보 · 점수 · 판정 · 알림 규칙 변경 없음(출력 모양 그대로). 비교에서 판정이 달라질 차이가 보이면 따로 보고하고 승인받는다.
- AACT 계정 가입 · 비밀값 추가 없음.
- 읽는 곳 5곳 수정 없음.

## 9. 위험
| # | 위험 | 막는 방법 |
|---|---|---|
| 1 | 후원사가 후보 이름과 다르게 등록돼 검색에 안 걸림 | 별칭으로 넓힘 · 5절 95% 기준 · 빠진 목록 보고 |
| 2 | API 자료가 며칠 늦음 | 자료 시각 칸 · 7일 넘게 늦으면 warning |
| 3 | 분당 한도 | 1.5초 간격 · 429 즉시 멈춤 · 한도 근거 상수 |
| 4 | API 모양 변경 | 출력 모양 시험 · 0건 · 30% 줄어듦 가드 |
| 5 | 이름이 너무 넓어 쪽이 끝없이 나옴 | 질의당 쪽 상한 20 · 넘으면 잡 전체 멈춤 |
| 6 | 서버 IP 가 이 API 에서 403 (09/20 기록) | 1-1 서버 확인 먼저 · 403 이면 멈추고 사용자 결정 · 우회 금지 |
| 7 | 법인 접미어가 붙은 검색어로 결과가 크게 줄어듦 | 정리한 이름으로 검색 · 0건 이름 세기 |
| 8 | 월 단위 날짜 모양 변화로 판정 경로 오류 | 그 달 마지막 날로 바꿈 · 판정 경로 시험 |

AACT 코드를 지우는 다음 정리 때 `biotech_h6_aact_theme_extract.py:50` 이 h69 함수를 가져다 쓰는지 먼저 확인한다.
