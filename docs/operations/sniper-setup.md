# 스나이퍼 설정 — 관리자 매뉴얼

> **접근 대상**: 서버 관리자 · SOPS age key 보유자 한정.
> **본 문서를 보는 이유**: `/sniper` 공개 페이지에서 로컬 경로·env 이름·SOPS 파일명을 제거하고 (TBE Phase 6-1) 이 내부 문서로 이관.

---

## 1. 자동매매 실행 스위치 설계 (2단계 게이트)

스나이퍼 실주문은 두 스위치가 모두 On 일 때만 실행된다.

| 게이트 | 위치 | 목적 |
|---|---|---|
| **라이브 스위치** (서버측) | SOPS 암호화 env · 관리자만 편집 | 실 매매 활성화의 최종 방벽 · 재기동 필요 |
| **enabled 토글** (UI측) | `/sniper` 하드 파라미터 편집기 · 토큰 인증 | 운영자가 UI 에서 즉시 On/Off · hot reload |
| **인증 토큰** (X-API-Token) | 서버측 SOPS env · 클라이언트 localStorage | 편집·실주문 API 인증 |

두 스위치를 분리한 이유 · UI 조작만으로 실 매매가 시작되지 않도록 서버측 관리자 승인 게이트를 별도 유지.

---

## 2. 최초 셋업 (관리자 1회)

### 2.1 토큰 발급

```bash
openssl rand -base64 32
```

출력된 32자 랜덤 문자열이 인증 토큰. 안전한 곳에 임시 보관.

### 2.2 SOPS 암호화 env 편집

`docs/operations/secrets-management.md` §2 (SOPS + age 최초 셋업) 완료 상태에서:

```bash
cd <repo-root>
sops edit backend/.env.sops.yaml
```

에디터가 뜨면 다음 두 라인을 추가/수정 후 저장:

```yaml
SNIPER_LIVE_ENABLED: "true"
SNIPER_API_TOKEN: "<위에서 생성한 32자 랜덤 토큰>"
```

⚠️ **경고**: 값에 따옴표 필수. YAML 안전성 확보용.

### 2.3 백엔드 재기동

`docs/operations/deployment.md` §서비스 재기동 참조. 로컬 검증만 하려면:

```bash
# 로컬 dev
cd backend
export $(sops -d .env.sops.yaml | xargs)  # 임시 로드 (평문 상주 X)
uvicorn api.main:app --reload
```

프로덕션 반영은 커밋·push → GHA `deploy.yml` 자동 반영 (2~3분).

### 2.4 클라이언트 토큰 저장

관리자가 발급한 토큰을 UI 사용자에게 안전한 채널로 전달. 사용자는 `/sniper` 페이지 🔐 X-API-Token 카드에 붙여넣고 "저장" 클릭 (브라우저 localStorage 저장).

⚠️ **알림**: v2 인증(httpOnly 쿠키 + JWT)이 TBE Phase 6-3 로드맵에 있음. 현재 localStorage 방식은 임시.

---

## 3. UI 3단계 활성화 흐름 (사용자 관점)

`/sniper` 페이지의 시작 가이드 3단계는 아래와 대응:

| Step | UI 표기 | 백엔드 조건 |
|---|---|---|
| 1 | 서버 라이브 스위치 준비 | 관리자가 §2.2 완료 · `SNIPER_LIVE_ENABLED=true` |
| 2 | 브라우저에 토큰 저장 | 사용자가 §2.4 완료 |
| 3 | Sniper 활성 On (`enabled` 토글) | ParamsEditor 최상단 토글 · UI 저장 |

3개 스위치 모두 켜져야 `StatusPanel` 이 "실행 중"으로 표시.

---

## 4. 토큰 회전 (권장 · 분기 1회)

```bash
openssl rand -base64 32      # 새 토큰 생성
sops edit backend/.env.sops.yaml
# SNIPER_API_TOKEN 값을 신규 토큰으로 교체
git add backend/.env.sops.yaml
git commit -m "chore(secrets): sniper token rotation $(date +%Y-%m-%d)"
git push
# GHA 자동 배포 후 사용자에게 신규 토큰 재배포
```

기존 사용자 브라우저 토큰은 401 로 실패 · localStorage 재입력 필요.

---

## 5. 트러블슈팅

| HTTP 코드 | 원인 | 대응 |
|---|---|---|
| **401** X-API-Token 헤더 누락/불일치 | 토큰 오타 · 회전 후 미갱신 | 브라우저 localStorage 재입력 |
| **403** LIVE 비활성 (실주문 라우트만) | `SNIPER_LIVE_ENABLED != true` | §2.2 재확인 · 백엔드 재기동 |
| **500** 서버 토큰 미설정 | env 로드 실패 · SOPS 복호화 실패 | 서버 로그 · `sops -d backend/.env.sops.yaml` 로 복호화 확인 |

서버 로그 grep (관리자):
```bash
journalctl -u tossbot-backend -f | grep 'sniper auth'
```

---

## 6. 관련 문서

- `docs/operations/secrets-management.md` — SOPS + age 셋업
- `docs/operations/deployment.md` — 배포 자동화
- `docs/operations/vip-setup.md` — VIP 감시 활성화
- `docs/plans/tradebot-tobe/tradebot-tobe-prompt.md` — TBE Phase 6 로드맵 (보안·인증 고도화)
