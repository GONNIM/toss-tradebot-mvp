"""급등주 스나이퍼 · Sprint 1 · KR live tape reader.

정체성: [[project_true_identity]] — 급등주 사전 예측 봇
계획서: docs/plans/sniper/00-sprint1-plan.md

5단계 loop:
  신호대기 → 신호발생 → 실시간매수 → Trailing Stop → 실시간매도 → 신호대기 (∞)
"""
from .params import SniperParams, get_sniper_params_store

__all__ = ["SniperParams", "get_sniper_params_store"]
