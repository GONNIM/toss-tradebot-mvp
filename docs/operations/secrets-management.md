# Secrets 관리 — SOPS + age

**목적**: 서버 `backend/.env` 를 로컬 폴더에서 안전하게 편집·서버 반영.
**방식**: 파일 자체를 age 로 암호화해서 git 커밋 → 로컬 `sops edit` 로 평문 편집 → GitHub Actions 가 CI 에서 복호화 → 서버 `.env` 생성.
**보안 원칙**: 평문 자격증명은 로컬·git·CI 어디에도 상주하지 않음. 유일한 평문 접점은 사용자가 `sops edit` 실행 중일 때의 임시 파일뿐 (SOPS 가 종료 시 삭제).

**관련**:
- 글로벌 가드레일 `~/.claude-profiles/naver/CLAUDE.md` §1 (평문 자격증명 금지)
- 배포 자동화 [[reference_tossbot_deploy]] · [[feedback_workflow_first_before_manual_deploy]]

---

## 1. 왜 SOPS + age 인가

| 대안 | 채택 | 이유 |
|------|------|------|
| **SOPS + age** | ✅ | 파일 자체 암호화 · git 커밋 안전 · git diff 로 어떤 키가 변했는지 추적 · IDE 편집 지원 · age key 관리 단순 |
| git-crypt | ❌ | GPG 필요 → macOS 세팅 번거로움 · unlock 상태에서 실수 노출 위험 |
| GitHub Secrets 완전 이관 | ❌ | 로컬 폴더에 파일 없음 → "로컬에서 편집" 요구 불충족 · 값 개수 증가 시 관리 부담 |
| Vault / SSM | ❌ | MVP 규모에 과함 |

---

## 2. 최초 셋업 (사용자 1회)

### 2.1 도구 설치

```bash
brew install sops age
sops --version    # 3.x
age --version     # 1.x
```

`pre-commit` / `gitleaks` 는 이미 설치되어 있음 (없으면 `brew install pre-commit gitleaks`).

### 2.2 age key 생성

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt

# public key 확인 (안전 · 커밋 가능)
grep 'public key' ~/.config/sops/age/keys.txt
# 예: # public key: age1abc0123...def
```

⚠️ **백업**: `keys.txt` 를 1Password 등에 사본 보관. 분실 시 모든 secret 접근 불가 · 복구 불가.

### 2.3 `.sops.yaml` 에 public key 등록

리포 루트 `.sops.yaml` 의 `REPLACE_ME_WITH_AGE_PUBLIC_KEY` 를 방금 생성한 public key 로 교체:

```yaml
creation_rules:
  - path_regex: (^|/)\.env\.sops\.yaml$
    encrypted_regex: '.*'
    age: age1abc0123...def
```

### 2.4 초기 `.env.sops.yaml` 생성

```bash
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp

# 예시 파일 복사 (평문 상태)
cp backend/.env.sops.yaml.example backend/.env.sops.yaml

# ⚠️ 이 시점 backend/.env.sops.yaml 은 평문 · 커밋 금지
# 즉시 암호화:
sops -e -i backend/.env.sops.yaml

# 파일이 sops 헤더(sops: version:)를 포함한 암호화 상태로 바뀜 → 커밋 안전
head -20 backend/.env.sops.yaml
```

### 2.5 실 값 입력 (SOPS 편집)

```bash
sops edit backend/.env.sops.yaml
# 임시 tmpfs 위치에 평문으로 열림
# 값 입력 후 저장 → 자동 재암호화 → tmpfs 파일 삭제
```

편집 예시:

```yaml
TOSS_CLIENT_ID: "실 client id"
TOSS_CLIENT_SECRET: "실 secret"
TELEGRAM_BOT_TOKEN: "1234:abcd..."
VIP_ENABLED: "true"
VIP_AVG_PRICE: "7.77"
VIP_QTY: "100"
```

### 2.6 GitHub Secret 등록

```bash
gh secret set SOPS_AGE_KEY < ~/.config/sops/age/keys.txt
# 또는: GitHub 웹 UI → Settings → Secrets → SOPS_AGE_KEY 붙여넣기
```

### 2.7 pre-commit 훅 활성화

```bash
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp
pre-commit install
# .git/hooks/pre-commit 활성화 → 커밋 직전 gitleaks 자동 스캔

# 초기 검증
pre-commit run --all-files
```

---

## 3. 일상 편집 워크플로우

```bash
# 값 편집 (평문 노출 최소화)
sops edit backend/.env.sops.yaml

# 확인 (평문으로 stdout — 저장 X)
sops -d backend/.env.sops.yaml

# 특정 키만 조회
sops -d backend/.env.sops.yaml | grep VIP_AVG_PRICE

# 커밋 → push → GitHub Actions 자동 배포 → 서버 backend/.env 갱신
git add backend/.env.sops.yaml
git commit -m "chore(secrets): rotate telegram token"
git push origin main
```

**push 후 배포 진행 관찰**:

```bash
gh run list --workflow=deploy.yml --limit 1
gh run watch <run-id>
```

---

## 4. GitHub Actions 통합 (별도 커밋 대기 상태)

**⚠️ 현재 상태**: 스캐폴딩만 완료. workflow 는 아직 SOPS 를 사용하지 않고 기존 방식(개별 GitHub Secret 3개 inject) 유지. 아래 절차를 사용자가 준비 완료한 뒤 별도 커밋으로 workflow 를 SOPS 방식으로 교체할 예정.

### 준비 완료 체크리스트
- [ ] `brew install sops age` 완료
- [ ] `age-keygen` 실행 → private key 백업 (1Password)
- [ ] `.sops.yaml` 에 public key 등록
- [ ] `backend/.env.sops.yaml` 실 값 입력 완료 (평문 편집 → 자동 재암호화)
- [ ] `gh secret set SOPS_AGE_KEY` 등록 완료
- [ ] `pre-commit install` 완료

### workflow 변경안 (준비 완료 후 적용)

`.github/workflows/deploy.yml` 의 "Inject runtime secrets into backend/.env" 스텝을 다음으로 대체:

```yaml
- name: Setup SOPS + age
  run: |
    curl -sSfL https://github.com/getsops/sops/releases/latest/download/sops-v3.9.0.linux.amd64 \
      -o /usr/local/bin/sops
    chmod +x /usr/local/bin/sops
    curl -sSfL https://github.com/FiloSottile/age/releases/latest/download/age-v1.2.1-linux-amd64.tar.gz \
      | tar xz -C /tmp && sudo mv /tmp/age/age* /usr/local/bin/
    mkdir -p ~/.config/sops/age
    echo "${{ secrets.SOPS_AGE_KEY }}" > ~/.config/sops/age/keys.txt
    chmod 600 ~/.config/sops/age/keys.txt

- name: Decrypt .env and push to server
  run: |
    # SOPS → dotenv 로 변환 (YAML → KEY=VALUE)
    sops -d --output-type=dotenv backend/.env.sops.yaml > /tmp/backend.env
    scp -o StrictHostKeyChecking=no /tmp/backend.env \
        ${{ secrets.OPTIMUS8_USER }}@${{ secrets.OPTIMUS8_HOST }}:/root/toss-tradebot-mvp/backend/.env
    ssh ${{ secrets.OPTIMUS8_USER }}@${{ secrets.OPTIMUS8_HOST }} 'chmod 600 /root/toss-tradebot-mvp/backend/.env'
    shred -u /tmp/backend.env
```

이 스텝을 **checkout 뒤 · Deploy to optimus8 앞** 에 삽입하고, 기존 개별 secret inject 스텝은 삭제한다.

---

## 5. 로컬 → 서버 반영 흐름 (최종)

```
[로컬 편집]                     [git]                    [GitHub Actions]              [서버]
   ↓                              ↓                            ↓                          ↓
sops edit → 평문 tmpfs         backend/.env.sops.yaml    checkout 후 SOPS 복호화     backend/.env (chmod 600)
   ↓ 저장                      (암호문만 커밋)                ↓                    systemctl restart
자동 재암호화                       git push              scp .env → 서버              tradebot-*
   ↓
암호문 저장 완료
```

평문이 상주하는 순간:
- 로컬 tmpfs (sops edit 세션 · 종료 시 삭제)
- CI runner ephemeral disk (workflow 종료 시 파기)
- 서버 backend/.env (chmod 600 · root 만 접근)

---

## 6. 키 롤테이션 · 백업 · 복구

### 로컬 age key 유출 의심
1. 새 age key 생성 (`age-keygen -o ~/.config/sops/age/keys.txt.new`)
2. `.sops.yaml` 에 새 public key 추가 (기존 것도 유지 → 이중 recipient)
3. 재암호화: `sops updatekeys backend/.env.sops.yaml`
4. GitHub Secret `SOPS_AGE_KEY` 도 새 key 로 교체
5. 기존 key 유출 → **모든 secret 값 재발급** (Telegram token, DART API 등)
6. `.sops.yaml` 에서 기존 public key 제거 · `sops updatekeys` 재실행

### 사용자 추가 (팀 확장)
- 새 팀원이 `age-keygen` → public key 공유
- `.sops.yaml` `age:` 에 콤마 구분으로 추가
- `sops updatekeys backend/.env.sops.yaml` → 새 recipient 로 재암호화

### 로컬 key 분실
- 백업 (1Password 등) 에서 복원
- 백업 없으면 **복구 불가** — 위 롤테이션 절차로 새 key 로 재시작 (모든 값 다시 입력)

---

## 7. 문제해결

**`sops: config file not found`**
→ `.sops.yaml` 이 repo root 에 있는지 확인. `sops` 실행 위치는 repo 안이어야 자동 탐색.

**`Error: failed to load age identity`**
→ `~/.config/sops/age/keys.txt` 파일 존재·권한 (chmod 600) 확인.

**`gh secret set` 실패**
→ `gh auth status` 로 GitHub 인증 확인. 리포 admin 권한 필요.

**pre-commit 훅이 SOPS 파일을 자격증명이라 잘못 탐지**
→ `.gitleaks.toml` allowlist paths 에 `backend/.env.sops.yaml` 이 포함돼 있어 정상 통과. 오탐 발생 시 이 파일에 규칙 추가.

**서버 `.env` 가 예전 상태**
→ SOPS 방식 활성화 전이면 GitHub Actions "Inject runtime secrets" 가 여전히 개별 secret 만 주입. workflow 교체 완료 후엔 SOPS 파일 커밋 → 자동 배포로 전체 갱신.

---

## 8. 관련 파일

- `.sops.yaml` — SOPS 규칙 (public key 만)
- `backend/.env.sops.yaml` — 암호화된 실제 secret 파일 (git 커밋)
- `backend/.env.sops.yaml.example` — 평문 스키마 예시 (커밋 · placeholder 만)
- `.pre-commit-config.yaml` — pre-commit 훅 설정
- `.gitleaks.toml` — gitleaks 커스텀 룰 · SOPS 파일 allowlist
- `.github/workflows/deploy.yml` — CI 배포 (SOPS 통합은 별도 커밋 예정)
- 이 문서 — 셋업·롤테이션·복구 절차
