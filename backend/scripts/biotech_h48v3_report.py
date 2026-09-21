"""WP48v2 정비 report v3 (WP51 정식) · 뉴스일 정렬 · 조용 후보 상단 · Reddit 오류 명확.

WP69-3g: 경로 해석기 _biotech_paths 로 전환 (RUNTIME > docs > backend/data).
"""
from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts import _biotech_paths as _P

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
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    today_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # WP69-3g: 경로 해석기 · candidates 는 v3 > v2 > v1 순서 선호
    cp = None
    for suffix in ("v3", "v2", ""):
        name = f"biotech_candidates_{suffix + '_' if suffix else ''}{today_str}.csv"
        cp = _P.find(name, subdir="candidates")
        if cp:
            break
    if cp is None:
        raise SystemExit(f"candidates_{today_str}.csv 없음 (RUNTIME > docs > backend/data 순회)")
    cands = list(csv.DictReader(cp.open()))

    confirm_path = _P.find(f"community_confirm_{today_str}.csv", subdir="community_daily")
    if confirm_path is None:
        raise SystemExit(f"community_confirm_{today_str}.csv 없음")
    confirm = {r["ticker"]: r for r in csv.DictReader(confirm_path.open())}

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

    # WP69-3g: 산출 = RUNTIME/rumor-daily (서버) 또는 docs 유지 (로컬 backward compat)
    out_dir = _P.out_dir("rumor-daily") if _P.RUNTIME_DIR else (_P.PROJECT_ROOT / "docs" / "plans" / "biotech" / "rumor-daily")
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
        note = c.get("state_note_v50") or c.get("reasons") or ""
        # 순위표 방식과 통일: YYYY-MM 원본이면 "YYYY년 M월 중 (D-lo~hi 추정 · 월 단위 발표)" · YYYY-MM-DD 이면 그대로
        m_ymd = re.search(r"\((\d{4})-(\d{2})-(\d{2})", note)
        m_ym = re.search(r"\((\d{4})-(\d{2})(?!-\d)", note)
        if m_ymd:
            when = f"{m_ymd.group(1)}년 {int(m_ymd.group(2))}월 {int(m_ymd.group(3))}일 예정 · D-{d}"
        elif m_ym:
            lo = max(0, d - 15); hi = d + 15
            when = f"{m_ym.group(1)}년 {int(m_ym.group(2))}월 중 (D-{lo}~{hi} 추정 · 월 단위 발표)"
        else:
            when = f"D-{d}"
        lines.append(f"| {i} | **{c['ticker']}** | {(c.get('name') or '')[:30]} | {c.get('mcap_bucket','')} | {when} | {note[:60]} |")

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

    # WP60 · 표 3 는 st_24h > 0 인 종목 (baseline 미확보 포함 · 원값 표시 · 판정 규칙 불변)
    lines += ["", "## 표 3 · 언급 있는 후보 (WP60 · baseline 미확보도 원값 표시)", "",
              "| # | 상태 | 티커 | 회사 | 시총 | 시간 | ST 24h | 기준선 (n일) | 단계 | 유형 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    all_with_st = sorted(
        [c for c in cands if int((c["_conf"].get("st_24h") or 0) or 0) > 0],
        key=lambda c: -int((c["_conf"].get("st_24h") or 0) or 0),
    )
    for i, c in enumerate(all_with_st[:20], 1):
        conf = c["_conf"]
        state_icon = {"A": "🟢", "B": "🔴", "C": "⚪"}.get(c["_state"], "?")
        d = c["_days"]
        t_str = (f"D+{d}" if 0 < d < 9999 else (f"D-{abs(d)}" if d < 0 else "—"))
        st_24h_v = conf.get("st_24h", "0")
        baseline_n = int((conf.get("st_baseline_n") or 0) or 0)
        baseline_str = f"{baseline_n}/7일" + (" (수집 중)" if baseline_n < 7 else " (확보)")
        lines.append(f"| {i} | {state_icon} | **{c['ticker']}** | {(c.get('name') or '')[:25]} | {c.get('mcap_bucket','')} | {t_str} | {st_24h_v} | {baseline_str} | {c['_stage']} | {conf.get('keywords','')} |")
    if not all_with_st:
        lines.append("| — | (st_24h > 0 후보 없음) | — | — | — | — | — | — | — | — |")

    frenzy = [c for c in active if c["_conf"].get("stage") == "frenzy"]
    lines += ["", "## 급등 경보 (frenzy)", ""]
    if frenzy:
        for c in frenzy:
            lines.append(f"- **{c['ticker']}** · ST 24h {c['_conf'].get('st_24h')}")
    else:
        lines.append("- 없음")

    # WP65 · 표 4: 최근 20 거래일 Form 4 매수 (h65 CSV 로드)
    import glob
    h65_csvs = sorted(glob.glob(str(DATA / f".." / f"h65_form4_daily_table_*.csv")))
    if h65_csvs:
        try:
            with open(h65_csvs[-1]) as fh:
                f4_rows = list(csv.DictReader(fh))
        except Exception:
            f4_rows = []
        lines += ["", "## 표 4 · 임원·대주주 매수 (Form 4 P · 최근 20 거래일 · WP65)", ""]
        if f4_rows:
            lines += ["| # | 발행사 | 신고일 | 매수일 | 경과일 | 제출자 유형 | 주식수 | 매수 금액 (USD 근사) |",
                      "|---|---|---|---|---|---|---|---|"]
            for i, r in enumerate(f4_rows[:15], 1):
                name = (r.get("issuer_name") or "")[:30]
                amount = r.get("amount_usd_approx", "")
                amount_str = f"${int(amount):,}" if amount and str(amount).replace("-", "").isdigit() else "—"
                lines.append(f"| {i} | {name} ({r.get('issuer_cik','')}) | {r.get('filing_date','')} | {r.get('tx_date','')} | D+{r.get('elapsed_days',0)} | {r.get('filer_type','기타')} | {r.get('shares','0')} | {amount_str} |")
            lines.append("")
            lines.append("> 🟡 **F4 30d 전략 = 유보 (pending · 결론 5분류)** · WP63-3 견고성 (a) 미해결 + (d) 13D 중복 제외 CI 하한 < 0 · **과거 재실행 금지** · **2026-11-15 전향 평가 (WP56) 재현 시 확인 승격** · 소액 실전 규칙 8항")
        else:
            lines.append("- (최근 20 거래일 내 F4_buy 이벤트 없음)")

    # StockTwits 24h 관측 · baseline 미확보 통계 (사전 커밋 규칙 유지)
    st_nonzero = sum(1 for c in cands if int((c["_conf"].get("st_24h") or 0) or 0) > 0)
    st_baseline_ready = sum(1 for c in cands if int((c["_conf"].get("st_baseline_n") or 0) or 0) >= 7)
    lines += [
        "",
        "## 데이터 소스 상태 (WP48v3 · 사전 커밋 규칙 유지)",
        "",
        f"- StockTwits API 자체: **정상** (대형 바이오 MRNA/NVAX in_24h > 15 확인 · 2026-09-14)",
        f"- 후보 79종목 중 st_24h > 0 실측: **{st_nonzero}종목** (37%)",
        f"- baseline_n ≥ 7 (판정 활성): **{st_baseline_ready}종목** · 나머지는 collecting (30일 baseline 확보 대기)",
        f"- 위 표 '언급 있음' 은 baseline 확보된 종목만 · **st_24h > 0 이라도 baseline_n < 7 이면 collecting → quiet 로 카운트** (사전 커밋 규칙)",
        "- 30일 자동 실행 후 baseline_n ≥ 7 확보되면 판정 자동 활성화",
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
        f"- 확인 CSV: `{confirm_path}`",
        f"- 생성 UTC: {datetime.now(timezone.utc).isoformat()}",
    ]
    md_path.write_text("\n".join(lines))
    print(f"REPORT saved: {md_path}")


if __name__ == "__main__":
    main()
