# 02. Meme Confluence Score 설계

**작성일**: 2026-06-25
**선행**: 01 시그널 소스 명세 (Q6~Q10 추천안 채택)
**상태**: 설계 완료 — 03 (백테스트) 으로 진행 가능

> 핵심 아이디어 — Sector Leaders 의 Confluence 패턴을 재활용하되,
> 5요소가 **모두 양방향(급등 트리거)** 인 점이 차이. Sector Leaders 는
> agreement/disagreement 가 있었지만, Meme 은 "동시 발현 강도" 합산.

---

## 1. 스코어 산출 공식

### 1.1 기본 공식

```
MemeScore = Σ (weight_i × normalized_signal_i)     ∈ [0, 1.0+]
```

- 각 `normalized_signal_i` ∈ [0, 1.5] (clip — overshoot 허용)
- 모든 가중치 합 = 1.0
- 결과는 [0, 1.5] 사이 (이론적으로 1.0 초과 가능 — "초강력" 시그널)

### 1.2 가중치 (1차 — Phase 1, ⑤ catalyst 제외)

| # | 시그널 | 가중치 | 근거 |
|---|---|---|---|
| ① | 공매도 잔고 | **0.30** | 구조적 트리거 — squeeze potential |
| ② | 소셜 모멘텀 | **0.30** | 발화 트리거 — 매수세 폭주의 원인 |
| ③ | 유동성 폭주 | **0.25** | 확정 시그널 — 실제 매수가 들어오는 중 |
| ④ | Oversold + 반전 | **0.15** | 추가 신뢰도 (기술적 turning point) |
| (⑤ catalyst) | (Phase 2) | (예약: 0.15 — 재정규화 시 0.0) |  |

Phase 1 합 = 1.0. Phase 2 catalyst 도입 시 ①②③④ 가중치를 ×0.85 로
스케일 + ⑤=0.15.

### 1.3 동적 가중치 재정규화 (소스 가용성 보정)

외부 API 실패로 시그널 일부 결손 시 자동 재정규화 — 메모리
[[feedback_partner_accountability]] 원칙 준수 (빈 값 마무리 금지,
가능한 시그널로 score 산출).

```python
def normalize_weights(available_signals: set[str]) -> dict[str, float]:
    base = {"short": 0.30, "social": 0.30, "volume": 0.25, "oversold": 0.15}
    if "catalyst" in available_signals:
        base = {k: v * 0.85 for k, v in base.items()}
        base["catalyst"] = 0.15
    # 결손 시그널 제거 + 합이 1.0 되도록 보정
    active = {k: v for k, v in base.items() if k in available_signals}
    s = sum(active.values()) or 1.0
    return {k: v / s for k, v in active.items()}
```

---

## 2. 시그널별 정규화

### 2.1 ① 공매도 잔고 (`short_norm`)

| 입력 | 출력 |
|---|---|
| US: `pct_of_float` ∈ [0, 100] | `min(1.5, max(0, pct / 15))` (15% 임계) |
| KRX: `pct_of_float` ∈ [0, 100] | `min(1.5, max(0, pct / 5))` (5% 임계, 한국 보정) |

예시:
- 공매도 23% (Wendy's) → 23/15 = **1.53 → 1.5** (overshoot clipped)
- 공매도 8% → 8/15 = **0.53**
- 공매도 2% → 2/15 = **0.13**

### 2.2 ② 소셜 모멘텀 (`social_norm`)

3개 sub-source (Reddit + Stocktwits + Google Trends) → z-score 평균.

```python
# 24h 윈도우 - mention_count 의 30일 평균·std
z_reddit    = (today_mentions - mean_30d) / std_30d
z_stocktwits = (today_bullish_pct - mean_30d) / std_30d
z_trends    = (today_trends_score - mean_30d) / std_30d

# 가용 sub-source 평균
z_avg = sum(z for z in [z_reddit, z_stocktwits, z_trends] if z is not None) / count

social_norm = min(1.5, max(0, z_avg / 5))  # +5σ → 1.0
```

예시:
- z_avg = +8σ (Wendy's WSB 바이럴) → **1.5 clipped**
- z_avg = +3σ → **0.6**
- z_avg = +1σ (잡음) → **0.2**

### 2.3 ③ 유동성 폭주 (`volume_norm`)

```python
vol_z = (today_volume - mean_20d) / std_20d
volume_norm = min(1.5, max(0, vol_z / 10))   # +10σ → 1.0
```

예시:
- 거래량 20배 (Wendy's: 평소 1,000만주 → 2억주) → z ≈ +20σ → **1.5 clipped**
- 거래량 5배 → z ≈ +6σ → **0.6**
- 거래량 평소 → z ≈ 0 → **0.0**

### 2.4 ④ Oversold + 반전 (`oversold_norm`)

복합 조건 — binary 합성:

```python
rsi = compute_rsi(closes, period=14)
return_1d = (today_close / yesterday_close - 1) * 100

# 두 조건 동시 충족 — strong
if rsi <= 30 and return_1d >= 5:
    oversold_norm = 1.0
# RSI 만 충족 — weak
elif rsi <= 35:
    oversold_norm = 0.5
# 반등 만 (이미 다 빠진 상태에서) — moderate
elif return_1d >= 8 and rsi <= 45:
    oversold_norm = 0.7
else:
    oversold_norm = 0.0
```

예시:
- Wendy's (RSI=22, 1D=+26%) → **1.0**
- 일반 종목 1D=+3% → **0.0**

### 2.5 ⑤ Catalyst (Phase 2 — 1차 제외)

지금은 가중치 0 / 미계산. Phase 2 도입 시:
- VI 발동 (KRX) / trading halt (US) → 1.0
- gap up ≥ +15% → 0.8
- DART 공시 (자본조정 / 인수합병 등) → 0.6

---

## 3. 라벨링 (등급)

| Score 범위 | 라벨 | 의미 |
|---|---|---|
| ≥ 1.00 | **🔥🔥 BLAZING** | 4~5 요소 동시 발현 — 즉각 워치 |
| 0.75 ~ 0.99 | **🔥 HOT** | 3~4 요소 강력 발현 |
| 0.50 ~ 0.74 | **⚠️ WATCH** | 2~3 요소 발현 — 모니터 |
| 0.25 ~ 0.49 | **👀 OBSERVE** | 1~2 요소 발현 — 약한 신호 |
| < 0.25 | **💤 SLEEP** | 시그널 없음 — 제외 |

→ **Top 워치리스트** 는 score ≥ 0.50 (WATCH 이상) 종목만 노출.

---

## 4. 보조 메트릭 (UI 표시용)

각 ticker 별로 함께 산출 — Sector Leaders 와 동일 패턴.

| 필드 | 정의 |
|---|---|
| `active_signals` | normalized ≥ 0.5 인 시그널 개수 (0~5) |
| `strongest_signal` | 최대 contribution 시그널 이름 |
| `confidence_label` | "strong"(≥4 가용) / "medium"(3) / "weak"(≤2) |
| `sample_warning` | True if 가용 시그널 < 3 |
| `lead_time_hint` | (백테스트 후 추가) — 임계 돌파 후 평균 D+? 폭등 |

---

## 5. Pydantic 응답 모델 (스키마 안)

```python
class MemeSignalContribution(BaseModel):
    name: str               # "short" / "social" / "volume" / "oversold"
    label: str              # "공매도 잔고" / "소셜 모멘텀" / ...
    raw_value: Optional[float]
    raw_label: str          # "23.0%" / "+8σ" / "20배" / "RSI 22"
    normalized: float       # [0, 1.5]
    weight: float           # [0, 1]
    contribution: float     # normalized × weight
    detail: str             # 사용자 설명


class MemeScoreResponse(BaseModel):
    ticker: str
    market: str             # "US" / "KRX"
    score: float            # [0, 1.5+]
    label: str              # "BLAZING" / "HOT" / "WATCH" / "OBSERVE" / "SLEEP"
    emoji: str              # "🔥🔥" / "🔥" / "⚠️" / "👀" / "💤"
    active_signals: int
    strongest_signal: str
    confidence_label: str
    sample_warning: bool
    contributions: list[MemeSignalContribution]
    computed_at: str
```

---

## 6. UI — 5축 레이더 차트 (Q10 채택안)

Recharts `RadarChart` 사용. 5축:
- ① Short Interest
- ② Social Momentum
- ③ Volume Surge
- ④ Oversold + Reversal
- ⑤ Catalyst (Phase 2)

각 축 [0, 1.5] 스케일. 점 색상:
- 🔥🔥 BLAZING = rose
- 🔥 HOT = orange
- ⚠️ WATCH = amber
- 👀 OBSERVE = cyan

워치리스트 Top 10 모달에서 종목 클릭 → 레이더 펼침.

---

## 7. 백테스트 가능성 점검

다음 사례를 D-day 기준으로 시그널 시계열 재구성, 우리 score 가
임계값 (0.75 HOT) 을 D-1~D-3 사이 넘었는지 검증.

| 사례 | 예상 D-day | 가용 데이터 |
|---|---|---|
| GME (2021-01-27) | 2021-01-27 | Reddit + Yahoo + FINRA — 완전 |
| AMC (2021-06-02) | 2021-06-02 | 동일 |
| BBBY (2022-08-15) | 2022-08-15 | 동일 |
| Wendy's (2026-06) | 2026-06-?? | 부분 — 실시간 후속 검증 |
| 한국 작전주 (예: 케이씨아이 2024) | 2024-? | pykrx + Google Trends 만 |

**합격 기준**:
- 10 사례 중 6 이상 D-3 이내 score ≥ 0.75 진입
- 동일 기간 매월 random ticker 사이 false positive < 5%

---

## 8. 미해결 사항 — 사용자 결정 대기

### Q11. 가중치 시작값
- A. 추천 (Short 0.30 / Social 0.30 / Volume 0.25 / Oversold 0.15) ← **추천**
- B. 균등 (각 0.25)
- C. Social 비중 ↑ (Short 0.25 / **Social 0.35** / Volume 0.25 / Oversold 0.15)

### Q12. 임계값 — WATCH 진입 기준
- A. 0.50 이상 (느슨 — Top 워치리스트 후보 多) ← **추천**
- B. 0.60 이상 (중간)
- C. 0.75 이상 (엄격 — HOT 만)

### Q13. 한국 시장 보정 — 공매도 임계
- A. 5% (한국 평균 기준) ← **추천**
- B. 8% (보수적)
- C. 3% (공격적)

### Q14. 백테스트 합격선
- A. 10건 중 **6건** D-3 이내 score≥0.75 진입 ← **추천**
- B. 7건 (엄격)
- C. 5건 (느슨)

### Q15. score 값 노출 정책
- A. 0~1.0 정규화 표시 (overshoot 도 cap=1.0) ← UI 단순
- B. 원본 0~1.5 노출 + "초강력" 라벨 ← **추천** (정보 풍부)

---

## 9. 빠른 답변 예시

> "Q11=A, Q12=A, Q13=A, Q14=A, Q15=B, 진행"

이렇게 답주시면 다음 (03-backtest-cases.md) 진행합니다.
