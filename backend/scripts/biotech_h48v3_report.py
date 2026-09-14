"""WP48v2 정비 report v3 (WP51 정식) · 뉴스일 정렬 · 조용 후보 상단 · Reddit 오류 명확."""
from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def next_news_days(reasons_str: str, state_note: str = ""):
    today = datetime.now(timezone.utc).date()
    # A 상태: 자문위 회의 또는 CT.gov 완료 예정 (미래)
    for text in (state_note, reasons_str or ""):
        m = re.search(r"자문위 회의 D-(\d+)", text or "")
        if m:
            return -int(m.group(1))  # 음수 = 미래 D-일 (예정)
        m = re.search(r"완료 예정 D-(\d+)", text or "")
        if m:
            return -int(m.group(1))
    # B 상태: 결과 발표 · 발표 후 n일 (양수)
    m = re.search(r"발표 후 (\d+)일", state_note or "")
    if m:
        return int(m.group(1))
    m = re.search(r"결과 발표 D-day (\d{4}-\d{2}-\d{2})", reasons_str or "")
    if m:
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            return (today - d).days
        except Exception:
            pass
    return 9999


def main():
    require_secure_logging()
    DATA = Path("backend/data/biotech")
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for suffix in ("v3", "v2", ""):
        name = f"biotech_candidates_{suffix + '_' if suffix else ''}{today_str}.csv"
        cp = DATA / "candidates" / name
        if cp.exists():
            break
    cands = list(csv.DictReader(cp.open()))
    confirm = {r["ticker"]: r for r in csv.DictReader((DATA / "community_daily" / f"community_confirm_{today_str}.csv").open())}

    active = []
    quiet = []
    for c in cands:
        tk = c["ticker"]
        conf = confirm.get(tk, {})
        stage = conf.get("stage", "quiet")
        state = c.get("time_state_v50") or c.get("time_state", "C")
        days = next_news_days(c.get("reasons", ""), c.get("state_note_v50") or c.get("state_note", ""))
        c["_stage"] = stage
        c["_state"] = state
        c["_conf"] = conf
        c["_days"] = days
        if stage in ("quiet", "collecting"):
            quiet.append(c)
        else:
            active.append(c)

    # A 상태 우선 정렬 (예정일 가까운 순 · 음수 값 = 예정 · abs 작을수록 가까움)
    quiet.sort(key=lambda c: (0 if c["_state"] == "A" else 1, abs(c["_days"]) if c["_days"] < 9999 else 9999))
    active.sort(key=lambda c: (abs(c["_days"]) if c["_days"] < 9999 else 9999, -int(c["_conf"].get("st_24h") or 0)))

    out_dir = Path("docs/plans/biotech/rumor-daily")
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{today_dash}.md"

    from collections import Counter
    state_dist = Counter(c["_state"] for c in cands)

    lines = [
        f"# 소문 확인 일일 보고서 · {today_dash} v4 (WP51 (cron 정식화) · 후보 중심 · UTC)",
        "",
        "> 📖 [`GLOSSARY.md`](../GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "> ⚠️ **토론방 소문은 진위 미검증 · 참고용** · 매수 신호 아님 · 소액 실전 규칙 적용",
        "",
        f"- **후보 (레이더 v1.3 관찰 대상)**: {len(cands)}종목 · 시간 상태: A(뉴스 예정) {state_dist.get('A',0)} · B(뉴스 통과) {state_dist.get('B',0)} · C(해당없음) {state_dist.get('C',0)}",
        f"- **오늘 언급 있음 (StockTwits 24h 관측)**: {len(active)}종목 · **조용 (초기 자리 후보 · baseline 미확보 포함)**: {len(quiet)}종목",
        "",
        "## 표 1 · 소문에 살 자리 후보 (A (뉴스 예정) ∧ 조용/초기 (quiet/collecting) · 예정일 가까운 순)",
        "",
        "| # | 티커 | 회사 | 시총 | 예정일까지 | 근거 |",
        "|---|---|---|---|---|---|",
    ]
    a_quiet = [c for c in quiet if c["_state"] == "A"]
    if not a_quiet:
        lines.append("| — | (A 상태 후보 없음) | — | — | — | h1a mapped_ticker 부재 + CT.gov 스폰서 검색 실측 (WP50) 결과 |")
    for i, c in enumerate(a_quiet[:20], 1):
        d = abs(c["_days"])
        lines.append(f"| {i} | **{c['ticker']}** | {(c.get('name') or '')[:30]} | {c.get('mcap_bucket','')} | D-{d} | {(c.get('state_note_v50') or c.get('reasons') or '')[:70]} |")

    lines += ["", "## 표 2 · 뉴스 통과 종목 (팔 자리 · 관찰용)", "",
              "| # | 티커 | 회사 | 시총 | 발표 후 | 방향 |",
              "|---|---|---|---|---|---|"]
    b_all = [c for c in cands if c["_state"] == "B"]
    b_all.sort(key=lambda c: c["_days"] if c["_days"] < 9999 else 9999)
    for i, c in enumerate(b_all[:20], 1):
        note = c.get("state_note_v50") or c.get("state_note", "")
        m = re.search(r"dir=(\S+)", note)
        dir_v = m.group(1) if m else ""
        d = c["_days"] if c["_days"] < 9999 else 0
        lines.append(f"| {i} | **{c['ticker']}** | {(c.get('name') or '')[:30]} | {c.get('mcap_bucket','')} | D+{d} | {dir_v} |")

    lines += ["", "## 표 3 · 언급 있는 후보", "",
              "| # | 상태 | 티커 | 회사 | 시총 | 시간 | ST 24h | 단계 | 유형 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(active[:15], 1):
        conf = c["_conf"]
        state_icon = {"A": "🟢", "B": "🔴", "C": "⚪"}.get(c["_state"], "?")
        d = c["_days"]
        t_str = (f"D+{d}" if 0 < d < 9999 else (f"D-{abs(d)}" if d < 0 else "—"))
        lines.append(f"| {i} | {state_icon} | **{c['ticker']}** | {(c.get('name') or '')[:25]} | {c.get('mcap_bucket','')} | {t_str} | {conf.get('st_24h','0')} | {c['_stage']} | {conf.get('keywords','')} |")

    frenzy = [c for c in active if c["_conf"].get("stage") == "frenzy"]
    lines += ["", "## 급등 경보 (frenzy)", ""]
    if frenzy:
        for c in frenzy:
            lines.append(f"- **{c['ticker']}** · ST 24h {c['_conf'].get('st_24h')}")
    else:
        lines.append("- 없음")

    lines += [
        "",
        "## 하단 고정",
        "",
        "- 토론방 소문은 진위 미검증 · 소액 실전 규칙 적용",
        "- 하루 1회 후보 종목만 확인 (상시 순찰 없음)",
        "- Reddit 셀프서비스 API 종료 (2025-11) · RSS 만 사용",
        "",
        "---",
        "",
        f"- 후보 CSV: `{cp}`",
        f"- 확인 CSV: `backend/data/biotech/community_daily/community_confirm_{today_str}.csv`",
        f"- 생성 UTC: {datetime.now(timezone.utc).isoformat()}",
    ]
    md_path.write_text("\n".join(lines))
    print(f"REPORT saved: {md_path}")


if __name__ == "__main__":
    main()
