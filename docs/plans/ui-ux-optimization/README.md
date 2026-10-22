# 사이트 UI/UX 최적화 (기획 폴더)

**상태:** 기획 전 · 범위와 결정만 기록 (2026-10-22 사용자 승인)
**기준:** gonnim.dev /dominance (운영 콘솔) · /sangsik (공개 사이트) 를 최적화한 방식 (결정 D61 · 2026-10-21). 규칙 요약은 로컬 `docs/plans/biotech/fable-bundles/20261022_observe/gonnim-ui-rules.md` (git 제외). 원본은 Next 16 · Tailwind 4 이므로 Next 14 · Tailwind 3 에 맞춰 옮긴다.

## 사용자 결정 (2026-10-22)
- 순위는 아래 표대로 한다. 0·1순위 (알림) 는 `docs/plans/alert-settings/` 에서 다룬다.
- `docs/design-rules.md` 를 gonnim 기준 (강조색 틸 하나 · 본문 17px · 그림자 없음 · 반경 8·14·알약 · 내부 코드 숨김) 으로 개정한다.
- 버전 번호는 `frontend/package.json` 과 `backend/api/main.py` 둘 다 쓴다 (화면 변경 → frontend · 서버 변경 → backend).
- 순위마다 기획 → Fable → 승인 → 배포.

## 순위
| 순위 | 항목 | 현재 문제 (2026-10-22 감사 · 비로그인 라이브) |
|---|---|---|
| 2 | 홈을 "오늘" 화면으로: 오늘의 급등 후보 · 오늘 할 판단 하나 · 시스템이 한 일 (실패 위) | 홈에 오늘 할 일 없음 · 컨트롤 타워 4칸 하드코딩 "— (연결 대기)" (`frontend/app/page.tsx:63`). 홈 설계 출처 `docs/plans/toss-tradebot-tobe/identity.md` · `stage1-optimization.md` 개정 또는 대체 필요 |
| 3 | 메뉴 15 → 5 (안: 오늘 · 후보 · 보유 · 기록 · 설정) · 한글 이름 · 옛 주소 유지 | L1 8 + L2 7 · 영어+이모지 (`frontend/components/layout/AppNav.tsx`) · 모바일 헤더 218px = 화면 26% (측정값) · sticky (`frontend/app/layout.tsx:30`) |
| 4 | 로그인 하나 (헤더) · 비로그인 401 비노출 · 빈 상태 문구 | 페이지마다 다른 로그인 칸 ("SNIPER_API_TOKEN 입력") · 핵심 화면 4개 비어 보임 · 401 노출 (측정값) |
| 5 | 문구: 내부 코드 숨김 · 영어 용어는 한글 이름 표 한 곳 · 상태 문구에 다음 동작 | "Phase F" · "Week 3 T64~T66" · "Phase J" · 문서 경로 노출 |
| 6 | 시각 통일 + `docs/design-rules.md` 개정 | 지금 규칙 (amber·sky · 16px · 그림자 허용) 과 화면이 서로 어긋남 (cyan · purple · `text-[10px]`) |
| 7 | 모바일: 터치 44px · 가로 스크롤 0 · /powderkeg 배너 접기 | /powderkeg 2,202줄 · 높이 24,049px · 표 1018px 가로 스크롤 · /principles 503px (측정값) |
| 8 | 정리: 백업 폴더 · 실험/운영 경계 · `/admin/settings` 읽기 표 | `frontend/app/influencer/serenity-hunter/_backup-20260805-094738/` |

검증: chrome-devtools 데스크톱·모바일 렌더 · 콘솔 오류 0 · 로그인 후 화면 확인.

## 근거 (로컬 · git 제외)
- `docs/plans/biotech/fable-bundles/20261022_observe/gonnim-ui-rules.md` (옮겨 쓸 규칙 요약)
- 같은 폴더 `2026-10-22-uiux-*.md` (Fable 질의·답변)
