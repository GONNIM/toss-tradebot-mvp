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


def title(category: str, fact: str, icon: str, label: Optional[str] = None, keep: str = "") -> str:
    """`<아이콘> <종류 이름> · <사실><꼬리>` (escape 된 결과).

    fact·keep 은 escape 전 원문으로 받는다. 40자(화면 글자 수)를 넘으면 fact 끝만 「…」로 자르고
    keep (종목 코드·사건 이름처럼 잘리면 안 되는 꼬리) 은 그대로 둔다. 자른 뒤 escape 하므로 엔티티가 반쪽 나지 않는다.
    """
    head = f"{icon} {_label(category, label)} · "
    room = TITLE_MAX - len(head) - len(keep)
    if len(fact) > room:
        fact = fact[: max(room - 1, 0)] + "…"
    return esc(head) + esc(fact) + esc(keep)


def stock_fact(name: Optional[str], code: str) -> tuple[str, str]:
    """제목용 (줄여도 되는 이름, 지킬 꼬리) — 이름이 없으면 코드가 꼬리."""
    if not name:
        return "", f"{code} (종목명 확인 안 됨)"
    return name, f"({code})"


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


def next_run(hour: int, minute: int, now: Optional[datetime] = None, weekday: Optional[int] = None) -> str:
    """한국 시각 기준 다음 `hour:minute` (weekday 를 주면 그 요일 · 월=0) 을 `MM/DD HH:MM` 으로."""
    now = (now or datetime.now(timezone.utc)).astimezone(KST)
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        run += timedelta(days=(weekday - run.weekday()) % 7)
        if run <= now:
            run += timedelta(days=7)
    elif run <= now:
        run += timedelta(days=1)
    return run.strftime("%m/%d %H:%M")


_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def next_run_spec(spec: str, now: Optional[datetime] = None) -> str:
    """`"07:00"` (매일) 또는 `"mon 06:00"` (매주) → 다음 실행 `MM/DD HH:MM`."""
    parts = spec.split()
    weekday = _WEEKDAYS[parts[0].lower()] if len(parts) == 2 else None
    hour, minute = (int(x) for x in parts[-1].split(":"))
    return next_run(hour, minute, now=now, weekday=weekday)


LEVEL_ICON = {"critical": "🚨", "warning": "⚠️", "info": "🧬"}


def biotech_message(level: str, fact: str, lines: list[str], next_spec: Optional[str] = None,
                    now: Optional[datetime] = None) -> tuple[str, str]:
    """바이오 알림 (제목, 본문) · fact 는 원문 · lines 는 이미 escape 된 줄 · 다음 실행과 링크를 붙인다."""
    head = title("biotech", fact, LEVEL_ICON.get(level, "🧬"))   # fact 는 원문
    body = list(lines)
    if next_spec:
        body.append(f"다음 실행: {next_run_spec(next_spec, now=now)}")
    body.append(link("biotech"))
    return head, "\n".join(body)


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


def signed_usd(v: Optional[float]) -> str:
    return NONE if v is None else f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def md(date_str: Optional[str]) -> str:
    """`YYYY-MM-DD` → `MM/DD` (모양이 다르면 그대로)."""
    if date_str and len(date_str) >= 10 and date_str[4] == "-":
        return f"{date_str[5:7]}/{date_str[8:10]}"
    return esc(date_str or NONE)


def sec_form_text(form: str) -> str:
    """SEC 양식 → 쉬운 이름 (원문 괄호). 모르는 양식은 그대로."""
    f = (form or "").upper().replace("SCHEDULE ", "SC ").strip()
    table = (
        ("SC 13D/A", "보유 변경 보고 (13D/A)"),
        ("SC 13D", "경영 참여 목적 5% 이상 보유 신규 보고 (13D)"),
        ("SC 13G/A", "단순 투자 보유 변경 보고 (13G/A)"),
        ("SC 13G", "단순 투자 5% 이상 보유 보고 (13G)"),
        ("13D/A", "보유 변경 보고 (13D/A)"),
        ("13D", "경영 참여 목적 5% 이상 보유 신규 보고 (13D)"),
        ("4", "임원·주요주주 매매 보고 (Form 4)"),
    )
    for key, text in table:
        if f == key:
            return text
    return esc(form)


def entry_status_text(status: Optional[str]) -> str:
    """섹터 진입 상태 코드 문자열 (🟢/🟡/🔴 머리 · 화면 판정용 그대로 둠) → 알림용 사실 문장."""
    import re

    s = status or ""
    if s.startswith("🟢"):
        return "현재가가 지정가 참고선 근처"
    if s.startswith("🟡"):
        m = re.search(r"([\d.]+)%", s)
        return f"참고선까지 {m.group(1)}% 아래" if m else "참고선보다 위"
    if s.startswith("🔴"):
        m = re.search(r"\((.*)\)", s)
        why = m.group(1).replace("52W ", "1년 범위 위쪽 ").replace("MA200 ", "200일 평균 대비 ") if m else ""
        return f"과열 ({esc(why)})" if why else "과열"
    if "현재가 없음" in s:
        return "현재가 없음"
    return esc(s) if s else NONE


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
    "TP1": ("🎯", "설정한 1차 기준 도달"),
    "TP2": ("🎯", "설정한 2차 기준 도달"),
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
    "status_gen": "상태 파일 만들기",
}
