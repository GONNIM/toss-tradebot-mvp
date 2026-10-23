"""알림 종류별 설정 — 종류 목록 · 권고값 · 프로세스별 60초 캐시 (1022-09 · 2026-10-23).

설계: docs/plans/alert-settings/design.md
- 행이 없거나 DB 를 읽지 못하면 기본값(켜짐·즉시·간격 0·최소 등급 info) — 설정 읽기 실패 = 발송.
- 끌 수 없는 종류(LOCKED)는 enabled 를 끌 수 없다 (모드는 바꿀 수 있음).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

SITE_BASE_URL = "https://optimus8.cafe24.com"
CACHE_TTL_SEC = 60.0
LEVELS = ("info", "warning", "critical")
MODES = ("immediate", "digest")


@dataclass(frozen=True)
class CategoryMeta:
    label: str          # 알림 제목 앞·설정 화면 행 이름 (한 곳)
    group: str          # 11묶음
    page: str           # 사이트 경로 (자세히 보기)
    recommended: dict = field(default_factory=dict)
    reason: str = ""    # 권고 이유 한 줄
    locked: bool = False


@dataclass(frozen=True)
class SettingView:
    enabled: bool = True
    mode: str = "immediate"
    resend_minutes: int = 0
    min_level: str = "info"


DEFAULT_VIEW = SettingView()

_G1, _G2, _G3, _G4 = "① Serenity", "② 화약고 거래 주의", "③ 화약고 후보", "④ 화약고 티켓·재평가"
_G5, _G6, _G7, _G8 = "⑤ VIP", "⑥ 행동주의 투자자", "⑦ 종목 발굴", "⑧ 밈 급등"
_G9, _G10, _GX = "⑨ 실주문·Kill Switch", "⑩ 바이오", "시스템"

CATEGORIES: dict[str, CategoryMeta] = {
    "serenity": CategoryMeta("Serenity 작업", _G1, "/influencer/serenity", {"min_level": "warning"}, "2주 90건이 모두 성공 알림 · 실패만 받기"),
    "powderkeg_dnt": CategoryMeta("화약고 거래 주의", _G2, "/powderkeg", {}, "회사 자금 손실 공시 · 즉시 확인"),
    "powderkeg_a1": CategoryMeta("화약고 후보 · 오너 사법 리스크", _G3, "/powderkeg", {}, "유지"),
    "powderkeg_a2": CategoryMeta("화약고 후보 · A2", _G3, "/powderkeg", {"enabled": False}, "백테스트 근거 약함"),
    "powderkeg_a3": CategoryMeta("화약고 후보 · A3", _G3, "/powderkeg", {"enabled": False}, "백테스트 12개월 평균 음수"),
    "powderkeg_a5": CategoryMeta("화약고 후보 · A5", _G3, "/powderkeg", {}, "유지"),
    "powderkeg_a6": CategoryMeta("화약고 후보 · A6", _G3, "/powderkeg", {}, "유지"),
    "powderkeg_ticket": CategoryMeta("화약고 티켓 승인", _G4, "/powderkeg", {"enabled": False}, "2주 0건 · 직접 승인한 일이라 알림 불필요"),
    "powderkeg_reeval": CategoryMeta("화약고 12개월 재평가", _G4, "/powderkeg", {}, "유지"),
    "vip": CategoryMeta("VIP 감시", _G5, "/vip", {"resend_minutes": 10080}, "같은 종목·같은 사건은 7일에 한 번"),
    "activist_strong": CategoryMeta("행동주의 · 강한 신호", _G6, "/activist-radar", {}, "STRONG 이상 · 유지"),
    "activist_info": CategoryMeta("행동주의 · 참고 신호", _G6, "/activist-radar", {"enabled": False}, "WATCH·NOTE 는 화면에서 확인"),
    "discovery_sector": CategoryMeta("섹터 리더", _G7, "/sector-leaders", {}, "유지"),
    "discovery_crazy": CategoryMeta("Crazy 종목", _G7, "/lab/crazy", {}, "유지"),
    "discovery_moonshot": CategoryMeta("Moonshot 종목", _G7, "/lab/moonshot", {}, "유지"),
    "meme_erupting": CategoryMeta("밈 · 급등 진행", _G8, "/lab/meme-watch", {}, "즉시 · 같은 종목 재발송은 기존 규칙"),
    "meme_blazing": CategoryMeta("밈 · 급등 가능성", _G8, "/lab/meme-watch", {"mode": "digest"}, "2주 562건 중 대부분 · 하루 요약으로"),
    "execution": CategoryMeta("실주문", _G9, "/sniper", {}, "끌 수 없음", locked=True),
    "kill_switch": CategoryMeta("Kill Switch", _G9, "/lab/execution", {}, "끌 수 없음", locked=True),
    "biotech": CategoryMeta("바이오", _G10, "/biotech", {}, "유지"),
    "system": CategoryMeta("시스템 경고", _GX, "/admin/notifications", {}, "끌 수 없음 · 하루 요약은 가능", locked=True),
}

LOCKED = {k for k, m in CATEGORIES.items() if m.locked}
ALL_FIELDS = {"enabled", "mode", "resend_minutes", "min_level"}


def editable_fields(category: str) -> set[str]:
    """화면·API 에서 바꿀 수 있는 칸. Kill Switch·실주문은 전부 고정 · 시스템 경고는 받는 방식(하루 요약)만."""
    if category == "system":
        return {"mode"}
    if category in LOCKED:
        return set()
    return set(ALL_FIELDS)

# 화면에만 보이는 행 (설정 대상 아님)
DISPLAY_ONLY = {"deploy": CategoryMeta("배포 알림", "⑪ 배포", "/admin/notifications", {}, "GitHub Actions 가 보냄 · 설정 대상 아님")}

_cache: dict[str, tuple[float, SettingView]] = {}


def invalidate_cache() -> None:
    _cache.clear()


async def _load_row(category: str) -> Optional[SettingView]:
    from backend.services.db import get_session
    from backend.services.models import NotificationSetting

    async with get_session() as session:
        row = await session.get(NotificationSetting, category)
        if row is None:
            return None
        return SettingView(row.enabled, row.mode, row.resend_minutes, row.min_level)


async def get_setting(category: str) -> SettingView:
    """종류 설정 (60초 캐시). 행 없음·읽기 실패 → 기본값."""
    now = time.monotonic()
    hit = _cache.get(category)
    if hit and now - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    try:
        view = await _load_row(category) or DEFAULT_VIEW
    except Exception as exc:  # noqa: BLE001 — 설정 읽기 실패 = 발송
        logger.warning(f"[notify-settings] {category} 읽기 실패 · 기본값 사용: {exc.__class__.__name__}")
        view = DEFAULT_VIEW
    _cache[category] = (now, view)
    return view


async def save_setting(
    category: str,
    *,
    enabled: Optional[bool] = None,
    mode: Optional[str] = None,
    resend_minutes: Optional[int] = None,
    min_level: Optional[str] = None,
) -> SettingView:
    """부분 갱신. 알 수 없는 종류 → KeyError · 잘못된 값·잠긴 종류 끄기 → ValueError."""
    from backend.services.db import get_session
    from backend.services.models import NotificationSetting

    if category not in CATEGORIES:
        raise KeyError(category)
    requested = {k for k, v in (("enabled", enabled), ("mode", mode), ("resend_minutes", resend_minutes), ("min_level", min_level)) if v is not None}
    blocked = requested - editable_fields(category)
    if blocked:
        raise ValueError(f"{CATEGORIES[category].label} 은(는) 안전을 위해 {', '.join(sorted(blocked))} 를 바꿀 수 없습니다")
    if mode is not None and mode not in MODES:
        raise ValueError(f"mode: {mode}")
    if min_level is not None and min_level not in LEVELS:
        raise ValueError(f"min_level: {min_level}")
    if resend_minutes is not None and resend_minutes < 0:
        raise ValueError("resend_minutes < 0")

    async with get_session() as session:
        row = await session.get(NotificationSetting, category)
        if row is None:
            row = NotificationSetting(category=category, enabled=True, mode="immediate", resend_minutes=0, min_level="info")
            session.add(row)
        if enabled is not None:
            row.enabled = enabled
        if mode is not None:
            row.mode = mode
        if resend_minutes is not None:
            row.resend_minutes = resend_minutes
        if min_level is not None:
            row.min_level = min_level
        view = SettingView(row.enabled, row.mode, row.resend_minutes, row.min_level)
    invalidate_cache()
    return view


async def apply_recommended() -> int:
    """모든 종류에 권고값 적용. 바뀐 종류 수."""
    n = 0
    for key, meta in CATEGORIES.items():
        if meta.recommended:
            await save_setting(key, **meta.recommended)
            n += 1
    return n


_ACTIVIST_STRONG = {"CRITICAL", "REGIME_CHANGE", "STRONG", "CRITICAL_PACK", "STRONG_PACK"}


def powderkeg_category(event_type: str) -> str:
    """화약고 이벤트 유형 → 종류. B* = 거래 주의 · A1·A2·A3·A5·A6 = 후보 · 그 밖은 unknown (항상 발송)."""
    et = (event_type or "").upper()
    if et.startswith("B"):
        return "powderkeg_dnt"
    key = f"powderkeg_{et.lower()}"
    return key if key in CATEGORIES else "unknown"


def activist_category(intensity_label: str) -> str:
    """행동주의 강도 → 종류. STRONG 이상(무리 포함) = 강한 신호 · 그 밖 = 참고 신호."""
    return "activist_strong" if (intensity_label or "").upper() in _ACTIVIST_STRONG else "activist_info"
