# 03. 백테스트 사례 분석

**작성일**: 2026-06-25
**선행**: 02 Confluence 점수 (Q11~Q15 추천안 채택 — 가중치
0.30/0.30/0.25/0.15, WATCH≥0.50, KRX 공매도 5%, 합격 6/10, score 0~1.5 노출)
**상태**: 작성 — Q16~Q19 결정 대기 후 코드 구현

> 목적 — 02 의 MemeScore 공식이 **과거 실제 폭등 사례** 에서 D-day 전후
> 임계값을 통과했는지 검증. 합격하면 모델 채택, 미달이면 가중치/임계값
> 튜닝 후 재검증.

---

## 1. 검증 사례 매트릭스 (10건)

| # | Ticker | 시장 | D-day | 폭등 (D~D+5) | 핵심 트리거 | 데이터 가용성 |
|---|---|---|---|---|---|---|
| 1 | **GME** | NYSE | 2021-01-27 | +389% (5d) | r/WSB · Robinhood 매수 폭주 · short 140% | ⭐⭐⭐ (모든 소스 가능) |
| 2 | **AMC** | NYSE | 2021-06-02 | +95% (3d) | WSB 2차 · 공매도 squeeze | ⭐⭐⭐ |
| 3 | **BBBY** | NASDAQ | 2022-08-15 | +351% (10d) | Ryan Cohen 13G 공시 → WSB 점화 | ⭐⭐⭐ |
| 4 | **KOSS** | NASDAQ | 2021-01-27 | +1,800% (3d) | GME 동반 squeeze (low float) | ⭐⭐⭐ |
| 5 | **SPRT** | NASDAQ | 2021-08-27 | +570% (5d) | 합병 발표 + WSB 발화 | ⭐⭐⭐ |
| 6 | **ATER** | NASDAQ | 2021-09-23 | +220% (3d) | Short squeeze + WSB | ⭐⭐⭐ |
| 7 | **MULN** | NASDAQ | 2022-09-26 | +85% (2d) | EV 테마 + 개인 매수 폭주 | ⭐⭐⭐ |
| 8 | **APE** | NYSE | 2022-08-08 | +84% (3d) | AMC preferred 도입 발표 | ⭐⭐⭐ |
| 9 | **WEN** (Wendy's) | NASDAQ | 2026-06-?? | +26%+ | 본 프로젝트 트리거 사례 | ⭐⭐⭐ (실시간 후속) |
| 10 | **한국 사례** | KRX | TBD (Q16) | TBD | 정치테마/작전주/SNS | ⭐ (소셜 데이터 부족) |

> Wendy's 사례는 **현재 진행형** — 출시 후 실시간 검증으로 활용.

---

## 2. D-day 정의 — 어떻게 정하나

| 정의 | 장점 | 단점 |
|---|---|---|
| **A. 최초 단일일 +20% 이상 마감일** | 명확, 자동화 가능 | 큰 폭등 사례에만 적용 가능 |
| **B. 5일 누적 +30% 이상 시작일** | 더 많은 사례 포착 | 시작점 정의 모호 |
| **C. 거래량 z-score +10σ 처음 돌파일** | 시그널 기반 — 우리 모델과 일치 | 가격 폭등 없는 false signal 포함 |

→ **추천 A 1차** (clear definition). 사례별 D-day 자동 추출 함수:
```python
def detect_d_day(closes: list[float]) -> Optional[date]:
    """일일 +20% 첫 도달일."""
    for i in range(1, len(closes)):
        if (closes[i] / closes[i-1] - 1) >= 0.20:
            return closes[i].date
    return None
```

---

## 3. 시그널 시계열 재구성

각 사례별로 D-30 ~ D+5 기간의 일별 시그널 점수 계산.

### 3.1 데이터 수집 (D-day 알면 역산)

| 시그널 | 수집 방법 |
|---|---|
| ① 공매도 | FINRA 격주 발표 — D-30 ~ D 사이 인터폴레이션 (linear) |
| ② 소셜 — Reddit | pushshift.io 또는 Reddit API `search?q=$TICKER&t=day&after={D-30}` |
| ② 소셜 — Stocktwits | API `/streams/symbol/{ticker}.json?max={msg_id_at_D}` |
| ② 소셜 — Google Trends | pytrends 기간 지정 fetch |
| ③ 거래량 | yfinance 일봉 D-30 ~ D+5 |
| ④ RSI + 반전 | 동일 일봉 |

### 3.2 시그널 시계열 시각화 (보고서 포맷)

각 사례별로:

```
[GME] D-day = 2021-01-27
═══════════════════════════════════════
D-30   D-15   D-5   D-3   D-1   D    D+1  D+5
Score: 0.05  0.15  0.42  0.78  0.95 1.42 0.85  0.20
Label: 💤   👀   👀   🔥   🔥🔥 🔥🔥 🔥   👀

D-day 진입: D-3 (score 0.78 → HOT) ✅
폭등: +389% (D ~ D+5)
```

→ 사례별 동일 포맷 보고.

---

## 4. 합격 기준

### 4.1 1차 — Lead time (Q14 추천: 10건 중 6건)

| 항목 | 합격 기준 |
|---|---|
| **Lead time** | D-day 기준 D-3 ~ D-1 사이 score ≥ 0.75 (HOT) 진입 |
| **합격률** | 10 사례 중 **≥ 6건** 위 조건 충족 |

### 4.2 2차 — False positive

| 항목 | 기준 |
|---|---|
| **Sample** | 2021-2025 매월 random 100 ticker × 60 month = 6,000 종목·월 |
| **임계** | score ≥ 0.75 진입한 종목·월 비율 |
| **합격** | < 5% (= 6,000 중 < 300건) |

> false positive 가 5% 미만이어야 사용자에게 의미 있는 신호 — 그렇지
> 않으면 단순 노이즈 알람.

### 4.3 미달 시 튜닝 순서

1. 가중치 조정 (예: social ↑ 0.35, short ↓ 0.25)
2. 임계값 조정 (예: HOT 0.75 → 0.70)
3. Oversold 조건 완화 (RSI 30 → 35)
4. Sub-source 정규화 상수 (z/5, z/10) 보정

각 튜닝 후 재검증, 합격 시점에 가중치 동결.

---

## 5. 한국 사례 — 어떤 종목으로?

00 문서에서 후보 — "케이씨아이 (2024 작전주)", "정치테마주". 다만:

- **공매도 데이터**: KRX 일별 공시 — 가용 ✓
- **거래량 / RSI / 반등**: pykrx — 가용 ✓
- **소셜 데이터**: Google Trends KR 가용, 네이버 종토방·디시는 과거
  데이터 백테스트 거의 불가능 (실시간 크롤만)

→ **한국 사례 1건 시도**, 소셜 시그널 부재 시 그 가중치 0 로 보고
가중치 재정규화. score 만 산출 가능.

### Q16 — 한국 사례 후보 (사용자 결정)
- A. **2차전지 테마 — 에코프로비엠 2023-07** (시총 큼, 데이터 풍부)
- B. **정치 테마주 — 안랩 2022-12** (대선 후보 관련)
- C. **품절주 — 케이씨아이 2024-?** (작전주 의심)
- D. 미국 10건만 진행 (한국 검증은 출시 후 실시간)

---

## 6. 백테스트 코드 — 모듈 설계

`backend/discovery/meme_watch/backtest.py`:

```python
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class BacktestCase:
    ticker: str
    market: str            # "US" / "KRX"
    d_day: date
    note: str              # 사례 설명

@dataclass(frozen=True)
class BacktestResult:
    case: BacktestCase
    score_series: list[tuple[date, float, str]]  # (date, score, label)
    lead_time_days: Optional[int]      # D-day 와 첫 HOT 진입의 차이
    max_score: float
    max_score_date: date
    passed: bool


async def run_backtest(cases: list[BacktestCase]) -> list[BacktestResult]:
    """각 사례별로 D-30 ~ D+5 시그널 재구성 + score 계산."""

async def report_summary(results: list[BacktestResult]) -> dict:
    """합격률 + lead time 분포 + 보고서 생성."""
```

CLI 사용:
```bash
python -m backend.discovery.meme_watch.backtest \
    --cases default \
    --output docs/plans/meme-stock-discovery/03-backtest-report.md
```

---

## 7. 검증 보고서 — 출력 포맷 (예시)

`03-backtest-report.md` 생성 시:

```markdown
# Meme Score 백테스트 보고 — 2026-06-XX

## 합격률
- Lead time (≥6/10): **7 / 10 ✅**
- False positive (<5%): **3.2% ✅**

## 사례별

### GME (2021-01-27) ✅
- D-day score: 1.42 (🔥🔥 BLAZING)
- 첫 HOT 진입: D-3 (score 0.78)
- 최대 score: 1.42 (D-day)
- Lead time: 3일

| Date | Short | Social | Volume | Oversold | Score | Label |
|---|---|---|---|---|---|---|
| D-30 | 0.5 | 0.1 | 0.0 | 0.0 | 0.18 | 💤 |
| D-5  | 1.5 | 0.3 | 0.2 | 0.0 | 0.59 | ⚠️ |
| D-3  | 1.5 | 0.7 | 0.4 | 0.0 | 0.78 | 🔥 |
| D    | 1.5 | 1.5 | 1.5 | 1.0 | 1.43 | 🔥🔥 |

(... 나머지 9 사례)

## False positive 분석
- 2021-01 ~ 2025-12 매월 100 random ticker
- HOT 진입: 192 / 6,000 = 3.2%

## 결론 및 동결 가중치
- 가중치 동결: Short 0.30 / Social 0.30 / Volume 0.25 / Oversold 0.15
- 임계값 동결: WATCH 0.50 / HOT 0.75 / BLAZING 1.00
```

---

## 8. Reddit 과거 데이터 — 가용성 위험

Reddit API 는 최근 1년 정도만. 2021 GME/AMC 데이터는:

| 방법 | 가용성 |
|---|---|
| **A. pushshift.io** | 2022 이전 데이터 풍부 — 2023 차단 후 복구됨 |
| **B. Wayback Machine 크롤** | 가능하지만 비효율 |
| **C. Kaggle public datasets** | GME-WSB 전용 데이터셋 존재 (수집 완료된 dump) |

→ **C + A 병행** — Kaggle 검색 우선, 없으면 pushshift.

### Q17 — Reddit 과거 데이터 입수 방안
- A. Kaggle 데이터셋 다운로드 + pushshift 보완 ← **추천**
- B. pushshift.io 만 (직접 fetch)
- C. Reddit 데이터 없이 Stocktwits + Google Trends 로 대체

---

## 9. 백테스트 우선순위

| 순서 | 사례 | 소요 |
|---|---|---|
| 1 | GME (2021-01-27) — 가장 잘 알려진 사례 | 0.5d |
| 2 | AMC (2021-06-02) — GME 후속 | 0.5d |
| 3 | BBBY (2022-08-15) | 0.5d |
| 4 | KOSS / SPRT / ATER / MULN / APE | 2~3d (자동화된 동일 파이프라인) |
| 5 | Wendy's (2026-06) — 실시간 후속 | 출시 후 |
| 6 | 한국 1건 (Q16) | 1d |
| 7 | False positive 6,000 샘플 | 1~2d |

총 약 5~7일.

---

## 10. 미해결 사항 — 사용자 결정 대기

### Q16. 한국 사례
- A. **에코프로비엠 2023-07** (2차전지 테마) ← **추천**
- B. 안랩 2022-12 (정치 테마)
- C. 케이씨아이 (작전주)
- D. 미국 10건만 (한국은 출시 후)

### Q17. Reddit 과거 데이터
- A. Kaggle + pushshift 병행 ← **추천**
- B. pushshift 만
- C. Reddit 제외 (Stocktwits + Trends 대체)

### Q18. 백테스트 D-day 정의
- A. 일일 **+20%** 첫 도달일 ← **추천**
- B. 5일 누적 +30% 시작일
- C. 거래량 z 첫 +10σ 돌파일

### Q19. False positive 샘플 크기
- A. 6,000 종목·월 (5년 × 12월 × 100 random) ← **추천**
- B. 12,000 (10년)
- C. 3,000 (간략, 빠른 검증)

---

## 11. 빠른 답변 예시

> "Q16=A, Q17=A, Q18=A, Q19=A, 진행"

이렇게 답주시면 다음 (04-implementation-roadmap.md) 작성합니다.
