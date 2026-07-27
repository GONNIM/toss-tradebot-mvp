# P2-3 · 정합성 이슈 근본 해결 · list union + 원자성 + UI 명확화

**작성일**: 2026-07-27
**우선순위**: 🚨 긴급 · 라이브 신뢰성 파괴 실측 후 · 사용자 지시 · 전문가 리뷰 근거
**예상 소요**: ~4h

---

## 1. 실측 이슈

`optimus8.cafe24.com/powderkeg`에서 카드 1 (저PBR 대량 발굴) → 25s → 카드 2 (Tier 1 재평가) 클릭.
UI가 최신 run_id 하나만 표시 → 카드 1 발굴 30 종목이 사라져 보임 (실 DB엔 유지).

## 2. 전문가 진단

**아키텍트/QA**: 스키마 append-only (unique(run_id,ticker)) · GET /list가 최신 run 하나만 반환하는 게 근본. 방안 B/D (이전 run 복사)는 P4-1 provenance 오염 → 폐기.

**추가 리스크**:
- 같은 초 동시 클릭 시 run_id unique 충돌 · IntegrityError
- ManualAddForm도 동일하게 파괴됨

**UX**: 카드 2 라벨 오독 · 두 카드가 동일 리스트를 파괴적으로 덮어씀 · 색·라벨·경고 필요.

## 3. 채택 방안 · 통합 Phase 1 (~4h)

### 3.1 Backend (2h)
1. **GET /list?union_last_n_runs=5** (기본 5 · 백워드 호환 1)
   - `PowderKegRun.started_at.desc()`로 최근 N run 조회
   - `PowderKegList.run_id.in_(recent_runs)` 조회 · Python dedupe (ticker → 최신 run)
   - 응답 필드 확장: `source_run_ids: list[str]` (뱃지 소스)
2. **run_screener 원자성**
   - run_id 초 충돌 시 `-N` suffix 재시도 3회 (예: `20260727-210840K-2`)
   - INSERT PowderKegRun에서 IntegrityError catch
3. **runScreener 응답 확장**
   - `universe_type`: `"low_pbr"` / `"manual"` / `"locked_only"` / `"custom"` (호출 카드 구분용)
   - `universe_size`: input tickers 수

### 3.2 Frontend (1h)
- `api.ts` · `union_last_n_runs` 파라미터 · `runScreener` 응답 타입 확장
- `ListTab` · `union_last_n_runs=5` 조회 · 상단 유니버스 뱃지 (source_run_ids 개수·최신)
- `ReScreenGuide` 카드 (`page.tsx:1671~`)
  - 라벨 `🎯 관찰 종목 재평가 (내 지정 티커만)`
  - 색 sky → **amber** (파괴 경고)
  - onClick 전 `window.confirm` · "이 액션은 카드 1 발굴 결과를 덮어씁니다. 계속?"
- `LowPbrDiscoveryCard` · 버튼 라벨 강화 · "→ 화약고 리스트 신규 run 생성 · 최근 5 run 병합 뷰"

### 3.3 Tests (1h · `test_powderkeg_list_union.py` 신규)
1. `test_union_last_n_default_1_backward_compat`
2. `test_union_last_n_5_merges_multiple_runs`
3. `test_union_duplicate_ticker_picks_latest`
4. `test_concurrent_run_screener_no_integrity_error`
5. `test_run_diff_unaffected_by_union`
6. `test_universe_type_returned_by_run_screener`

### 3.4 배포·실측 (30분)
- v1.49 커밋·push → GHA
- 실측: 카드 1 → 25s → 카드 2 → `?union_last_n_runs=5` 응답에 30+11 병합 확증
- 3중 실측 (SSR SHA + Tier 1 lock 10 + 신규 API)

## 4. 회귀 방어

- `union_last_n_runs=1`로 원복 시 기존 UX 완전 동일
- P4-1 RunDiff는 run 단위 · union은 조회 전용 · 무영향
- 특정 run_id 명시 조회 (?run_id=…) 기존 방식 그대로

## 5. 다음 확장 정합

- Phase 2 완전 PIT · 매일 auto 스케줄러 도입 시 · union 계약이 자동으로 최근 N일 뷰 유지
- 원자성 락은 auto 스케줄 + 수동 트리거 동시성 방어 자산

## 6. 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-27 | v1.0 | 신규 · 전문가 리뷰 근거 · 사용자 승인 후 저장 |
