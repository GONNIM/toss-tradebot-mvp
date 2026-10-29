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
- 배포는 `git push origin main` 이 곧 배포다. 사용자 승인이 필요한 push 는 배포가 도는 push(main 에 코드가 바뀌는 push · 병합 포함)다 — 기능 브랜치 push 와 문서·`.claude/` 만 바뀌는 main push 는 배포가 돌지 않는다(deploy.yml paths-ignore). 커밋 전 완료 보고(HOW 3단계)는 그대로다. 수동 SSH 배포는 workflow 실패 시에만.
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

## 다음 과제 (2026-10-28 11시대 갱신 · 순서 = `docs/plans/site-roadmap/README.md` 고도화 방안 · 새 세션은 여기와 `docs/plans/biotech/PENDING.md` 최상단부터 읽는다)

### 지금 남은 일 (10/28 11시대)
| # | 우선순위 | 진행 여부 | 할 일 | 누가 | 언제 | 보실 곳·끝 기준 |
|---|---|---|---|---|---|---|
| 1025-03 | — | 완료 (10/28 · 알림 링크 열림 사용자 확인) | 엔진–알림–화면 잇기 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1026-02 | — | 완료 (10/28 08:10 outcomes 오류 없음) | 결과 계산 후속 확인 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1025-06 | — | 완료 (10/28 07:40 WEN 1981-05-27 일치) | 웬디스 코드 대조 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-16 | 3 (기다림) | 진행 중 (10/26 아침 확인 · 11/1 비용 대조) | Opus 전환 확인 | Claude | 11/1 뒤 | 더 하실 일 없습니다 |
| 1022-08 | 3 (기다림) | 예정 (11/1 07:00 뒤 · 번들 항목 PENDING 10/27 줄) | FR-6c 재판정 대조 | Claude | 11/1 07:00 뒤 | — |
| 1023-03 | — | 완료 (10/28 · 화면 회사명·섹터 사용자 확인 · PENDING 영구 규칙) | Finnhub 종목 정보 실패 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1023-07 | — | 완료 (10/28 06:30 3곳 50건 · 403 없음) | 뉴스 피드 3곳 403 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-12 | 2→— | 완료 (10/28 #131 배포 · 전체 pytest 0 실패) | 남은 실패 테스트 4건 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-10 | 2 (답 필요) | 코드 준비됨·배포 대기 (10/29 3단계 PR · Fable 병합 승인) | 화면 재구성 (메뉴 5 · 종목 화면) | 사용자 | 지금 | PR 병합을 실행해 주십시오. |
| 1028-03 | — | 완료 (10/28 #134 배포 · 운영 401 확인) | 인증 없는 쓰기 API 3화면 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1028-04 | — | 완료 (10/28 #135 배포 · 운영 build 16799a4) | 편집 실패 한국어 안내 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1027-01 | — | 완료 (10/28 #128 배포 · 운영 JS 새 문구 확인) | 청산 계획 뜻 통일 | Claude | 끝남 | 로그인 뒤 판단만 있는 종목 카드를 한 번 봐 주시면 좋습니다. |
| 1027-02 | — | 완료 (10/28 #129 배포 · 사용자 목록 확인) | 로그인 칸 첫 조회 중복 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1027-03 | — | 완료 (10/29 · 46/59 · 빠진 13 일치) | Crazy 시총 필터 켜기 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1027-04 | — | 완료 (10/29 · 24h 56건 · 매치 0 · 오탐 0) | 뉴스 티커 오탐 측정 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1028-01 | — | 완료 (10/29 · fetched 3줄 · collected·earnings 줄 없음) | Crazy 피드 반복 조회 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1028-02 | 3→2 (답 필요) | 시작 가능·사용자 신호 대기 (10/28 1028-01 배포) | 상장폐지 의심 4종목 | Claude | 1022-10 뒤 | 정리 방안을 올리면 승인해 주십시오. |
| 1025-02 | 3 (기다림) | 미착수 (사용자 보류 · 10/25) | 손실 자동 정지 수리 | — | 추후 상세 정리 뒤 | 실주문 허용을 다시 켜기 전 필수 (로드맵 A1 문장 유지). |

자세히 (표와 같은 번호 · 번호마다 한 줄)
- 1025-06: 07:40 배치는 레이더 CSV 종목만 물어 WEN 이 대상에 없었음 (10/26 asked 79 · found 79 · toss_stock_code WEN 0행) → #123 으로 미국 보유 종목 추가 (사용자 승인 10/26 ①). 10/28 07:40 로그 `[broker-links] asked=… · WEN list_date=…` 로 US19810527001 = 1981-05-27 대조. verified 는 사람이 확인한 뒤에만 켠다 (Fable 10/27). 기획 `docs/plans/site-roadmap/broker-link.md`.
- 1026-02: Fable #122 권고 — 긴 horizon (730일) 만기 계산 · 전 종목 조회 실패 시 알림 · /journal 대체·청산 행 「자동 계산 대상 아님」 · README 에 수동 실행 주의. 더해서 Fable 10/27 권고 `frontend/app/account/page.tsx:149` 「지금 가격」→「현재 가격」. 보류: ③ -0.0 반올림 표시 · ④ fx 캐시 잠금 없음 (Fable 10/27 · 고치지 않아도 됨). → PR #124 병합 140faf2 · run 40444966508 성공 · 운영 /account 「현재 가격」 · /journal 대체·청산 문구 확인 (10/27 공개 JS) · 서버 0.3.10 은 공개 경로에 버전이 없어 미확인 (d8a5836 · 서버 0.3.10 · 화면 0.3.8 · diff SHA-256 ace8e4aa… · Fable 10/27 GO · 범위 조건부 「병합 승인됨」 → #124 에 적용). 배포 뒤: 운영 /journal 대체·청산 행 문구 · /account 「현재 가격」 · 다음 08:10 `[outcomes]` 요약 확인 (렌더 확인을 이것으로 갈음 · Fable). 다음 outcomes 손질 권고: RuntimeError 메시지에 마지막 예외 이름 · 긴 판정 unavailable 종목 매일 재조회 → 건수 늘면 제외 목록.
- 1022-16: PR #113 (병합 4dcc11a · run 40165890732 · 10/25). 기본 모델 claude-opus-5-5 · effort medium (사용자 10/25). 실측 분석 글 13.8초 · 판정 2.8초 · 비용 추정 월 ~$12 (콘솔 월 한도). 남은 것: 11/1 콘솔 사용량 대조 (2배 이상이면 모델·effort 재질의). 되돌리기 LLM_PROVIDER=zai PR.
- 1025-03: 10/27 사용자 「1025-03 권고대로」 → 기획 `docs/plans/site-roadmap/b1-engine-links.md` · 브랜치 feat/b1-engine-links · 서버 0.3.11 · 화면 0.3.9 · 테스트 test_lab_picks_routes 6 통과 · 전체 1610 통과·4 실패 (기존과 같음) · tsc 통과 · 질의 `2026-10-27-1025-03-02.md` Fable GO (권고 1·2 주석·.env.example 반영) → 로그인 칸이 없던 것을 PO 가 찾아 crazy·moonshot 화면에 AdminSessionBar 추가 → 재질의 `-03.md` Fable GO · v2 diff SHA-256 14cbabb7… · 「병합 승인됨 · PR #125」 (커밋 6527f1b · 병합 15880af · run 40474487382 성공 · 10/27 17:34). 배포 뒤 운영: super_signal_enabled false · signal_router false · paper · crazy·moonshot·summary 비로그인 401 · /lab/crazy 로그인 칸 + 안내 (build 15880af · chrome-devtools) · /lab/backtest 200. 로그인 뒤 목록 사용자 확인 (10/27 「1025-03 로그인 뒤 목록 보임」). 남은 것: 10/28 06:30 Crazy 알림 링크. 넷째 화면 UsageGuide.tsx:101 「카지노」 도 고침. 배포 뒤: /sniper/status super_signal_enabled false (true 면 서버 .env 명시 → 사용자 보고 · 멈춤) · /api/v1/crazy 401 · 운영 /lab/crazy 로그인 안내 · 다음 06:30 Crazy 알림 링크 1회. 이전 기록: `docs/plans/site-roadmap/README.md` B1. 10/27 조사 · 질의 `docs/plans/biotech/fable-bundles/2026-10-27-1025-03-01.md` (Fable 조건부 GO · 막음 3 반영 · 재질의 불필요). 권고안: ① Crazy·Moonshot 살림 (crazy.py·moonshot.py GET 등록 · 라벨 「과거 실현 결과 · 미래 수익 보장 아님 · n건」 · 20건 미만 숫자 없음) ② 조회 로그인 필수 (401 → 로그인 안내 · 텔레그램 링크로 오면 로그인 먼저) ③ Super Signal 5분 잡 (main.py:126-138 · SUPER_SIGNAL_ENABLED 기본 true · 승격+매수 진입) 끔 = 서버 동작 변경 WP92 · 서버 .env 명시 시 기본값만으론 안 꺼짐 → 배포 뒤 시작 로그 확인 ④ Backtest 화면 퇴역 ⑤ 「카지노」 문구 화면 세 곳 (settings.py:14 · lab/page.tsx Moonshot·Meme · meme-watch/page.tsx:97) · LLM 프롬프트 llm.py:118 그대로 ⑥ /account 「청산 계획 있음」 과 /positions/plan has_plan (positions.py:115-118) 뜻 통일은 다른 PR 로 보류. 함께: lab Crazy 설명 「Claude Haiku」 고침 · 라우트 인증 테스트 · /crazy?limit 307 확인 · 서버 0.3.11 · 화면 0.3.9. 운영 /sniper/status 10/27: signal_router_enabled false · paper · live false. 결정 뒤 기획 문서 `docs/plans/site-roadmap/b1-engine-links.md` 저장 → 한 PR → Fable 병합 승인.
- 1027-01: /account 「청산 계획 있음」 과 /positions/plan has_plan (positions.py:115-118) 뜻 통일. 10/28 사용자 「1027-01 A로 진행」 (손절가나 목표가가 있어야 「있음」 · 판단만 있으면 내용 표시 + 「없음」 경고). 브랜치 fix/exit-plan-meaning · 서버 0.3.14 · 화면 0.3.10 · 테스트 4 · 전체 1622 통과·4 실패 (기존) · tsc 통과 · 코드 diff SHA 5880f51f… · 질의 `2026-10-28-1027-01-01.md` Fable GO · 「병합 승인됨」 (SHA 조건) → 커밋 d95f0d5 · PR #128 · SHA 5880f51f 일치 확인. 병합 932af61 · run 40632193406 성공 (10/28 13시대) · 운영 /positions 200 · 공개 JS page-905e1bdb… 에 「손절가·목표가가 비어 있습니다」 있음 · 서버 0.3.14 는 공개 경로에 버전이 없어 미확인 (health ok). 배포 뒤: 공개 JS 「손절가·목표가가 비어 있습니다」 · 가능하면 로그인 화면 판단만 있는 종목 카드 (amber + 경고) · 결과 이 줄에. Fable R2: 머리 배너 「미기록」→「없음」 은 다음 page.tsx 때.
- 1027-02: AdminSessionBar.tsx:49-56 첫 로드 whoami 에도 onSessionChange → PicksSessionBar 가 첫 조회 1회 중복 (Fable 10/27 권고 · 동작 결함 아님). 10/28 사용자 「1027-02 진행」 → PicksSessionBar 만 고침 (첫 콜백: 비로그인 무시 · 로그인이면 실패한 조회만 다시) · 화면 0.3.11 · tsc 통과 · 운영 기준값 비로그인 1회씩 · 코드 diff SHA 3bb682ee… · 질의 `2026-10-28-1027-02-01.md` Fable GO · 「병합 승인됨」 (SHA 조건). 배포 뒤: 로그인 → 목록 · 로그인된 채 새로고침 → 목록 · 안내 없음. → PR #129 병합 f5c97f7 · run 40634523457 성공 (10/28 13시대) · 운영 JS 6153-052546fb… 에 새 콜백 (비로그인 무시 · error 만 다시) 확인 · 사용자 로그인 확인 대기.
- 1023-03: 원인 확정 10/27 — backend/.env.sops.yaml:33 `FINNHUB_API_KEY: ""` (평문 빈 값) · deploy.yml:123-147 이 배포마다 서버 .env 를 SOPS 로 교체 → 서버 키 없음 → 401 인데 base.py:93-97 이 4xx 를 올리지 않아 「profile not found」 로 기록. 영향: ticker_universe 회사명·섹터·시총 빈칸 · Crazy catalyst(0.30) 어닝 D-day 없음. 질의 `2026-10-27-1023-03-01.md` (Fable 조건부 GO · M1·M2 반영). 권고 A: 사용자 무료 키 발급 → 다른 터미널 `sops backend/.env.sops.yaml` → Claude PR (4xx → 「키 없음·무효」 로그 · 하루 1회 운영 알림) + SOPS 커밋 → Fable 병합 승인 · PENDING 에 반영일 한 줄. → 10/27 사용자 키 발급·sops 입력 · 무료 플랜 profile2·earnings 200 확인 · PR #126 (c30a0aa · 서버 0.3.12 · 코드 diff SHA-256 2ad54439… · 질의 `-02.md` Fable GO · 「병합 승인됨 · PR #126」 조건: 코드 커밋 뒤 추가 커밋 없음). 배포 뒤: 사용자 ! 로 서버 .env 키 길이만 · 06:00 `[universe] refresh complete — N/59` · 키 오류 알림 없음 · 06:30 Crazy 회사명·섹터 · PENDING 한 줄 (배포일 KST 06:00 부터 Finnhub 입력 반영). → 병합 34292c6 · run 40485572163 성공 (10/27 19:04) · 사용자 ! 확인: 서버 .env 키 8자 이상 줄 1 · 서버 0.3.12. 10/28 서버 로그 원문: `2026-10-28 06:00:33,701 [__main__] INFO: [universe] refresh complete — 53/59 enriched` · 실패 SPY·QQQ (ETF) · HCDI·BREA (profile not found) · ZAPP·NUKK (yfinance delisted) · 키 오류 없음 · 사용자 화면 회사명·섹터 확인 → PENDING 영구 규칙 추가 (10/28). 이전 남은 것: 10/28 06:00 `[universe] refresh complete — N/59` · 키 오류 알림 없음 · 06:30 Crazy 회사명·섹터 → 확인 뒤 PENDING 영구 규칙 한 줄 「2026-10-28 06:00 universe 실행부터 Crazy 입력에 Finnhub 회사 정보·어닝 D-day 반영 · 그 전은 Finnhub 입력 0」 (Fable R3). 서버 로그는 사용자 ! 실행.
- 1027-03: cron.py:268·282 가 is_crazy·is_moonshot 을 강제 True (시총 ≥$1B 필터 꺼짐) · current_price=None 이라 그냥 켜면 전부 탈락 (universe.py:58-59) · 후보 집합 변경 = WP92 승인 필요. → 10/28 측정 (`diffs/1027-03-mcap.py`): 59 중 시총 ≥$1B 46 (그중 가격<$1 0) · 빠지는 13 = ETF 2 (SPY·QQQ) · 마이크로캡 7 · 상장폐지 의심 4. 질의 `2026-10-28-1027-03-01.md` Fable GO. 권고 A: Crazy 만 DB 시총 ≥$1B (가격 조건은 가격 열 추가 = B 때) · Moonshot 그대로 · 로그 「Crazy 대상 N/59」. → 10/28 사용자 「B로 진행」 · 브랜치 feat/crazy-mcap-filter · ticker_universe.current_price 열 (API 시작 때 ensure_columns) · universe 잡이 종가 저장 · is_crazy = passes_crazy_filter (시총 ≥$1B · 가격 ≥$1) · Moonshot 그대로 · 테스트 2건 · 서버 0.3.16 · 전체 1631 passed · PR #132 · 질의 `2026-10-28-1027-03-02.md` Fable GO (병합 승인 SHA ce8df3c4… · PR diff 일치 확인 · 10/29 06:00 전 병합). 병합 d97bc61 · run 40672779038 성공 · 서버 api.error.log 「2026-10-28 19:35:30 [db] 열 추가 ticker_universe.current_price」 · PRAGMA 「10|current_price|FLOAT|0||0」 (사용자 ! 조회). → 10/29 서버 cron.error.log 「06:30:00 [crazy] Crazy 대상 46/59 (시총 ≥ $1B · 가격 ≥ $1)」 (사용자 ! 조회) · 측정 46 과 일치. → 10/29 서버 DB 읽기 (사용자 ! 조회 · 자동 모드가 막음): 시총 <$1B 또는 가격 <$1 인 active 종목 = AZTR · BURU · CARV · EHGO · IPDN · MNTS · WAVE (측정 마이크로캡 7 그대로 · AZTR 가격 $0.90 도 미달) · SPY·QQQ·ZAPP·HCDI·NUKK·BREA 6 은 ticker_universe active 에 없어 market_cap_usd=None (cron.py:269-275) → 탈락 · 합 13 일치 → 완료.
- 1023-07: RSS 피드 4곳 중 3곳이 403. 10/27 조사: GlobeNewswire 2 · BusinessWire (HTML 포털 주소) 403 AkamaiGHost · 원인 미확인 · 브라우저 UA 우회 시험은 자동 모드가 막음 (우회 안 함). PRNewswire 공식 피드 (전체·건강·금융) 200. 질의 `2026-10-27-1023-07-01.md` Fable 조건부 GO (M1 중복 제거 · M2 반영). 권고 A: 막힌 3곳 빼고 PRNewswire 전체·건강 추가 + link 기준 중복 제거 · 기대 효과 작음 · 오탐 위험. 다음 후보: Finnhub company-news · SEC 8-K. → 10/27 사용자 「1023-07 권고대로」 · PR #127 (서버 0.3.13 · 코드 SHA 073ae396… · 질의 `-02.md` Fable GO · 「병합 승인됨 · PR #127」 · 병합 e3ade26 · run 40492959077 성공 · 10/27 20시대). 로컬 실수집 3곳 200 · 60→53 · 티커 8. 배포 뒤: 서버 0.3.13 · 06:30 `[RSS] <피드> fetched N entries` 3줄 · N>0 (1028-01 뒤 · 그 전 기준은 `[RSS] collected N items from 3 feeds`) · HTTP 403·fetch failed 없음 (INFO 없으면 경고 부재 + news_count_24h). rss.py:3·:36 옛 피드 이름 주석은 다음 rss.py 수정 때.
- 1028-03: (10/28 1022-10 조사 중 발견) 서버 쓰기 API 4곳에 인증 없음 — /vip 설정 (meme_watch.py:206) · /activist-radar 감시 대상 편집·삭제 (:259·:267) · /principles/verification 확인 (principles.py:232) · 공개 사이트라 누구나 바꿀 수 있음. 범위: 4 엔드포인트에 기존 `require_sniper_token` (auth.py:149) 추가 · 화면 호출 credentials 확인 · 로그인 상태 편집 테스트 · 서버 변경 (배포 승인) · 점수·후보 규칙 변경 아님. 질의 `2026-10-28-1022-10-01.md`. → 10/28 브랜치 fix/auth-write-endpoints · 5곳 (recompute-wolf-pack 추가) · 3화면 로그인 칸 · 테스트 12건 새로 · 전체 1644 passed · tsc 통과 · 서버 0.3.18 · 화면 0.3.12 · 질의 `2026-10-28-1028-03-01.md` Fable GO (병합 승인 SHA 3fbcc4bb… · PR diff 일치 조건) · 커밋 8b5837a · PR #134 (PR diff SHA 일치 확인) · 병합 5bbb6de · run 40702913536 성공 (10/28 23시대) · 운영 PATCH /meme-watch/vip/config 401 · POST /principles/verification/confirm 401 · GET /activist/universe 200. 배포 뒤: PATCH /meme-watch/vip/config 401 · GET /activist/universe 200 확인. 사고 (10/28): 화면 확인 중 로컬 uvicorn 을 예약 작업 켠 채 띄움 → 토스 토큰 발급 18회 · 주문 0 · 텔레그램 0 · 즉시 종료.
- 1028-04: (Fable 1028-03 권고) /activist-radar 삭제 실패가 소리 없음 (page.tsx:833-839 onError 없음) · activist·vip 수정 실패가 영어 일반 문구 (api.ts:45) → 401 이면 「관리자 로그인이 필요합니다」 안내 · 화면 문구만 (승인 불필요 · 검사 통과 시 병합). → 10/28 브랜치 fix/edit-auth-message · lib/auth.ts `editErrorMessage`·`LOGIN_REQUIRED_MESSAGE` · VIP·Activist 저장 실패 · Activist 삭제 실패 (alert) · 확인 화면 문구 공용화 · 화면 0.3.13 · tsc 통과 · 브라우저: 비로그인 VIP 저장 → 「저장 실패: 관리자 로그인이 필요합니다…」. PR #135 · 병합 16799a4 · run 40705476144 성공 · 운영 /vip 200 · build 16799a4 (10/28 23시대).
- 1028-01: (등록 10/28 아침: 「종목마다 RSS·Finnhub 어닝을 다시 받음」) → 10/28 조사로 정정: RSS 는 잡 1회 캐시 (rss.py:93-99 · 1023-01) 라 다시 받지 않고 `[RSS] collected` 줄만 캐시 재해석 때마다 반복 (rss.py:156) · Finnhub 어닝은 종목별 symbol 요청 (같은 자료 반복 아님). 질의 `2026-10-28-1028-01-01.md` Fable GO. 권고 A: 로그만 정리 (RSS 줄은 피드를 실제 받을 때 1번 · Finnhub earnings 줄 debug) · WP92 아님. B (어닝 전체 시장 1회) 는 점수 입력 경로라 승인 필요 · 권하지 않음. → 10/28 사용자 「A로 진행」 · 브랜치 chore/feed-log-noise · RSS info 는 _fetch_entries (잠금 안 · 피드별 1번) · collected·Finnhub earnings 줄 debug · rss.py:3·36 옛 주석 정리 · 테스트 1건 · 서버 0.3.17 · 전체 1632 passed · PR #133 · 질의 `2026-10-28-1028-01-02.md` Fable GO (병합 승인 SHA 24261564… · PR diff 일치 확인). 병합 250093c · run 40680511020 성공 (10/28 20시대). → 10/29 서버 cron.error.log 06:30:06 「[RSS] PRNewswire (All·Health·Financial) fetched 20 entries」 3줄 · collected·earnings 줄 없음 → 완료.
- 1028-02: universe·Crazy 에서 yfinance 「possibly delisted」 ZAPP·NUKK·HCDI·BREA (10/28 06:00·06:30) · Finnhub profile 도 HCDI·BREA 없음 · WATCHLIST 정리 = 후보 집합 변경이라 승인 필요.
- 1027-04: 같은 날 스냅샷으로 종목별 news_count_24h 를 교체 전·후 피드 구성으로 계산해 5건 (=20점) 도달 종목 수 비교 · V · BREA 등 1~3자 티커와 지명 오탐 (rss.py:173-180 단어 경계 매치) · Fable 10/27 권고 3. → 10/28 측정: 24h 55건 · 매치 V (「S.A. de C.V.」) · BREA (「BREA, Calif.」) 2건 모두 오탐 · 진짜 매치 0 · 20점 도달 0 · 명시 표기 항목 17 (대소문자 무시 19) 중 WATCHLIST 0 · 교체 전 비교 불가 (옛 3곳 원래 403). 질의 `2026-10-28-1027-04-01.md` Fable 조건부 GO (사실 3건 반영). 권고 A: 명시 표기만 셈 (대소문자 무시 · 표기 전부 수집) = WP92 승인 한 건. 구현 PR 때 테스트 3건 추가 (Fable 지시 5). → 10/28 사용자 「A로 진행」 · 브랜치 fix/rss-explicit-ticker · 명시 표기만 · 거래소 이름 대소문자 무시 · 표기 전부 · 테스트 3건 · 서버 0.3.15 · 실피드 재측정 WATCHLIST 오탐 2 → 0 · PR #130 · 질의 `2026-10-28-1027-04-02.md` Fable GO (병합 승인 SHA 0ade9f52… · PR diff 일치 확인). 병합 324c02e · run 40657682029 성공 (10/28 17시대). → 10/29 확인: news_count_24h 는 DB 에 따로 저장되지 않아 (scoring 입력만) 같은 코드로 로컬 재계산 · 공개 RSS 24h 56건 · WATCHLIST 59 중 매치 0 · 20점 도달 0 · 오탐 0 → 완료 (어제 오탐 V·BREA 2 → 0 유지) · 거래소 표기 변형 (NYSE American · OTCQB) 은 PENDING 한 줄만.
- 1022-12: serenity_extractor 2 · test_stooq 1 · powderkeg_models 1 (순서 의존). watchlist_execute 2 는 주말 실행 때만 실패 (execute.py:67-68 주말 차단). 10/27 전체 1600 통과 · 4 실패 그대로. → 10/28 테스트만 수정 (브랜치 test/stale-tests-1022-12): serenity 2 = processed_at 기준으로 맞춤 · stooq = "2d"·"4d" 값 단언 · powderkeg = 시작 때 7개 테이블 비움 · 전체 1629 passed · 0 failed · PR #131 (병합 83f5ecc · run 40666313312 성공) · 질의 `2026-10-28-1022-12-01.md` Fable GO (병합 승인 SHA 8518bb36… · PR diff 일치 확인) · 버전 갱신 없음.
- 1022-10: 2 홈 "오늘" · 3 메뉴 15→5 · 4 로그인 하나 · 5 문구 · 6 시각 통일 · 7 모바일 · 8 정리. `docs/plans/ui-ux-optimization/README.md`. → 10/28 사용자 지시 (메뉴 산재·중복 · 가이드라인 기반 최적 화면 · 정보를 묶어 한눈에 종합 판단). 조사: 메뉴 헤더+L1 9+L2 7(+2) · page.tsx 35 · 보유 3벌 · 스크리너 3벌 · 종목 상세는 Serenity 1곳 · 로그인 칸 13화면. 기획 요약: 메뉴 5 (오늘 · 후보 · 종목 · 내 계좌 · 기록) + ⚙ · 새 종목 화면 · 단계 0 보안(1028-03) → 1 메뉴·로그인 → 2 내 계좌 합침 → 3 종목 화면 → 4 오늘 홈 → 5 문구·시각·모바일. 질의 `2026-10-28-1022-10-01.md` Fable 조건부 GO (알림 링크 11곳 · Lab 경계 · 단계별 배포 근거 반영). 「MCP 가이드라인」 은 이 계정에 없음 → 사용자 확인. → 10/28 사용자: 가이드라인은 /design-md 스킬 (claude-studio) → 4곳 비교 뒤 coinbase DESIGN.md 를 루트에 받음 · 이 프로젝트 값 (반경 8·14·알약 · 그림자 없음 · 17px · tabular-nums · 상승 빨강·하락 파랑·강조 틸) 은 CLAUDE.md 「디자인 기준」 · 사용자 「색은 A · 1028-03 먼저 · 1022-10 이대로」 · 기획 문서 `docs/plans/ui-ux-optimization/2026-10-28-information-architecture.md`. → 10/29 사용자 「1022-10 권고대로」 (1단계 주소 유지 · 종목 메뉴 3단계 · 질의 `2026-10-29-1022-10-02.md` Fable GO) · 브랜치 feat/nav-stage1 · 메뉴 묶음 4 + 설정 · 헤더 로그인 하나 (HeaderSession · useSessionListener) · 문구 7곳 · 화면 0.3.14 · 34 주소 200 · JS 오류 0 · 질의 `-03.md` 조건부 GO (M1 하드 로드 중복) → `-04.md` GO · 병합 승인 SHA c533c8b4… (문서 커밋 1 포함 PR 한정) · PR #136 (PR diff SHA 일치). 배포: 병합 28b2e58 · run 40809927522 성공 (10/29 12시대) · 운영 5 주소 200 · 화면에 빌드 28b2e58 · 「관리자 로그인」 버튼. 배포 뒤: /lab/crazy 새 탭 비로그인 → /api/v1/crazy?limit=10 1회 (401 · 비로그인 정상) · admin/session 2회 (헤더·화면 각 1) · 콘솔 오류는 favicon 404 · 비로그인 401 (기존). 헤더 로그인 「관리자」 표시는 운영 토큰이 필요해 사용자 확인으로 남김 (로컬 확인 끝). → 10/29 2단계: 사용자 운영 관리자 로그인 OK · 조사 (보유 3벌 · 세 API 각자 토스 holdings · 알림 링크는 /vip 1곳) · 질의 `2026-10-29-1022-10-05.md` Fable 조건부 GO (앱 안 옛 주소 링크는 #plan 잃음 · user-guide:23) → 사용자 「권고대로」 (A: dashboard·account·positions → /account · VIP 탭 유지 / 옛 주소 307) · 브랜치 feat/account-merge · TossSummary·PositionPlans 부품 · 보유 표 하나 · next.config redirect 2 · 탭 계좌·VIP · 홈 카드·user-guide 새 주소 · 화면 0.3.15 · 토스 호출 첫 로드 holdings 3·환율 1·buying-power 0 · #plan 세 경로 확인 · 질의 `-06.md` 조건부 GO (60초 다시 읽기 때 튐) → 고침 → `-07.md` GO · 병합 승인 SHA f7965f44… (코드 1 + 문서 1 · 추가 커밋 없음 한정 · PR 번호는 배포 반영 때 기록) · PR #137 (PR diff SHA 일치) · 병합 256dcf1 · run 40823906887 성공 (10/29 14시대) · 운영 /dashboard 307 → /account · /positions 307 → /account#plan · /account·/vip 200 · 빌드 256dcf1 · 「종목별 청산 계획」·「VIP 감시」 렌더. 로그인 /account#plan 스크롤·60초 튐 없음은 운영 토큰 필요 → 사용자 확인 (로컬 확인 끝). 남은 것: 환율 1330 고정 (TossSummary 달러 현금) 별도 손질. → 10/29 3단계: 조사 (종목 열 표 · 종목별 API · 종목 칸 약 45곳 · journal ?ticker= 화면 미지원 · 알림 링크 종목 없음) · 질의 `2026-10-29-1022-10-08.md` Fable 조건부 GO (get_current_role · 캐시 헤더 · 비로그인 null 테스트 · is_kr_code·normalize_symbol·func.upper · WP92 승인 항목 아님) → 사용자 「권고대로」 (저장된 자료만 · 공개 칸 늘·내 것 관리자 · 링크 없는 칸 연결 · 알림 링크 다음) · 브랜치 feat/stock-page · GET /api/v1/stock/{ticker} (외부 호출·쓰기 0) · /stock/[ticker] · StockLink 22파일 29곳 · /journal?ticker= · 테스트 14건 · 전체 1658 passed · 서버 0.3.19 · 화면 0.3.16 · 바이오 행은 관리자 전용 (radar.json 토큰 · 결정 1 목록과 다름 · 사용자 보고) · 비로그인 이름 유무로 미국 유니버스 소속 추정 가능 (낮음 · 사용자 보고) · 질의 `-09.md` Fable GO · 병합 승인 SHA d08d6fb1… (코드 1 + 문서 1 · 추가 커밋 없음 한정 · PR 번호는 배포 반영 때 기록). 사용자에게 물음: 비로그인 미국 종목 바이오 잠금 행 (권고 그대로 둠). 배포 뒤: 비로그인 curl /api/v1/stock/WEN 헤더 2·holding·judgments null · 로그인 200 · 서버 로그 [stock] warning 0 · 자료 있는 종목 2개 (레이더 1 · 국내 1) · /journal?ticker= 칩. 다음: 4단계 (오늘 홈).
- 1025-02: `docs/plans/site-roadmap/README.md` A1.

참고
- 로컬 `backend/data/tradebot.db` 는 ORM 표가 없는 상태이며 사용자 결정 (2026-10-22) 으로 그대로 둔다. 테스트는 루트 conftest 가 메모리 DB · 빈 텔레그램 토큰 · 빈 LLM 키로 고정한다.
- 병합·배포 피할 시각 (KST): 05:55–06:45 · 09:00–09:15 · 16:40–17:15 · 18:00 앞뒤.
- Fable 질의·답변: 로컬 `docs/plans/biotech/fable-bundles/` (git 제외) 와 세션 scratchpad.

### 해결 기록
- 2026-10-27 완료 3건 (번호 그대로):
  - 1022-02: 10/27 완료 · 번들 `docs/plans/biotech/fable-bundles/20261027_1022-02.zip` (SHA-256 281ecd59…) · Fable GO · 결과는 PENDING 2026-10-21 지시의 10/27 진행 줄. 서버 로그는 SSH 읽기가 자동 모드에 막혀 사용자 ! 실행 · 스크린샷은 사용자 촬영 (chrome-devtools 가 headless).
  - 1026-01: 첫 실행 국내 10/26 15:50 (보유 1 · 일봉 200 · 당일 봉 포함) · 미국 10/27 07:10 (보유 2 · 일봉 400 · 환율 1326.5 toss) · 3종목 peak_complete true. #123 (병합 ab48bdc · run 40430159264 성공 · 서버 0.3.9 · 화면 0.3.7 · Fable 「병합 승인됨 · PR #123」): 청산 계획 「있음」= 손절가·목표가 · 「현재가가 … 최고」 · 「장 열린 날」 · dashboard/positions 환율 to_thread · 07:40 배치에 미국 보유 종목 · conftest 환율 캐시 초기화. Fable 권고 ③·④ 보류는 1026-02 줄.
  - 1025-05: 계획 `docs/plans/judgment-outcomes/README.md`. #122 (ebe6e93 · 서버 0.3.8 · 화면 0.3.6). 첫 실행 10/27 08:10: 판정 계산 1 · 대기 2 · Crazy 70/50 · Moonshot 30/0 · 빠진 종목 0 · 오류 없음.
- 2026-10-23~26 완료 20건 (번호 그대로):
  - 1022-01 (10/23) 서버 관측 정상 · 1022-03 (10/23) PR #107 병합 · 1022-04 (10/23) #107 배포 확인 · 1022-05 (10/23) 재가동 비용 확정.
  - 1022-06 (10/26) 발동 버튼 수리 — PR #114 (c93f85b · run 40168073825) · `POST /api/v1/sniper/kill-switch` (require_sniper_token) · 사용자 발동·해제 확인.
  - 1022-07 (10/25) 시스템 경고 받는 방식 — 운영 system → 하루 요약 (전 값 immediate) · 이후 /admin/notifications 에서 사용자가 직접 정한다.
  - 1022-09 (10/23) 알림 설정 페이지 — PR #111 (f2310c4 · run 39924284050) · 설계 `docs/plans/alert-settings/`.
  - 1022-11 (10/25) 옛 브랜치·PRD 사본 — 보관 `docs/plans/biotech/fable-bundles/backup-*-20261025.*` 뒤 삭제.
  - 1022-13 (10/23) LLM 전환 방식 사용자 결정 · 1022-14 (10/25) Anthropic 키 로컬 등록 (서버는 sops) · 1022-15 (10/23) PR #109 FallbackLLM (d996135).
  - 1023-01 (10/23) 아침 알림 실패 수리 — PR #110 (14802f4 · feedparser 스레드가 기본 실행기를 막음).
  - 1023-02 (10/26) Z.ai 분석 글 시간 초과 — anthropic 전환으로 10/10 · 시간 초과 없음.
  - 1023-04 (10/26) 뉴스 조회 수리 확인 — Crazy 10/24·25·26 「보냄」.
  - 1023-05 (10/25) 알림 문구 개편 — PR #112 (724460a · run 39990908416) · 문구 `docs/plans/alert-settings/wording.md` · 미룬 지적 7건은 그 문서 참조.
  - 1023-06 (10/25) 금지 규칙 폐지 반영 — `.claude/agents/fable.md:23` 교체.
  - 1025-01 (10/25) 실주문 안전 상황판 — #116 · 1025-04 (10/25) 서버 실주문 허용 끄기 — PR #115 (17d48cb · run 40175706246 · live_enabled 거짓).
  - 1025-07 (10/25) 안내 문구 · 셋째 경로 — #119 · 1025-08 (10/26) 실계좌 보유 화면·기록 — #120 (eebb461) · #121 (411f539).
- 2026-10-22 완료 7건: 세션 관측 정상 · PENDING 영구 규칙 5줄 (#104) · wp72 로컬 브랜치 삭제 · 테스트 16건 수정과 실 DB·실 텔레그램 차단 (#105 · 배포 run 39758639048) · 다음 과제·기획 폴더 (#106) · 텔레그램 알림 인벤토리·유용성 검증 · UI/UX 감사와 중요도 순 제안.
- 2026-10-21~22: fable 역할 추가 · P4 판정 수령 · #100 (시총 배지) · #95~#98 (P4-1~P4-4) 병합 · 배포 success · #101 · #102 문서 · worktree 정리 · 병합된 로컬 브랜치 103개 삭제.
