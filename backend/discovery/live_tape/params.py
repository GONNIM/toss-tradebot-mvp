"""Sniper Params — 하드 파라미터 UI 편집 가능한 store.

정체성 원칙: 사용자가 언제든 UI로 조정할 수 있어야 함 · 코드 하드코딩 X.

- JSON 파일 기반 (backend/data/sniper_params.json)
- Hot reload (파일 mtime 변경 감지 시 자동 재로드)
- thread-safe
- REST API로 GET/PUT (backend/api/routes/sniper.py)

스펙: docs/plans/sniper/00-sprint1-plan.md §1-2 하드 파라미터
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _PROJECT_ROOT / "backend" / "data" / "sniper_params.json"


@dataclass
class SniperParams:
    """급등주 스나이퍼 전 파라미터. 모두 UI 편집 가능."""

    # ─── 시드·주문 상한 ─────────────────────────
    seed_cap_krw: float = 1_000_000.0
    per_order_krw: float = 100_000.0
    max_concurrent_positions: int = 3

    # ─── Trailing Stop / 손절 ────────────────
    trailing_giveback_pct: float = 0.03            # peak 대비 3% 하락 시 청산
    hard_stop_loss_pct: float = -0.03              # 진입가 대비 -3% 시 즉시 손절

    # ─── 손실 캡 (Kill Switch 트리거) ───────
    daily_loss_limit_pct: float = -0.03            # -3% (30,000 KRW)
    weekly_loss_limit_pct: float = -0.08           # -8% (80,000 KRW · 주말까지 정지)

    # ─── 활성 시간 (KST · HH:MM) ─────────────
    active_start_kst: str = "10:00"                # 개장 1시간 후 (노이즈 회피)
    active_end_kst: str = "15:00"                  # 이 시각 이후 신규 진입 차단
    force_close_enabled: bool = True               # 장 마감 전 강제 청산 On/Off (사용자 선택)
    force_close_kst: str = "15:00"                 # 강제 청산 실행 시각 (enabled 시)

    # ─── 유니버스 필터 (KOSDAQ) ────────────
    universe_market_cap_min_krw: float = 30_000_000_000.0     # 시총 300억
    universe_market_cap_max_krw: float = 2_000_000_000_000.0  # 시총 2조
    universe_adv_20d_min_krw: float = 2_000_000_000.0         # ADV 20일 20억+
    universe_float_max_shares: float = 30_000_000.0           # 유통 3000만주 이하
    universe_price_min_krw: float = 1_000.0                   # 가격 1000원+
    universe_squeeze_float_max: float = 5_000_000.0           # squeeze 후보 500만주

    # ─── Composite Score 임계값 ──────────
    tape_score_threshold: float = 2.0              # z-score 임계
    rank_velocity_z_min: float = 2.0               # rank 이동 z-score
    trades_intensity_z_min: float = 2.5            # 초당 체결 건수 z-score
    orderbook_z_min: float = 2.5                   # bid stack z-score
    # 가중치 (0.5 + 0.3 + 0.2 = 1.0)
    score_weight_rank: float = 0.5
    score_weight_trades: float = 0.3
    score_weight_orderbook: float = 0.2

    # ─── 진입 조건 ────────────────────────
    entry_return_min_pct: float = 0.02             # 상승률 +2%부터
    entry_return_max_pct: float = 0.07             # 상승률 +7%까지 (초과는 상투)
    sustained_rise_min_sec: int = 300              # 5분 이상 상승 지속
    same_ticker_daily_limit: int = 1               # 종목당 1일 1회 진입 (통정매매 오인 회피)
    rank_target_min: int = 20                      # rank 이동 목표 (100→50 → 20 이하)
    rank_target_max: int = 50                      # rank 이동 목표 상단

    # ─── 폴링 주기 (초) ──────────────────
    poll_rankings_sec: int = 10
    poll_trades_sec: int = 20
    poll_orderbook_sec: int = 20
    poll_trailing_price_sec: int = 5

    # ─── 활성화 스위치 ─────────────────
    enabled: bool = False                          # 기본 비활성 (안전)


class SniperParamsStore:
    """파일 기반 파라미터 스토어 · hot reload · thread-safe."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _DEFAULT_PATH
        self._lock = threading.RLock()
        self._cached: Optional[SniperParams] = None
        self._mtime: float = 0.0

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("sniper_params.json 파싱 실패 · %s · default 사용", exc)
            return None

    def _parse(self, raw: Optional[dict]) -> SniperParams:
        if not raw:
            return SniperParams()
        allowed = {f.name for f in fields(SniperParams)}
        clean = {k: v for k, v in raw.items() if k in allowed}
        try:
            return SniperParams(**clean)
        except (TypeError, ValueError) as exc:
            logger.error("sniper_params 필드 파싱 실패 · %s · default 사용", exc)
            return SniperParams()

    def get(self) -> SniperParams:
        with self._lock:
            mtime = self._path.stat().st_mtime if self._path.exists() else 0.0
            if self._cached is not None and mtime == self._mtime:
                return self._cached
            self._cached = self._parse(self._read())
            self._mtime = mtime
            logger.info("sniper_params 로드 · mtime=%s", mtime)
            return self._cached

    def save(self, params: SniperParams) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = asdict(params)
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._cached = None  # 다음 조회 시 재로드
            self._mtime = 0.0
            logger.info("sniper_params 저장 · %s", self._path)

    def patch(self, updates: dict[str, Any]) -> SniperParams:
        """부분 업데이트 · 미지정 필드는 유지."""
        current = self.get()
        allowed = {f.name for f in fields(SniperParams)}
        merged = {**asdict(current), **{k: v for k, v in updates.items() if k in allowed}}
        try:
            new_params = SniperParams(**merged)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"sniper_params patch 실패: {exc}") from exc
        self.save(new_params)
        return new_params


_store: Optional[SniperParamsStore] = None


def get_sniper_params_store() -> SniperParamsStore:
    global _store
    if _store is None:
        _store = SniperParamsStore()
    return _store


def get_sniper_params() -> SniperParams:
    """편의 함수 · 어디서든 params 조회."""
    return get_sniper_params_store().get()
