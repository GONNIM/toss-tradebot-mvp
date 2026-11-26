"""DART 응답 · 원문 읽기 (1119-03 ② · 바깥 호출 없음 · 순수 함수).

elestock 응답 칸 이름은 OpenDART DS004 명세(기획서 2절 10)를 따른다. 원문(document.xml) 안의 표 모양은
[추정]이다 — 시험은 지어낸 자료이고, 실제 원문은 서버에서 한 번 보기 전에는 읽히지 않을 수 있다.
읽히지 않으면 doc_status=unparsed 로 남기고 유형 판정을 「모름」으로 둔다(맞춰 넣지 않는다).
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Optional

MAX_BODY_CHARS = 200_000

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_yyyymmdd(s: Any) -> Optional[date]:
    t = str(s or "").strip()
    if len(t) == 8 and t.isdigit():
        try:
            return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        except ValueError:
            return None
    return None


def row_key(*parts: Any) -> str:
    """같은 줄을 다시 받아도 같은 열쇠가 나오게 한다 (다시 돌려도 중복 없음)."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _seq_part(seq: int) -> tuple:
    """순번 0 은 열쇠에 넣지 않는다 (순번 도입 전에 만든 열쇠와 같게)."""
    return (f"#{seq}",) if seq > 0 else ()


def number_duplicate_lines(items: list) -> list:
    """같은 (접수번호 · 보고자 · 보유 수 · 증감 수) 줄이 여럿이면 나온 순서대로 순번 0, 1, 2... 를 붙인다.

    응답에 같은 줄이 두 번 나오면 둘 다 저장해 사건 수가 줄지 않게 한다 (열쇠가 같아 하나로 합쳐지던 문제).
    """
    seen: dict[tuple, int] = {}
    out = []
    for it in items:
        base = (it.rcept_no, it.repror, it.hold_qty, it.change_qty)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(replace(it, seq=n) if n else it)
    return out


@dataclass(frozen=True)
class InsiderItem:
    rcept_no: str
    rcept_date: date
    corp_code: str
    stock_code: Optional[str]
    repror: str
    position: Optional[str]
    is_main_holder: Optional[str]
    hold_qty: Optional[float]
    change_qty: Optional[float]
    hold_rate: Optional[float]
    change_rate: Optional[float]
    seq: int = 0          # 같은 접수번호 안에 네 값이 같은 줄이 또 있을 때의 순번 (첫 줄은 0 · 열쇠는 그대로)

    @property
    def key(self) -> str:
        return row_key("E", self.rcept_no, self.repror, self.hold_qty, self.change_qty, *(_seq_part(self.seq)))


def parse_elestock_item(item: dict[str, Any]) -> Optional[InsiderItem]:
    """elestock 한 줄 → InsiderItem. 접수번호나 접수일이 없으면 버린다."""
    rcept_no = str(item.get("rcept_no") or "").strip()
    d = parse_yyyymmdd(item.get("rcept_dt"))
    if not rcept_no or d is None:
        return None
    sc = str(item.get("stock_code") or "").strip()
    return InsiderItem(
        rcept_no=rcept_no, rcept_date=d, corp_code=str(item.get("corp_code") or "").strip(),
        stock_code=sc or None,
        repror=str(item.get("repror") or "").strip(),
        position=(str(item.get("isu_exctv_ofcps") or "").strip() or None),
        is_main_holder=(str(item.get("isu_main_shrholdr") or "").strip() or None),
        hold_qty=to_float(item.get("sp_stock_lmp_cnt")),
        change_qty=to_float(item.get("sp_stock_lmp_irds_cnt")),
        hold_rate=to_float(item.get("sp_stock_lmp_rate")),
        change_rate=to_float(item.get("sp_stock_lmp_irds_rate")),
    )


@dataclass(frozen=True)
class MajorItem:
    rcept_no: str
    rcept_date: date
    corp_code: str
    stock_code: Optional[str]
    report_tp: str
    repror: str
    hold_qty: Optional[float]
    change_qty: Optional[float]
    hold_rate: Optional[float]
    change_rate: Optional[float]
    report_resn: str
    seq: int = 0

    @property
    def key(self) -> str:
        return row_key("M", self.rcept_no, self.repror, self.hold_qty, self.change_qty, *(_seq_part(self.seq)))


def parse_majorstock_item(item: dict[str, Any]) -> Optional[MajorItem]:
    rcept_no = str(item.get("rcept_no") or "").strip()
    d = parse_yyyymmdd(item.get("rcept_dt"))
    if not rcept_no or d is None:
        return None
    sc = str(item.get("stock_code") or "").strip()
    return MajorItem(
        rcept_no=rcept_no, rcept_date=d, corp_code=str(item.get("corp_code") or "").strip(),
        stock_code=sc or None,
        report_tp=str(item.get("report_tp") or "").strip(),
        repror=str(item.get("repror") or "").strip(),
        hold_qty=to_float(item.get("stkqy")), change_qty=to_float(item.get("stkqy_irds")),
        hold_rate=to_float(item.get("stkrt")), change_rate=to_float(item.get("stkrt_irds")),
        report_resn=str(item.get("report_resn") or "").strip(),
    )


# ── 원문 ────────────────────────────────────────────────────────────────

def document_zip_to_text(content: bytes) -> Optional[str]:
    """document.xml 응답(ZIP) → 태그를 걷어 낸 글. ZIP 이 아니면(오류 JSON) None."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            parts = []
            for name in zf.namelist():
                raw = zf.read(name)
                for enc in ("utf-8", "euc-kr"):
                    try:
                        parts.append(raw.decode(enc))
                        break
                    except UnicodeDecodeError:
                        continue
    except zipfile.BadZipFile:
        return None
    text = _WS.sub(" ", _TAG.sub(" ", " ".join(parts))).strip()
    return text[:MAX_BODY_CHARS]


@dataclass(frozen=True)
class TradeLine:
    trade_date: date
    method: str
    qty: float
    unit_price: Optional[float]


_DATE = r"(?P<y>\d{4})\s*[-./년]\s*(?P<m>\d{1,2})\s*[-./월]\s*(?P<d>\d{1,2})\s*일?"
_LINE = re.compile(
    _DATE + r"\s+(?P<method>[가-힣][가-힣A-Za-z0-9()+\-/· ]{1,28}?)\s+(?P<qty>[+-]?[\d,]+)\s+(?P<price>[\d,]+(?:\.\d+)?)"
)


def parse_insider_trade_lines(text: str) -> list[TradeLine]:
    """임원 · 주요주주 소유보고 원문에서 (변동일 · 취득/처분 방법 · 수량 · 단가) 줄을 찾는다. 못 찾으면 빈 목록."""
    out: list[TradeLine] = []
    for m in _LINE.finditer(text or ""):
        try:
            d = date(int(m["y"]), int(m["m"]), int(m["d"]))
        except ValueError:
            continue
        qty = to_float(m["qty"])
        if qty is None:
            continue
        out.append(TradeLine(d, m["method"].strip(), qty, to_float(m["price"])))
    return out


_PURPOSE = re.compile(r"보유\s*목적[^가-힣]{0,6}(?P<tail>.{0,60})")


def parse_holding_purpose(text: str, report_nm: Optional[str] = None) -> Optional[str]:
    """5% 보고 원문의 보유 목적 → management(경영 참가) | simple(단순 투자) | None(모름)."""
    m = _PURPOSE.search(text or "")
    if m:
        tail = m["tail"]
        if "단순" in tail:
            return "simple"
        if "경영" in tail:
            return "management"
    nm = report_nm or ""
    if "(일반)" in nm:
        return "management"
    if "(약식)" in nm:
        return "simple"
    return None
