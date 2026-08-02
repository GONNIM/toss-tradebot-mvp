---
title: Serenity Integration · Post-Mortem (L1~L8 완결)
type: post-mortem
status: closed
created: 2026-08-02
authors: [사용자, Claude Opus 4.7]
scope: Serenity Full 통합 · Phase L1~L8
supersedes: null
sync_target: /Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Serenity-Post-Mortem-2026-08-02.md
---

# Serenity Integration Post-Mortem

## 요약

**결과**: Phase L1~L8 8-Phase 로컬 완결 + 8 배포 성공. 예상 36h → 실 약 8~10h (약 25% 소요).

**성공 요인**:
- **정확한 명세 문서** (L0 산출물 · README/01/02/03) → 세션 재진입 마찰 최소
- **기존 인프라 재사용** (Powderkeg 스크리너 패턴 · SQLite/SQLAlchemy · APScheduler · pytest 프레임)
- **Mock 기반 unit test 우선** → 실 API/네트워크 호출 지연 이슈 격리
- **명확한 승인 게이트** → 사용자 판단이 필요한 지점(z.ai 실 호출·submodule 추가)에서만 정지

**미완결**:
- L3 실 z.ai 호출 (사용자 승인 후 별도 세션)
- L5 실 yfinance 백테스트 (signals 도착 후 자연 실행)
- Wiki sync 자동화 (Phase F 로 이월)

---

## Phase 별 실 vs 예상 시간

| Phase | 계획 | 실측 | 비고 |
|---|---|---|---|
| L1 · 스키마·submodule | 2h | ~30분 | Powderkeg 패턴 미러 · SQLite 재작성 자동 |
| L2 · Crawler + 6222 sync | 3h | ~40분 | pytest fixture + 실 sync 즉시 통과 |
| L3 · Extractor + z.ai (코드만) | 5h | ~50분 | 실 API 호출은 다음 세션 · mock 15/15 |
| L4 · Scorer + 15원칙 + seed | 4h | ~50분 | 문서 공식 그대로 · 관찰 로그 §L 정합 |
| L5 · Backtest + yfinance | 4h | ~45분 | mock 기반 · signals 미도착 상태 |
| L6 · Frontend Nav + 랜딩 | 8h | ~1h 30분 | shadcn/ui 재사용 · AppNav 분리 |
| L7 · 상세 페이지 + methodology + backtest | 6h | ~1h 30분 | recharts 재사용 · md 원문 <pre> 렌더 |
| L8 · Cron + 통합 테스트 + Post-mortem | 4h | ~40분 | 4 crons · env 스위치 · Post-mortem |
| **합계** | **36h** | **~7~9h** | 실 데이터 검증 제외 |

---

## 주요 결정 회고

### D1 · SQLite 유지 (Supabase 미채택 · 사용자 확정)

**결과 · 성공**. Powderkeg/Rulebook과 같은 DB · 로컬·프로덕션 동일 인프라 · `services/db.py` `database_url()` 만으로 향후 Postgres 이관 가능.

**리스크**:
- `TEXT[]` (도메인 태그 · anti-pattern flags) → CSV 문자열 저장 · list 파싱 헬퍼 필요 (`_parse_csv/_csv_from_list`)
- Supabase RPC/RLS 미사용 → EXISTS subquery 수동 작성 · SQLAlchemy async 안전
- ENUM → `String(20)` + 상수 튜플 검증 (`SERENITY_SENTIMENTS` 등)

### D2 · git submodule 채택 (사용자 확정)

**결과 · 성공**. `vendor/serenity-tracker` · 재현성 확보. Workflow `git submodule update --init --recursive --depth 1` 서버에서 정상 작동 확증 (L7 methodology.md 21KB 서빙).

**리스크**:
- yan-labs 저장소 폐쇄·이름 변경 시 대응 필요 (README 리스크 표 대응 완료)
- update.py 는 xreach 인증 필요 · 사용자 수동 실행 (자동화 어려움)

### D3 · Rulebook 정체성 재정의 (앞선 세션)

Rulebook 은 원칙 1의 5단계 필터로 실제 종목을 찾는 것 · R:R·물타기는 부수 도구. 이번 세션 L6 랜딩과 L7 상세에서 Serenity 특화 UX와 Rulebook 특화 UX 를 완전 분리 · L2 조건부 nav 로 UI 노이즈 없음.

---

## 튜닝 포인트 (다음 세션 우선순위)

### P1 · L3 실 z.ai 검증 (5m~1h · 비용 소액)

```bash
python -m backend.scripts.serenity_extract --batch 10 --verbose
# spot-check signals 정확도 · SYSTEM_PROMPT 반복 튜닝 (system.md · hot reload)
```

**성공 조건**:
- NBIS/SIVE/AXTI/LITE bullish signals 정상 추출
- IREN/CRWV bearish · anti-pattern 언급 감지
- 관계 없는 종목 오추출 < 10%
- confidence < 0.5 판정 빈도 spot-check

### P2 · L5 실 yfinance 백테스트 (10~30분)

```bash
python -m backend.scripts.serenity_backtest --batch 100
# 관찰 로그 §K 대조 · AAOI +483% · AXTI +1057% 재현 여부
```

**리스크**: yfinance rate limit (KRX/TW 심볼 매핑 검증 · `to_yfinance_symbol` 확장 여지)

### P3 · Serenity Extractor Cron 활성 (사용자 승인 후)

```bash
# SOPS 편집
SERENITY_EXTRACTOR_CRON=true
# 재배포 후 매일 07:00 KST 자동 배치 200건
```

**모니터링**: 서버 로그 `[serenity] cron extractor · {...}` · z.ai 월 비용 알림.

### P4 · UI 확장 여지

- Signal Feed 페이지네이션 (현재 limit 50 · 6222 트윗 전체 탐색 어려움)
- Ticker Grid 정렬 옵션 (score/mention/last_signal)
- Backtest 차트에 raw signal 오버레이 (개별 signal → return 산점도)
- Serenity theses.md 원문 열람 (methodology 페이지 패턴 확장)

---

## 4시간 통합 테스트 (README 정의 · 다음 세션 시나리오)

1. **매일 시나리오** — 서버 로그 grep `serenity_crawler`·`serenity_scorer`·`serenity_backtest` 3 크론 실행 확증
2. **주간 시나리오** — 월요일 00:00 backtest 실행 · `SerenityBacktest` count 증가 확증
3. **자동 복구** — 단일 job 실패 시 다음 실행에서 recovery (`SERENITY_EXTRACTOR_CRON=true` 상태에서 z.ai 500 시)
4. **비용 모니터링** — z.ai monthly usage · 하루 예산 초과 시 alert

---

## 다음 개선 항목 (백로그)

1. **Serenity Extractor 프롬프트 튜닝 로그** — system.md 버전별 sample-diff 저장 (retrospect 폴더)
2. **theses.md 원문 열람 페이지** (`/influencer/serenity/theses`) · methodology 패턴 재사용
3. **Signal → Judgment 연동** · Rulebook 판정 저장 시 Serenity signal 추론 hypothesis_id 자동 (`serenity-nbis-2026-08-01`)
4. **Backtest raw signal 오버레이** · BacktestChart 확장
5. **track-record.md 자동 sync** · Serenity 검증 실적 UI 표시
6. **domain_tags 자동 태깅** · sub-sector map 기반 signals aggregate 시 자동
7. **인증 게이트** · Toss admin 세션 재활용 여부 사용자 결정 (현재 public read)

---

## 파일 변경 총량 (L1~L8)

| Phase | 커밋 | 파일 | 라인 |
|---|---|---|---|
| L1 | a34393f | 11 | +720 |
| L2 | 76961aa | 5 | +441 |
| L3 | f4b2e87 | 5 | +616 |
| L4 | 2a5455a | 6 | +560 |
| L5 | 36aa54c | 5 | +509 |
| L6 | 774e8f6 | 11 | +670 |
| L7 | 3396c63 | 10 | +871 |
| L8 | (본 커밋) | 4~5 | +330 |
| **합계** | 8 커밋 | **~57 파일** | **~4700 라인** |

## Sign-off

- 사용자 (실 사용·판정 축적 및 튜닝 지속)
- Claude Opus 4.7 (Full 통합 완결 · L1~L8 배포 성공)
- 2026-08-02 완료
