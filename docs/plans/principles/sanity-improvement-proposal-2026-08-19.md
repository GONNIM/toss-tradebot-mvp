# Sanity Check 설계 개선안 (2026-08-19)

> **결정 안건 · 구현 하지 말 것**. 사용자 승인 전 커밋 금지 (v1.0.3 재발 방지 원칙 유지).
> 다음 세션 큐 1번 · 승인 후 v1.0.6 로 반영.

## 문제

v1.0.4 sanity check (TTM vs 사업보고서 연간 ±100% 이내) 는 **실 실적 급증도 오탐**.

**실제 관측 (run #5 · 2026-08-19)**:
- INSUFFICIENT 140 종목 중 **137 종목 (98%)** 이 ttm_sanity_fail
- 주요 대형주 대량 포함: 삼성전자 (ratio 2.50), SK하이닉스 (3.02), SK (4.39), 두산 (4.65), S-Oil (4.29), HD현대 (2.26), 신세계 (7.63) 등
- 삼전의 경우 **DART 원본 검증 완료** (Q1'26 47.10조·반기 71.27조 원본과 완전 일치 · 이중 계상 없음)
- 2026 시장 국면상 (반도체·화학 초호황·건설 침체 등) 동일 오탐 다수 추정

**즉 sanity check 는 파싱 오매칭 (v1.0.1 자본 오염 · ratio 12+) 은 잘 잡지만 · 실적 급증 (ratio 2~8) 도 함께 잡아버림.**

## 개선안 (2 stage)

### 1차 · 분기 누적 분해 내부 정합성 검증 (기본)

TTM 계산의 정확성을 · 외부 연간값과의 비교가 아닌 · **분기 누적 분해 자체의 내부 정합성**으로 검증.

**검증 규칙**:
```
Q_cumulative_check:
  Q1 <= Q2 (반기 누적은 Q1 이상 · 적자 아니면 절대값 기준)
  Q2 <= Q3 (3분기 누적은 반기 이상)
  Q3 <= Q4 (연간은 3분기 이상)

Q_standalone_check:
  Q단독 값이 특정 분기에서 ±5σ (분기 평균 대비 5 표준편차) 초과 시 경고
  → 파싱 오염 (자본 계정 등) 또는 매우 이례적 실적 signal
  → sanity_fail 강등 대상
```

**장점**:
- 실 실적 급증 (연간 대비 ±100% 초과) 도 정합성 검증 통과
- 파싱 오매칭 (자본 매핑 시 Q별로 자본 잔액이 반영 · 통상 Q4 < Q3 · Q1 아님) 은 여전히 감지

### 2차 · 분기 YoY 급증 원값 확인 (연간 대비 큰 괴리 시)

TTM 이 연간 대비 ±100% 초과 시 · **원값 재검증** 후 통과 처리:
```
if abs(ratio) > 2.0:
  # 분기 YoY 비교
  latest_q_cumulative = cache[latest_year, latest_q].net_income_owner_cum
  prev_year_same_q = cache[latest_year - 1, latest_q].net_income_owner_cum
  q_yoy = (latest_q_cumulative - prev_year_same_q) / abs(prev_year_same_q)
  
  if q_yoy > 0.5:
    # 분기 YoY 50% 초과 성장 → 실적 급증 확진
    verdict.reasons.append("ttm_surge_verified · Q YoY +X%")
    # sanity_fail 대신 pass 처리 (실 실적 급증)
```

**장점**:
- 삼전 (Q2 반기 71.27조 vs 2025 반기 4.93조 · YoY +1,346%) 은 명백한 실 급증 · 통과
- 파싱 오매칭 (자본 매핑 시 Q YoY 도 자본 증가율 · 실 순이익 증가 아님) 은 감지 유지

## Charter diff 초안 (v1.0.6 · 승인 시)

```diff
- "version": "1.0.5"
+ "version": "1.0.6"

+ "principles.per.sanity_check": {
+   "primary": "quarterly_cumulative_monotonicity",
+   "secondary": "ttm_surge_verified_via_q_yoy",
+   "threshold_yoy_surge": 0.5,
+   "note": "실 실적 급증 (YoY +50% 초과) 확인 시 ±100% sanity 통과. 파싱 오염만 정탐."
+ }

+ revision_history:
+   {
+     "version": "1.0.6",
+     "enacted_at": "TBD",
+     "changed_by": "사용자 승인 후",
+     "summary": "sanity check 재설계 · 분기 누적 정합성 우선 · 실적 급증 verified 통과",
+     "rationale": "v1.0.4 원복 결과 · KOSPI 대형주 137종목 sanity_fail (95% 대량 오탐) · 개선 필요"
+   }
```

## 예상 효과

- INSUFFICIENT (137 sanity_fail) 대량 감소 · 실 판정 (PASS/FAIL) 로 재분류
- 삼전·하이닉스 등 반도체 초호황 종목 · 실 PER 통과 시 pass 재판정 예상
- 파싱 오염 감지 능력 유지 (자본 계정 오매핑 등)

## 승인 절차 (v1.0.3 재발 방지)

1. 본 문서 사용자 검토
2. 사용자 승인 시 diff 검토
3. 승인 후에만 v1.0.6 커밋 (charter + screener 로직)
4. Recompute + 137종목 재판정 결과 검증
5. 문제 시 즉시 롤백 (revision_history 기록)

**절대 우회 금지**: sanity·게이트·임계값 완화 변경은 사용자 사전 승인 없이 커밋 금지 (v1.0.3 사고 원칙).
