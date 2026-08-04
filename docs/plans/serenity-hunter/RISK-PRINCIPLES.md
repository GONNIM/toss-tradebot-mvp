# Serenity Hunter · 리스크 원칙 (Phase L14 착수 조건)

**작성일**: 2026-08-04
**상태**: v6 착수 조건 · Fable 5 6차 GO 시점 확정본
**해당 페이지**: `/influencer/serenity-hunter`
**참조 코드**: `backend/discovery/serenity/constants.py` (수치의 코드 상수 대응)

**본 문서 성격**: Serenity Hunter 페이지가 실제 100만원 시드 매매에 사용되기 전 · 사용자와 시스템이 함께 지켜야 할 매매 원칙. **문서 수치와 코드 상수는 동일해야 하며, 변경 시 두 곳 모두 갱신 + 이력 append (§11)** 강제.

---

## §0 목적

시드 100만원 보전을 최우선. 본 페이지는 X @Serenity_Stocks (팔로워 900K+) 트윗을 z.ai 로 signal 화한 뒤 IWM/SPY 초과수익으로 알파 존재 여부를 검증하는 실험대. **알파 유무는 미검증 상태** · Step A 검증 데이터가 축적된 이후에만 판단.

**검증 실패 시나리오**: 유효 이벤트 150건 이상 축적 후 IWM 대비 비용 차감 초과수익이 0 이하이면 페이지는 자동 폐기 (배너가 아니라 리스트 사라짐 · §10 참조).

---

## §1 종목당 한도

- **시드의 20%** = 20만원 (KRW 기준 · 실 매수 시점 환율 반영)
- 이보다 낮추면 정액 수수료 비중이 과대해짐 (Fable 5 권고)
- 상한 초과 매수는 매뉴얼상 금지 · 시스템 강제 아님 (사용자 준수)

## §2 총 노출 캡

- **동시 보유 티커 ≤ 3개**
- **총 노출 ≤ 시드 60%** = 60만원 (현금 40% 협상 불가 · Fable 5 권고)
- Serenity Hunter 리스트가 매일 5+개 후보 공급해도 3개 초과 진입 금지

## §3 유동성 필터 (예시 아닌 필수 · 슬리피지 +1% 방어)

- **20일 평균 거래대금 (ADV) ≥ $2M** (미만 티커 매매 금지)
- **내 주문 금액 / ADV ≤ 0.5%** (200만원 상당 매수 시 ADV $4M 이상 필요)
- 이 필터가 유일한 슬리피지 방어 · UI 에서 `passes_liquidity=false` 티커는 회색 처리

## §4 기계적 손절

- **entry 대비 -10%** OR **5거래일 경과** · 둘 중 선도달 조건 발동 시 청산
- ⚠ **갭 하락은 이 손절선이 못 막습니다** · 익일 시가가 -15% 갭이면 -15% 손실 확정
- Fable 5 권고 · -8% 는 마이크로캡 일중 노이즈에 걸림 → -10%

## §5 익절

- **entry 대비 +15% 도달 시 절반 청산** · 나머지 절반 트레일링 stop -7%
- Fable 5 권고 · 트레일링 -5% 는 이 변동성 구간에서 즉시 발동 → -7%

## §6 절대 회피

- **`⚠ 인플루언서 경고 신규`** 배지 (auto_avoid + first_mention_at ≤ 7d 조합) · Serenity 가 경고한 신규 종목
- **`financing_tier F`** · 재무 위험 최고 등급
- **`active_atm_pct > 40`** · ATM 발행 진행 중

## §7 진입 시점 (Look-ahead 방지)

- **entry 기준가 = 트윗 이후 다음 거래일 시가 + 슬리피지 +1%**
- signal 시점 종가는 이미 트윗 반응 포함 · 진입 불가
- 백테스트 수익률도 이 기준으로 통일 (v6 §2.7 게이트 · §2.8 폐기식)

## §8 비용

- **왕복 1.0% (수수료 0.5% + 환전 스프레드 0.5%) 보수 가정**
- **본인 브로커 조건에서 실측 확인 · 실측치가 1.0% 미만이면 하향 갱신 가능 · 이상이면 상향 필수**
- 갱신 절차:
  1. `backend/discovery/serenity/constants.py::COST_ROUND_TRIP_PCT` 값 수정
  2. 하향 시 `backend/tests/serenity/test_constants_hardening.py::MIN_COST_PCT` 도 함께 수정 (git diff 노출 강제 · Fable 5 옆문 마찰)
  3. `RISK-PRINCIPLES.md` §8 수치 갱신
  4. §11 이력 append (변경 사유 · 실측 근거)
- **하향은 절대 안 됨** · 폐기식 관대해짐 → 시드 손실 위험

## §9 검증 게이트 (하드 게이트)

- **유효 first_mention 이벤트 < 50건**: `/hunter` API 빈 배열 · UI HunterEmptyGate 렌더
- **IWM benchmark row < 50 영업일**: 게이트 close
- **health.warn=true** (크롤러·signals·prices 24h+ 미갱신): 게이트 close
- **deprecation_triggered=true**: 게이트 강제 close (§10)
- 게이트 close 상태에서는 매수 후보 검토 자체 불가

## §10 폐기 조건 (자동)

**판정식** (Step C `hunter.py::is_deprecation_triggered()`):
- `valid_backtest_events >= 150`
- AND `avg(raw_return_3d − benchmark_iwm_return_3d) − SLIPPAGE_PCT − COST_ROUND_TRIP_PCT <= 0` (**IWM 단독** · SPY 는 참고)
- AND `DEPRECATION_OVERRIDE_TICKET is None`

**발동 시**:
- `/hunter` API 자동 `gate_open=false` · rows=[]
- UI HunterEmptyGate ("검증 결과 알파 부재로 폐기됨" 메시지)
- 매일 크론 로그에 판정값 기록 (`[serenity][deprecation]`)
- **배너 아님 · 리스트 완전 사라짐** (Fable 5 3차 (2a) · 무시 방지)

**재개** (2단계 마찰):
1. `docs/plans/serenity-hunter/RISK-PRINCIPLES.md` §11 이력 append (재개 사유·담당자·수치)
2. `backend/discovery/serenity/constants.py::DEPRECATION_OVERRIDE_TICKET = "TT-XXX"` 값 변경 (재개 티켓 번호 문자열)
3. 두 단계 없이는 자동 hunter_rows() 빈 배열 유지

## §11 폐기 이력 (append-only)

**작성 규칙**: 신규 항목은 최상단 삽입 · 이전 항목 편집·삭제 금지 · git 이력 남김.

<!-- 이력 시작 -->

_아직 폐기 발동 없음._

<!-- 이력 끝 -->

---

## Meta · 문서 갱신 이력

- 2026-08-04 · v6 착수 조건 확정 · Fable 5 3차 권고값 채택 · 6차 GO 후 커밋 · 초안 (수치 · §1 20% · §2 3종목/60% · §3 $2M/0.5% · §4 -10%/5d · §5 +15%/-7% · §8 1.0%)
