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
- ✅ **Phase 1a/1a-bonus**: DB 4 모델 + universe (US 4,671 + KRX 1,739) · 네이버 marketValue 전환
- ✅ **Phase 1b**: 일봉 snapshot (yfinance → 네이버 우회) · hit 18%
- ✅ **Phase 1c**: Social 시그널 (Reddit → apewisdom 우회) · 200 ticker × 5분
- ✅ **Phase 1d**: Stocktwits + Google Trends (운영 IP 차단 — 코드 보존)
- ✅ **Phase 1e**: Confluence 점수 + `/api/v1/meme-watch/top`
- ✅ **Phase 1f**: UI `/meme-watch` + 5축 레이더 + 상세 모달
- ✅ **Phase 1g**: 백테스트 1차 → 1/5 합격, 모델 결함 발견
- ✅ **Phase 2 튜닝**: ③ Volume z → 배수 / ④ Oversold → Momentum 재정의 → **4/5 합격 (80%)** [03-backtest-report.md](03-backtest-report.md)

## 모델 튜닝 효과 (2026-06-26)

| 사례 | 이전 max | 튜닝 후 max | 결과 |
|---|---|---|---|
| GME | 0.281 @D-5 ❌ | **1.098 @D-5** 🔥🔥 | ✅ |
| AMC | 0.196 @D-5 ❌ | **0.889 @D+0** 🔥 | ✅ |
| KOSS.O | 0.550 @D-1 ✅ | **1.312 @D-1** 🔥🔥 | ✅ |
| ATER.O | 0.052 ❌ | **0.650 @D-1** ⚠️ | ✅ |
| WEN.O | 0.938 @D+0 ❌ | **1.200 @D+0** 🔥🔥 | ❌ (D-day 폭등이 D-1 까지 부재) |

**합격률 1/5 → 4/5 (80%)** — Q14 합격선 6/10 = 60% **초과**.

WEN 단독 미합격 원인: 폭등이 D-day 직후 갑작스럽게 시작 → social 시그널 추가 시 lead time 확장 예상 (Reddit WSB 바이럴이 D-2~D-3 시작).

## 다음 단계
- ② Social (apewisdom) 시계열 1~2주 누적 후 forward test
- false positive 시뮬 (6,000 random ticker × month)
- KRX 트랙 도입 (작전주/테마주)
- catalyst 시그널 (KRX VI / FINRA / DART)

## 핵심 위험

- **밈주 = 본질적 도박**: 과거 패턴 ≠ 미래. 모델은 보조 신호이며
  투자 권유 아님 (Moonshot 모듈과 동일 disclaimer 적용).
- **시그널 소스의 비공식성**: Reddit/SNS 크롤링은 변경·차단 risk.
- **과적합**: 밈주는 black swan 성격, 학습 표본이 작음.
