# 🚀 Sprint 1 서버 배포 준비 체크리스트

**작성일**: 2026-07-12
**대상**: Sprint 1 완결 커밋을 optimus8.cafe24.com 서버에 반영
**배포 방식**: GitHub Actions 자동 배포 (`main` push 시 트리거)

## 0. 배포 원칙 요약

- **자동화 우선**: `.github/workflows/deploy.yml` 이미 존재 · 수동 SSH 배포 금지 (`[[feedback_workflow_first_before_manual_deploy]]`)
- **SOPS 자동 파이프라인**: `backend/.env.sops.yaml` → 배포 시 자동 복호화 → 서버 `/root/toss-tradebot-mvp/backend/.env`
- **안전 기본값**: 프로덕션 초기엔 `SNIPER_LIVE_ENABLED=false` 유지 · Paper 시뮬로 forward test 후 활성
- **Phase 단위 완결 후 배포**: `[[feedback_deploy_only_when_complete]]` — Sprint 1 완료 상태 (T44~T50 완결 · Test 78 pass)

---

## 1. 사전 확인

### 1-1. 로컬 커밋 상태
```bash
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp
git log origin/main..HEAD --oneline
```
**예상**: 10 커밋 선행 (Phase 0~3 + Sprint 1 + UI 개선)

### 1-2. GitHub Secrets (이미 등록됨 · 재확인)
- `OPTIMUS8_SSH_KEY` — ed25519 deploy key
- `OPTIMUS8_HOST` — `optimus8.cafe24.com`
- `OPTIMUS8_USER` — `root`
- `SOPS_AGE_KEY` — age 개인키

**확인 방법**: GitHub 웹 → Settings → Secrets → repository secrets 목록

### 1-3. Toss OpenAPI 허용 IP
- optimus8 IP `210.114.22.59` 는 Phase 0에서 WTS 허용 IP 등록 완료 (재확인 불필요)

---

## 2. SOPS `.env` 갱신 (사용자 수행)

### 2-1. 스나이퍼 신규 env 3종 추가

로컬에서 실행:
```bash
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp

# 1) 32자 랜덤 토큰 생성
openssl rand -base64 32
# 예: kJ8Nz2mQ7xY5pL9vR3sT6wA4bC1dE0fG=

# 2) SOPS 편집
sops edit backend/.env.sops.yaml
```

편집기에서 아래 값 추가/저장:
```yaml
SNIPER_ENABLED: "true"
SNIPER_LIVE_ENABLED: "false"     # 초기엔 false 유지 · forward test 통과 후 true
SNIPER_API_TOKEN: "<위에서 생성한 32자>"
PAPER_INITIAL_CASH: "1000000"
```

### 2-2. 기존 값 확인 (재확인 · 변경 없음)
```yaml
TOSS_CLIENT_ID: "<Phase 0 저장분>"
TOSS_CLIENT_SECRET: "<Phase 0 저장분>"
TOSS_ACCOUNT_SEQ: "1"

EXECUTION_ENABLED: "false"        # 지금은 Sniper만 사용 · Router는 별개
EXECUTION_BROKER: "paper"          # 기본 Paper 시뮬 · Sniper 오케스트레이터가 참조
EXECUTION_MAX_ORDER_AMOUNT: "100000"

TELEGRAM_BOT_TOKEN: "<기존>"
TELEGRAM_CHAT_ID: "<기존>"
```

### 2-3. SOPS 저장 확인
```bash
grep -c 'ENC\[AES256_GCM' backend/.env.sops.yaml
# 예상: 32+ (SNIPER 3종 · PAPER 1종 추가)
```

---

## 3. 배포 트리거 방식 (사용자 선택)

### 옵션 A · 자동 배포 (권장)
```bash
git push origin main
```
- `main` push 즉시 GitHub Actions 워크플로우 실행
- 5분 이내 서버 반영 · `/health` 자동 확인
- 실패 시 workflow 로그에서 원인 확인

### 옵션 B · workflow_dispatch (수동 트리거)
```
GitHub 웹 → Actions → Deploy to optimus8 → Run workflow
```
- 임의 시점 재실행 · code 상태는 그대로 사용

### 옵션 C · 로컬만 유지 (배포 안 함)
- 지금 상태로 로컬에서만 검증
- 월요일 09:00 KST 개장 후 사용자 판단 시 옵션 A로 배포

---

## 4. 배포 후 검증 (사용자 협업)

### 4-1. 자동 확인 (workflow 자체)
- `[5/5] pm2 reload` 이후 20초 대기 · `https://optimus8.cafe24.com/health` → 200 확인
- 실패 시 workflow 로그에 `✗ health check failed after 3 retries` 표시

### 4-2. 수동 확인 (실 서비스)

**a. 헬스체크**:
```
curl https://optimus8.cafe24.com/health
# 예상: {"status":"ok","service":"toss-tradebot-mvp"}
```

**b. Sniper API 라우트**:
```
curl https://optimus8.cafe24.com/api/v1/sniper/status
# 예상: {"live_enabled":false,"sniper_enabled":false,...}
```

**c. 프론트엔드**:
- 브라우저 → `https://optimus8.cafe24.com/sniper`
- 📖 시작하기 카드 · Status Panel · Universe 150 종목 · Params Editor 표시

**d. 인증 방어**:
```
curl -X PUT https://optimus8.cafe24.com/api/v1/sniper/params -d '{}'
# 예상: 403 · "Sniper 실주문이 비활성화되어 있습니다"
```

---

## 5. 롤백 절차 (사고 시)

### 5-1. GitHub main revert
```bash
git revert <sprint1-commits> --no-edit
git push origin main
# 자동 배포 트리거 · 이전 커밋 상태로 복귀
```

### 5-2. 서버 직접 롤백 (긴급 · SSH · 감독하 승인 필요)
```bash
ssh root@optimus8.cafe24.com
cd /root/toss-tradebot-mvp
git reset --hard <이전-good-hash>
systemctl restart tradebot-api tradebot-cron
pm2 reload tradebot-web
```

### 5-3. .env 백업 복원
- workflow 가 매 배포 시 `.env.bak.<timestamp>` 생성 · 최근 10개 유지
- 문제 시: `cp .env.bak.<timestamp> .env` · 서비스 재기동

---

## 6. Sprint 1 서버 활성 순서 (배포 후 · 사용자 결정)

배포로 **코드는 반영**되지만 실주문은 여전히 비활성 (안전 원칙):

### Stage 1: 서버 상태 확인 (배포 직후)
- `SNIPER_ENABLED=true` (기본) · APScheduler 잡 등록 확인 (로그)
- `sniper.enabled=false` (기본) · 실 스캔 안 함
- Paper Adapter 만 활성

### Stage 2: Paper 시뮬 활성 (배포 후 언제든)
- 로컬에서 `sniper edit`로 `SNIPER_API_TOKEN` 저장
- 브라우저 `/sniper` → 토큰 입력
- ParamsEditor `sniper.enabled=On` 토글
- 5분 관찰 · Paper 시뮬 매매 로그 확인
- `EXECUTION_BROKER=paper` 유지 · 실 자금 위험 zero

### Stage 3: Toss 실 매매 (Sprint 2 이후 · 신중)
- Forward test 최소 5거래일 통과
- `SNIPER_LIVE_ENABLED=true` · `EXECUTION_BROKER=toss` 로 승격
- 실 계좌 잔고 확인 · 하드 상한 10만원/주문 유지
- 매일 09:00 손실 리뷰

---

## 7. 배포 전 체크리스트

- [ ] 로컬 커밋 상태 확인 (`git log origin/main..HEAD`)
- [ ] SOPS `.env.sops.yaml` 에 SNIPER_ENABLED · SNIPER_LIVE_ENABLED · SNIPER_API_TOKEN · PAPER_INITIAL_CASH 추가 저장
- [ ] SOPS 저장 후 `git status` 로 파일 변경 확인 · 재커밋 필요 시 진행
- [ ] `.env.example` · `.env.sops.yaml.example` 스키마 업데이트 확인 (본 커밋 포함)
- [ ] 프로덕션 초기 `SNIPER_LIVE_ENABLED=false` 유지 확정
- [ ] GitHub Actions Secrets 4종 존재 확인 (OPTIMUS8_SSH_KEY · OPTIMUS8_HOST · OPTIMUS8_USER · SOPS_AGE_KEY)
- [ ] `git push origin main` 실행 승인 (사용자 결정)

---

## 8. 참조

- 워크플로우: `.github/workflows/deploy.yml`
- SOPS 워크플로우: `[[reference_sops_age_workflow]]`
- 서버 구조: `[[reference_tossbot_deploy]]`
- Sprint 1 계획서: `docs/plans/sniper/00-sprint1-plan.md`
- 정체성: `[[project_true_identity]]`
- 보안: `[[feedback_sniper_security_and_flexibility]]`
