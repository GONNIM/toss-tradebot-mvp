---
name: moonshot
description: Moonshot Picks Top 3/10 조회 — Toss Tradebot Discovery 모듈의 +100% 가능 후보 종목을 Claude 세션 안에서 표시
allowed-tools: [Bash]
---

# Moonshot Picks Skill

토스 Tradebot MVP의 **Moonshot Picks** 모듈 결과를 조회한다.
미국 주식 (페니스톡 포함 모든 가능성) 중 회당 +100% 수익 가능 후보를 매일 KST 16:50 cron으로 발굴.

**상태**: 🚧 **Placeholder** — `moonshot` CLI는 PRD v1.0 구현 후 활성화. 현재는 정의만 존재.

## 사용

사용자가 `/moonshot [command]` 입력 시 다음 분기:

| 명령 | 의미 | Bash 실행 |
|---|---|---|
| `/moonshot` | 오늘 Top 3 (기본) | `moonshot` |
| `/moonshot top` | Top 10 전체 | `moonshot top` |
| `/moonshot detail <TICKER>` | 종목 상세 (thesis + news + 매수가 3 옵션) | `moonshot detail <TICKER>` |
| `/moonshot history [N]` | 최근 N일 이력 (기본 7) | `moonshot history [N]` |
| `/moonshot perf` | 추천 적중률 통계 (1d/3d/5d) | `moonshot perf` |
| `/moonshot live` | 실시간 가격 갱신 (60초 polling) | `moonshot live` (짧은 시간만) |
| `/moonshot positions` | 사용자 보유 종목 | `moonshot positions` |

## 처리 절차

1. **Bash로 CLI 설치 여부 확인**:
   ```bash
   command -v moonshot >/dev/null 2>&1
   ```

2. **설치돼 있으면** (PRD v1.0 구현 후):
   - `moonshot $ARGS` 실행 (또는 `python -m backend.cli.moonshot $ARGS`)
   - 출력을 그대로 사용자에게 보고
   - ANSI 컬러 코드는 마크다운으로 재포맷 (rich 라이브러리 출력 → 마크다운 표·인용·강조)

3. **설치 안 됐으면** (현재):
   - 다음 안내 표시:
   ```
   🚧 Moonshot CLI 미구현 (PRD v1.0 구현 후 활성화)

   - CLI 명세: docs/plans/PRD/02-strategy-decision.md §3.2.3
   - 구현 위치: backend/cli/moonshot.py (예정)
   - Toss API 오픈 후 구현 진입
   ```

## 출력 가이드 (CLI 구현 후 적용)

CLI는 rich 라이브러리 컬러 박스 출력. Claude 세션에선 마크다운으로 변환:

| CLI 요소 | 마크다운 변환 |
|---|---|
| `═══════` 박스 | `## ` 헤더 또는 `---` 구분선 |
| 종목 카드 (`#1 ABCD ⭐⭐⭐ 87/100`) | `### #1 ABCD ⭐⭐⭐ (87/100)` |
| 컬러 강조 (현재가·점수) | `**굵게**` |
| 위험 수준 (HIGH/MED/LOW) | 이모지 + 텍스트 (`🔴 HIGH`, `🟡 MED`, `🟢 LOW`) |
| 매수가 옵션 (a/b/c) | 인용 블록 또는 인라인 코드 |

### 예시 변환

CLI 원본:
```
#1 ABCD                                         ⭐⭐⭐ 87/100
   카탈리스트: 어닝 D-1 (06-20 장 마감 후)
   현재가: $4.50  │  52w High: $8.20
   📈 매수가 옵션:
     (a) 즉시 진입: $4.50
     (b) 떡락 대기: $4.27  (-5%)
```

마크다운 변환:
```markdown
### #1 ABCD ⭐⭐⭐ (87/100)

| 항목 | 값 |
|---|---|
| 카탈리스트 | 어닝 D-1 (06-20 장 마감 후) |
| 현재가 | **$4.50** |
| 52w High | $8.20 |

📈 **매수가 옵션**:
- (a) 즉시 진입: `$4.50`
- (b) 떡락 대기: `$4.27` (-5%)
```

## 안전 가이드

- **Moonshot은 추천 시스템**: 매수·매도는 사용자가 토스 WTS에서 수동 진행
- **시드 100% 소실 가능성 인지** (결정 29 — 카지노 자금)
- **매수 옵션 (a) 즉시 진입은 HIGH 위험 종목엔 비권고** — (b) 떡락 대기 우선 (결정 33)
- **manipulation 위험** 표시 종목은 신중 (결정 40)

## 관련 문서

- `docs/plans/PRD/02-strategy-decision.md`
  - §3.2 Moonshot Picks 결정 매트릭스 (12 결정: 27~36, 40, 41)
  - §3.2.3 /moonshot CLI 명세 (결정 36)
  - §3.2.4 Claude Code Skill 정의 (본 파일)
- `docs/plans/PRD/03-PRD-v1.md` §4.4 — 모듈 명세
- `docs/analysis/moonshot-factor-research.md` — 9 인자 학술 검증 (v2)

## CLI 구현 후 활성화 절차

1. `backend/cli/moonshot.py` 구현 (click + rich)
2. `backend/pyproject.toml` console_scripts entry point:
   ```toml
   [project.scripts]
   moonshot = "backend.cli.moonshot:cli"
   ```
3. `pip install -e ./backend` (사용자 로컬 + optimus8 서버 양쪽)
4. 본 Skill 자동 작동 시작 (placeholder 단계 → 실 호출)
