# 관측성 활성화 — 관리자 매뉴얼

> **접근 대상**: 서버 관리자 · SOPS age key 보유자 한정.
> **본 문서를 보는 이유**: Phase D 주 8 로 Sentry / PostHog 코드는 배선 완료.
> DSN·KEY 미설정 시 완전 no-op 이므로 앱은 정상 동작. 관측을 켜려면 아래 절차.

---

## 1. 왜 필요한가

| 도구 | 무엇을 관측하나 | 게이트 D 조건 |
|---|---|---|
| **Sentry** | 백엔드·프론트 예외·에러 rate · 라우트별 실패 추이 | "Sentry 첫 error 관측" (roadmap-12week §Phase D) |
| **PostHog** | 페이지 방문·판정 저장 이벤트·자기 사용 패턴 | Phase E 사용 정착기 KPI 근거 |

**둘 다 무료 티어**로 시작 가능. 신용카드 불필요.

---

## 2. Sentry 설정 (백엔드 + 프론트 공용)

### 2.1 계정·프로젝트 생성

1. https://sentry.io/signup/ → GitHub OAuth 로 가입 (개인 무료 · 5k events/month).
2. 프로젝트 2개 생성 · 각각 DSN 복사:
   - **Backend**: Platform = `Python / FastAPI` → DSN
   - **Frontend**: Platform = `JavaScript / Next.js` → DSN
3. Alerts → 이슈 알림 규칙 (선택). 초기엔 기본값 유지.

### 2.2 SOPS 편집 (백엔드 env)

```bash
sops edit backend/.env.sops.yaml
```

다음 3줄 추가·수정 (SOPS 자동 재암호화):

```yaml
SENTRY_DSN: "https://<key>@sentry.io/<project_id>"
APP_ENV: "production"
SENTRY_TRACES_SAMPLE_RATE: "0"    # 트래픽 늘면 0.05~0.1
```

### 2.3 프론트 env (Vercel 스타일 · SOPS 이관 시 backend SOPS 에 함께)

프론트 `.env.local` 은 서버에서 빌드 시 주입. 현 프로젝트는 backend/.env 를 공통으로 쓰므로:

```yaml
NEXT_PUBLIC_SENTRY_DSN: "https://<key>@sentry.io/<frontend_project_id>"
NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE: "0"
NEXT_PUBLIC_APP_ENV: "production"
```

**주의**: `NEXT_PUBLIC_` 접두는 클라이언트 번들에 노출됨. Sentry DSN 은 노출 허용된 값(rate-limit 만 걸림).

### 2.4 재배포 · 활성 확증

```bash
gh workflow run deploy.yml    # 또는 아무 파일 커밋·push
```

배포 후:
- 백엔드 로그: `[observability] Sentry 활성 · env=production · traces_sample_rate=0.00`
- 프론트 브라우저 콘솔: 오류 없이 진입 · Sentry.io Issues 탭에서 첫 event 대기.

**첫 event 강제 (검증용)**: 백엔드에서 잘못된 URL 호출로 500 유발 →
```bash
curl -sS https://optimus8.cafe24.com/api/v1/does-not-exist
```
Sentry.io Issues 탭에 이벤트 도착하면 배선 확증. 이후 게이트 D 조건 통과.

---

## 3. PostHog 설정 (프론트 전용)

### 3.1 계정·프로젝트 생성

1. https://posthog.com/signup → 무료 (1M events/month).
2. Region: **US** 권장 (기본 host `https://us.i.posthog.com`).
3. Project → Settings → **Project API Key (public)** 복사. `phc_...` 로 시작.

### 3.2 SOPS 편집

```yaml
NEXT_PUBLIC_POSTHOG_KEY: "phc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
NEXT_PUBLIC_POSTHOG_HOST: "https://us.i.posthog.com"
```

### 3.3 재배포 · 활성 확증

배포 후 브라우저에서 `/journal` 열기 → PostHog dashboard `Events`:
- `$pageview` · 자동 pageview 수집
- 판정 1건 저장 → `judgment_created` event 도착
  - properties: `page_source`, `hypothesis_id`, `mood`, `horizon_days`, `has_target`

---

## 4. 코드 배선 참조 (수정 없이 즉시 활성)

**Backend**
- `backend/services/observability.py` · `init_sentry()` · DSN 미설정 시 no-op
- `backend/services/config.py` · `sentry_dsn/environment/traces_sample_rate`
- `backend/api/main.py` · lifespan startup 에서 호출

**Frontend**
- `frontend/lib/observability.ts` · `initObservability()` + `capture()`
- `frontend/app/providers.tsx` · useEffect 초기화
- `frontend/components/journal/JudgmentDialog.tsx` · 저장 성공 시 capture

---

## 5. 로테이션 · 폐기 절차

- Sentry DSN 노출 의심 시 sentry.io → Project Settings → Client Keys → **Revoke** → 새 DSN 발급 → SOPS 갱신.
- PostHog Public Key 폐기 시 Project Settings → API Keys → Regenerate → SOPS 갱신.
- 두 도구 모두 프로젝트 삭제해도 이벤트 데이터는 무료 티어 기준 30일 후 자동 소멸.

---

## 6. 트러블슈팅

| 증상 | 원인·조치 |
|---|---|
| Sentry 이벤트 안 옴 | DSN 오타 · APP_ENV 로그로 활성 여부 재확인. `[observability]` 로그 없으면 lifespan 미도달. |
| 프론트 Sentry 안 옴 | 브라우저 콘솔에 `[observability] Sentry init 실패` 확인. CSP 헤더가 sentry.io 차단하는지 점검. |
| PostHog `$pageview` 안 옴 | POSTHOG_HOST region 불일치 (`us.i.posthog.com` vs `eu.i.posthog.com`). Project region 확인. |
| capture(`judgment_created`) 안 옴 | Journal 저장 성공까지 완료했는지 확인. `posthog.capture` 는 network idle 후 flush · 몇 초 지연 정상. |
