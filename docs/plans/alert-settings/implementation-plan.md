# 알림 설정 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 텔레그램 알림을 종류별로 화면(`/admin/notifications`)에서 켜고·끄고·하루 요약으로 돌리고, 발송 성공·실패를 화면에서 본다.

**Architecture:** 모든 앱 발송이 거치는 `TelegramNotifier.send` 에 설정 확인·재발송 간격·하루 요약 대기·발송 기록을 넣는다(거름 지점 1곳). meme 은 `telegram_notifier.send_message` 경로를 `TelegramNotifier` 로 옮긴다. 설정은 DB 표 3개 + 프로세스별 60초 캐시, 화면은 Next.js 페이지 + FastAPI 라우트.

**Tech Stack:** FastAPI · SQLAlchemy async (SQLite) · APScheduler(cron) · Next.js 14 + react-query · pytest

**Spec:** `docs/plans/alert-settings/design.md` (2026-10-23 승인) · 계획 승인 2026-10-23 사용자 "Fable 최적안 승인 · 9번 구현 시작"

## Global Constraints
- 배포 직후 모든 종류 = 켜짐 · 즉시 · 간격 0 (결정 A) — 배포만으로 받는 알림이 바뀌면 안 됨
- 하루 요약 발송 = 18:00 KST cron (결정 B)
- 끌 수 없음 = `kill_switch` · `execution` · `system` (결정 C) · `system` 은 `digest` 모드 선택 가능
- 설정 읽기 실패 = 발송 · 기록 쓰기 실패가 발송을 막지 않음
- 새 표는 `init_db` `create_all` 로 생성 (`backend/services/db.py:62-67` · api lifespan) — cron·biotech 은 표가 없어도 동작
- 텔레그램 HTML parse_mode 고정 · 본문 escape
- 테스트 실발송 금지: `backend/tests/conftest.py` 가드 유지·갱신
- 버전: backend `backend/api/main.py` 0.1.3→0.2.0 · frontend `frontend/package.json` 0.1.1→0.2.0
- 단일 배포 (CLAUDE.md 멀티 Phase) · PR 은 Fable "병합 승인됨 · PR #번호" 뒤 병합 (WP92)

## 종류(category) 목록 — 11묶음 안의 설정 행 21개 + 배포 표시 1행 (코드 상수 `CATEGORIES`) · 호출 29곳 · 16파일 (notifier.py·tests 제외) + api/main.py:214 + meme 1곳
| key | 묶음 | 호출처 | 권고값 |
|---|---|---|---|
| `serenity` | ① | serenity/scheduler.py:56(warning),64(info) | min_level=warning (성공 끔·실패만) |
| `powderkeg_dnt` | ② | triggers.py process_type_b (urgent) | 즉시 (리스트 구분은 가능하나 후속 · 보유 구분은 정보 없음) |
| `powderkeg_a1` `powderkeg_a2` `powderkeg_a3` `powderkeg_a5` `powderkeg_a6` | ③ | triggers.py process_type_a (event_type 으로) | a2·a3 끔 · 나머지 즉시 |
| `powderkeg_ticket` | ④ | orders.py:195 | 끔 |
| `powderkeg_reeval` | ④ | powderkeg/scheduler.py:84 | 즉시 |
| `vip` | ⑤ | vip/notifier.py:66,89 | 간격 10080분 (식별자 = 종목) |
| `activist_strong` | ⑥ | activist/notifier.py:70,183 (intensity CRITICAL·REGIME_CHANGE·STRONG) | 즉시 |
| `activist_info` | ⑥ | 같은 곳 (WATCH·NOTE) | 끔 |
| `discovery_sector` `discovery_crazy` `discovery_moonshot` | ⑦ | cron.py:581,346,437 | 즉시 |
| `meme_erupting` | ⑧ | meme_watch/alert.py:202 | 즉시 · 간격 0(기존 쿨다운) |
| `meme_blazing` | ⑧ | 같은 곳 | digest |
| `execution` | ⑨ | live_tape/entry.py:261 · exit.py:165 | 끌 수 없음 |
| `kill_switch` | ⑨ | execution/kill_switch.py:168,170 | 끌 수 없음 |
| `biotech` | ⑩ | scripts 6파일 10곳 (biotech_notify 3 · h69 2 · h48v3 1 · h46v3 2 · radar_inputs 1 · llm 1) · biotech_notify 는 CLI 기본값 `biotech` (셸 수정 없음) | 즉시 |
| `system` | + | cron.py:469(잡 실패),505(LLM 대체) | 끌 수 없음 · digest 선택 가능 |
| (`deploy`) | ⑪ | GitHub Actions | 화면에 "설정 대상 아님" 행만 |

## Review Focus
1. DB 표가 아직 없는 cron·biotech 프로세스에서 send → 예외 없이 발송 (설정 읽기 실패 = 발송) — Task 2 테스트
2. 끌 수 없는 종류를 PUT 으로 enabled=false → 422 거절 · 화면 토글 없음 — Task 3·6
3. 18:00 요약 발송 실패 → 큐 유지, 다음 날 함께 보냄 · 중복 발송 없음 — Task 7
4. meme 본문의 `<`·`&`·종목명 특수문자 → HTML escape 후 400 없음 — Task 5
5. category 없는 호출(새 코드·누락) → 제목 추정 → 그래도 unknown 이면 항상 발송·기록 — Task 2
6. force(send_critical) 는 프로필·중복 억제만 우회 · `powderkeg_dnt` 를 끄면 send_critical 도 skipped (force 와 설정 분리) — Task 2
7. 발송 실패 기록·화면의 오류 문구에 봇 토큰이 없음 — Task 2

---

### Task 1: 표 3개와 설정 캐시
**Files:** Modify `backend/services/models.py` (끝에 3클래스) · Create `backend/services/notification_settings.py` · Test `backend/tests/test_notification_settings.py`
**Interfaces — Produces:**
- 표 이름 `notification_setting` · `notification_log` · `notification_digest_queue` (design.md 와 같음)
- 모델 `NotificationSetting(category PK str, enabled bool=True, mode str='immediate'|'digest', resend_minutes int=0, min_level str='info', updated_at)` · `NotificationLog(id, category, title, result 'sent'|'failed'|'skipped'|'queued', error str|None, created_at)` · `NotificationDigestItem(id, category, title, body, created_at)`
- `CATEGORIES: dict[str, CategoryMeta]` (`CategoryMeta(label, group, locked: bool, recommended: dict, reason: str, page: str)` · `page` = 사이트 경로 · 상수 `SITE_BASE_URL = "https://optimus8.cafe24.com"`) · `LOCKED = {"kill_switch","execution","system"}`
- `async get_setting(category: str) -> SettingView` (60초 캐시 · 실패/없음 → 기본값) · `invalidate_cache()`
- URL 이 `sqlite+aiosqlite` 로 시작할 때만 엔진에 `connect_args={"timeout": 5}` (SQLite busy timeout · `backend/services/db.py:31-36`) · 기존 테스트 통과 확인
- [ ] 테스트: 행 없음 → `SettingView(enabled=True, mode="immediate", resend_minutes=0, min_level="info")` · DB 예외(엔진 monkeypatch) → 같은 기본값 · 캐시 60초 안 재조회 없음
- [ ] 구현 → 통과 → 커밋

### Task 2: `TelegramNotifier.send` 거름·간격·요약 대기·기록
**Files:** Modify `backend/services/notifier.py:84-161` (send · send_info/warning/critical 에 `category: str|None=None, dedupe_id: str|None=None`) · Test `backend/tests/test_notifier_gate.py` (`@pytest.mark.real_notifier_send` + httpx 가짜)
**Interfaces — Consumes:** Task 1 · **Produces:** `send(level, title, body, force=False, category=None, dedupe_id=None, gate=True) -> bool` · `gate=False` = 설정 거름·간격·요약 대기를 건너뜀 (요약 잡·WATCH flush 전용 · 기록은 남김) · force 는 프로필·중복 억제 우회만 · 기록 error = HTTP 상태코드 + 응답 본문 앞 200자 / 그 밖은 `type(exc).__name__` + `_mask(str(exc))[:200]` · URL 절대 넣지 않음 · 기록 전 `self.config.bot_token` 문자열을 `***` 로 치환 (`_mask` 는 `token=` 꼴만 잡음 · logging_setup.py:24-28) · digest 큐 쓰기 실패 = 즉시 발송 · 순서: category 결정(인자 → `_infer_source` → "unknown") → 설정 확인(locked 는 enabled 무시) → min_level → 재발송 간격(키 `category+(dedupe_id or title)` · `NotificationLog` 마지막 sent **또는 queued** 시각) → digest 면 `NotificationDigestItem` 넣고 'queued' → 프로필 필터(기존) → HTTP → 기록
- [ ] 테스트 6건: 끔 → False·'skipped' 기록·HTTP 없음 · locked 끔 → 그래도 발송 · min_level warning 에 info → skipped · 간격 60분 안 같은 dedupe_id → skipped · digest → queued·HTTP 없음 · 기록 쓰기 예외 → 발송 True
- [ ] Review Focus 1·5·6·7 테스트 4건 (표 없음 → 발송 · category 없음 → 'unknown' 발송·기록 · `powderkeg_dnt` 끔 + send_critical → skipped · 가짜 httpx 400 → 기록 error 에 bot_token 없음 · HTTP 아닌 예외 문자열에 `bot<토큰>/` 이 있어도 기록에 토큰 없음)
- [ ] 테스트 2건: digest 종류를 gate=False 로 → 큐 없이 발송 · 큐 쓰기 예외 → 즉시 발송
- [ ] 구현 → 통과 → 커밋

### Task 3: API
**Files:** Create `backend/api/routes/notifications.py` · Modify `backend/api/main.py` (include_router `/api/v1/notifications`) · Test `backend/tests/test_api_notifications.py`
**Interfaces — Produces:** `GET /settings` → `[{category,label,group,locked,enabled,mode,resend_minutes,min_level,recommended,last_sent_at,last_failed_at,last_error}]` · `PUT /settings/{category}` body 부분 갱신 · `POST /settings/apply-recommended` · `GET /log?category=&limit=50` · 모두 `Depends(require_sniper_token)` · PUT 후 `invalidate_cache()`
- [ ] 테스트: 인증 없음 401 · locked enabled=false → 422 · system mode=digest → 200 · 알 수 없는 category → 404 · apply-recommended 후 serenity min_level=warning·powderkeg_a2 enabled=false
- [ ] 구현 → 통과 → 커밋

### Task 4: 호출처 category 붙이기 (meme 제외)
**Files:** 위 종류표의 호출처 전부 (meme 제외) · `backend/api/main.py:214` WATCH flush 에 `gate=False` · A 유형이 a1·a2·a3·a5·a6 밖이면 category `unknown`(항상 발송) + 테스트 1건 · triggers.py `_send_notification(title, body, urgent=False, category=None)` · activist 는 intensity 로 strong/info · vip 는 `dedupe_id=ticker`
- [ ] 테스트: `backend/tests/test_notifier_categories.py` — 각 모듈 발송 함수를 가짜 notifier 로 불러 category 값 확인 (serenity 2 · powderkeg b/a1/a2 · ticket · reeval · vip · activist 2 · cron 5 · kill_switch · live_tape 2 · biotech_notify)
- [ ] 기존 테스트 전부 통과 (send 시그니처 호환 · 키워드 인자만 추가)
- [ ] 커밋

### Task 5: meme 을 TelegramNotifier 로
**Files:** Modify `backend/discovery/meme_watch/alert.py:19,40-95,202` (Markdown → HTML · `html.escape`) · `backend/tests/conftest.py:49` (가드 대상 갱신) · Test `backend/tests/test_meme_alert_html.py`
- [ ] 테스트: 변환 전후 본문 텍스트(태그·Markdown 기호 제거 후)가 같음 · 종목명 `A&B <X>` → 본문에 `A&amp;B &lt;X&gt;` · ERUPTING → category `meme_erupting` · BLAZING 만 → `meme_blazing` · 기존 쿨다운·재발동 동작 그대로(기존 meme 테스트 통과)
- [ ] `telegram_notifier.send_message` 호출처가 0 인지 grep · 모듈은 남겨 둠(다른 호출 없음 확인 후 삭제는 범위 밖)
- [ ] 커밋

### Task 6: 화면 `/admin/notifications`
**Files:** Create `frontend/app/admin/notifications/page.tsx` · Modify `frontend/lib/api.ts` (notifications.list/update/applyRecommended/log · credentials include) · `frontend/app/admin/settings/page.tsx` (링크 1줄)
- 묶음별 카드 · 행: 이름 · 토글(locked 는 "끌 수 없음" 글자) · 모드 선택(즉시/하루 요약 18:00) · 간격(분) · 최소 등급 · 권고값 글자 · 마지막 성공·최근 실패(오류 요지) · 권고 이유 한 줄 · 최근 10건 제목 펼침(`GET /log?category=`) · 오늘 설정으로 건너뜀 N건 · 맨 위 "권고값 한 번에 적용"(확인창) · 토글 즉시 PUT · 실패 시 되돌림 + 알림 띠 · 저장 문장 "저장했습니다 · 1분 안에 반영"
- ⑪ 배포 알림 행: "설정 대상 아님 (GitHub Actions)"
- [ ] `cd frontend && npx tsc --noEmit` 통과
- [ ] chrome-devtools 로 dev 렌더 확인 (토글·실패 되돌림·locked 행)
- [ ] 커밋

### Task 7: 18:00 하루 요약 잡
**Files:** Create `backend/services/notification_digest.py` (`async send_daily_digest() -> int`) · Modify `backend/scheduler/cron.py` (CronTrigger(hour=18, minute=0) · 잡 감싸기·실패 warning) · Test `backend/tests/test_notification_digest.py`
- 문구는 새 원칙(한글 묶음 이름 · 사실형 · 절대 주소 `SITE_BASE_URL+page` · 아이콘 1개 · 제목 40자)
- 묶음별 1건: 제목 "📬 하루 요약 · {label} {n}건" · 본문 제목 목록(최대 20 · 넘으면 "외 N건") · 보낸 묶음만 큐에서 삭제 · `gate=False, force=True, category=` 원래 종류 (설정·프로필 재거름 방지 · 기록 남김) · 큐 항목 보관 상한 7일 · 요약 뒤 30일 지난 `notification_log` 삭제 (결정 D · 삭제 실패는 발송에 영향 없음)
- [ ] 테스트: 2종류 3건 → 발송 2건·큐 0 · 8일 지난 큐 항목 삭제 · 31일 지난 기록 삭제·29일 기록 유지 · 발송 실패 종류는 큐 유지 · 큐 비면 발송 0
- [ ] 커밋

### Task 8: 마무리
- [ ] 버전 backend 0.2.0 · frontend 0.2.0 · `docs/plans/alert-settings/README.md` 상태 줄 갱신 · design.md 포함
- [ ] 전체 pytest (기존 실패 4건 외 0) · compileall · tsc · gitleaks
- [ ] reviewer → Fable 검수 → PR → "병합 승인됨 · PR #번호" → 사용자 병합 (16:40~17:15·05:55~06:45·09:00~09:15 피함)
- [ ] 배포 뒤 조회 확인: 표 3개 생성 · `/admin/notifications` 렌더 · 다음 알림의 `NotificationLog` 기록
