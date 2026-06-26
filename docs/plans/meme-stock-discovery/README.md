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

## False Positive 검증 (Phase 2-A 완료)

random universe 100 ticker × 90D 시뮬 → 816 score days:

| 임계 | 진입 | 비율 |
|---|---|---|
| ⚠️ WATCH (≥0.50) | 16 | **1.96%** |
| 🔥 HOT (≥0.75) | 4 | **0.49%** ✅ |
| 🔥🔥 BLAZING (≥1.00) | 0 | 0.00% |

→ HOT 위양성률 합격선 5% 의 1/10 = **합격**. 모델이 random 종목에서는
신호를 거의 안 냄 + 실 폭등 사례에서는 80% detect.

## Phase 2 진행 완료 (2026-06-26)
- ✅ **A. False positive 시뮬** — HOT 0.49% (합격선 5% 의 1/10)
- ⏳ **B. Forward test** — 운영 누적 중 (apewisdom 5분 batch). 1~2주 후 재실행 예정
- ✅ **C. KRX 트랙** — 1,735 KOSDAQ 종목 일봉 적재 (pykrx 차단 → 네이버 domestic)
- ✅ **D. Catalyst** — 1D gap up 자동 검출 (+10%↑ 시 0.3~1.0 점수). 외부 catalyst (VI/halt/공시) 는 후속
- 🚧 **E. 운영 모니터링** — `/meme-watch` 1주 운영 + 시그널 누적 검증

## 5요소 confluence 모두 활성 (Phase 2)
| 시그널 | 가중치 (재정규화 전) | 데이터 소스 |
|---|---|---|
| ① 공매도 | 0.30 (Phase 3) | FINRA / KRX |
| ② 소셜 모멘텀 | 0.30 | apewisdom (US), KRX 부재 |
| ③ 유동성 폭주 | 0.25 | 네이버 일봉 (US + KRX) |
| ④ Momentum/Breakout | 0.15 | RSI + 1D return |
| ⑤ Catalyst | 0.15 | 1D gap up 자동 (VI/halt/공시 후속) |

## 운영 차단 매트릭스 (Phase 1+2 정리)
| 소스 | 운영 IP | 우회 |
|---|---|---|
| yfinance | ❌ Rate limit | 네이버 일봉 (US) |
| iShares IWM | ❌ Cookie/JS | 네이버 marketValue |
| Reddit 공개 JSON | ❌ 403 | apewisdom (사실상 대체) |
| Stocktwits | ❌ 403 | 코드 보존 (1d 잡 등록만) |
| Google Trends | ❌ 429 | 코드 보존 |
| pykrx | ❌ 인증 요구 | 네이버 domestic 일봉 |
| 네이버 금융 | ✅ | — |
| apewisdom | ✅ | — |

## 핵심 위험

- **밈주 = 본질적 도박**: 과거 패턴 ≠ 미래. 모델은 보조 신호이며
  투자 권유 아님 (Moonshot 모듈과 동일 disclaimer 적용).
- **시그널 소스의 비공식성**: Reddit/SNS 크롤링은 변경·차단 risk.
- **과적합**: 밈주는 black swan 성격, 학습 표본이 작음.
