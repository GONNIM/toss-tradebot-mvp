# 알림 문구 개편 (PR 가) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 텔레그램 알림 21종의 제목·본문을 사이트 목표 ("쉽고 자세하게") 에 맞춘 한국어 문구로 바꾸고, 화약고·실주문 알림에 종목명을 붙인다.

**Architecture:** 공통 문구 도구와 한글 풀이 표를 `backend/services/alert_text.py` 한 곳에 두고 (원칙 ⑬), 각 호출처는 그 도구로 제목·본문을 만든다. 종목명은 `backend/services/stock_names.py` 의 읽기 전용 조회. 보내는 시점·조건·설정·게이트는 바꾸지 않는다 (WP92 승인 불요 범위).

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy async (SQLite) · pytest-asyncio · Next.js 14 (Top10Modal 문구만)

**Spec:** `docs/plans/alert-settings/wording.md` (사용자 승인 10/23) · 근거 `docs/plans/alert-settings/design.md`

## Global Constraints

- 제목 40자 이내 · 본문 비지 않은 줄 10줄 이내 · 아이콘 1개 (제목 맨 앞).
- 제목 = `<아이콘> <설정 화면 종류 이름> · <핵심 사실>` — 종류 이름은 `notification_settings.CATEGORIES[cat].label` 에서만 가져온다.
- 본문 마지막 줄 = `자세히: https://optimus8.cafe24.com<page>` (`ns.SITE_BASE_URL` + `CATEGORIES[cat].page`). 밈은 `/lab/meme-watch`.
- 사실만 쓴다. 금지 낱말 (테스트로 검사): `DO NOT TOUCH` `URGENT` `rows` `confidence=` `P&L` `Accession` `Filer` `order_uuid` `tape_score` `VALIDATED` `hypothesis` `캐비어트` `Picks` `Sector Leaders` `Meme Score` `Intensity` `ERUPTING` `BLAZING` `step:` `detail:` `매수 후보` `매수가` `예측수익가` `즉시 검토`.
- 추정값에는 「추정」과 기간·근거, 섹터는 「보장 아님」을 붙인다. 섹터 「진입가」→「지정가 참고」, 「예측수익가」→「통계 추정 N개월 뒤」.
- 시각은 한국 시각 `MM/DD HH:MM`. 실패 알림에는 `다음 실행: MM/DD HH:MM`.
- 종목은 `이름(코드)`. 이름을 못 찾으면 `종목명 확인 안 됨 (코드)`.
- 문구에 들어가는 바깥 값 (회사 이름·공시 제목·오류 문장·분석 글) 은 모두 `html.escape` (parse_mode HTML).
- 바꾸지 않는 것: `category=` · `dedupe_id=` · `force=` · `gate=` · 등급 (send_info/warning/critical) · 발송 조건 · 스케줄.
- 버전: `backend/api/main.py` · `frontend/package.json` 0.2.0 → 0.3.0.
- 커밋 hook 은 biotech 묶음·compileall·tsc 만 돈다. 각 Task 끝에 관련 테스트 파일을 직접 돌린다.

## Review Focus

1. 회사 이름·공시 제목에 `&` `<` 가 들어간 경우 (예: `S&T모티브`, 공시 `mean < -5%`) → 텔레그램 400 없이 글자 그대로 보여야 한다 (10/22 A3 28건 실패의 재발 방지). → Task 1 `test_escapes_outside_values` · Task 4 `test_dnt_name_with_ampersand`.
2. 값이 None (섹터 현재가·진입가 없음, 밈 이전 점수 없음, VIP 수량 없음) → 「—」 로 보이고 예외가 없어야 한다 (10/22 Sector None 26회 실패). → Task 6 `test_sector_none_fields` · Task 7 `test_meme_without_previous`.
3. 이름 조회가 예외·지연 (DB 잠금) → 알림은 그대로 나가야 한다. → Task 3 `test_lookup_error_returns_fallback` · `test_lookup_timeout`.
4. 긴 제목 (행동주의 운용사 이름 · 긴 회사 이름) → 40자에서 「…」로 잘리고 아이콘·종류 이름은 남아야 한다. → Task 1 `test_title_truncates_fact_only`.
5. 실패 알림 「다음 실행」 이 자정·당일 지난 시각을 넘을 때 (예: 23:50 실패한 06:30 잡) → 다음 날 날짜. → Task 1 `test_next_run_rolls_over`.

---

### Task 1: 공통 문구 도구 `alert_text` + 감싸기 아이콘 1개

**Files:**
- Create: `backend/services/alert_text.py`
- Modify: `backend/services/notifier.py:210-211` (감싸기) · `backend/services/notification_digest.py:31` (요약 줄 아이콘 제거)
- Create: `backend/tests/alert_rules.py` (테스트 도우미) · Test: `backend/tests/test_alert_text.py`

**Interfaces:**
- Produces (`alert_text`):
  - `title(category: str, fact: str, icon: str) -> str` — `f"{icon} {label} · {fact}"`, 40자 넘으면 fact 끝을 「…」로 자름.
  - `link(category: str) -> str` — `"자세히: " + SITE_BASE_URL + page`.
  - 설정 목록 밖 종류 (`unknown` · 화약고 A4): `title(..., label="화약고 후보 · 5% 보고")` · `link(..., page="/powderkeg")` 처럼 `label`·`page` 키워드로 넘긴다. 둘 다 없고 목록 밖이면 `ValueError` (테스트 `test_unknown_category_needs_label`).
  - `kst(dt: datetime | None) -> str` — UTC naive/aware 모두 받아 `MM/DD HH:MM`, None → 「—」.
  - `next_run(hour: int, minute: int, now: datetime | None = None) -> str` — 한국 시각 기준 다음 `MM/DD HH:MM`.
  - `stock(name: str | None, code: str) -> str` — `이름(코드)` 또는 `종목명 확인 안 됨 (코드)` (이름 escape).
  - `won(v) / usd(v) / pct(v) -> str` — 원은 소수 없음 `102,700원`, 달러 `$2.14` (1 미만은 4자리), 퍼센트 `+15.3%`; None → 「—」.
  - `esc(s) -> str` — `html.escape(str(s), quote=False)`.
  - 풀이 표 (dict): `POWDERKEG_TYPE` (B1 횡령·배임 · B2 감사의견 비적정 · B3 거래 정지 · A1 오너 사법 리스크 · A2 상속 · A3 담보 제공 · A4 5% 보고 · A5 배당·자사주 · A6 저PBR 압박), `VIP_EVENT`, `ACTIVIST_LEVEL`, `EXIT_REASON` (hard_sl 손절선 도달 · trailing 고점에서 되돌림 · force_close 장 마감 정리), `SERENITY_JOB`, `BIOTECH_STEP` — 값은 wording.md §1 그대로.
- Produces (`tests/alert_rules.py`): `violations(title: str, body: str) -> list[str]` — 40자·10줄·아이콘 수·`https://optimus8.cafe24.com/` 포함·금지 낱말 검사.
- 감싸기 규칙: 제목 첫 글자가 기호 (`unicodedata.category(c) == "So"` 또는 `⚠`) 이면 등급 아이콘을 붙이지 않는다. 아니면 지금처럼 `LEVEL_ICONS[level]` 를 붙인다 (옮기지 않은 호출 대비 · Fable 권고 3 의 (b) 안).

- [ ] **Step 1: 실패하는 테스트** — `test_title_format` (`title("vip","Wendy's 1차 목표가 도달","🎯") == "🎯 VIP 감시 · Wendy's 1차 목표가 도달"`) · `test_title_truncates_fact_only` (60자 fact → len ≤ 40, 「…」로 끝, `"🎯 VIP 감시 · "` 로 시작) · `test_link_absolute` (`link("powderkeg_dnt") == "자세히: https://optimus8.cafe24.com/powderkeg"`) · `test_kst_from_utc_naive` (`kst(datetime(2026,10,23,1,42)) == "10/23 10:42"`) · `test_next_run_rolls_over` (now=KST 10/23 23:50 · `next_run(6,30) == "10/24 06:30"`; now=KST 10/23 05:00 → `"10/23 06:30"`) · `test_stock_fallback` (`stock(None,"012345") == "종목명 확인 안 됨 (012345)"`) · `test_escapes_outside_values` (`stock("S&T모티브","064960") == "S&amp;T모티브(064960)"`) · `test_number_formats` (`won(102700.0)=="102,700원"` · `usd(2.14)=="$2.14"` · `usd(0.5123)=="$0.5123"` · `pct(0.153)=="+15.3%"` · `won(None)=="—"`) · `test_wrapper_single_icon` (notifier 를 httpx 가짜로 보내 `text` 가 `"<b>🎯 VIP"` 로 시작, 아이콘 없는 제목은 `"<b>ℹ️ "` 로 시작) · `test_digest_line_drops_icon` (대기 제목 `"🔥 밈 · 급등 전 단계 · X"` → 요약 줄 `"· 밈 · 급등 전 단계 · X"`) · `test_digest_line_ampersand` (대기 제목 `"🚨 화약고 거래 주의 · S&T(064960)"` → 요약 줄에 `S&amp;T` 한 번).
- [ ] **Step 2: 실행해 실패 확인** — `backend/venv/bin/pytest backend/tests/test_alert_text.py -q` → ImportError.
- [ ] **Step 3: 구현** — 위 Interfaces 대로.
- [ ] **Step 4: 통과 확인** — 같은 명령 + `backend/venv/bin/pytest backend/tests/test_notifier_gate.py backend/tests/test_notification_digest.py -q` 통과.
- [ ] **Step 5: 커밋** — `feat(notify): 문구 공통 도구 alert_text · 아이콘 1개 (1023-05 Task 1)`

### Task 2: 설정 화면 종류 이름

**Files:** Modify `backend/services/notification_settings.py:50-53,63` · Test `backend/tests/test_notification_settings.py`

- 이름: `powderkeg_a2` 「화약고 후보 · 상속」 · `a3` 「화약고 후보 · 담보 제공」 · `a5` 「화약고 후보 · 배당·자사주」 · `a6` 「화약고 후보 · 저PBR 압박」 · `meme_blazing` 「밈 · 급등 전 단계」. 키·권고값은 그대로.
- [ ] Step 1 테스트 `test_labels_have_no_internal_codes` (모든 label 에 `A2`~`A6` · `B1`~`B3` 없음 · `meme_blazing` 이름 확인) → Step 2 실패 확인 → Step 3 수정 → Step 4 `test_notification_settings.py test_api_notifications.py` 통과 (`test_api_notifications.py:50` 의 VIP 이름 확인은 그대로 유효) → Step 5 커밋 `feat(notify): 설정 화면 종류 이름 한국어로 (Task 2)`.

### Task 3: 종목명 읽기 조회 `stock_names`

**Files:** Create `backend/services/stock_names.py` · Test `backend/tests/test_stock_names.py`

**Interfaces:**
- Produces: `async def lookup_kr_name(ticker: str, cache: dict[str, str | None] | None = None) -> str | None`
  - 한 세션에서 순서대로: `KrxMarketSnapshot` (같은 ticker 의 최신 snapshot_date · name 비지 않음) → `LiveTapeUniverse.name` → `PowderKegList.name` (최신 행) → `KrxStockMeta.name`. 처음 찾은 값.
  - 전체를 `asyncio.wait_for(..., 2.0)` 로 감싸고, 시간 초과·모든 예외는 `logger.warning("[stock-names] …")` 뒤 None.
  - `cache` 가 주어지면 ticker 별 결과 (None 포함) 를 넣고 다시 묻지 않는다 (실행 1회 단위 · 모듈 전역 캐시 없음).
- [ ] Step 1 테스트: `test_lookup_order` (snapshot 과 universe 둘 다 있을 때 snapshot 이름 · snapshot 지우면 universe · 둘 다 없으면 powderkeg_list · 그다음 krx_stock_meta) · `test_lookup_missing_returns_none` · `test_lookup_error_returns_fallback` (get_session 이 예외 → None · 예외 안 올라옴) · `test_lookup_timeout` (조회 함수가 3초 잠 → None, 2초 안팎에 끝) · `test_lookup_cache` (두 번째 호출은 DB 안 감).
- [ ] Step 2 실패 확인 → Step 3 구현 → Step 4 `backend/venv/bin/pytest backend/tests/test_stock_names.py -q` → Step 5 커밋 `feat(notify): 종목명 읽기 조회 (Task 3)`.

### Task 4: 화약고 (②~⑨)

**Files:** Modify `backend/powderkeg/triggers.py:80-118,166-222` · `backend/powderkeg/orders.py:183-196` · `backend/powderkeg/scheduler.py:74-86` · Test `backend/tests/test_powderkeg_wording.py` (새로) · 기존 `test_powderkeg_triggers.py` 기대 문자열 갱신

**Interfaces:** Consumes `alert_text.*`, `lookup_kr_name`.
- `process_pending_events` 1회 실행에 `cache: dict` 하나를 만들어 `process_event` → `process_type_a/b` 로 넘긴다 (인자 추가 · 기본값 None).
- Type B: `name = await lookup_kr_name(event.ticker, cache)` 를 `_remove_from_latest_list()` **앞**에서 (Fable 권고 1).
- 문구는 wording.md §1 ②~⑨ 그대로. A1 확신 낮음 아이콘 🔍 · 근거 좋음 🎯 아님 → `📊` (지시 아님) · 음수 🔬 · 그 밖 📊. 재평가 줄은 최대 5줄 + 「외 N종목」.
- [ ] Step 1 테스트: `test_dnt_wording` (B1 이벤트 · 이름 있음 → 제목 `"🚨 화약고 거래 주의 · 가나다전자(012345)"`, 본문에 `횡령·배임` · `화약고 후보 목록에서 뺐습니다 (1건).` · `공시 원문:` · `violations()==[]`) · `test_dnt_name_with_ampersand` (발송 text 에 `S&amp;T` 한 번 · 기록된 plain_title 에 `S&T` — `&amp;amp;` 없음) · `test_dnt_name_looked_up_before_removal` (목록 삭제 뒤엔 이름이 사라지는 가짜로 순서 확인) · `test_candidate_negative_wording` (A3 → `담보 제공` · `12개월 뒤 평균 -5% 아래 (통계 · 보장 아님)` · `<` 없음) · `test_ticket_and_reeval_wording` (재평가 7종목 → 5줄 + `외 2종목`).
- [ ] Step 2~4: `backend/venv/bin/pytest backend/tests/test_powderkeg_wording.py backend/tests/test_powderkeg_triggers.py backend/tests/test_notifier_categories.py -q` (triggers 는 단독 실행 실패가 기존 문제이므로 묶어서 돌린다).
- [ ] Step 5 커밋 `feat(notify): 화약고 알림 문구 · 종목명 (Task 4)`.

### Task 5: VIP · 행동주의 (⑩⑪⑫)

**Files:** Modify `backend/discovery/vip/notifier.py:17-89` · `backend/discovery/activist/notifier.py:18-184` · Test `backend/tests/test_vip_activist_wording.py` · 기존 `test_activist_wolfpack_fix.py` 기대 문자열 갱신

- VIP 사건 이름·아이콘은 `alert_text.VIP_EVENT` (STOP_APPROACH 「손절선 아래」 · TP2 도 아이콘 🎯 하나). 공시 본문은 `hints.sec_filing_detail_url` 주소 한 줄.
- 행동주의: `SC 13D` 「경영 참여 목적 5% 이상 보유 신규 보고」, `13D/A` 「보유 변경 보고」, 13G 「단순 투자 5% 이상 보유 보고」. 「매매 개시 확률 최상」 삭제. 무리 알림은 wording.md 형식.
- [ ] Step 1 테스트: `test_vip_tp1` (wording.md 예시와 같은 3줄 + 링크 · `violations()==[]`) · `test_vip_stop` (제목에 `손절선 아래`) · `test_activist_13d_new_vs_amend` · `test_activist_long_filer_title_len` (운용사 이름 60자 → 제목 ≤40) · `test_wolfpack_wording`.
- [ ] Step 2~4 `backend/venv/bin/pytest backend/tests/test_vip_activist_wording.py backend/tests/test_activist_wolfpack_fix.py -q` → Step 5 커밋.

### Task 6: 섹터 · Crazy · Moonshot · 시스템 경고 (⑬⑭⑮㉑)

**Files:** Modify `backend/services/notifier.py:283-368` (format_*) · `backend/scheduler/cron.py:450-509` · `backend/services/notifier_profile.py:126-150` · Test `backend/tests/test_discovery_wording.py` · 기존 `test_alerts_p0.py` 기대 문자열 갱신

- 섹터: 종목당 1줄 `"{n}. {이름} {현재가} · 지정가 참고 {진입가} · 통계 추정 {N}개월 뒤 {가격} ({%})"` + 마지막에 `추정은 수출 자료와 과거 상관으로 계산 · 보장 아님`. `horizon_months` 사용. 진입 상태: `entry_status` 문자열(🟢/🟡/🔴 머리)은 **바꾸지 않는다** — 화면 `Top10Modal.tsx:264` 가 `startsWith("🟢")` 로 판정하고 API 가 그대로 내보냄. 알림에서만 `alert_text.entry_status_text(status) -> str` 가 머리 기호로 풀어 씀 (🟢 「현재가가 지정가 참고선 근처」 · 🟡 「참고선까지 N% 아래」 · 🔴 「과열 (사유)」 · 그 밖 원문 escape). `entry_price.py` · `test_entry_price.py` 무변경 (Fable 막음 1 (a)).
- Crazy: 상위 **5**종목 한 줄씩 (`분석 글` 첫 30자 · escape) + `나머지 N종목과 분석 전문은 화면에서` (사용자 결정 10/23).
- Moonshot: 종목당 3줄 이내 (wording.md ⑮) · 3종목.
- `_alert_job_failure(job_name, exc, hour: int | None = None, minute: int | None = None)` — None 이면 「다음 실행」 줄 생략 (기존 2인자 호출·테스트 유지). 호출처는 **다음 실행** 시·분을 넘김: Crazy 6:30 · Moonshot 16:50 · 섹터 09:05 실패 → 17:05 · 섹터 17:05 실패 → 09:05 · 하루 요약 18:00. 섹터 두 시각은 cron.py 안 상수 쌍 `SECTOR_SLOTS = ((9, 5), (17, 5))` 하나에서 `add_job` 과 `_alert_job_failure` 양쪽이 읽는다. 제목 `"⚠️ 시스템 경고 · {표시 이름} 실패"`, 본문 `원인: {쉬운 원인}` · `다음 실행: {next_run}` · 링크. 쉬운 원인 표: `ReadTimeout`/`TimeoutError` 「외부 응답 시간 초과」, `ConnectError` 「외부 연결 실패」, `HTTPStatusError` 「외부 사이트 오류 응답 (HTTP n)」, 그 밖 「프로그램 오류 ({예외 이름})」. `_failure_alerted` 열쇠는 **기존 job_name 그대로** (하루 1회 동작 유지).
- 표시 이름: Crazy Picks→「Crazy 종목」 · Moonshot Picks→「Moonshot 종목」 · Sector Leaders 09:05→「섹터 리더 09:05」 · 알림 하루 요약 그대로.
- LLM 대체·WATCH 요약 문구는 wording.md ㉑.
- [ ] Step 1 테스트: `test_sector_wording` (3종목 → 비지 않은 줄 ≤10 · `지정가 참고` · `통계 추정 6개월 뒤` · `보장 아님`) · `test_sector_none_fields` (현재가·진입가·추정가 None → `—`, 예외 없음) · `test_crazy_top5` (10종목 입력 → 5줄 + `나머지 5종목`) · `test_moonshot_wording` · `test_job_failure_next_run` (now 고정 · Crazy 실패 → `다음 실행: 10/24 06:30`) · `test_job_failure_dedupe_key_unchanged` · `test_sector_0905_failure_next_is_1705` · `test_job_failure_without_time_omits_line` · `test_sector_entry_status_prefix_kept` (format 결과에 풀어 쓴 문장 · 입력 entry_status 는 그대로).
- [ ] Step 2~4 `backend/venv/bin/pytest backend/tests/test_discovery_wording.py backend/tests/test_alerts_p0.py -q` → Step 5 커밋.

### Task 7: 밈 (⑯⑰)

**Files:** Modify `backend/discovery/meme_watch/alert.py:36-121` · Test `backend/tests/test_meme_alert_html.py` 갱신

- Markdown 단계를 없애고 `alert_text` 로 제목·본문을 바로 만든다 (`_to_title_body` 제거 · 발송 호출 `alert.py:233` 의 인자는 그대로).
- 급등 진행 🌋 / 급등 전 단계 🔥 · 링크 `/lab/meme-watch` · 점수 줄 「(추정 · 커뮤니티 언급·거래량 등 5가지 · 보장 아님)」 · 다시 오른 알림은 제목 끝 「· 다시 오름」.
- [ ] Step 1 테스트: `test_meme_erupting_wording` · `test_meme_blazing_wording` · `test_meme_without_previous` (이전 점수 None) · `test_meme_link_real_path` · 각 `violations()==[]` → Step 2~4 `backend/venv/bin/pytest backend/tests/test_meme_alert_html.py backend/tests/test_conftest_guards.py -q` → Step 5 커밋.

### Task 8: 실주문 · Kill Switch (⑱⑲)

**Files:** Modify `backend/discovery/live_tape/entry.py:253-261` · `exit.py:157-165` · `backend/execution/kill_switch.py:146-160` · Test `backend/tests/test_execution_wording.py`

- 진입·청산 이름: 진입은 `candidate` 에 이름이 없으므로 `lookup_kr_name(ticker)` (캐시 없이 1회). 원화는 소수 없음. 청산 이유는 `EXIT_REASON`.
- Kill Switch: wording.md ⑲ — 시각 `kst()` · 이유 `daily_loss_limit_reached(-3.12%)` → 「오늘 손실 한도 도달 (-3.12%)」 · 누가 `auto:sniper` → 「자동 (스나이퍼)」, `user:manual` → 「직접」 · 풀기 줄 `https://optimus8.cafe24.com/lab/execution 의 「수동 해제」 (관리자 로그인)`.
- [ ] Step 1 테스트: `test_entry_wording` · `test_exit_reason_korean` · `test_kill_switch_wording` (시각 KST · `DELETE` 없음 · 풀기 주소) · `violations()==[]` → Step 2~4 `backend/venv/bin/pytest backend/tests/test_execution_wording.py backend/tests/test_notifier_categories.py -q` → Step 5 커밋.

### Task 9: Serenity · 바이오 (① ⑳)

**Files:** Modify `backend/discovery/serenity/scheduler.py:33-66,123-128` · `backend/scripts/biotech_notify.py` · `biotech_h48v3_daily_server.sh:35-41` · `biotech_h69_aact_weekly.py:611-624` · `biotech_h46v3_radar.py:144-186` · `biotech_h48v3_confirm.py:362` · `biotech_radar_inputs_weekly.py:64` · `biotech_llm.py:98` · Test `backend/tests/test_serenity_biotech_wording.py`

- Serenity: `SERENITY_JOB` 이름 · 성공 본문은 작업별 2줄 요약 (모르는 키는 `키 값` 그대로 최대 3줄) · 실패에 `다음 실행` (작업별 시각은 scheduler.py:191-269 의 CronTrigger 값을 상수로 함께 둠).
- 바이오: 제목 「바이오 · …」 · 서버 이름·로그 경로·스크립트 이름 줄 삭제 · `다음 실행` (매일 07:00 · AACT 월 06:00) · 셸 스크립트는 `biotech_notify.py` 위치 인자 `level title body` (와 `--category`) 의 문자열만 바꿈 (biotech_notify.py:43-46). 「레이더 입력 N개 빠짐」 본문은 한국어 이름 뒤 원래 입력 파일 이름을 괄호로 남김 (WP94 대조용 · biotech_h46v3_radar.py:162-164).
- biotech 커밋 hook 묶음 테스트가 돈다 — 기존 biotech 테스트의 기대 문자열도 함께 갱신.
- [ ] Step 1 테스트: `test_serenity_success_wording` · `test_serenity_failure_next_run` · `test_biotech_daily_failure_wording` (서버·로그 경로 없음) → Step 2~4 `backend/venv/bin/pytest backend/tests/test_serenity_biotech_wording.py backend/tests -k biotech -q` → Step 5 커밋.

### Task 10: 화면 Top10Modal · 버전 · 전체 확인

**Files:** Modify `frontend/components/sector-leaders/Top10Modal.tsx:149-355` · `frontend/package.json` · `backend/api/main.py` (version) · `docs/plans/alert-settings/README.md` (상태 한 줄)

- 이름: 진입가→「지정가 참고」 · 예측수익가→「통계 추정가」 (툴팁 「N개월 뒤 · 수출 자료와 과거 상관 · 보장 아님」) · Stop/Take→「손절 참고선」/「익절 참고선」 · 「지금 매수하면 물릴 위험 큼」「매수 검토」 류 지시 문장 → 사실 문장 (예: 「1년 범위 위쪽 91% · 200일 평균보다 31% 높음」). 투자 권유 아님 문장은 유지.
- [ ] Step 1: `cd frontend && npx tsc --noEmit` 통과 · `grep -n "예측수익가\|매수 검토\|물릴" frontend/components/sector-leaders/Top10Modal.tsx` 결과 0줄.
- [ ] Step 2: 로컬 화면 확인 (playwright · /sector-leaders 모달 열기 · 표 머리 「지정가 참고」「통계 추정가」).
- [ ] Step 3: 전체 확인 — `backend/venv/bin/pytest backend/tests -q` 결과를 main (f2310c4) 의 기존 실패 목록과 대조해 새 실패 0건 · `backend/venv/bin/python -m compileall -q backend` · `grep -rn "DO NOT TOUCH\|URGENT ·\|Picks —" backend --include=*.py | grep -v tests` 0줄.
- [ ] Step 4: 커밋 `chore(alert-wording): Top10Modal 이름 · 버전 0.3.0 (Task 10)`.

## 배포 뒤 확인 (병합은 사용자 · 피할 시각 05:55–06:45 · 09:00–09:15 · 16:40–17:15 · 18:00 앞뒤)
- 다음 실제 알림 1건씩 (Crazy 06:30 · 섹터 09:05 · 밈) 의 제목이 새 형식인지 `/admin/notifications` 최근 10건에서 확인.
- 알려 둘 것: `dedupe_id` 가 없는 종류는 새 제목 첫 발송이 재발송 간격 검사에 안 걸려 1번 더 나갈 수 있음 (Fable 답 2).
