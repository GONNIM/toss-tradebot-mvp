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

## 다음 과제
1. 사용자가 지시할 유지보수 작업.
2. 기존 실패 테스트 21건 분류(serenity_extractor 4 · dart_financials 8 · rulebook 2 · signal_router 2 · integration_dod 2 · data_sources 2 · powderkeg_models 1).
3. `feature/biotech-p4-4` 등 main 미병합 4커밋의 PR·병합 상태 확인.
4. 미추적 `docs/plans/PRD/biotech/` 커밋 여부 사용자 결정.
