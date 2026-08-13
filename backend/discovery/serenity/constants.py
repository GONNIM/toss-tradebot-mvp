"""Serenity Hunter · 매매 상수 (Phase L14 착수 조건).

본 파일의 수치는 `docs/plans/serenity-hunter/RISK-PRINCIPLES.md` 와 1:1 동기화.
변경 시 두 곳 모두 갱신 + §11 이력 append + git commit 필수.

Fable 5 옆문 마찰 규칙 (2026-08-04 5차 리뷰):
- COST_ROUND_TRIP_PCT · SLIPPAGE_PCT 는 하한 1.0 유지
- 하한 이하로 낮추면 `backend/tests/serenity/test_constants_hardening.py` 도 함께 수정 필요
- 이 이중 수정이 git diff 노출을 강제 → "조용한 변경" 방지
"""
from __future__ import annotations

from typing import Optional

# ─── 비용 · 슬리피지 (RISK-PRINCIPLES §7 · §8) ────────────────────

SLIPPAGE_PCT: float = 1.0
"""매수 슬리피지 (%) · entry_next_open + 1% · 실체결가 근사.

Fable 5 3차 권고: +1% 는 마이크로캡 시가 체결에서도 낙관적 가정.
§3 유동성 필터 (ADV≥$2M · 주문≤0.5%) 로 이를 방어.

하향 시: test_constants_hardening.py MIN_SLIPPAGE_PCT 도 함께 수정 필요.
"""

COST_ROUND_TRIP_PCT: float = 1.0
"""왕복 수수료 + 환전 스프레드 (%) · 매수+매도 총비용.

구성: 수수료 왕복 0.5% + 환전 스프레드 왕복 0.5% (Fable 5 3차 권고 · 보수 가정).
사용자 브로커 실측 확인 후 갱신 (§8 절차 참조).

하향 시:
- test_constants_hardening.py MIN_COST_PCT 도 함께 수정
- RISK-PRINCIPLES §8 · §11 이력 append
- 폐기식이 관대해지므로 시드 손실 위험
"""

# ─── 게이트 · 폐기 임계 (RISK-PRINCIPLES §9 · §10) ─────────────────

GATE_EVENTS_MIN: int = 50
"""하드 게이트 임계 · 유효 first_mention 이벤트 최소 건수.

미달 시 /hunter API 빈 배열 · UI HunterEmptyGate 렌더.
IWM benchmark row 도 동일 임계 (50 영업일).
"""

DEPRECATION_EVENTS_MIN: int = 150
"""폐기 조건 활성화 임계 · 유효 이벤트 최소 건수.

이 값 미만이면 폐기 판정 자체 대기.
50 ≤ N < 150 구간에서 excess ≤ 0 시 mid_gate_excess_warning 발동 (§10 참조).
"""

DEPRECATION_OVERRIDE_TICKET: Optional[str] = None
"""폐기 재개 마찰 · 재개 시 티켓 번호 (예 "TT-042") 문자열 로 변경.

None 상태 · deprecation_triggered=true 인 한 자동으로 hunter_rows() 빈 배열 유지.
재개 절차 (RISK-PRINCIPLES §10):
  1. §11 이력 append (재개 사유·수치·담당자)
  2. 이 상수 값을 티커 번호 문자열 로 변경
  3. git commit
"""

# ─── 오늘의 실행 카드 필터 (L14+ · 2026-08-05) ─────────────────────
# 사용자 지시서 §1.1 · 전부 AND · Serenity Hunter 페이지 상단 섹션
# 하향 변경 시 test_constants_hardening.py 도 함께 갱신 → git diff 노출 강제

BULL_PCT_MIN: float = 70.0
"""90d bullish % 최소 · 강세 소스만 카드 발급."""

MENTIONS_90D_MIN: int = 10
"""표본 최소 · 90일 언급 건수."""

MENTIONS_7D_MIN: int = 2
"""살아있는 관심 · 7일 언급 건수."""

SHELL_INDUSTRIES: tuple[str, ...] = ("Shell Companies",)
"""무조건 제외 industry · CCXI 케이스 · yfinance industry 필드 매치."""

# ─── 실행 계획 계산 (RISK-PRINCIPLES §1·4·5·7·8 · 2026-08-05) ──────

SLIPPAGE_LIMIT_PCT: float = 1.0
"""매수 지정가 상한 = 다음 시가 × (1 + SLIPPAGE_LIMIT_PCT/100).

Fable 5 3차 권고 · 마이크로캡 시가 체결 방어. RISK-PRINCIPLES §7 진입 원칙.
"""

SL_PCT: float = 10.0
"""손절 임계 · entry −A% (RISK-PRINCIPLES §4 · Fable 5 3차 -8% → -10% 상향)."""

SL_DAYS: int = 5
"""시간 손절 · B거래일 무진전 (RISK-PRINCIPLES §4)."""

TP_TRIGGER_PCT: float = 15.0
"""익절 trigger · entry +C% 도달 후 트레일링 발동 (RISK-PRINCIPLES §5)."""

TRAIL_PCT: float = 7.0
"""트레일링 stop · +TP 후 최고가 대비 -D% (RISK-PRINCIPLES §5 · Fable 5 3차 -5% → -7% 상향)."""

POSITION_KRW: float = 200_000.0
"""종목당 매수 상한 (KRW · RISK-PRINCIPLES §1 · 시드 20% = 20만원)."""

USDKRW_RATE: float = 1330.0
"""환율 (USD/KRW · 하드코딩 · 신규 데이터 소스 스코프 밖).

실측 환율 사용 시 이 상수 갱신 + docs/plans/serenity-hunter/RISK-PRINCIPLES.md §8 수정.
"""

MIN_RR_WARNING: float = 2.0
"""Rulebook 최소 R:R 기준 · 미달 시 카드에 노란 배지 (사용자 확인 후 진행 UX)."""
