"""KDI 수출입 동향 자료 목록 자동 discovery.

KDI EIEC (eiec.kdi.re.kr) 검색 페이지 크롤 → 산업통상부 발행 "수출입 동향" 자료 목록 파싱.
발표월(YYYY-MM)별 num 매핑 반환. 캐시 파일 저장.

문제 재발 방지 (2026-08-14 사고):
- 기존 downloader.KDI_NUM_CATALOG 는 사용자 수동 등재 방식 → 매월 갱신 누락 시 silent skip.
- 본 모듈로 discovery 자동화 · 캐시 fallback · 크론 진입 전 refresh.

HTML 구조 (2026-08-14 확진):
    <li>
        <a href="./materialView.do?num=XXX&...">
            <div class="list_txt">
                <p>2026년 7월 수출입 동향</p>       ← 자료 제목
                <span>산업통상부</span>              ← 발행기관 필터
                <span>2026.08.01                    ← 발표일 (= 발표월 1일)
                    <span>36p</span>
                </span>
            </div>
        </a>
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


KDI_LIST_URL = "https://eiec.kdi.re.kr/policy/materialList.do"
KDI_SEARCH_TXT = "수출입 동향"
KDI_TOPIC = "O"  # 동향자료
DEFAULT_PP = 40

DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "research"
    / "motir_exports"
    / "kdi_num_cache.json"
)


# ─── HTML 파싱 ───────────────────────────────────────────────────

# 리스트 아이템 정규식 — a href + <p>제목</p> + <span>기관</span> + <span>YYYY.MM.DD
_LIST_ITEM_RE = re.compile(
    r'<a\s+href="\.?/materialView\.do\?num=(?P<num>\d+)[^"]*">\s*'
    r'<div\s+class="list_txt">\s*'
    r'<p>(?P<title>[^<]+)</p>\s*'
    r'<span>(?P<org>[^<]+)</span>\s*'
    r'<span>(?P<date>\d{4}\.\d{2}\.\d{2})',
    re.DOTALL,
)

# 산업통상부 발행 & 정확 "수출입 동향" 자료만 매치 (ICT·정보통신산업 등 배제).
# 지원 형식:
#   "YYYY년 M월 수출입 동향"
#   "YYYY년 M월 및 상반기 수출입 동향"       (6월)
#   "YYYY년 상반기 및 M월 수출입 동향"       (드물게 순서 뒤바뀜 대비)
#   "YYYY년 연간 및 M월 수출입 동향"         (12월)
_TITLE_RE = re.compile(
    r"^(?P<year>20\d{2})년\s+"
    r"(?:연간\s+및\s+\d+월|\d+월\s+및\s+상반기|상반기\s+및\s+\d+월|\d+월)\s+"
    r"수출입\s+동향$"
)

_ISSUING_ORG = "산업통상부"


@dataclass
class KDIEntry:
    """KDI 자료 1건."""

    num: int
    title: str
    org: str
    published: date  # 발표일 (매월 1일)
    report_month: str  # "YYYY-MM" 발표월 = published 의 year-month

    def to_dict(self) -> dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        return d


# ─── 크롤링 ──────────────────────────────────────────────────────


async def fetch_kdi_export_index(
    *,
    pp: int = DEFAULT_PP,
    pg: int = 1,
    timeout: float = 30.0,
    max_pages: int = 3,
) -> list[KDIEntry]:
    """KDI 검색 페이지 → 산업통상부 발행 수출입 동향 자료 목록.

    다중 페이지 순회 (기본 3페이지 = 최대 120건 · 10년치 이상 커버).
    """
    entries: list[KDIEntry] = []
    seen_nums: set[int] = set()

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "toss-tradebot-mvp/0.1 (sector_leaders discovery)"},
    ) as client:
        for page in range(pg, pg + max_pages):
            params = {
                "search_txt": KDI_SEARCH_TXT,
                "topic": KDI_TOPIC,
                "pp": pp,
                "pg": page,
            }
            logger.debug(f"[kdi_discovery] GET pg={page} pp={pp}")
            resp = await client.get(KDI_LIST_URL, params=params)
            resp.raise_for_status()
            html = resp.text

            page_entries = _parse_list_html(html)
            new_on_page = 0
            for e in page_entries:
                if e.num in seen_nums:
                    continue
                seen_nums.add(e.num)
                entries.append(e)
                new_on_page += 1

            logger.debug(
                f"[kdi_discovery] pg={page} · parsed={len(page_entries)} · new={new_on_page}"
            )
            # 페이지 결과 0 → 목록 끝
            if new_on_page == 0:
                break

    logger.info(f"[kdi_discovery] total 산업통상부 수출입 동향 자료: {len(entries)}")
    return entries


def _parse_list_html(html: str) -> list[KDIEntry]:
    """HTML → 필터 통과 자료만 KDIEntry 리스트."""
    result: list[KDIEntry] = []
    for m in _LIST_ITEM_RE.finditer(html):
        num_s = m.group("num")
        title = m.group("title").strip()
        org = m.group("org").strip()
        date_s = m.group("date")

        # 필터 1: 발행기관 = 산업통상부 (ICT · 정보통신산업 등 배제)
        if org != _ISSUING_ORG:
            continue
        # 필터 2: 제목 = "수출입 동향" 정확 매치
        if not _TITLE_RE.match(title):
            continue

        try:
            num = int(num_s)
            published = datetime.strptime(date_s, "%Y.%m.%d").date()
        except (ValueError, TypeError):
            logger.warning(
                f"[kdi_discovery] parse fail num={num_s} date={date_s} · skip"
            )
            continue

        report_month = f"{published.year:04d}-{published.month:02d}"
        result.append(
            KDIEntry(
                num=num,
                title=title,
                org=org,
                published=published,
                report_month=report_month,
            )
        )
    return result


# ─── 캐시 파일 I/O ───────────────────────────────────────────────


def load_cache(path: Path | None = None) -> dict[str, int]:
    """캐시 파일 → {report_month: num} dict. 파일 없으면 빈 dict."""
    p = path or DEFAULT_CACHE_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        return {e["report_month"]: int(e["num"]) for e in entries if "report_month" in e and "num" in e}
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(f"[kdi_cache] load fail {p}: {exc} · treat as empty")
        return {}


def save_cache(entries: list[KDIEntry], path: Path | None = None) -> Path:
    """KDIEntry 목록 → 캐시 파일 (원자적 쓰기)."""
    p = path or DEFAULT_CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": KDI_LIST_URL,
        "search_txt": KDI_SEARCH_TXT,
        "topic": KDI_TOPIC,
        "issuing_org": _ISSUING_ORG,
        "entries": [e.to_dict() for e in sorted(entries, key=lambda x: x.published, reverse=True)],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    logger.info(f"[kdi_cache] saved {len(entries)} entries → {p}")
    return p


async def refresh_kdi_cache(
    *,
    cache_path: Path | None = None,
    max_pages: int = 3,
) -> dict[str, int]:
    """KDI 크롤 + 캐시 파일 갱신 → {report_month: num}.

    실패 시 raise · 호출자가 기존 catalog 로 fallback.
    """
    entries = await fetch_kdi_export_index(max_pages=max_pages)
    if not entries:
        raise RuntimeError(
            "[kdi_discovery] 결과 0건 · KDI 검색 결과 파싱 실패 (사이트 구조 변경 가능)"
        )
    save_cache(entries, path=cache_path)
    return {e.report_month: e.num for e in entries}


def resolve_num_from_cache(
    report_month: date,
    *,
    cache_path: Path | None = None,
) -> Optional[int]:
    """캐시에서 발표월 → num 조회 (없으면 None)."""
    key = f"{report_month.year:04d}-{report_month.month:02d}"
    return load_cache(cache_path).get(key)
