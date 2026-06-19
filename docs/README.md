# Toss Tradebot MVP — 문서 구조

본 폴더는 자매 프로젝트 `upbit-tradebot-mvp`의 검증된 분류 체계를 차용한다.
**서브디렉터리는 첫 산출물이 생길 때 생성**한다 (빈 placeholder 폴더 X).

## 표준 서브디렉터리

| 폴더 | 용도 | 예시 |
|---|---|---|
| `plans/` | 기획안·구현계획서·PRD | `plans/PRD/01-research-foundation.md` |
| `architecture/` | 시스템 설계도·모듈 분할·DB 스키마 | `architecture/system-overview.md` |
| `analysis/` | 데이터·시장·기법 분석 보고 | `analysis/cape-by-country.md` |
| `issues/` | Issue별 트러블슈팅 (#1부터 누적) | `issues/issue-01-toss-auth.md` |
| `work-orders/` | 작업 지시서 (WO-YYYY-NNN 번호) | `work-orders/WO-2026-001-paper-trading.md` |
| `operations/` | 운영 매뉴얼·알림 인벤토리 | `operations/notifications.md` |

## 명명 규칙

### 시리얼 순서 문서 (plans/PRD, work-orders 등)
- `NN-짧은-설명.md` (NN: 01~99 zero-pad)
- 예: `01-research-foundation.md`, `02-strategy-decision.md`, `03-PRD-v1.md`

### 일자 기반 문서 (analysis, thoughts 등)
- `YYYYMMDD-NN-설명.md` 또는 `YYYY-MM-DD-설명.md`
- 예: `20260616-01-toss-api-survey.md`

### Issue 번호 (issues/)
- `issue-NN.md` (Upbit 프로젝트 Issue #21까지와 무관, #1부터 신규)

## 작성 규칙

1. **승인 후 작성**: 메모리 `feedback-plan-doc-protocol` — 채팅 보고 → 사용자 승인 → 문서 저장
2. **선행 작성 금지**: 메모리 `feedback-plan-doc-protocol` — 무단 교훈/기획 문서 작성 절대 금지
3. **변경 이력 섹션**: 모든 plans·architecture 문서 하단에 "## 변경 이력" 표 유지

## 자매 프로젝트 참조

`upbit-tradebot-mvp/docs/` 의 다음 자산을 분류 체계 학습용으로 참고:
- `docs/operations/notifications.md` — 운영 매뉴얼 패턴 (목차·인벤토리·트러블슈팅)
- `docs/issues/issue-NN.md` — 단일 Issue 문서 패턴
- `docs/work-orders/2026-001-confirmed-candle.md` — 작업 지시서 패턴

복사가 아닌 학습. Toss 환경에 맞춰 재작성.
