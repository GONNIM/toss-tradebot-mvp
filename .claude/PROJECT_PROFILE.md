# PROJECT_PROFILE

| 항목 | 값 |
|---|---|
| 프로젝트 | toss-tradebot-mvp (`/Users/gonnim/Project-MVP/Source/toss-tradebot-mvp`) |
| 판정 단계 | B 진행 · 근거: 최근 30일 커밋 262건, biotech P4-1~P4-4 기능 개발 진행 중 (2026-10-21 실측) |
| 하위 분리 | 없음 (backend·frontend 가 한 서비스) |
| 스택 | backend: Python 3.12 · FastAPI 계열 · SQLAlchemy/alembic · `backend/venv` / frontend: Next.js 14 · TypeScript · Tailwind · npm (dev 포트 4000) |
| 문서 | `CLAUDE.md`, `.claude/context/project-rules.md`, `.claude/lessons-learned.md`, `docs/plans/<주제>/`, `docs/design-rules.md`, `docs/operations/` · PRD·ADR 단일 파일 없음(주제별 계획서로 대신) |
| 테스트 | biotech 묶음: `cd backend && venv/bin/python -m pytest -q tests/test_biotech_*.py` (640 통과 · 14초) / 전체: `cd backend && venv/bin/python -m pytest -q` (1309 통과 · **21 실패** · 211초 · 2026-10-21) |
| 린트 | backend: `python3 -m compileall -q -x venv backend` (CI validate 와 같음) · ruff 는 venv 미설치 / frontend: `cd frontend && npx tsc --noEmit` · eslint 설정 없음 |
| 배포 | GitHub Actions `.github/workflows/deploy.yml` — main push 시 자동(문서·`.claude/` 변경은 제외) → optimus8.cafe24.com · 수동 fallback 은 프로젝트 스킬 `deploy-optimus8` |
| 원격 저장소 | `git@github.com-gonnim:GONNIM/toss-tradebot-mvp.git` · **공개(PUBLIC)** · 비밀 파일 미추적 확인(2026-10-21) · `.git/hooks/pre-commit` gitleaks |
| 화면 작업 | 있음 · frontend-reference 부착(설치된 것: chrome-devtools, firecrawl) · 디자인 기준은 `docs/design-rules.md` |
| 프로필 | **공용** — thetak(`/Users/gonnim/.claude-thetak`) · naver(`/Users/gonnim/.claude-profiles/naver`) 어느 쪽에서도 연다. intake 는 thetak 에서 실행 |
| intake 일자 | 2026-10-21 |

## 배치한 역할
| 역할 | 모델 | 도구 | 이유 |
|---|---|---|---|
| po | opus | Read, Grep, Glob, Bash, Edit, Write, Agent | 오케스트레이터 · planner 겸임(계획서는 기존 승인 절차로 작성) |
| backend | sonnet | (tools 줄 없음 · 세션 도구 전체 상속) | Python 구현 · alembic 마이그레이션 겸임(db-migrator 미배치). 프로필마다 MCP 가 달라 상속으로 둠 |
| frontend | sonnet | (tools 줄 없음 · 세션 도구 전체 상속) | Next.js 구현 · chrome-devtools 렌더 확인. 상속 이유 동일 |
| tester | sonnet | Read, Grep, Glob, Bash, Edit, Write | 테스트 작성·실행 · 수정은 테스트 파일만 |
| reviewer | opus | Read, Grep, Glob, Bash | 지적만 |
| fable | fable | Read, Grep, Glob, Bash | biotech 설계·봉인·PR 검수자. GO·조건부 GO·NO-GO 판정과 "병합 승인됨 · PR #번호" 발행. 배포 실행은 하지 않음 (2026-10-21 추가) |

미배치: planner(po 겸임), db-migrator(backend 겸임), devops(배포 자동화가 이미 있음), security-auditor(실주문 인증 변경 시 일회성으로 검토 요청).

## 설치 제안 (미설치)
| 도구 | 쓸 역할 | 이유 |
|---|---|---|
| ruff (backend venv) | backend, tester | pyproject 에 dev 의존성으로 적혀 있으나 venv 에 없음. 설치 후 hook 의 backend 검사에 추가 검토 |
| playwright-mcp | tester | E2E 가 수용 기준이 될 때만(현재 아님) |
| naver 프로필 MCP(chrome-devtools·firecrawl·context7) | backend, frontend | naver 쪽 설치 여부 미확인. naver 세션 시작 때 `claude mcp list` 로 확인 |

## 프로젝트 적용 (역할 템플릿을 이 프로젝트에 맞추는 규칙)
- 템플릿의 `docs/PRD.md`·`docs/adr/`·`docs/specs/` 는 이 프로젝트에서 `docs/plans/<주제>/` 의 기획안·구현계획서로 대신한다. 새 계획 문서는 채팅 요약 → 폴더·파일명 제안 → 사용자 승인 → 저장 순서(무단 생성 금지).
- 워크플로는 `CLAUDE.md` HOW 절 9단계를 따른다: 로컬 구현 → 로컬 테스트 → 완료 보고(승인 대기) → 커밋 → 배포 전 승인 → 배포 → 서버 확인.
- 배포는 `git push origin main` 이 곧 배포다. push 전 반드시 사용자 승인. 수동 SSH 배포는 workflow 실패 시에만.
- 멀티 Phase 작업은 모든 Phase 로컬 완성 후 단일 배포.
- frontend 검증: dev 서버 실행 중 `npm run build` 금지 → `npx tsc --noEmit` + dev 로그 grep + `curl -sI http://localhost:4000/<경로>` + chrome-devtools 렌더.
- 로컬 실행·포트: 원래 구성(backend 8000, frontend 4000)과 점유 프로세스(`lsof` + `ps`)를 먼저 확인하고 보고 후 지시 대기. 임의 우회 포트 금지.
- biotech 계열 판정·봉인 문서는 외부 리뷰(Fable) 가 "무조건 GO" 를 낼 때까지 개정. 검수용 자료는 `python3 scripts/fable_bundle.py` 번들 zip 으로 제공(절대 경로 + SHA-256).

## 공용 규칙 (naver 프로필 프로젝트 메모리 요약 · 2026-10-21 기준)
원문은 아래 "메모리 지도"의 naver 경로. 어느 프로필로 열어도 이 절이 적용된다.

| 규칙 | 요지 |
|---|---|
| 정체성 | 급등주(폭등 직전) 사전 예측 봇. 안정 수익형 전략(PEAD·평균회귀·인덱스 DCA 등) 권고는 채택하지 않는다. 신규 신호는 "급등 직전을 미리 잡는가"로 먼저 판단 |
| 설정 자유도 | 파라미터는 ① 실시간 소스 동기화 ② JSON override(`data/*.json`) ③ 코드 default 순. 하드 파라미터는 UI 에서 조정 가능해야 한다 |
| 실주문 보안 | 자금이 움직이는 엔드포인트·Kill Switch·파라미터 편집 API 는 `X-API-Token`(`SNIPER_API_TOKEN`, SOPS) 필수, 불일치 403. 실주문은 `SNIPER_LIVE_ENABLED=true` 일 때만(기본 Paper) |
| 버전 갱신 | 런타임 소스 변경 시에만. 문서·`.gitignore`·테스트만 바뀌면 생략 |
| 스펙 밖 추가 | 요구하지 않은 UI 요소를 넣으면 응답 본문에 데이터 소스·목적을 바로 설명 |
| 라이브 위치 | 본 프로젝트 라이브는 optimus8.cafe24.com. `gonnim.dev` 는 별개 프로젝트 |
| biotech 원칙 | 검증 단계는 로컬 산출물만·배포 없음. 각 리포트에 `alpha_confirmed` 와 폐기 경로를 둔다 |
| 자격증명 | 평문 키·토큰·계좌번호 작성·커밋 금지. 공개 저장소이므로 이 파일에도 비밀값·개인 이름을 적지 않는다 |

## 메모리 지도 (두 프로필 공용 운용)
Claude Code 는 **현재 프로필의** 프로젝트 메모리만 자동으로 읽는다. 그래서 세션 시작 때 다른 쪽도 읽는다.

| 프로필 | 이 프로젝트 메모리 경로 | 현황(2026-10-21) |
|---|---|---|
| naver | `/Users/gonnim/.claude-profiles/naver/projects/-Users-gonnim-Project-MVP-Source-toss-tradebot-mvp/memory/` | 22건 · 최종 2026-09-30 · 이력의 원본 |
| thetak | `/Users/gonnim/.claude-thetak/projects/-Users-gonnim-Project-MVP-Source-toss-tradebot-mvp/memory/` | 0건 |
| desktop(thetak 창 Code 탭) | `/Users/gonnim/.claude/projects/-Users-gonnim-Project-MVP-Source-toss-tradebot-mvp/memory/` | 폴더 없음 |

운용 규칙:
1. 세션 시작 때 현재 프로필이 아닌 쪽의 `MEMORY.md` 를 **읽기만** 한다(핸드북 규칙 2·3 — 다른 프로필로 `claude` 명령 실행 금지, 설정 폴더 쓰기 금지).
2. 오래 지켜야 할 규칙은 메모리가 아니라 저장소에 남긴다: `CLAUDE.md` "## 축적된 규칙" 또는 이 파일 "공용 규칙". 저장소는 두 프로필이 같은 파일을 본다.
3. 메모리 쓰기는 사용자 허용 시에만, 현재 프로필 쪽에만, append 로. 다른 프로필 메모리와 겹치는 주제면 쓰지 않고 저장소 쪽에 적는다.
4. 메모리끼리 내용이 어긋나면 저장소 문서 → 최신 날짜 메모리 순으로 따르고, 어긋남을 보고한다.

## 프로필별 상황 대응
| 상황 | 자동 적용되는 것 | 직접 챙길 것 |
|---|---|---|
| thetak CLI (`claude-thetak`) | 프로젝트 `.claude/`(agents·hooks·settings·skills), CLAUDE.md, thetak MCP 4종, studio 스킬 | naver `MEMORY.md` 읽기 |
| naver CLI (`claude-pss`) / PSS 데스크톱 Code 탭 | 위 프로젝트 `.claude/` 와 CLAUDE.md, naver 메모리 | `claude mcp list` 로 MCP 확인(미설치면 "미설치" 표시), studio 스킬 링크 확인 |
| thetak 데스크톱 Code 탭 (`~/.claude`) | 프로젝트 `.claude/`, CLAUDE.md | studio 스킬·MCP 미연결(핸드북 결정 대기 항목). 두 메모리 모두 수동으로 읽기 |
| 두 프로필 동시 사용 | — | 같은 작업 트리·같은 브랜치를 동시에 편집하지 않는다. 두 번째 세션은 `git worktree` 로 분리 |
| 사용자가 `!` 로 실행한 명령 | hook 미적용 | 위험 명령은 사용자 책임. Claude 는 `!` 실행을 제안할 때 키를 넣지 않는다 |
| 커밋 서명 | 프로필별 Co-Authored-By 안내를 따름 | `includeCoAuthoredBy` 는 설정하지 않음(최근 커밋 관례 유지) |

공유 자원(프로필 무관): git 작업 트리, `gh` 인증, SSH 키·호스트 별칭 `github.com-gonnim`, `.claude/settings.local.json`(ssh·git 등 넓은 allow 포함 — hook 이 `reset --hard`·강제 push 를 막음), `.git/hooks/pre-commit`.

## hook 동작 (`.claude/hooks/block-dangerous.sh`)
- 위험 명령 차단: 광범위 `rm -rf`, 강제 push, `git reset --hard`, `git clean -f`, DB DROP/TRUNCATE, terraform apply/destroy, 세 설정 폴더(`~/.claude`, `-thetak`, `-profiles`) 쓰기.
- 커밋 전 검사(스테이징 목록 + 명령 문자열 기준): `backend/` → compileall + biotech 테스트, `frontend/` → `tsc --noEmit`. venv·node_modules 가 없으면 경고 후 건너뜀.
- 전체 pytest 는 기존 실패 21건이 정리될 때까지 걸지 않는다.

## 다음 과제 (2026-10-22 22시대 갱신 · 새 세션은 여기와 `docs/plans/biotech/PENDING.md` 최상단부터 읽는다)

### 지금 남은 일 (10/22 22시대)
| # | 진행 여부 | 할 일 | 누가 | 언제 | 확인 위치·끝 기준 |
|---|---|---|---|---|---|
| 1022-01 | 예정 (매 세션 첫 작업) | 서버 관측 | Claude | 세션 시작 | — |
| 1022-02 | 예정 (10/23 07:00 뒤) | P4 첫 실행 확인 | Claude | 10/23 07:00 뒤 | — |
| 1022-03 | 사용자 답 대기 (장 마감 뒤) | PR #107 병합 | 사용자 | 장 마감 뒤 | `! gh pr merge 107 --merge` 를 실행해 주십시오. |
| 1022-04 | 예정 | #107 배포 뒤 확인 | Claude | 1022-03 뒤 | — |
| 1022-05 | 예정 | 재가동 비용 확정 | Claude | 1022-03 뒤 | — |
| 1022-06 | 사용자 답 대기 | 발동 버튼 경로 결정 | 사용자 | 아무 때나 | (가) 인증 API 추가 · (나) 숨김 · (다) 그대로 중 하나를 답해 주십시오. |
| 1022-07 | 사용자 답 대기 | Sector 실패알림 횟수 | 사용자 | 아무 때나 | 시간대별 유지 · 하루 1회 합치기 중 하나를 답해 주십시오. |
| 1022-08 | 예정 (11/1 07:00 뒤) | FR-6c 재판정 대조 | Claude | 11/1 07:00 뒤 | — |
| 1022-09 | 미착수 (0순위 배포 뒤) | 알림 설정 페이지 기획 | Claude | 1022-04 뒤 | 기획 요약을 보시고 승인해 주십시오. |
| 1022-10 | 미착수 | UI/UX 2~8순위 기획 | Claude | 1022-09 뒤 | 순위마다 기획 요약을 승인해 주십시오. |
| 1022-11 | 사용자 답 대기 | 옛 브랜치·PRD 사본 | 사용자 | 아무 때나 | 지울지 남길지 답해 주십시오. |
| 1022-12 | 미착수 | 남은 실패 테스트 4건 | Claude | 1022-10 뒤 | — |

자세히 (표와 같은 번호)
- 1022-01: PENDING 영구 규칙 · 조회 전용. 서버 `/root/toss-tradebot-mvp/var/biotech/logs/daily.log` 최신 실행이 `[11/11]` 까지 갔는지 · `/biotech` 날짜 · 서버 HEAD.
- 1022-02: PENDING 2026-10-21 Fable 판정 항목. P4-2 `var/biotech/fr6c/cells_202610.json` 첫 판정 (표시 행 68 · 긍정 43 기대) · P4-4 readout_text 첫 실행 (START_ET 2026-10-22) · SEC 장부 합계 ≤ 300 · 배지 표시 수 · 화면 빌드 해시 · /biotech 과거 기록 · 새 8-K 확인 섹션 스크린샷 → `scripts/fable_bundle.py` 번들 zip (절대 경로 + zip SHA-256) 으로 fable 역할에 보고.
- 1022-03: PR #107 = 0순위 알림 고장 수리 (F1 apewisdom 이름 충돌 → Crazy·Moonshot 복구 · F1b reddit.py 삭제 · F2 Sector None · F3 400 · F4 deploy-watch 오발송 · F5 Kill Switch 해제 API `DELETE /api/v1/sniper/kill-switch` · F6 잡 실패 warning · 버전 0.1.1). 병합 = 배포 run (backend · frontend build). 계획 `docs/plans/alert-settings/p0-fixes.md`.
- 1022-04: `gh run list --workflow=deploy.yml --limit 1` 로 run 번호 · success 확인 · 서버 `/var/log/toss-tradebot/cron.error.log` 에 `ApewisdomClient` ImportError 가 없음 · 다음 실행 crazy 06:30 · sector 09:05 / 17:05 · moonshot 16:50 의 `[Notifier] sent` 제목 확인 · 서버 HEAD · /health. 조회만 (수동 `--once` 실행은 승인 대상).
- 1022-05: 서버 `backend/.env` 의 `LLM_PROVIDER` 이름 · `ticker_universe` 행 수 조회 (값 출력 금지). 추정: 외부 호출 약 826회/일 + universe 118회 · LLM 13~26회/일.
- 1022-06: `frontend/app/lab/execution/page.tsx` 의 발동 버튼이 옛 경로 `/execution/kill-switch` (미등록 · 404) 를 부름. 자동 발동 (sniper 일일 손실 한도) 은 서버 안에서 따로 동작. 권고 (가).
- 1022-07: F6 는 Sector Leaders 09:05 · 17:05 를 따로 하루 1회씩 보냄. 권고: 유지.
- 1022-09: 1순위 `/admin/notifications` · 사용자가 알림 11묶음별로 켜기·끄기·요약·재발송 간격을 직접 설정 (기본값 = 2026-10-22 유용성 검증 권고). 범위·근거 `docs/plans/alert-settings/README.md`.
- 1022-10: 2 홈 "오늘" · 3 메뉴 15→5 · 4 로그인 하나 · 5 문구 · 6 시각 통일 (`docs/design-rules.md` gonnim 기준 개정) · 7 모바일 · 8 정리. `docs/plans/ui-ux-optimization/README.md`.
- 1022-11: 미병합 `feature/biotech-aact-weekly` · `wip/local-docs` (각 1커밋) · 미추적 `docs/plans/PRD/biotech/` (10/04 PRD v0.4 사본).
- 1022-12: serenity_extractor 2 · test_stooq 1 · powderkeg_models 1 (순서 의존).

참고
- 로컬 `backend/data/tradebot.db` 는 ORM 표가 없는 상태이며 사용자 결정 (2026-10-22) 으로 그대로 둔다. 테스트는 이제 루트 conftest 가 메모리 DB · 빈 텔레그램 토큰으로 고정한다 (#105).
- 이번 세션 Fable 질의·답변과 근거 자료: 로컬 `docs/plans/biotech/fable-bundles/20261022_observe/` (git 제외) · 알림 유용성 전문 `alerts-usefulness-report.md` · gonnim 규칙 요약 `gonnim-ui-rules.md`.

완료 7건 (2026-10-22) | 세션 관측 정상 · PENDING 영구 규칙 5줄 (#104) · wp72 로컬 브랜치 삭제 · 테스트 16건 수정과 실 DB·실 텔레그램 차단 (#105 · 배포 run 39758639048 success · 서버 HEAD cdb09a2) · 다음 과제·기획 폴더 (#106) · 텔레그램 알림 인벤토리·유용성 검증 · UI/UX 감사와 중요도 순 제안
완료 (2026-10-21~22): fable 역할 추가 · P4 판정 수령 · #100 (시총 배지) · #95~#98 (P4-1~P4-4) 병합 · 배포 success · #101 · #102 문서 · worktree 정리 · 병합된 로컬 브랜치 103개 삭제.
