# Toss Tradebot MVP - 프로젝트 규칙

**목적**: 워크플로우·금지 사항·체크리스트 일원화 (자매 프로젝트 `upbit-tradebot-mvp`의 보편 자산 이전)
**시작일**: 2026-06-16

---

## 🚨 긴급 상황 대응 (TBD)

본 섹션은 첫 실 운영 이슈 발생 시부터 누적. 현재는 비어있음.

> 참고: `upbit-tradebot-mvp` `.claude/context/project-rules.md`의 "긴급 상황 대응 우선순위" 패턴을 따른다.

---

## 📋 Issue 인덱스 (0건)

| # | 제목 | 핵심 메시지 | 날짜 |
|---|------|------------|------|
| — | (없음) | 첫 Issue 발생 시 #1부터 누적 | — |

> Upbit 프로젝트의 Issue #1~#21은 코인·pyupbit 특화이므로 본 프로젝트에 직접 이전하지 않는다. 동일 유형 사례가 Toss 환경에서 재발하면 별도 Issue 번호로 신규 기록.

---

## ❌ 금지 사항 (CRITICAL)

### 코드 레벨 — 보편 원칙 (언어·API 무관)

```python
# ❌ 절대 금지: Timezone 미지정 datetime
ts = pd.Timestamp.now()
# ✅ 올바른 방법: Timezone 명시 (Asia/Seoul 또는 UTC)
ts = pd.Timestamp.now(tz='Asia/Seoul')

# ❌ 절대 금지: 모든 예외 swallow
try:
    risky_call()
except:
    pass  # 무엇이 실패했는지 알 수 없음
# ✅ 올바른 방법: 명시 처리
try:
    risky_call()
except SpecificError as e:
    logger.warning(f"...{e}")
    return fallback_value

# ❌ 절대 금지: 평문 자격증명 코드 작성
TOSS_API_KEY = "actual_key_value_here"
# ✅ 올바른 방법: env 또는 secrets 참조
TOSS_API_KEY = os.environ.get("TOSS_API_KEY")
```

### 코드 레벨 — Toss/주식 특화 (TBD)

본 섹션은 Toss API 사용 중 발견한 함정·우회법을 누적. 현재 비어있음.

> 예상 항목 (검증 필요):
> - 시세 API 호출 빈도 제한
> - 장 종료 직전·직후 주문 거부 조건
> - 휴장일·반휴장일 처리
> - 단주 거래 (1주 미만) 가능 여부
> - 호가 단위 (가격대별 차등)
> - 거래 정지 종목 감지

### 운영 레벨 — 보편 원칙

```bash
# ❌ 절대 금지: 사용자 승인 없는 운영 환경 변경
# ✅ 올바른 방법: "서버 배포해도 될까요?" 사용자 확인 후 진행

# ❌ 절대 금지: rm -rf *.db (감사 로그 삭제)
# ✅ 올바른 방법: mv tradebot.db archive/ (백업 후 보관)
```

---

## ✅ 필수 체크리스트

### 배포 전 확인 — 보편

- [ ] 로컬 테스트 완료 (단위·통합)
- [ ] 자격증명 시그니처 스캔 (글로벌 가드레일 §1.2)
- [ ] `.gitignore` 점검 (`.env`, `credentials.*`, `*.db` 등 포함)
- [ ] 런타임 코드 변경 시 버전 갱신 (해당 진입점 파일)
- [ ] 로그 레벨 설정 (DEBUG → INFO)
- [ ] 사용자 승인 획득

### Toss API 호출 시 확인 — TBD

본 섹션은 첫 통합 후부터 누적.

> 예상 항목:
> - [ ] 인증 토큰 유효 시간 확인
> - [ ] API rate limit 회피 (per-second / per-minute)
> - [ ] 응답 코드 분류 (재시도 가능 vs 비가능)
> - [ ] 장 운영 시간 검증 (KRX 개장 09:00, 폐장 15:30)

---

## 🔄 개발 방법론 (워크플로우)

`upbit-tradebot-mvp`의 워크플로우 그대로 이전.

### 순차 진행 (필수)

1. **로컬 구현** — 코드 작성
2. **로컬 테스트** — 단위·통합·백테스팅(가능 시)
3. **완료 보고** — 사용자 승인 대기 ⚠️
4. **GitHub 커밋 준비**
   - 변경 내용 명시
   - **런타임 소스 변경 시** 진입점 파일 버전 갱신 (예: 향후 dashboard.py 같은 파일이 생기면)
   - 형식: `v1.YYYY.MM.DD.HHMM`
5. **GitHub 커밋** — heredoc 메시지 + Co-Authored-By
6. **서버 배포 전 승인** — 사용자 확인 ⚠️
7. **서버 배포** — git pull / scp + restart
8. **서버 테스트** — 실시간 로그 확인 (정착까지 모니터링)
9. **완료 보고** — 검증 결과 보고

### 멀티 Phase 작업

- **모든 Phase 로컬 완성 후 단일 배포**. Phase별 부분 배포 금지.
- 사용자 명시 지시 시만 부분 배포 예외 허용.
- 참조: 메모리 `feedback-deploy-only-when-complete`

### 기획/구현계획서

- 채팅 요약 보고 → 사용자 승인 → 문서 저장 (예: `docs/plans/<주제>/plan.md`)
- 무단 문서 생성 절대 금지
- 참조: 메모리 `feedback-plan-doc-protocol`

---

## ⚠️ 커밋 전 필수 체크리스트

### 1단계: 코드 수정 완료 확인
- [ ] 모든 코드 수정 완료
- [ ] Syntax 검증 (`python3 -m py_compile`, `bash -n`)
- [ ] 로컬 로직 테스트 완료

### 2단계: 버전 갱신 판단 (해당 시)
- [ ] `git diff --stat` 으로 변경 파일 분류:
  - 모든 변경이 비런타임 (문서·gitignore·README) → 버전 갱신 **생략**
  - 한 파일이라도 런타임 코드 (`*.py` 동작 변경) → 진입점 파일 버전 갱신 **필수**
- [ ] 진입점 버전 파일이 있는지 확인 (예: 향후 dashboard.py 신설 시)
- [ ] 현재 시간 확인: `date '+%H%M'`

### 3단계: Git 커밋
- [ ] `git status` 변경 파일 확인
- [ ] 명시적 `git add <file>` (와일드카드·`-A` 금지)
- [ ] heredoc 커밋 메시지 (Why·How 명시)
- [ ] `Co-Authored-By: Claude` 포함

### 4단계: 서버 배포 승인
- [ ] "서버 배포를 진행해도 될까요?" 명시 요청
- [ ] 사용자 승인 확인됨

### 5단계: 서버 배포
- [ ] git pull 또는 scp (방식 명시)
- [ ] 서비스 재시작
- [ ] 상태 확인 (`systemctl is-active`)
- [ ] 로그 모니터링

---

## ❌ 과거 실수 사례 — 이전 자산 (반복 금지)

### 실수 #A: 사용자 승인 없이 배포 (보편)
**근거**: Upbit 프로젝트 Issue #16
**교훈**: 서버 배포·외부 시스템 변경은 명시 승인 필수

### 실수 #B: 편협적 수정 (보편)
**근거**: Upbit 프로젝트 Issue #19
**교훈**: 변수·API 수정 전 `grep -r "이름" --include="*.py" .` 으로 전체 영향 범위 확인. 모든 관련 파일 함께 수정.

### 실수 #C: 교훈 문서 선행 작성 (보편)
**근거**: Upbit 프로젝트 실수 #2
**교훈**: 교훈·기획 문서는 사용자 요청 시에만 작성. 선제적 작성 절대 금지.

### 실수 #D: 비런타임 변경에 버전 갱신 (보편)
**근거**: 메모리 `feedback-version-bump-scope`
**교훈**: 문서·gitignore만 바뀌었으면 진입점 파일 버전 갱신 생략.

### 실수 #E: 부분 배포 (보편)
**근거**: 메모리 `feedback-deploy-only-when-complete`
**교훈**: 멀티 Phase는 전 Phase 완성 후 일괄 배포. 사용자 명시 지시 시만 예외.

---

## 📖 상세 문서 (TBD)

### Issue 상세
- `docs/issues/` (없음 — 첫 Issue 발생 시 생성)

### 설계 문서
- `docs/architecture/` (없음 — 설계 단계에서 생성)
- `docs/plans/` (없음 — 기획안 작성 시 생성)

### 분석/운영
- `docs/analysis/` (없음 — 분석 결과 시 생성)
- `docs/operations/` (없음 — 운영 매뉴얼 시 생성)

---

## 🔗 자매 프로젝트 활용 가이드

`upbit-tradebot-mvp`의 다음 자산을 **참고·학습용**으로 활용 (복사·이전 X):

| 영역 | 참고 위치 | 학습 포인트 |
|---|---|---|
| Telegram 알림 | `services/notifier.py` | dedupe·level prefix·예외 흡수 패턴 |
| 한국어 에러 매핑 | `services/error_messages.py` | 도메인 에러코드 → 한국어 라벨 모듈화 |
| 운영 매뉴얼 | `docs/operations/notifications.md` | 알림 인벤토리 + 트러블슈팅 + 페이저 우선순위 |
| 서버 워치독 | `scripts/server/watchdog_tradebot_engine.sh` | 로그 부재 감지 + flag 파일 dedupe |
| 백업·롤백 | `scripts/{backup,rollback}.sh` | Boilerplate 적용 전 안전망 패턴 |
| `.gitignore` | `.gitignore` | Python + 자격증명 + `!scripts/**/*.sh` 패턴 |

→ Toss API·주식 시장 특성을 검토 후 적합한 자산을 적응·도입.

---

**마지막 업데이트**: 2026-06-16
**버전**: 0.1 (메타 자산 초기 셋업)
