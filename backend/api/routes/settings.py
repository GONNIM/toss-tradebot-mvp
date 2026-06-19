"""파라미터 라우트."""
from __future__ import annotations

from fastapi import APIRouter

from backend.api.schemas import SettingsResponse

router = APIRouter()


# 정적 설정 (DB 미사용 — 추후 Phase J 확장)
STATIC_SETTINGS = {
    "max_position_size_usd": ("1000000", "단일 종목 최대 매수 (KRW)"),
    "moonshot_seed_krw":     ("1000000", "Moonshot 카지노 자금"),
    "auto_trade_seed_krw":   ("15000000", "자동매매 시드"),
    "take_profit_pct":       ("0.20", "단타 익절 (+20%)"),
    "crazy_top_n":           ("10", "Crazy Top N"),
    "moonshot_top_n":        ("3", "Moonshot Top N"),
    "moonshot_high_risk_ratio": ("0.6", "Moonshot HIGH 위험 최소 비율"),
}


@router.get("/", response_model=list[SettingsResponse])
async def list_settings():
    """전체 파라미터."""
    return [
        SettingsResponse(key=k, value=v, description=desc)
        for k, (v, desc) in STATIC_SETTINGS.items()
    ]


@router.get("/{key}", response_model=SettingsResponse)
async def get_setting(key: str):
    """단일 파라미터."""
    if key not in STATIC_SETTINGS:
        from fastapi import HTTPException
        raise HTTPException(404, f"파라미터 {key} 없음")
    v, desc = STATIC_SETTINGS[key]
    return SettingsResponse(key=key, value=v, description=desc)
