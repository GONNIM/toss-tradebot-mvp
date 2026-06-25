# Meme Stock Discovery — 화끈한 밈주 찾기

**가칭**: 화끈한 밈주 찾기
**상태**: 기획 — 방향·논점 정리 단계
**시작일**: 2026-06-25
**계기**: Wendy's +26% 사례 (2026-06 추정) — 레딧 WSB "Save Wendy's"
바이럴, 공매도 23% 상태에서 개인 매수세 폭주, 거래량 평소 20배,
거래 일시정지까지 발동.

## 미션

소셜·심리·squeeze 메커니즘 기반 급등 가능성 종목을 발굴해
사용자에게 "급등 후보 워치리스트" 형태로 제시. 기존 Crazy/Moonshot/
Sector Leaders 와 차별되는 **소셜·유동성·공매도** 중심의 새 시그널.

## 문서 인덱스

| # | 문서 | 상태 |
|---|---|---|
| 00 | [방향·논점 정리](00-vision-and-debate.md) | ✅ 완료 — Q1=B/Q2=A/Q3=A/Q4=A/Q5=B 추천안 채택 |
| 01 | [시그널 소스 명세](01-signal-sources.md) | ✅ 완료 — Q6=A/Q7=B/Q8=B/Q9=A/Q10=A+C 추천안 채택 |
| 02 | [Confluence 점수 설계](02-confluence-design.md) | ✅ 완료 — Q11=A/Q12=A/Q13=A/Q14=A/Q15=B 추천안 채택 |
| 03 | [백테스트 사례 분석](03-backtest-cases.md) | ✅ 완료 — Q16=A/Q17=A/Q18=A/Q19=A 추천안 채택 |
| 04 | [구현 로드맵](04-implementation-roadmap.md) | ✅ 완료 — Q20=A/Q21=A/Q22=A/Q23=A 추천안 채택 |

## 진행 현황 (2026-06-25 ~)
- 🚧 **Phase 1a** (D+0 ~ D+3): DB 모델 + universe 빌드 — **진행 중**
- ⏳ Phase 1b ~ 1g: 대기

## 핵심 위험

- **밈주 = 본질적 도박**: 과거 패턴 ≠ 미래. 모델은 보조 신호이며
  투자 권유 아님 (Moonshot 모듈과 동일 disclaimer 적용).
- **시그널 소스의 비공식성**: Reddit/SNS 크롤링은 변경·차단 risk.
- **과적합**: 밈주는 black swan 성격, 학습 표본이 작음.
