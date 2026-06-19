# Toss Tradebot MVP

Toss Open API 기반 주식 자동매매 봇 + Discovery 모듈 (Crazy Picks + Moonshot Picks).

자매 프로젝트 [`upbit-tradebot-mvp`](../upbit-tradebot-mvp) 에서 검증된 알림·운영·워크플로우 자산을 차용.

## 🎯 핵심 컨셉

3 모듈 자금·로직 완전 분리:

| 모듈 | 자금 | 데이터 소스 | 매매 방식 |
|---|---|---|---|
| **① 자동매매 코어** | 1,500만원 | **Toss API** | 자동 매수/매도 |
| **② Crazy Picks** | 0원 (정보) | Stooq + Finnhub + Reddit + RSS | 사용자 별도 결정 |
| **③ Moonshot Picks** | 100만원 | Stooq + SEC EDGAR + FINRA + Reddit + LLM | **토스 WTS 수동 매수** |

## 🚧 현 단계 — Phase A: 프로젝트 골격 완료 (2026-06-19)

| Phase | 상태 |
|---|---|
| **A** 프로젝트 골격 | ✅ 완료 |
| B DB 인프라 | 대기 |
| C 데이터 소스 클라이언트 | 대기 |
| D Discovery 코어 | 대기 |
| E /moonshot CLI | 대기 |
| F Telegram 알림 | 대기 |
| G FastAPI Backend | 대기 |
| H Frontend (Next.js) | 대기 |
| I 인프라 셋업 | 대기 |
| J 통합 테스트 + 1주 dry-run | 대기 |
| K 자동매매 코어 (Toss API 오픈 후) | 대기 |

상세: [`docs/plans/implementation-roadmap.md`](./docs/plans/implementation-roadmap.md)

## 📂 디렉터리 구조

```
toss-tradebot-mvp/
├── backend/                # Python (FastAPI + Discovery + CLI)
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── .env.example        # placeholder만 — 실 .env 는 chmod 600
│   ├── core/               # 자동매매 코어 (Phase K)
│   ├── engine/             # Phase K
│   ├── discovery/          # Phase D
│   ├── services/           # Phase C, F
│   ├── api/                # Phase G — FastAPI
│   ├── cli/                # Phase E — /moonshot
│   ├── tests/
│   └── data/               # SQLite + 캔들 캐시
│
├── frontend/               # Next.js 14 + Tailwind + shadcn/ui
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── .env.example
│   ├── app/                # App Router 페이지
│   ├── components/
│   └── lib/
│
├── docs/
│   ├── plans/PRD/          # 01·02·03 PRD
│   │   ├── 01-research-foundation.md
│   │   ├── 02-strategy-decision.md      # 44 결정 매트릭스
│   │   └── 03-PRD-v1.md                 # 시스템 요구사항
│   ├── plans/
│   │   └── implementation-roadmap.md    # Phase A~K
│   └── analysis/
│       ├── toss-api-survey.md
│       └── moonshot-factor-research.md  # Phase 1 학술 검증
│
├── .claude/                # Claude Code
│   ├── context/project-rules.md
│   └── skills/moonshot.md  # /moonshot Skill placeholder
│
├── .github/workflows/
│   └── deploy.yml          # GitHub Actions CI/CD (Phase I 완성)
│
├── CLAUDE.md               # 작업 계약
└── README.md               # 본 문서
```

## 🚀 로컬 개발 시작 (Phase A 후)

### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -e .[dev]
cp .env.example .env  # 자격증명 본인 입력 (chmod 600)
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env.local  # 자격증명 본인 입력
npm run dev  # http://localhost:3000
```

## 🔒 보안 가이드 (글로벌 가드레일 준수)

- **`.env`/`.env.local`** chmod 600, git 추적 X
- **SSH 키 기반 인증** (비밀번호 비활성화 권고)
- **GitHub Secrets**: SSH key + API key (workflow yml 평문 X)
- **NextAuth.js** Google OAuth + Gmail 화이트리스트 (`ALLOWED_EMAIL=suauncle@gmail.com`)
- 자격증명 노출 시 즉시 로테이션 (글로벌 CLAUDE.md §1.3)

## 📋 작업 규칙

- 사용자 승인 없이 다음 단계 진행 금지
- 멀티 Phase 는 전 Phase 완성 후 단일 배포 (Phase K 자동매매 별도)
- 기획안·구현계획서는 채팅 보고 → 승인 → 문서 저장
- 자격증명 평문 금지

상세: [`CLAUDE.md`](./CLAUDE.md) 및 [`.claude/context/project-rules.md`](./.claude/context/project-rules.md)
