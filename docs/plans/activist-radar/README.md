# Activist Radar — 헤지펀드 경영권 매수 초기 신호 감지

**가칭**: Activist Radar
**상태**: 기획 · 사용자 승인 대기 (2026-07-09~)
**계기**: 사용자 요청 — "헤지펀드가 경영권 확보 등 목적으로 공격적으로 매수하는 사례를 초기에 포착하고 싶다"
**대상 시장**: 미국 (SEC 규제) + 한국 (금감원·DART 규제) · 병행 진행
**목적**: 밈주 워치(급등 후 확산)와 정반대 — 정보 있는 소수 자본이 조용히 움직이는 **초기 매집·경영권 요구** 신호를 매매 시각에 포착

## 문서 인덱스

| # | 문서 | 내용 |
|---|------|------|
| 00 | [비전·초기신호 분류](00-vision-and-signal-taxonomy.md) | 무엇이 "초기"인지 · 신호 유형 · 성공 지표 |
| 01 | [Activist Universe](01-universe.md) | 미국 40 + 한국 20 감시 대상 리스트 |
| 02 | [데이터 소스 설계](02-data-sources.md) | SEC EDGAR + DART 통합 · 폴링 주기 · 재활용 지점 |
| 03 | [Phase A~C 로드맵](03-phase-a-c-roadmap.md) | 구현 상세 · 파일 구조 · API · UI 통합 |

## 이번 사이클 사용자 결정 (Step 0)

| 항목 | 채택 |
|------|------|
| 범위 | **Phase A~C** (미국 SC 13D + 한국 대량보유 + 강도 스코어링) |
| 시장 | **미국·한국 병행** |
| Universe | **하드코딩 + UI 편집** (30~50개 시작, UI 에서 추가·삭제) |
| 절차 | **기획서 작성 → 승인 → 구현** |

## Phase 로드맵 요약

| Phase | 기간 | 핵심 산출물 |
|-------|------|-------------|
| **A. 미국 SC 13D 폴러** | 2~3일 | Activist 30 CIK 감시 · 신규 SC 13D 즉시 Telegram + `[ACTIVIST-US · <fund> · <ticker>]` |
| **B. 한국 대량보유공시 폴러** | 2~3일 | DART API · activist 이름 매칭 · 경영참여 목적 필터 |
| **C. 강도 스코어링 · Wolf Pack** | 2일 | 다중 activist 30일 내 동일 종목 진입 = 강 신호 · 개별 신호 강도 0~100 |

**총**: 6~8일. 배포 완결 원칙([[feedback_deploy_only_when_complete]])에 따라 Phase A~C 로컬 완결 후 단일 배포.

## 후속 Phase (사용자 승인 시)

| Phase | 내용 |
|-------|------|
| D | 13G→13D 전환 감지 · 지분 5%↑ 대량 증가 필터 |
| E | Form 4 임원 대량 매수 · Wolf Pack 판정 보조 |
| F | 전용 `/activist-radar` 대시보드 (Phase A~C 는 밈주 워치 임시 통합) |

## 관련 프로젝트 · 재활용 지점

- **VIP 감시** ([[project_wen_vip_watch]]) — `backend/discovery/vip/activist_tracker.py` 로직 확장(multi-CIK)
- **밈주 워치** ([[project_meme_stock_discovery]]) — Telegram 봇·스케줄러 인프라 재활용
- **DART** — 이미 프로젝트에 통합 (`DART_API_KEY` 환경변수 활성)
- **SOPS 배포** ([[reference_sops_age_workflow]]) — 새 activist 목록 override 도 UI 편집기로

## 위험·주의

- **SC 13D 는 이미 매집 완료 후 신고** — 완전 초기(매집 진행 중)는 옵션 UOA·거래량 급증 등 추가 신호 필요(Phase D+ 대상). 학술 연구상 SC 13D 신고 후 30일 초과수익 +6~8% 이므로 신고 즉시 진입 전략은 여전히 유효
- **오검출 우려** — filer 이름·CIK 매칭에서 이름이 유사한 다른 fund 포함 위험. Tier 1 리스트 검증 후 확장
- **한국 소액주주 결집체** 는 신호가 약함(액티비즘 실행력 부족) — Universe 에 포함하지 않음
- **투자 권유 아님** — 참고 신호. 매매는 사용자 판단

**마지막 업데이트**: 2026-07-09 (초안)
