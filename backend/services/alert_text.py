"""알림 문구 공통 도구 · 한글 풀이 표 (1023-05 · 2026-10-23).

기준: docs/plans/alert-settings/wording.md — 제목 `<아이콘> <종류 이름> · <핵심 사실>` (40자),
본문 10줄 · 끝줄 절대 링크 · 사실만 · 바깥 값은 escape (parse_mode HTML).
풀이 표는 이 파일 한 곳에서만 관리한다 (원칙 ⑬).
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.services import notification_settings as ns

TITLE_MAX = 40
KST = timezone(timedelta(hours=9))
NONE = "—"


def esc(s) -> str:
    return html.escape(str(s), quote=False)


def _label(category: str, label: Optional[str]) -> str:
    if label:
        return label
    meta = ns.CATEGORIES.get(category)
    if meta is None:
        raise ValueError(f"설정 목록 밖 종류는 label 이 필요합니다: {category}")
    return meta.label


def title(category: str, fact: str, icon: str, label: Optional[str] = None) -> str:
    """`<아이콘> <종류 이름> · <사실>` · 40자를 넘으면 사실 끝을 「…」로 자른다."""
    head = f"{icon} {_label(category, label)} · "
    room = TITLE_MAX - len(head)
    if len(fact) > room:
        fact = fact[: max(room - 1, 0)] + "…"
    return head + fact


def link(category: str, page: Optional[str] = None) -> str:
    if page is None:
        meta = ns.CATEGORIES.get(category)
        if meta is None:
            raise ValueError(f"설정 목록 밖 종류는 page 가 필요합니다: {category}")
        page = meta.page
    return f"자세히: {ns.SITE_BASE_URL}{page}"


def kst(dt: Optional[datetime]) -> str:
    """UTC (naive 는 UTC 로 봄) → 한국 시각 `MM/DD HH:MM`."""
    if dt is None:
        return NONE
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%m/%d %H:%M")


def next_run(hour: int, minute: int, now: Optional[datetime] = None) -> str:
    """한국 시각 기준 다음 `hour:minute` 을 `MM/DD HH:MM` 으로."""
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run <= now:
        run += timedelta(days=1)
    return run.strftime("%m/%d %H:%M")


def stock(name: Optional[str], code: str) -> str:
    """`이름(코드)` · 이름이 없으면 코드를 앞에 둔다 (제목이 잘려도 코드는 남게)."""
    if not name:
        return f"{esc(code)} (종목명 확인 안 됨)"
    return f"{esc(name)}({esc(code)})"


def won(v: Optional[float]) -> str:
    return NONE if v is None else f"{v:,.0f}원"


def usd(v: Optional[float]) -> str:
    if v is None:
        return NONE
    return f"${v:,.4f}" if abs(v) < 1 else f"${v:,.2f}"


def pct(v: Optional[float]) -> str:
    """비율 (0.153) → `+15.3%`."""
    return NONE if v is None else f"{v * 100:+.1f}%"


# ── 한글 풀이 표 ──────────────────────────────

POWDERKEG_TYPE = {
    "B1": "횡령·배임",
    "B2": "감사의견 비적정",
    "B3": "거래 정지",
    "A1": "오너 사법 리스크",
    "A2": "상속",
    "A3": "담보 제공",
    "A4": "5% 보고",
    "A5": "배당·자사주",
    "A6": "저PBR 압박",
}

# 사건 코드 → (아이콘, 이름)
VIP_EVENT = {
    "TP1": ("🎯", "1차 목표가 도달"),
    "TP2": ("🎯", "2차 목표가 도달"),
    "STOP_APPROACH": ("🛑", "손절선 아래"),
    "TRAIL_ARMED": ("🔒", "고점 추적 시작"),
    "TRAIL_GIVEBACK": ("📉", "고점에서 내려옴"),
    "ACTIVIST_FILING": ("🕵", "행동주의 공시"),
}

ACTIVIST_LEVEL = {
    "REGIME_CHANGE": "단순 투자→경영 참여 전환",
    "CRITICAL": "매우 강함",
    "STRONG": "강함",
    "INSIDER": "임원·주요주주 매매",
    "WATCH": "참고",
    "NOTE": "기록",
    "CRITICAL_PACK": "매우 강함",
    "STRONG_PACK": "강함",
    "PACK": "참고",
}

EXIT_REASON = {
    "hard_sl": "손절선 도달",
    "trailing": "고점에서 되돌림",
    "force_close": "장 마감 정리",
}

SERENITY_JOB = {
    "crawler": "글 수집",
    "extractor": "신호 추출",
    "scorer": "점수 계산",
    "backtest": "과거 성적 계산",
    "price_snapshot": "가격 기록",
    "benchmark": "시장 비교",
    "zai_cost_audit": "AI 사용량 점검",
}

BIOTECH_STEP = {
    "aact_weekly": "임상시험 주간 자료",
    "candidates": "후보 고르기",
    "time_state": "일정 상태",
    "confirm": "확인",
    "report": "보고서",
    "radar": "레이더",
}
