"""저평가 우량주 투자원칙 v1.0 (2026-08-17 제정).

3층 구조:
  1. charter.json — 헌장 (버전·정의·임계값·개정 이력)
  2. screener — 일 1회 배치 · KOSPI 전종목 · 5원칙 통과 리스트
  3. gate — 봇 매수 pre-check · fail-closed 화이트리스트

문서 자체가 SSOT. 임의 완화 금지.
"""
from backend.principles.charter import load_charter

__all__ = ["load_charter"]
