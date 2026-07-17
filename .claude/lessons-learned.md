# Toss Tradebot MVP - 교훈 (Lessons Learned)

**목적**: 트러블슈팅·실수·비효율에서 얻은 실전 교훈을 축적하여 재발 방지 및 유사 상황에서의 판단 근거로 활용.

> **총 교훈 수**: 2개
> **마지막 업데이트**: 2026-07-17

---

## 📚 목차

- [교훈 #1: GitHub Actions 자동배포 확인 선행 — 수동 SSH 배포 계획 전 workflow 파일 먼저 확인](#교훈-1-github-actions-자동배포-확인-선행--수동-ssh-배포-계획-전-workflow-파일-먼저-확인)
- [교훈 #2: 문서 §6 팔림세스트 재발 3회째 — 숫자 변경 커밋 시 §6 동시 정합 필수](#교훈-2-문서-6-팔림세스트-재발-3회째--숫자-변경-커밋-시-6-동시-정합-필수)

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

---

## 교훈 #2: 문서 §6 팔림세스트 재발 3회째 — 숫자 변경 커밋 시 §6 동시 정합 필수

**발생일**: 2026-07-16 (3차 리뷰 지적으로 인식)
**카테고리**: 문서 정합성
**심각도**: P2-Medium (누적 3회 재발)

### 문제 상황

Phase 7 완료 보고서 `docs/plans/powderkeg-screener/phase7-final-report.md` §6 "프로덕션 데이터" 라인이 코드/DB 실측과 지속 불일치:

1. **v1.10~v1.11 (2026-05)**: 상폐 imputation 결과 정정 · §6 갱신 누락 → v1.11 정정
2. **v1.12 (2026-05)**: "팔림세스트 정합화" 커밋으로 명시 수정 후 종결 선언
3. **v1.19 (2026-07-16)**: 최대주주 51 → 168 확대 실행 · §6 여전히 "51 최대주주" · **3차 리뷰가 지적**
   - 반박문(`2nd-review-rebuttal.md` §3)에서 168 확대를 인정했으나 본문 §6 미갱신
   - 재재반박이 정확 지적: "§6 갱신 프로세스 결함 3회째"

### 근본 원인

- 코드/DB 수치 변경 시 문서 정합 검증이 **커밋 시점**에 자동화되어 있지 않음
- 개별 커밋은 각자 완결됐다고 판단 (§17-3 등 세부 섹션은 갱신) 하지만 §6 요약 헤더는 chore 취급되어 스킵
- "완결 문서 ≠ 실전 완결" 원칙(반박문 §9) 재확인

### 교훈

숫자·개수·비율을 변경하는 모든 커밋은 관련 요약 문서 `§6 프로덕션 데이터` (또는 유사 요약 헤더) 를 함께 갱신한다. 갱신하지 않았다면 커밋 전 스스로 재검토.

### 체크리스트 (숫자 변경 커밋 전)

- [ ] `git diff` 에 숫자 (카운트·비율·티어 개수·티커 수) 변경 포함?
- [ ] `grep -n "N 종목\|N+ \|카운트\|비율" docs/plans/<subject>/**final*.md` 로 관련 §6 요약 위치 확인
- [ ] §6 라인 미변경이면 **의도적인지** 자문 → 의도 없다면 함께 갱신
- [ ] 개정 이력 (§17-*, 개정 이력 표) 에 원인 커밋 SHA 명시

### 관련 문서

- `docs/plans/powderkeg-screener/phase7-final-report.md` §6 (line 26 · 3회 정정 대상)
- `docs/plans/powderkeg-screener/2nd-review-rebuttal.md` §3 (168 확대 인정하나 §6 미갱신)
- `docs/plans/powderkeg-screener/3rd-review-response.md` §5 (팔림세스트 3회째 확증 · P1 정정)
- 정정 커밋: v1.29 (본 교훈 커밋과 동시 진행)

### 메타 · 반박문 §9 인용

> "완결 문서 ≠ 실전 완결 · 지속 리뷰 필요"

3차 리뷰가 이 원칙의 실증. 문서 정합은 코드 정합만큼의 리뷰 리소스가 필요.

---
**기록일**: 2026-07-17
**기록자**: Claude (3차 리뷰 재재반박 §3 지적 후 인식)
