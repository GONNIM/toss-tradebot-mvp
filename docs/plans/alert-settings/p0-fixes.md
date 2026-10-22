# 0순위 · 알림 고장 수리 계획 (2026-10-22 사용자 승인)

**결정:** 계획 승인 · Kill Switch 해제 = (b) sniper 라우터에 인증 걸린 API · Crazy·Moonshot 은 고친 뒤 다시 돌림.
**배포:** CLAUDE.md 멀티 Phase 규칙에 따라 한 브랜치 (`fix/alerts-p0`) 에 건별 커밋 → PR 1개 · 배포 1회.
**버전:** backend `backend/api/main.py` 0.1.1 · frontend `frontend/package.json` 0.1.1.

| # | 고장 | 고친 방법 |
|---|---|---|
| F1 | `data_sources/apewisdom.py` 를 같은 이름 패키지 `apewisdom/` 가 가려 `scheduler/cron.py` 의 `ApewisdomClient` import 실패 (Crazy 6/26 · Moonshot 6/24 이후 무발송) | 내용을 `apewisdom/aggregate.py` 로 옮기고 `__init__.py` 에서 export |
| F1b | `data_sources/reddit.py` 를 `reddit/` 가 가림 · `RedditClient` 런타임 미사용 | `reddit.py` 와 skip 된 테스트 삭제 · `implementation-roadmap.md` 갱신 |
| F2 | Sector Leaders 과열 종목 `entry_price=None` 에서 형식 오류 (28회 중 26회) | None 칸 "-" · 비율 부호 정리 |
| F3 | A3 본문 `mean < -5%` 가 HTML 모드에서 400 (28건) | "미만" 글자로 · HTTP 오류 응답 본문 로그 (토큰 URL 제외) |
| F4 | deploy-watch 가 배포 대상 없는 PR 에도 미시작 알림 (건너뛴 step output null) | 두 step 조건에 `deployable == '1'` 추가 |
| F5 | Kill Switch 알림의 해제 안내가 404 (execution 라우터는 인증 없는 라우트가 많아 의도적으로 미등록) | `GET /api/v1/sniper/kill-switch/status` · `DELETE /api/v1/sniper/kill-switch` (관리자 세션 또는 X-API-Token) · 알림 본문과 화면 호출 경로 갱신 |
| F6 | Crazy · Moonshot · Sector Leaders 잡이 실패해도 알림 없음 | 잡 실패 시 하루 1회 warning (마스킹 → 200자 → HTML escape · 발송 성공 시에만 기록) |

## 남은 것
- Kill Switch **발동** 버튼 (`frontend/app/lab/execution/page.tsx`) 은 여전히 옛 경로라 동작하지 않음 (범위 밖 · 사용자 결정 대기).
- 다른 알림 본문의 HTML escape (예: 종목명 `F&F`) 는 1순위 알림 설정 페이지 작업 때 일괄 검토.
- 서버 `LLM_PROVIDER` · 유니버스 크기 조회 (재가동 비용 확정: 외부 호출 약 826회/일 · LLM 13~26회/일 추정).

## 배포 뒤 확인 (조회만)
- 다음 실행의 `cron.error.log` 에 `ApewisdomClient` ImportError 가 없음 (crazy 06:30 · sector 09:05 · moonshot 16:50 · sector 17:05).
- 텔레그램 발송 로그에 Crazy · Moonshot · Sector Leaders 제목이 있음.
