# 알림 설정 (기획 폴더)

**상태:** 구현 완료 (2026-10-23 · 브랜치 feat/alert-settings · 기획 design.md · 계획 implementation-plan.md) · 범위와 결정 (2026-10-22 사용자 승인)
**목적:** 텔레그램 알림을 사용자가 화면에서 직접 켜고·끄고·줄인다. 운영자에게 env·파일 작업을 시키지 않는다.

## 사용자 결정 (2026-10-22)
- 알림 관련 페이지가 필요하다. 유용성 검증에서 제안한 설정을 사용자가 그 페이지에서 고른다.
- 고장 수리는 페이지와 따로, 0순위로 먼저 한다 (각각 작은 PR · 사용자 승인 (CLAUDE.md HOW 절) · fable 검수).

## 0순위 · 고장 수리 (수리 5건 + 실패 warning 1건)
| # | 고장 | 근거 |
|---|---|---|
| 1 | 모듈·패키지 이름 충돌: `backend/discovery/data_sources/apewisdom.py` 와 `apewisdom/` → `scheduler/cron.py:94` ImportError (서버 552회) · Crazy 6/26 · Moonshot 6/24 이후 무발송 / `reddit.py` 와 `reddit/` → 테스트 1건 skip | cron.error.log · 코드 |
| 2 | Sector Leaders `NoneType.__format__` (28회 중 26회 · 알림 없이 실패) | `backend/services/notifier.py` format_sector_leaders_alert |
| 3 | 텔레그램 400 28건: A3 본문 `mean < -5%` 를 HTML 모드로 보냄 (강한 추정) | `backend/powderkeg/triggers.py:97` · `notifier.py:139` |
| 4 | deploy-watch 오발송 5건: check step 이 건너뛰면 output 이 null, `null == '0'` 이 참 | `.github/workflows/deploy-watch.yml:55-84` · `.github/` 변경도 배포 run 을 일으킴 |
| 5 | Kill Switch 해제 API · `/lab/execution` 버튼 404: `execution` 라우터가 `backend/api/main.py` 에 미등록 | `backend/api/routes/execution.py:81-103` |
| + | 조용히 실패하는 잡 (Crazy · Moonshot · Sector Leaders) 에 실패 warning 추가 | 4개월 무음 실패 재발 방지 |

## 1순위 · 알림 설정 페이지 (기획 범위)
- 자리: ⚙️ 아래 `/admin/notifications` (1단 메뉴에 넣지 않음 · 모바일 헤더 때문)
- 알림 11묶음별 항목: 켜기·끄기 · 즉시/하루 요약 · 재발송 간격 · 최소 등급. 기본값 = 유용성 검증 권고.
- 묶음별 상태 표시: 마지막 성공 시각 · 최근 실패 (잡 실행 기록을 새로 남겨야 함)
- 저장: 새 key/value 설정 표 + 쓰기 API (지금 `backend/api/routes/settings.py` 는 GET 전용) · 읽기는 DB 먼저, 없으면 env · 인증은 기존 쿠키 세션 (`frontend/lib/auth.ts`)
- 발송부 네 곳을 모두 설정값을 읽게 바꿔야 함: api 프로세스 (powderkeg · serenity · meme · kill switch) · cron 프로세스 (crazy · moonshot · sector · vip · activist) · biotech 셸 (`backend/scripts/biotech_notify.py`) · GitHub Actions (deploy-watch · DB 를 읽을 수 없으므로 워크플로 수정으로 처리)
- 화면 패턴은 gonnim.dev /dominance 설정 화면을 따른다 (저장 피드백 문장 · 토글 즉시 반영 후 실패 시 되돌림 · 알림 띠).

## 2026-10-22 유용성 검증 권고 (기본값 후보)
| 묶음 | 2주 건수 | 권고 |
|---|---|---|
| ① Serenity 작업 성공 | 90 | 성공 끄기 · 실패만 |
| ② 화약고 DO NOT TOUCH | 56 | 리스트·보유 종목만 critical · 나머지 하루 요약 |
| ③ 화약고 후보 | 9 (+실패 28) | A1·A5 유지 · A2 끄기 · A3 끄기 또는 수리 |
| ④ 티켓 승인 · 12개월 재평가 | 0 | 재평가 유지 · 승인 끄기 |
| ⑤ VIP | 15 | 7일 간격 또는 상태 변화만 |
| ⑥ Activist | 16 | STRONG 이상만 |
| ⑦ Sector · Crazy · Moonshot | 2 · 0 · 0 | 수리 후 유지 또는 끄기 |
| ⑧ meme | 562 | ERUPTING 즉시 · BLAZING 하루 요약 · 같은 종목 24시간 |
| ⑨ SNIPER · Kill Switch | 0 | 유지 |
| ⑩ biotech | 0 | 유지 |
| ⑪ 배포 미시작 | 5 (오발송) | 조건 수리 |

## 근거 (로컬 · git 제외)
- `docs/plans/biotech/fable-bundles/20261022_observe/alerts-usefulness-report.md` (유용성 검증 전문)
- 같은 폴더 `2026-10-22-alerts-*.md` · `2026-10-22-usefulness-*.md` (Fable 질의·답변)
