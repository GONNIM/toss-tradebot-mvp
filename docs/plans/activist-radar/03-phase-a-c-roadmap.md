# 03. Phase A~C 구현 로드맵

**총 6~8일**. 각 Phase 로컬 완결 후 단일 배포 원칙([[feedback_deploy_only_when_complete]]) — Phase A~C 모두 로컬 완료 후 배포 1회.

---

## Phase A — 미국 SC 13D 폴러 (2~3일)

### A-1. Universe 실측 (0.5일)
- `docs/plans/activist-radar/01-universe.md` Tier 1 30개 이름 → SEC EDGAR full-text search 로 CIK 확정
- 확정 CIK → `data/activist_universe.json` 초기값 커밋 대상
- 검증 방식: 각 CIK 의 `data.sec.gov/submissions/CIK{cik}.json` 실호출 → `name` 필드 매칭

### A-2. 신규 서브패키지 신설 (1일)
```
backend/discovery/activist/
├── __init__.py
├── universe.py            # 하드코딩 리스트 로드 · JSON override 병합
├── sec_poller.py          # data.sec.gov 폴링 · 신규 accession 감지
├── overrides.py           # data/activist_universe_overrides.json 편집기 · VIP overrides 패턴 재활용
├── state.py               # data/activist_state.json · filer 별 last_seen_accession[]
├── notifier.py            # Telegram 알림 포맷 · [ACTIVIST-US · <fund> · <ticker>]
├── scoring.py             # 강도 스코어링 (Phase C 에서 확장)
└── radar.py               # 오케스트레이터 · run_us_tick() / run_kr_tick() / get_status()
```

### A-3. 스케줄러 통합 (0.3일)
- `backend/scheduler/cron.py` 에 `job_activist_us` 추가
- `IntervalTrigger(seconds=300)` · `if VIP` 처럼 조건부 실행 안 함 (기본 활성)
- `--once activist_us_tick`, `--once activist_status` CLI 추가

### A-4. API 엔드포인트 (0.3일)
- `GET /api/v1/meme-watch/activist/status` — 최근 30일 감지 이벤트 · 강도 순 정렬
- `GET /api/v1/meme-watch/activist/universe` — 현재 activist 리스트
- `PATCH /api/v1/meme-watch/activist/universe` — UI 편집 (활성/비활성 · 신규 CIK 추가)

### A-5. 로컬 검증
- `--once activist_us_tick` → 최근 30일 SC 13D 몇 건 감지 확인
- 오검출 여부 육안 검증 · Universe 조정
- 성공 지표: SC 13D · 13D/A 30일 window 에 감지 이벤트 ≥ 5건

---

## Phase B — 한국 대량보유공시 폴러 (2~3일)

### B-1. 한국 filer 이름 정규화 사전 (0.5일)
- `backend/discovery/activist/kr_name_normalizer.py` — 유사도 매칭
- 예시:
  ```python
  ALIASES = {
      "얼라인파트너스": ["얼라인 파트너스", "Align Partners", "얼라인파트너스자산운용"],
      "KCGI": ["케이씨지아이", "강성부펀드"],
      ...
  }
  ```
- Universe([[01-universe]]) 15개 filer 기준

### B-2. DART 클라이언트 확장 (1일)
- `backend/services/dart_client.py` 신규 or 확장 (기존 DART 인프라 재활용)
- 메서드:
  - `list_recent_5pct(bgn_de, end_de)` — 대량보유공시 목록 (`pblntf_ty=F`)
  - `fetch_document(rcept_no)` — 상세 · `보유목적` 파싱
  - 파싱: `보유목적` 필드 · 지분율 · filer 이름 · 대상 종목명

### B-3. sec_poller 병렬 kr_poller (0.5일)
- `backend/discovery/activist/dart_poller.py`
- 로직:
  1. `list_recent_5pct` 로 최근 5일 조회
  2. 새 `rcept_no` 만 (state.json dedup)
  3. `fetch_document` 상세
  4. filer 이름 매칭 (정규화 사전)
  5. `보유목적` 필터 (경영참여 목적만)

### B-4. Telegram · API 확장 (0.3일)
- Telegram 태그: `[ACTIVIST-KR · <filer> · <target>]`
- API `/activist/status` 응답에 `us` / `kr` 두 트랙 필드 병합

### B-5. 로컬 검증
- `--once activist_kr_tick` → 최근 30일 대량보유공시 감지 확인
- 얼라인·KCGI 등 유명 사례 실 감지 여부 (2026년 상반기 사례 재현)

---

## Phase C — 강도 스코어링 · Wolf Pack (2일)

### C-1. 강도 스코어링 로직 (1일)
- `backend/discovery/activist/scoring.py`
- 함수 `compute_intensity(event, history) -> IntensityScore`
- 공식 ([[00-vision-and-signal-taxonomy]] §4):
  ```
  score = base_form_score
        × activist_tier_multiplier
        × market_cap_bonus
        × wolf_pack_bonus
        × momentum_bonus
  ```
- 임계값 3단계: CRITICAL (80+) · STRONG (60~79) · WATCH (40~59)

### C-2. Wolf Pack 감지 (0.5일)
- state.json 에 종목별 `activist_entries: [{filer, date}, ...]` 저장
- 30일 window 에 서로 다른 activist ≥ 2 → Wolf Pack 판정
- 기존 이벤트 재평가 (30일 sliding window)

### C-3. UI 표시 (0.5일)
- 지금은 `/vip` 페이지에 임시 카드 하나 추가 (Phase F 에서 전용 페이지)
- 카드 구조:
  ```
  🕵️ Activist Radar (US + KR)
    ─────────────────────────
    🌋 CRITICAL (2)
      · WEN (US) · Trian 지분 증가 · 2일 전 · Wolf Pack 후보
      · SM엔터 (KR) · 얼라인파트너스 목적 변경 · 5일 전
    🔥 STRONG (5)
      · ... (accordion)
    ⚠️ WATCH (8)
      · ...
  ```

### C-4. 로컬 검증
- 30일 backfill · Wolf Pack 판정 결과 검토
- 오검출률 목표: < 10%

---

## 최종 배포 · 검증

- **1회 배포**: Phase A~C 로컬 완결 후 SOPS 방식 push → 자동 워크플로우
- **검증 명령**:
  - `curl /api/v1/meme-watch/activist/status`
  - `curl /api/v1/meme-watch/activist/universe`
  - 프로덕션 로그에서 첫 알림 발송 확인 · Telegram 수신
- **성공 지표**:
  - Phase A~C 배포 후 7일 내 Telegram 알림 3건 이상 발송
  - 오검출률 육안 확인 < 10%
  - Wolf Pack 감지 1건 이상 (30일 이력 backfill)

---

## 파일 구조 (최종 예상)

```
backend/discovery/activist/          [신규 서브패키지 · Phase A~C]
├── __init__.py
├── universe.py                      [Phase A]
├── overrides.py                     [Phase A]
├── state.py                         [Phase A · C 확장]
├── sec_poller.py                    [Phase A]
├── dart_poller.py                   [Phase B]
├── kr_name_normalizer.py            [Phase B]
├── scoring.py                       [Phase C]
├── notifier.py                      [Phase A · B 확장]
└── radar.py                         [Phase A · B · C 확장]

backend/scheduler/cron.py            [수정 · job_activist_us + job_activist_kr 추가]
backend/api/routes/meme_watch.py     [수정 · /activist/status · /activist/universe]
backend/services/dart_client.py      [신규 or 확장 · Phase B]

data/activist_universe.json          [신규 · Universe 확정 리스트]
data/activist_universe_overrides.json [신규 · UI 편집 override]
data/activist_state.json             [신규 · filer 별 last_seen · 종목별 entries]

frontend/lib/api.ts                  [타입 확장]
frontend/app/vip/page.tsx            [임시 통합 카드 추가 · Phase F 에서 분리]
docs/plans/activist-radar/           [본 기획서 · 완료 후 상태 갱신]
```

## 위험 · 완화

| 위험 | 완화 |
|------|------|
| CIK 실측 실패 (여러 CIK 를 가진 fund) | Tier 1 30개 부터 순차 확정 · 실패 CIK 는 skip 이력 로그 |
| DART API 응답 형식 변경 | 파싱 실패 시 사용자 UI 확인 대기 · 자동 알림 skip |
| filer 이름 오검출 | 정규화 사전 사용자 확인 후 확정 |
| SC 13D 필링 desc 비어있음 | Phase A 기본 로직 skip · Phase A+β 개선 |
| 30일 window 저장 폭증 | 90일 초과 이벤트 자동 삭제 · state.json 크기 제한 |
| Wolf Pack 오검출 | 최소 2 서로 다른 Tier 1 activist · 특수관계인 제외 |
