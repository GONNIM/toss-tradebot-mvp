"""Execution 파라미터 override 3층 계층 — v2 트랙 C Phase 1.

우선순위: 종목별 > 시그널별 > global > env fallback
저장소: backend/data/execution_params.json (사용자 편집 가능)
Hot reload: 파일 mtime 변경 감지 시 자동 재로드 (재시작 불필요).

스펙: docs/plans/tradebot-mvp-v2/02-omi-interface-spec.md §12 (확정 결정 #6, #7)
참조 UI 패턴: [[project_wen_vip_watch]] `/vip` 편집기 · JSON override
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PATH = _PROJECT_ROOT / "backend" / "data" / "execution_params.json"


@dataclass
class ThresholdSet:
    """UI 편집 대상 3개 임계값 (Phase 1 스코프)."""
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    trailing_arm_pct: Optional[float] = None
    trailing_giveback_pct: Optional[float] = None

    def merge(self, other: "ThresholdSet") -> "ThresholdSet":
        """other 의 non-None 값이 self 를 덮어씀 (higher precedence)."""
        return ThresholdSet(
            take_profit_pct=other.take_profit_pct if other.take_profit_pct is not None else self.take_profit_pct,
            stop_loss_pct=other.stop_loss_pct if other.stop_loss_pct is not None else self.stop_loss_pct,
            trailing_arm_pct=other.trailing_arm_pct if other.trailing_arm_pct is not None else self.trailing_arm_pct,
            trailing_giveback_pct=other.trailing_giveback_pct if other.trailing_giveback_pct is not None else self.trailing_giveback_pct,
        )


@dataclass
class RiskBudget:
    """리스크 예산 (Phase 1은 JSON 직접 편집 · Phase 3에서 UI 노출)."""
    per_ticker_max_pct: float = 0.10        # 종목당 총 자본의 10%
    daily_loss_limit: float = -0.03         # 일일 누적 손실 -3%
    ticker_dd_limit: float = -0.05          # 종목별 Max DD -5%


@dataclass
class ExecutionParams:
    """파라미터 override 전체 파일 구조."""
    global_: ThresholdSet = field(default_factory=ThresholdSet)
    risk_budget: RiskBudget = field(default_factory=RiskBudget)
    tickers: dict[str, ThresholdSet] = field(default_factory=dict)
    signals: dict[str, ThresholdSet] = field(default_factory=dict)


def _env_defaults() -> ThresholdSet:
    """env fallback — 시스템 최후 default (JSON 미존재 시).

    참조: WEN VIP watch 의 VIP_TP1_PCT · VIP_STOP_PCT 등 패턴 재활용
    """

    def _f(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return float(raw)
        except ValueError:
            logger.warning("env %s=%r 를 float 변환 실패 · default 사용", name, raw)
            return default

    return ThresholdSet(
        take_profit_pct=_f("EXECUTION_TP_PCT", 0.05),
        stop_loss_pct=_f("EXECUTION_SL_PCT", -0.03),
        trailing_arm_pct=_f("EXECUTION_TRAIL_ARM_PCT", 0.08),
        trailing_giveback_pct=_f("EXECUTION_TRAIL_GIVEBACK_PCT", 0.02),
    )


class ExecutionParamsStore:
    """파일 기반 파라미터 스토어 · thread-safe · hot reload.

    Signal Router · Order Manager · Risk Budget 이 공통 사용.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._lock = threading.RLock()
        self._loaded: Optional[ExecutionParams] = None
        self._loaded_mtime: float = 0.0

    @property
    def path(self) -> Path:
        return self._path

    def _read_file(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            with self._path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("execution_params.json 파싱 실패 — %s · env fallback 사용", exc)
            return None

    def _parse(self, raw: Optional[dict]) -> ExecutionParams:
        if raw is None:
            return ExecutionParams(global_=_env_defaults())

        def _ts(node: Optional[dict]) -> ThresholdSet:
            node = node or {}
            return ThresholdSet(
                take_profit_pct=node.get("take_profit_pct"),
                stop_loss_pct=node.get("stop_loss_pct"),
                trailing_arm_pct=node.get("trailing_arm_pct"),
                trailing_giveback_pct=node.get("trailing_giveback_pct"),
            )

        env_ts = _env_defaults()
        global_ts = _ts(raw.get("global"))
        # global 항목이 JSON 에 없으면 env 값으로 대체
        global_ts = env_ts.merge(global_ts)

        rb_raw = raw.get("risk_budget", {}) or {}
        risk_budget = RiskBudget(
            per_ticker_max_pct=rb_raw.get("per_ticker_max_pct", 0.10),
            daily_loss_limit=rb_raw.get("daily_loss_limit", -0.03),
            ticker_dd_limit=rb_raw.get("ticker_dd_limit", -0.05),
        )

        tickers = {k: _ts(v) for k, v in (raw.get("tickers") or {}).items()}
        signals = {k: _ts(v) for k, v in (raw.get("signals") or {}).items()}
        return ExecutionParams(
            global_=global_ts,
            risk_budget=risk_budget,
            tickers=tickers,
            signals=signals,
        )

    def _load_if_needed(self) -> ExecutionParams:
        with self._lock:
            mtime = self._path.stat().st_mtime if self._path.exists() else 0.0
            if self._loaded is not None and mtime == self._loaded_mtime:
                return self._loaded
            raw = self._read_file()
            self._loaded = self._parse(raw)
            self._loaded_mtime = mtime
            logger.info("execution_params 로드 · mtime=%s", mtime)
            return self._loaded

    def get(self) -> ExecutionParams:
        return self._load_if_needed()

    def resolve(self, *, ticker: str, signal_source: Optional[str] = None) -> ThresholdSet:
        """3층 우선순위 병합: 종목별 > 시그널별 > global > env."""
        params = self._load_if_needed()
        resolved = params.global_
        if signal_source and signal_source in params.signals:
            resolved = resolved.merge(params.signals[signal_source])
        if ticker in params.tickers:
            resolved = resolved.merge(params.tickers[ticker])
        return resolved

    def risk_budget(self) -> RiskBudget:
        return self._load_if_needed().risk_budget

    def save(self, params: ExecutionParams) -> None:
        """UI API 로부터 사용자 수정 반영."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)

            def _clean(d: dict) -> dict:
                return {k: v for k, v in d.items() if v is not None}

            payload = {
                "global": _clean(asdict(params.global_)),
                "risk_budget": asdict(params.risk_budget),
                "tickers": {k: _clean(asdict(v)) for k, v in params.tickers.items()},
                "signals": {k: _clean(asdict(v)) for k, v in params.signals.items()},
            }
            self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._loaded = None  # 다음 조회 시 재로드
            self._loaded_mtime = 0.0
            logger.info("execution_params 저장 · %s", self._path)


# 프로세스 lifetime 싱글턴 — 라우트·Router·RiskBudget 공유
_store: Optional[ExecutionParamsStore] = None


def get_params_store() -> ExecutionParamsStore:
    global _store
    if _store is None:
        _store = ExecutionParamsStore()
    return _store
