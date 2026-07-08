# Toss Tradebot MVP - 교훈 (Lessons Learned)

**목적**: 트러블슈팅·실수·비효율에서 얻은 실전 교훈을 축적하여 재발 방지 및 유사 상황에서의 판단 근거로 활용.

> **총 교훈 수**: 1개
> **마지막 업데이트**: 2026-07-08

---

## 📚 목차

- [교훈 #1: GitHub Actions 자동배포 확인 선행 — 수동 SSH 배포 계획 전 workflow 파일 먼저 확인](#교훈-1-github-actions-자동배포-확인-선행--수동-ssh-배포-계획-전-workflow-파일-먼저-확인)

---

## 교훈 #1: GitHub Actions 자동배포 확인 선행 — 수동 SSH 배포 계획 전 workflow 파일 먼저 확인

**발생일**: 2026-07-08
**카테고리**: 시스템 (배포 워크플로우)
**심각도**: P2-Medium

### 문제 상황

Sector Leaders Top10 진입가 v2.0 핫픽스 배포 절차를 진행하던 중:

1. 메모리 `reference_tossbot_deploy` (2026-06-25 작성) 를 근거로 수동 SSH 배포를 계획
2. `ssh root@optimus8.cafe24.com` 시도 → auto-mode classifier가 **"Production Reads via remote shell not explicitly authorized"** 로 차단
3. 사용자에게 SSH 승인 요청 → 사용자가 승인
4. 사용자가 별도로 **"github push 하면 github action 동작하지 않나?"** 라고 지적
5. `.github/workflows/deploy.yml` 확인 → **push: branches: [main] 자동 트리거로 이미 완비되어 있었음**
6. 실제로 방금 푸시한 커밋(`a8ffc60`) 은 이미 2m 20s 만에 배포 성공 (`gh run list` 로 확인)

즉, **수동 SSH 배포는 완전히 불필요한 작업**이었고, 만약 병행 실행됐다면 자동 배포와 race condition을 일으켰을 가능성.

### 근본 원인

1. **배포 계획 수립 전 `.github/workflows/` 디렉터리를 사전 확인하지 않음** — 프로젝트의 CI/CD 상태를 리포지토리 자체보다 메모리(외부 문서)에 우선 의존.
2. **메모리 시점 편향** — `reference_tossbot_deploy` 메모리는 2026-06-25 (13일 전) 시점의 수동 배포 절차만 기록. 그 이후 GitHub Actions 자동화가 추가되었을 가능성을 검토하지 않음.
3. **Auto-mode classifier의 SSH 차단 시그널을 놓침** — "prod 접근 차단" 은 "이미 자동화가 존재할 수 있다" 는 힌트로 해석 가능했으나, 승인 요청으로만 대응.
4. **사용자가 지적할 때까지 workflow 존재를 인지하지 못함** — 파트너로서 사용자에게 지적당해야 알아채는 것은 [[feedback-partner-accountability]] 원칙 위반.

### 해결 방법

1. **`.github/workflows/deploy.yml` 확인** → `push: branches: [main]` 트리거 + validate/deploy/verify 3단계 완비 확인
2. **`gh run list --workflow=deploy.yml --limit 3`** 로 현재 커밋의 workflow run 상태 확인 → `completed / success / 2m20s` 확인
3. **`curl -sS -o /dev/null -w "%{http_code}" https://optimus8.cafe24.com/health`** → `200` 반환으로 배포 성공 검증
4. SSH 접속·수동 배포 계획 폐기.

### 재발 방지 대책

1. **배포 계획 수립 첫 단계 = `.github/workflows/` 확인**
   ```bash
   ls .github/workflows/ 2>/dev/null && cat .github/workflows/*.yml | grep -E "on:|push:|branches:"
   ```
2. **배포 관련 메모리 (`reference_*deploy`, `*deploy*`) 는 워크플로우 파일과 대조 후 신뢰** — 메모리는 시점 편향 있음 (13일이면 이미 낡음).
3. **Auto-mode classifier 의 prod 접근 차단** 이 발생하면 "자동화 존재 가능성" 을 먼저 조사한 뒤 승인 요청.
4. **`gh` CLI 활용 우선순위 올리기** — `gh run list`, `gh workflow view`, `gh run view <id>` 로 SSH 없이 배포 상태 확인 가능.

### 관련 문서

- `.github/workflows/deploy.yml` — 자동 배포 실체
- 메모리 `reference_tossbot_deploy` (upbit 프로젝트 하위, 이 프로젝트 관련) — 수동 배포 절차 (여전히 유효한 fallback)
- 메모리 `feedback_partner_accountability` — 파트너로서 사용자가 지적하기 전에 근본 확인 원칙
- 이번 세션 커밋: `a8ffc60` (feat(sector-leaders/top10): 진입가 v2.0)

### 체크리스트 (향후 배포 작업 시)

- [ ] `.github/workflows/` 디렉터리 존재 여부 확인
- [ ] workflow 파일의 트리거 (`on: push`, `on: workflow_dispatch`) 파악
- [ ] 배포 대상 브랜치·조건 확인 (`if: github.ref == 'refs/heads/main'` 등)
- [ ] `gh run list` 로 최근 배포 이력 확인 (자동 배포 실제 동작 여부)
- [ ] 자동 배포 존재 시: `git push` 만으로 완료 → `gh run watch` 또는 `curl health`
- [ ] 자동 배포 없거나 실패 시: 메모리의 수동 배포 절차로 fallback
- [ ] Auto-mode classifier 가 prod 접근 차단 시 → 즉시 자동화 조사

---
**기록일**: 2026-07-08
**기록자**: Claude (사용자 지적 후 인식)
