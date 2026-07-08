# Sector Leaders Top 10 진입가 고도화 기획안

**작성일**: 2026-07-08
**상태**: 초안 — v2.0 핫픽스 병행 착수 (사용자 승인 2026-07-08)
**배포 정책**: v2.0 핫픽스 즉시 단일 배포, v2.1+ 단계별 로컬 완료 후 각 Phase 단일 배포 (메모리 `feedback_deploy_only_when_complete`)

관련:
- 대상 자산 — `backend/discovery/sector_leaders/top10.py` (진입가 계산)
- 대상 자산 — `frontend/components/sector-leaders/Top10Modal.tsx` (UI 렌더)
- 대상 자산 — `backend/api/routes/sector_leaders.py:79-95` + `backend/api/schemas.py:337` (API 계약)
- 자매 기획서 — `docs/plans/sector-leaders-top10-alert/plan.md` (알림 인프라 — 동일 종목에 새 필드 노출 필요)

---

## 1. WHY (문제 정의)

### 1-1. 사용자 원문

> 현재 한국 주식 변동성에 따른 진입가 등 예측 추천 데이터가 미흡하다.
> 예를들어 SK하이닉스 최고점 3백만원 이상일 경우에도 진입가 지금으로 표시…
> 현재 SK하이닉스 2백만원 인 경우에도 진입가 지금으로 표시…
> 전문적인 애널리스트이자 전문투자자의 입장에서 해당 데이터에 대해 고도화 방안을 모든 방안을 찾아서 제안하시오.
> 현재도 훌륭하긴 하지만... 우리는 동업자로서 살아남아야 한다.

### 1-2. 근본 원인 — 현재 진입가 공식의 구조적 결함

`backend/discovery/sector_leaders/top10.py:279-290`

```python
point_price = current_price * (1 + horizon.point_estimate_pct / 100)  # 낙관 시 > 현재가
entry_price = min(current_price, point_price * 0.9)                   # → 항상 current_price
if entry_price >= current_price * 0.99:                                # → 항상 참
    entry_status = "🟢 지금 매수 가능"
```

`point_estimate_pct > +11.1%` (대다수 후보의 6M horizon 수익률) 이면 `point_price × 0.9 > current_price` 가 되고, `min()` 은 `current_price` 를 반환한다. 결과적으로 **모든 후보가 "지금 매수 가능"** 으로 표시된다.

### 1-3. 구조적 결함 5가지

| # | 결함 | 실제 영향 |
|---|---|---|
| ① | 진입가가 **미래 예측치의 파생** (앵커가 미래) | 낙관적 예측일수록 "지금" 강하게 나옴 |
| ② | **현재가 절대 수준을 평가 안 함** (300만 vs 200만 동일) | 최고점에서도 매수 권유 |
| ③ | **변동성(σ, ATR) 미반영** | 20만 종목과 5천원 종목이 동일 로직 |
| ④ | **기술적 지지선 미참조** (MA·피봇·피보) | 차트 무시 |
| ⑤ | **"관망(No-Go)" 신호 부재** | 어떤 상황에서도 매수 권유 |

동업자로서 살아남으려면 코드가 **"사지 말아야 할 때 사지 마라"** 를 먼저 알아야 한다.

---

## 2. WHAT (요구사항 — 5축 프레임워크)

### 2-1. 축 A — 가치 앵커 (Value Anchor)

**현재가가 역사적/섹터 대비 비싼가**를 먼저 판단.

| 지표 | 산출 | 활용 |
|---|---|---|
| **52W 위치** | `(현재가 − 52W저) / (52W고 − 52W저)` | ≥ 0.85 → 밴드 상단 경고 |
| **200일 이격도** | `현재가 / MA200 − 1` | ≥ +25% → "고평가 관망" |
| **PER/PBR 백분위수** | 5년 롤링 percentile | ≥ 90p → 밸류 부담 배지 |
| **DCF 안전마진** | `(Fair − 현재) / Fair` | ≤ −20% (거품) → 진입 차단 |

*SK하이닉스 300만 사례*: 200MA 이격 +40% + PBR 5년 95p → **관망 강제**

### 2-2. 축 B — 기술적 지지 (Technical Support Confluence)

매수 후보가는 **여러 지지선의 밀집 구간** 에서 나옴.

| 후보 | 산출 |
|---|---|
| **MA20/60/120 지지** | 각 MA 값 |
| **피보나치 되돌림** | 최근 스윙 저↔고 0.382 / 0.5 / 0.618 |
| **피봇 포인트** (S1, S2) | Classical + Camarilla |
| **볼륨 프로파일 POC** | 최근 60거래일 최대 거래량 가격대 |
| **직전 스윙 저점** | 최근 3개 |

→ 후보 5~7개 클러스터링 (`DBSCAN(eps=1×ATR)`) → 밀집 구간 = 진입 밴드.

### 2-3. 축 C — 변동성 조정 (Volatility-Adaptive)

KOSPI 대형주와 코스닥 소형주를 같은 %로 다루면 안 됨.

```
ATR14 = 14일 True Range 평균
Entry_ATR = current − k × ATR14   (k = 0.5 공격 / 1.0 표준 / 1.5 보수)
Stop_ATR  = Entry_ATR − 1.5 × ATR14
Target    = Entry_ATR + 3.0 × ATR14   (R:R = 2:1 강제)
```

R:R < 1.5 이면 표시 안 함 = "지금은 가성비 없음".

### 2-4. 축 D — 시황·모멘텀 필터 (Regime Filter)

**추세 이탈 종목은 아무리 싸도 매수 금지** 원칙.

| 필터 | 통과 조건 |
|---|---|
| **200MA 방향성** | 200MA 60일 회귀 β > 0 |
| **ADX(14)** | ≥ 15 (추세 존재) |
| **RSI(14)** | 30~70 (극단 진입 회피) |
| **거래대금 순위** | 상위 300위 이내 (유동성) |
| **섹터 상대강도** | 12주 RS ≥ KOSPI 대비 +0% |

→ 통과율(0~5)을 신뢰도 배지: `🟢5/5`, `🟡3/5`, `🔴1/5`

### 2-5. 축 E — 진입 구조 (Scale-In + Risk Budget)

단일 진입가 대신 **분할매수 3단계**.

```
1차 매수 (40%): 축B 상단 밴드   (즉시 진입 가능선)
2차 매수 (35%): 축B 중단 = MA60 부근
3차 매수 (25%): 축B 하단 = 스윙 저점 + ATR 완충

포지션 크기 = (계좌 × 리스크%) / (평단 − 손절가)   ← Kelly 축약형
리스크%     = 1.0% × 신뢰도배지(1~5) / 5
```

---

## 3. HOW (통합 진입가 알고리즘)

```
STEP 1  gate = 축D 필터 (통과 못하면 status="🔴 관망", 종료)
STEP 2  overheat = 축A (52W 위치 > 0.9 OR 200MA 이격 > +30%)
        → status="🟡 조정 대기", entry=None
STEP 3  support_candidates = 축B 5~7개 후보 산출
STEP 4  cluster = DBSCAN(support_candidates, eps=1×ATR)
        entry_band = [cluster.min, cluster.max]
STEP 5  volatility_adj = 축C k×ATR 완충 적용
STEP 6  entry_1, entry_2, entry_3 = 분할매수 3단계
STEP 7  R:R = (target − entry_avg) / (entry_avg − stop)
        R:R < 1.5 → status="🟡 리스크 대비 수익 부족"
STEP 8  confidence = 축D 통과 지표 수 (0~5)
STEP 9  최종 카드 렌더
```

---

## 4. 로드맵 (단계별 배포)

| Phase | 범위 | 공수 | 즉시 효과 |
|---|---|---|---|
| **v2.0 (핫픽스)** ⭐ | `top10.py:279-290` 즉시 교체 — 축A (52W 위치) + 축C (ATR14 완충) + "관망" 상태 추가 | 0.5일 | SK하이닉스 300만 사례 즉시 해결 |
| **v2.1** | 축B 지지 클러스터링 + 분할매수 3단계 + UI 카드 확장 | 2일 | 진입 정밀도 대폭 향상 |
| **v2.2** | 축D 시황 필터 + 신뢰도 배지 (1~5) | 1.5일 | 매수 금지 종목 시각화 |
| **v3.0** | 밸류에이션 (PER/PBR 백분위) + DCF 안전마진 | 3일 | Value trap 회피 |
| **v3.1** | 컨센서스 목표가 스크레이핑 + R:R 자동 강제 | 2일 | R:R 미달 자동 필터링 |

---

## 5. v2.0 핫픽스 상세 (즉시 착수)

### 5-1. 스코프

**목표**: SK하이닉스 300만원 최고점 사례에서 "지금 매수 가능" 이 나오지 않게 만드는 것 하나. 축B/D/E 는 후속 Phase.

**구현 원칙**:
- 기존 `KrxDailyCandle` 데이터만 사용 (신규 소스 없음)
- 기존 `Top10Item` dataclass 확장 (필드 추가만, 삭제 없음)
- UI 는 새 필드를 노출하되 레이아웃 대변경 없음

### 5-2. v2.0 진입가 알고리즘

```
INPUT: current_price, daily_ohlc (최근 260일)

STEP 1  52W 위치 계산
    high_52w = max(close[-252:])
    low_52w  = min(close[-252:])
    pos_52w  = (current − low_52w) / (high_52w − low_52w)

STEP 2  ATR14 계산 (Wilder 방식)
    tr[i] = max(high[i]-low[i], |high[i]-close[i-1]|, |low[i]-close[i-1]|)
    atr14 = SMA(tr[-14:])

STEP 3  200MA 이격도
    ma200 = mean(close[-200:])
    ma200_deviation = current/ma200 − 1

STEP 4  과열 판정
    overheat = (pos_52w >= 0.85) OR (ma200_deviation >= 0.25)

STEP 5  진입가 산출
    if overheat:
        entry_price    = None
        entry_status   = "🔴 과열 관망 (52W {pos_52w:.0%}, MA200 +{ma200_deviation:.1%})"
        entry_gap_pct  = None
    else:
        # 표준 스케일: 1.0 × ATR14 아래
        entry_price    = current − 1.0 × atr14
        entry_gap_pct  = (entry_price/current − 1) × 100   # 음수
        if entry_gap_pct >= -0.5:
            entry_status = "🟢 지금 매수 가능 (ATR 완충 흡수)"
        else:
            entry_status = f"🟡 {abs(entry_gap_pct):.1f}% 조정 대기"
```

### 5-3. 새 필드 (Top10Item / Top10ItemResponse / TypeScript)

| 필드 | 타입 | 의미 |
|---|---|---|
| `entry_price` | `float \| null` | 과열 시 null |
| `entry_gap_pct` | `float \| null` | 과열 시 null |
| `high_52w` | `float` | 52주 최고 종가 |
| `low_52w` | `float` | 52주 최저 종가 |
| `pos_52w` | `float` | 0~1 |
| `atr14` | `float` | 14일 ATR |
| `ma200` | `float \| null` | 200MA (250일 미만이면 null) |
| `ma200_deviation` | `float \| null` | 200MA 이격도 |
| `overheat` | `bool` | 과열 여부 |
| `entry_method` | `str` | "v2.0-atr" (미래 v2.1 호환용) |

### 5-4. UI 반영 (Top10Modal.tsx)

**진입가 컬럼 렌더 변경**:

```
과열:            "—" (dim gray)
                 "🔴 과열 관망"
                 "52W 92% · MA200 +32%"

정상 (조정대기): "1,880,000"
                 "🟡 6.0% 조정 대기"
                 "52W 45% · ATR 20,000"

정상 (지금):     "2,000,000"
                 "🟢 지금 매수 가능"
                 "52W 25% · ATR 20,000"
```

**사용 가이드 갱신** — 진입가 산출 방식 설명 교체.

### 5-5. 테스트

`backend/tests/test_entry_price.py` 신규:
- 52W 위치 극단 (0.0, 1.0)
- ATR14 알려진 값
- 200MA 데이터 부족 시 None 반환
- 과열 판정 (경계값 0.85, 0.25)
- 진입가 산출 (과열 / 정상)

### 5-6. 배포 체크리스트

- [ ] `backend/discovery/sector_leaders/entry_price.py` 생성
- [ ] `top10.py` 진입가 로직 교체 (기존 279-290 라인)
- [ ] `Top10Item` dataclass 필드 확장
- [ ] `Top10ItemResponse` (Pydantic) 필드 확장
- [ ] `Top10Item` (TypeScript) 필드 확장
- [ ] `Top10Modal.tsx` 진입가 렌더 갱신
- [ ] `test_entry_price.py` 단위 테스트 통과
- [ ] `pytest backend/tests/` 전체 통과
- [ ] 실 DB 로 `compute_top10` 호출 → SK하이닉스 케이스 검증
- [ ] 프론트 빌드 (`npm run build`) 통과
- [ ] 사용자 승인 → 서버 배포

---

## 6. 리스크·완화

| 리스크 | 완화 |
|---|---|
| 신규 필드 노출로 알림 (`top10-alert`) 메시지 포맷 깨짐 | 알림 포맷터는 기존 필드만 사용 — 새 필드는 Optional, 알림은 변경 없음 |
| 데이터 부족 종목 (250일 미만) 에서 200MA 계산 실패 | `ma200`, `ma200_deviation`, `overheat` 모두 fallback (`overheat=False`, MA200 조건 skip) — 52W 위치만으로 판정 |
| ATR14 계산이 상장 초기 종목에서 실패 | 14일 미만 → ATR = `current_price × 2%` fallback |
| 실시간 현재가와 종가 시계열 혼용 | 52W/MA200은 종가 기준 (기존 방식 유지), 현재가는 실시간 우선. 산출 시점 UI 표시 |

---

## 7. 후속 Phase 트리거 조건

- **v2.1 (축B) 착수**: v2.0 배포 후 1주일 관측 → 사용자 피드백 수집 → 승인
- **v2.2 (축D) 착수**: v2.1 완료 후 → 사용자 승인
- **v3.0 (밸류에이션) 착수**: 컨센서스/재무 데이터 소스 결정 후

---

**마지막 업데이트**: 2026-07-08
**버전**: 1.0 (v2.0 핫픽스 병행 착수)
