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

## 다음 과제 (2026-10-26 18시대 갱신 · 순서 = `docs/plans/site-roadmap/README.md` 고도화 방안 · 새 세션은 여기와 `docs/plans/biotech/PENDING.md` 최상단부터 읽는다)

### 지금 남은 일 (10/26 18시대)
| # | 우선순위 | 진행 여부 | 할 일 | 누가 | 언제 | 보실 곳·끝 기준 |
|---|---|---|---|---|---|---|
| 1025-06 | 3 (기다림) | 코드 준비됨·배포 대기 (1026-01 PR에 포함 · 사용자 승인 10/26) | 웬디스 코드 대조 | Claude | 1026-01 뒤 | 더 하실 일 없습니다 |
| 1022-16 | 3 (기다림) | 진행 중 (10/26 아침 확인 · 11/1 비용 대조) | Opus 전환 확인 | Claude | 11/1 뒤 | 더 하실 일 없습니다 |
| 1023-02 | — | 완료 (10/26 · anthropic 10/10 · 시간 초과 없음) | Z.ai 분석 글 시간 초과 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1023-04 | — | 완료 (10/26 · Crazy 10/24·25·26 「보냄」) | 뉴스 조회 수리 확인 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1025-05 | 3 (기다림) | 예정 (첫 실행 10/27 08:10 · 배포가 10/26 10:07) | 결과 계산 첫 실행 확인 | Claude | 10/27 08:10 뒤 | 더 하실 일 없습니다 |
| 1026-01 | 3 (기다림) | 진행 중 (국내 15:50 정상 · 브랜치 커밋 5fa9c28 · 미국 10/27 07:10) | 보유 기록 확인 · 정리 PR | Claude | 10/27 08:10 뒤 | PR이 열리면 병합 명령을 드리겠습니다. |
| 1026-02 | 3 (기다림) | 예정 (1026-01 뒤) | 결과 계산 후속 PR (권고 4건) | Claude | 1026-01 뒤 | 더 하실 일 없습니다 |
| 1025-03 | 3 (기다림) | 미착수 (방안 B1) | 엔진–알림–화면 잇기 | Claude·사용자 | 1026-02 뒤 | 화면마다 살림·알림만·끔을 골라 주십시오. |
| 1023-03 | 3 (기다림) | 미착수 (방안 B2) | Finnhub 종목 정보 실패 | Claude | 1025-03 뒤 | — |
| 1023-07 | 3 (기다림) | 미착수 (방안 B2) | 뉴스 피드 3곳 403 | Claude | 1025-03 뒤 | — |
| 1022-12 | 3 (기다림) | 미착수 (방안 C 전) | 남은 실패 테스트 4건 | Claude | 1023-07 뒤 | — |
| 1022-10 | 3 (기다림) | 미착수 (방안 C·D) | 홈 「오늘」 · UI/UX 2~8 | Claude | 1022-12 뒤 | 순위마다 기획 요약을 승인해 주십시오. |
| 1022-02 | 3 (기다림) | 시작 가능·사용자 신호 대기 | 바이오 P4 첫 실행 보고 | Claude | 아무 때나 | 「1022-02 시작」이라고 보내 주십시오. |
| 1022-08 | 3 (기다림) | 예정 (11/1 07:00 뒤) | FR-6c 재판정 대조 | Claude | 11/1 07:00 뒤 | — |
| 1025-02 | 3 (기다림) | 미착수 (사용자 보류 · 10/25) | 손실 자동 정지 수리 | — | 추후 상세 정리 뒤 | 실주문 허용을 다시 켜기 전 필수 (로드맵 A1 문장 유지). |
| 1025-08 | — | 완료 (10/26 · #120 #121 · 사용자 보유 표 확인) | 실계좌 보유 화면·기록 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1025-07 | — | 완료 (10/25 · #119 배포) | 안내 문구 · 셋째 경로 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1025-01 | — | 완료 (10/25 · #116 배포) | 실주문 안전 상황판 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-06 | — | 완료 (10/26 · 사용자 발동·해제 확인) | 발동 버튼 수리 확인 | 사용자 | 끝남 | 더 하실 일 없습니다 |
| 1022-07 | — | 완료 (10/25 · 운영 system → 하루 요약 · 전 값 immediate) | 시스템 경고 받는 방식 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-11 | — | 완료 (10/25 · 브랜치 2 · 사본 삭제 · 로컬 백업) | 옛 브랜치·PRD 사본 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1025-04 | — | 완료 (10/25 · #115 배포 · live_enabled 거짓 확인) | 서버 실주문 허용 끄기 | Claude·사용자 | 끝남 | 더 하실 일 없습니다 |
| 1022-01 | — | 완료 (10/23 · 서버 관측 정상) | 서버 관측 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-03 | — | 완료 (10/23 · #107 병합) | PR #107 병합 | 사용자 | 끝남 | 더 하실 일 없습니다 |
| 1022-04 | — | 완료 (10/23 · 배포 확인) | #107 배포 뒤 확인 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-05 | — | 완료 (10/23 · 비용 확정) | 재가동 비용 확정 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-09 | — | 완료 (10/23 · #111 · run 39924284050) | 알림 설정 페이지 | Claude | 끝남 | 원하시면 화면에서 「권고값 한 번에 적용」을 누르십시오. |
| 1022-13 | — | 완료 (10/23 · 사용자 결정) | LLM 전환 방식 결정 | 사용자 | 끝남 | 더 하실 일 없습니다 |
| 1022-15 | — | 완료 (10/23 · #109 병합·배포) | Anthropic 우선 전환 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1023-01 | — | 완료 (10/23 · #110 병합·배포) | 아침 알림 실패 수리 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1023-05 | — | 완료 (10/25 · #112 배포 · 「보냄」 확인) | 알림 문구 개편 | Claude | 끝남 | 더 하실 일 없습니다 |
| 1022-14 | — | 완료 (10/25 · 로컬 키 조회 200) | Anthropic 키 발급 | 사용자 | 끝남 | 더 하실 일 없습니다 |
| 1023-06 | — | 완료 (10/25 · fable.md:23 교체) | 금지 규칙 폐지 반영 | Claude | 끝남 | 더 하실 일 없습니다 |

자세히 (표와 같은 번호)
- 1025-08: 사용자 10/25 「토스증권은 실계좌 연동 · 보유 종목을 직접 확인 · 추후 매도 시점 방안 준비」. #120 (eebb461 · 서버 0.3.6): 토스 참고 환율 (backend/services/fx.py · 필수 baseCurrency·quoteCurrency · toss/cached/fallback 1330) · holding_snapshot 표 (15:50 평일 KR · 07:10 화~토 US · 거래일 = 토스 1d 최신 봉 · 첫 실행 200봉 백필 · 팔림 = 수량 0) · GET /api/v1/account/holdings. #121 (411f539 · 화면 0.3.5 · 서버 0.3.7): /account 보유 표. 서버 수동 --once holdings_* 는 자동 모드 분류기 (Remote Shell Writes) 가 막아 첫 잡에 맡김.
- 1026-01 (10/26 18시): 국내 15:50 첫 실행 정상 (보유 1 · 일봉 200). 브랜치 `feat/holdings-followup` 커밋 5fa9c28 (push 전): 청산 계획 「있음」=손절가·목표가 있을 때 · 「현재가가 … 최고」 (화면 금지어 「지금」 때문에 Fable 문구 대신) · 「장 열린 날」 · dashboard/positions 환율 to_thread · 07:40 배치에 미국 보유 종목 (1025-06 ① 승인) · conftest 환율 캐시 초기화 (순서 의존 테스트 실패 수리) · 서버 0.3.9 · 화면 0.3.7 · pytest 1600 통과/기존 4 실패. 다음: 10/27 07:10·08:10 첫 실행 확인 → main merge → Fable 검수 (코드 + PR) → push·PR → 사용자 병합 → WEN 대조는 10/28 07:40.
- 1025-05 (10/26): 08:10 잡은 10:07 배포로 등록돼 오늘은 돌지 않음 · 첫 실행 10/27 08:10. 미국 07:10 보유 기록도 같음.
- 1025-06 (10/26): 07:40 배치는 레이더 CSV 종목만 물어 WEN 이 대상에 없었음 (asked 79 · found 79 · toss_stock_code WEN 0행) → 1026-01 PR 로 해결.
- 1026-01: 첫 실행 확인 (표 생성 · 일봉 200봉 · peak_complete 전환 · 15:50 당일 봉 포함 여부) 뒤 Fable 권고 묶음 PR: 청산 계획 「있음」 조건 · 오늘 현재가가 최고일 때 「종가」 문구 · 「매일」→「장 열린 날」 · dashboard/positions fx to_thread. 브랜치는 main merge 뒤 PR.
- 1025-05: 계획 `docs/plans/judgment-outcomes/README.md` (사용자 결정 7건 10/26). #122 (ebe6e93 · 서버 0.3.8 · 화면 0.3.6): backend/services/outcomes.py · 08:10 잡 outcomes_daily · user_judgments.result_base_price/source (db.ensure_columns 앱 시작 멱등 ALTER · 운영 조회 정상 확인). --once outcomes 는 WP92 별도 승인.
- 1026-02: Fable #122 권고 — 긴 horizon (730일) 만기 계산 · 전 종목 조회 실패 시 알림 · /journal 대체·청산 행 「자동 계산 대상 아님」 · README 에 수동 실행 주의.
- 1022-12: 10/26 월요일 실행에서 watchlist_execute 2건 통과 (주말에만 실패) · 남은 4건 serenity_extractor 2 · stooq · powderkeg_models.
- 1022-06: (가) 승인 10/25 → PR #114 (병합 c93f85b · 배포 run 40168073825 성공 15:13 · Fable 「병합 승인됨 · PR #114」). `POST /api/v1/sniper/kill-switch` (require_sniper_token · reason 1~200자 · actor 패턴) · 화면 발동 → postWithToken. 운영 비로그인 POST 401 확인. 남은 것: 로그인한 화면에서 발동→해제 1회 클릭 확인 (발동 중에는 자동 주문 차단 · 바로 해제).
- 1025-01: /lab/execution 의 실행 상태·파라미터·모의 계좌·주문 카드가 미등록 `/api/v1/execution/*` (main.py:20-21 이월 dead 라우트) 를 불러 404. 라우터 등록 또는 sniper 이전 중 고르는 기획부터 (Fable 10/25: 1022-06 과 범위 분리).
- 1022-14: 완료 10/25 — 사용자가 로컬 `backend/.env` 에 `ANTHROPIC_API_KEY` 등록 · 모델 목록 조회 200 (claude-sonnet-5-5 포함). 서버로는 아직 안 감 (서버 env 는 `backend/.env.sops.yaml` 에서 옴 · 1022-16). 원래 안내: Anthropic 콘솔에서 API 키 발급. 넣기는 다른 터미널에서 `sops backend/.env.sops.yaml` (`ANTHROPIC_API_KEY`). 모델은 코드 기본값 Sonnet 5.5 (env 에 모델 없음 · 사용자 결정 10/23).
- 1022-16: PR #113 (병합 4dcc11a · 배포 run 40165890732 성공 10/25 14:37 · Fable 「병합 승인됨 · PR #113」). sops 에 ANTHROPIC_API_KEY · LLM_PROVIDER=anthropic. 기본 모델 claude-opus-5-5 · effort medium (사용자 10/25: 정확도 우선). 실측: 분석 글 13.8초 · 판정 2.8초. 비용 추정 월 ~$12 (콘솔 월 한도 사용자 설정). 남은 것: 10/26 Crazy 06:30·화약고 뒤 「LLM 대체 동작」 경고 없음 확인 · 11/1 콘솔 사용량 대조 (2배 이상이면 모델·effort 재질의). 되돌리기 LLM_PROVIDER=zai PR.
- 1023-05: Fable 최적안 (10/23 사용자 승인). E: AI 는 설계 때만 · 문구 틀은 코드에 고정. H: 숫자는 두고 「통계 추정가…보장 아님」 · 「지정가 참고」로 이름 변경 (Top10Modal.tsx 포함). 원칙 ⑦~⑬: 한국어 종류 이름 머리말 · 사실만 (지시 없음) · 절대 링크 · 추정 표시 · 제목 40자/본문 10줄/아이콘 1개 · 실패 알림에 다음 실행 시각 · 힌트 출처 하나. Kill Switch 알림에 화면 주소. 덧붙일 것: system 요약 실패 알림 gate=False · 「급등 가능성」→「급등 전 단계」 · SITE_BASE_URL 설정화. 순서: 종류별 전/후 초안 → 사용자 검토 → `docs/plans/alert-settings/wording.md`. → #112 병합 (724460a) · 배포 run 39990908416 성공 (10/24 02:02 · /health ok). 완료 근거 (10/25 13시대): 사용자가 /admin/notifications 에서 새 형식 제목 행과 결과 칸 「보냄」을 직접 확인 (종류·시각은 확인 문장에 없음). 「보냄」 행은 `[Notifier] sent` 로그 직후에만 기록되므로 서버 로그 확인을 갈음 (notifier.py:243-244 · Fable 10/25 수정 후 진행 → 막음 해소). 다음 PR: Crazy·Moonshot 실행 시각 상수 공유 · PR 나 (A4 설정 · system 요약 실패 gate=False · WP92). 미룬 지적 7건: ℹ️ 아이콘 판정 누락 · 밈 변수 `at` 가림 · 행동주의 SEC 링크(대상 CIK) 미확인 · Kill Switch 발동자 빈 값 「직접」 · 실주문 이름 조회 최대 2초 · 레딧 「다음 실행 07:00」 vs 06:30 혼동 · (Crazy·Moonshot 상수는 위 다음 PR).
- 1023-06: 완료 (10/25 · 사용자 승인 · Fable 2회 질의 → 진행). `.claude/agents/fable.md:23` 을 「추정 숫자는 같은 카드·알림 본문 안에 근거와 「추정 · 보장 아님」이 있으면 허용 · 권유·시기 지시는 NO-GO · 봉인 설계 금지(FR-6c 표)는 설계 우선」으로 교체 (확률 포함 · 사용자 승인). 그대로 둔 곳: `biotech_llm.py:49` FORBIDDEN_RE (AI 권유·전망 문장 거르기 · 바꾸면 WP92) · `biotech-fr6c.check.ts:38` (봉인 fr6c_design_v1.md 1·4절) · `backend/tests/alert_rules.py:8` (지시형·영어 이름 금지) · 미추적 `docs/plans/PRD/biotech/` (1022-11 · 보관 뒤 삭제 10/25).
- 1022-02: PENDING 2026-10-21 Fable 판정 항목. P4-2 `var/biotech/fr6c/cells_202610.json` 첫 판정 (표시 행 68 · 긍정 43 기대) · P4-4 readout_text 첫 실행 · SEC 장부 합계 ≤ 300 · 배지 표시 수 · 화면 빌드 해시 · /biotech 과거 기록 · 새 8-K 확인 섹션 스크린샷 → `scripts/fable_bundle.py` 번들 zip 으로 fable 역할에 보고.
- 1022-07: 이제 `/admin/notifications` 의 「시스템 경고」 받는 방식 (바로/하루 요약) 으로 사용자가 직접 정한다.
- 1022-11: 완료 10/25 — `feature/biotech-aact-weekly` (같은 수정이 main 에 있음) 로컬·원격 삭제 · `wip/local-docs` (main 에 없는 SCRIPTS.md·remote.sh·H6 zip) 는 `docs/plans/biotech/fable-bundles/backup-wip-local-docs-20261025.bundle` (verify ok) 보관 뒤 로컬 삭제 · `docs/plans/PRD/biotech/` 는 `backup-prd-biotech-copy-20261025.tgz` 보관 뒤 삭제. 원격 `hotfix/aact-zipfile-testzip` (b4abe77 · PENDING 60줄 옛 세션 상태) 도 사용자 지시로 `backup-hotfix-aact-20261025.bundle` 보관 뒤 삭제 (10/25).
- 1022-07: 완료 10/25 — 운영 `PUT /api/v1/notifications/settings/system` mode digest (전 값 immediate · 다른 행 변화 없음 확인).
- 1025-04: 완료 — PR #115 (병합 17d48cb · 배포 run 40175706246 성공 17:17 · Fable 「병합 승인됨 · PR #115」 · `SNIPER_LIVE_ENABLED` 한 키 false). 공개 /sniper/status live_enabled 거짓 · /admin/session live_enabled 거짓 확인. 확인: 자동 진입 (sniper·watchlist) 은 `EXECUTION_BROKER` 미설정 = paper. 실돈 경로는 `POST /sniper/entry` broker=toss 하나 (require_sniper_live_token).
- 1025-02 · 03 · 05 · 06: `docs/plans/site-roadmap/README.md` A1 · B1 · B0 · §5. 1025-06·01 기획 `docs/plans/site-roadmap/broker-link.md` (승인 10/25 · 배포 2a·2b 먼저 · WEN 대조 · 토큰 1개 규칙).
- 1023-04: #110 (rss.py httpx 피드당 4초 · 인스턴스 캐시 · Lock). 16:49 뒤 빈 오류 실패 0건 · Moonshot 16:52 · Sector 17:05 발송 확인. 남은 것: Crazy 10/24 06:30 발송 · 그때 `notification_log` 첫 기록과 18:00 하루 요약 실행 로그도 함께 본다.
- 1023-02: Z.ai glm-5.2 thesis 가 Crazy 전 종목에서 시간 초과. Anthropic 키 (1022-14·16) 로 해결 예정.
- 1022-10: 2 홈 "오늘" · 3 메뉴 15→5 · 4 로그인 하나 · 5 문구 · 6 시각 통일 · 7 모바일 · 8 정리. `docs/plans/ui-ux-optimization/README.md`.
- 1023-03: Finnhub 가 59종목 모두 profile not found.
- 1023-07: RSS 피드 4곳 중 3곳이 403.
- 1022-12: serenity_extractor 2 · test_stooq 1 · powderkeg_models 1 (순서 의존) · watchlist_execute 2 (주말 실행 시 실패 · execute.py:67-68 주말 차단 · 10/25 발견). test_powderkeg_triggers 도 단독 실행 시 실패 (main 도 같음).
- 1022-09: PR #111 (병합 f2310c4 · backend·frontend 0.2.0). 서버 표 3개 생성 · 화면 200 · 인증 없이 API 401 · 18:00 하루 요약 잡 등록. 설계 `docs/plans/alert-settings/design.md` · `implementation-plan.md`.
- 1022-15: PR #109 (FallbackLLM · 병합 d996135). 1023-01: PR #110 (병합 14802f4 · 원인: 제한 없는 feedparser 스레드가 기본 실행기 10개를 막아 DNS 조회까지 멈춤).

참고
- 로컬 `backend/data/tradebot.db` 는 ORM 표가 없는 상태이며 사용자 결정 (2026-10-22) 으로 그대로 둔다. 테스트는 루트 conftest 가 메모리 DB · 빈 텔레그램 토큰 · 빈 LLM 키로 고정한다.
- 병합·배포 피할 시각 (KST): 05:55–06:45 · 09:00–09:15 · 16:40–17:15 · 18:00 앞뒤.
- Fable 질의·답변: 로컬 `docs/plans/biotech/fable-bundles/` (git 제외) 와 세션 scratchpad.

### 해결 기록
- 2026-10-22 완료 7건: 세션 관측 정상 · PENDING 영구 규칙 5줄 (#104) · wp72 로컬 브랜치 삭제 · 테스트 16건 수정과 실 DB·실 텔레그램 차단 (#105 · 배포 run 39758639048) · 다음 과제·기획 폴더 (#106) · 텔레그램 알림 인벤토리·유용성 검증 · UI/UX 감사와 중요도 순 제안.
- 2026-10-21~22: fable 역할 추가 · P4 판정 수령 · #100 (시총 배지) · #95~#98 (P4-1~P4-4) 병합 · 배포 success · #101 · #102 문서 · worktree 정리 · 병합된 로컬 브랜치 103개 삭제.
