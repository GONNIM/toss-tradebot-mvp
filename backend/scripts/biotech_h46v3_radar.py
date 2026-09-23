"""WP46-3 · 레이더 v1.2 (h_radar_params v1.2 · Fable 지적 반영).

정정:
- expert = 회사별 실측 (h39 readout events count + 13D count + h6 membership) · z-score 정규화 · 순위 기반
- near = A 상태 잔여일 함수
- crowd = WP48v3 24h (baseline<7=0.5)
- unnoticed = 최근 90일 종목 수익률 − XBI 90일 수익률 (낮을수록 가점 · 순위 정규화 · 시총 대체 금지)
- risk = negative readout + dilution 키워드 (companyfacts 런웨이는 후속)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging
from backend.scripts import _biotech_paths as _P

import csv
import json
import logging
import math
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, pstdev

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h46v3_radar")


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def z_clip01(vals: list[float]) -> list[float]:
    if not vals:
        return []
    m = mean(vals); s = pstdev(vals) or 1.0
    return [max(0.0, min(1.0, 0.5 + (v - m) / s / 4)) for v in vals]


def load_returns_90d(sha: str) -> dict[str, float]:
    """티커별 최근 90일 수익률 (h3_prices_merged 재사용).

    WP69-3g: h3_prices_merged (47MB) 커밋 제외 · 서버 부재 시 빈 dict 반환.
    """
    p = _P.find(f"h3_prices_merged_{sha}.csv") or _P.find_glob("h3_prices_merged_*.csv")
    if p is None or not p.exists():
        return {}
    latest = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            try:
                c = float(r["close"])
            except Exception:
                continue
            tk = r["ticker"]
            d = r["date"]
            latest.setdefault(tk, {})[d] = c
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=90)
    out = {}
    for tk, dp in latest.items():
        keys = sorted(dp.keys())
        recent = [k for k in keys if k >= cutoff.strftime("%Y-%m-%d")]
        if len(recent) < 2:
            continue
        try:
            r90 = dp[recent[-1]] / dp[recent[0]] - 1.0
            out[tk] = r90
        except Exception:
            continue
    return out


def load_xbi_90d(sha: str) -> float:
    p = _P.find(f"benchmarks_{sha}.csv") or _P.find_glob("benchmarks_*.csv")
    if p is None or not p.exists():
        return 0.0
    xbi = {}
    with p.open() as f:
        for r in csv.DictReader(f):
            if r.get("ticker") == "XBI":
                try:
                    xbi[r["date"]] = float(r["close"])
                except Exception:
                    continue
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=90)
    recent = sorted(k for k in xbi if k >= cutoff.strftime("%Y-%m-%d"))
    if len(recent) < 2:
        return 0.0
    return xbi[recent[-1]] / xbi[recent[0]] - 1.0


def main():
    require_secure_logging()
    from backend.scripts._biotech_bootstrap import data_sha
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    # WP69-3g · h3_events_{sha}.csv 부재 시 anchor 파일에서 sha 추출
    if _P.find(f"h3_events_{sha}.csv") is None:
        fb = _P.data_sha_auto("h3_targets_v2_*.csv")
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb
    today_str = _P.today_kst_str("%Y%m%d")

    # WP69-3g hotfix · candidates v3 > v2 > v1 순 · _P 경로 해석기
    cp = None
    for suffix in ("v3", "v2", ""):
        name = f"biotech_candidates_{suffix + '_' if suffix else ''}{today_str}.csv"
        cp = _P.find(name, subdir="candidates")
        if cp:
            break
    if cp is None:
        raise SystemExit(f"biotech_candidates_{today_str}.csv 없음 (v3·v2·v1 모두)")
    cands = list(csv.DictReader(cp.open()))

    confirm_path = _P.find(f"community_confirm_{today_str}.csv", subdir="community_daily")
    if confirm_path is None:
        raise SystemExit(f"community_confirm_{today_str}.csv 없음")
    confirm = {r["ticker"]: r for r in csv.DictReader(confirm_path.open())}

    # expert 재료: 13D count · h6 membership · h39 readout count (30일)
    ev_by_cik = defaultdict(int)
    p = _P.find(f"h3_events_{sha}.csv") or _P.find_glob("h3_events_*.csv")
    if p is not None and p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                ev_by_cik[(r.get("target_cik") or "").zfill(10)] += 1
    memb_tk = set()
    mp = _P.find(f"h6_membership_{sha}.csv") or _P.find_glob("h6_membership_*.csv")
    if mp is not None and mp.exists():
        with mp.open() as f:
            for r in csv.DictReader(f):
                for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                    if t.strip():
                        memb_tk.add(t.strip())
    readout_by_cik = defaultdict(int)
    neg_by_cik = defaultdict(int)
    cp = _P.find("h39_readouts_checkpoint.json")
    if cp is not None and cp.exists():
        for e in json.loads(cp.read_text()).get("events", []):
            c = (e.get("cik") or "").zfill(10)
            readout_by_cik[c] += 1
            if e.get("direction") == "negative":
                neg_by_cik[c] += 1

    # returns
    ret_map = load_returns_90d(sha)
    xbi_90 = load_xbi_90d(sha)
    LOG.info("prices tickers: %d · xbi 90d ret: %.4f", len(ret_map), xbi_90)

    # Phase C 1 · PubMed / Preprint 인덱스 (있으면 반영 · 없으면 중립)
    pub_idx_path = _P.find(f"h57_pubmed_index_{sha}.json") or _P.find_glob("h57_pubmed_index_*.json")
    pub_idx = json.loads(pub_idx_path.read_text()) if pub_idx_path is not None and pub_idx_path.exists() else {}
    pre_idx_path = _P.find(f"h58_preprint_index_{sha}.json") or _P.find_glob("h58_preprint_index_*.json")
    pre_idx = json.loads(pre_idx_path.read_text()) if pre_idx_path is not None and pre_idx_path.exists() else {}
    LOG.info("pub_idx: %d · pre_idx: %d", len(pub_idx), len(pre_idx))

    # v1.4 · expert 채널 5/5 (Phase C 1 · 채널 확장 · 가중치 동일)
    # 채널: 13D 신규 + h6 membership + PubMed 게재 yoY + Preprint yoY + F4_P (별도 파일 부재 시 0)
    raw_exp = []
    for c in cands:
        cik = (c.get("cik") or "").zfill(10)
        tk = c.get("ticker", "")
        # 채널 1+2 (기존 v1.3)
        raw = ev_by_cik.get(cik, 0) * 1.0 + (3 if tk in memb_tk else 0)
        # 채널 4 · PubMed 게재 yoY (2026 > 2025 이면 +2)
        pub_entry = pub_idx.get(cik)
        if pub_entry:
            y26 = pub_entry.get("counts", {}).get("y2026", 0) or 0
            y25 = pub_entry.get("counts", {}).get("y2025", 0) or 0
            if y26 > y25 and y26 >= 1:
                raw += 2
        # 채널 5 · Preprint yoY
        pre_entry = pre_idx.get(cik)
        if pre_entry:
            y26p = pre_entry.get("counts", {}).get("y2026", 0) or 0
            y25p = pre_entry.get("counts", {}).get("y2025", 0) or 0
            if y26p > y25p and y26p >= 1:
                raw += 2
        raw_exp.append(raw)
    exp_norm = z_clip01(raw_exp)

    # unnoticed raw = (종목 - XBI) 낮을수록 가점 → 반전 정규화
    raw_un = []
    for c in cands:
        tk = c.get("ticker", "")
        r_stock = ret_map.get(tk, xbi_90)  # 없으면 중립
        raw_un.append(-(r_stock - xbi_90))  # 낮을수록 큰 값
    un_norm = z_clip01(raw_un)

    scored = []
    for c, exp, un in zip(cands, exp_norm, un_norm):
        tk = c.get("ticker", "")
        cik = (c.get("cik") or "").zfill(10)
        conf = confirm.get(tk, {})
        state = c.get("time_state_v50") or c.get("time_state", "C")

        def _f(v, d=0.0):
            try:
                return float(v or 0)
            except Exception:
                return d
        def _i(v, d=0):
            try:
                return int(v or 0)
            except Exception:
                return d

        # near
        near = 0.1
        note = c.get("state_note_v50") or ""
        pretty_when = ""  # 사용자 친화 표기 (예정일 원본이 YYYY-MM 이면 월 단위 · YYYY-MM-DD 이면 일 단위)
        if state == "A":
            m = re.search(r"D-(\d+)", note)
            days = int(m.group(1)) if m else 999
            if 90 <= days <= 180:
                near = 1.0
            elif 0 <= days < 90:
                near = 0.7
            elif 180 < days <= 365:
                near = 0.5
            m_ym = re.search(r"\((\d{4})-(\d{2})(?!-\d)", note)
            m_ymd = re.search(r"\((\d{4})-(\d{2})-(\d{2})", note)
            if m_ymd:
                pretty_when = f"{m_ymd.group(1)}년 {int(m_ymd.group(2))}월 {int(m_ymd.group(3))}일 예정 · D-{days}"
            elif m_ym:
                lo = max(0, days - 15); hi = days + 15
                pretty_when = f"{m_ym.group(1)}년 {int(m_ym.group(2))}월 중 (D-{lo}~{hi} 추정 · 월 단위 발표)"
            else:
                pretty_when = f"D-{days}"
        elif state == "B":
            near = 0.0
            pretty_when = "발표 통과"

        # crowd
        st_24h = _i(conf.get("st_24h"))
        bn = _i(conf.get("st_baseline_n"))
        if bn < 7:
            crowd = 0.5
        else:
            crowd = min(1.0, math.log10(max(1, st_24h)) / 2.0)

        # risk
        risk = 0.0
        kws = conf.get("keywords", "")
        if "dilution" in kws:
            risk += 0.5
        neg_n = neg_by_cik.get(cik, 0)
        if neg_n > 0:
            risk += min(0.5, neg_n / 5.0)
        risk = min(1.0, risk)

        tag_bonus = 0.0
        sources = c.get("sources", "")
        if len(sources.split("|")) >= 2:
            tag_bonus = 0.1

        score = 0.25 * (exp + crowd + near + un) + tag_bonus - 0.10 * risk

        # 이유 (예정일·근거 포함)
        if state == "A":
            why = f"뉴스 예정 · {pretty_when}"
        elif state == "B":
            why = f"뉴스 통과 · {pretty_when}"
        elif exp >= 0.6:
            why = "전문가 채널 신호 강함 (13D · membership · 8-K 미사용)"
        elif un >= 0.7:
            why = "최근 90일 XBI 대비 저조 · 미반영"
        else:
            why = "복합 관측"

        scored.append({
            "ticker": tk, "name": (c.get("name") or "")[:35],
            "mcap": c.get("mcap_bucket", ""), "time_state": state,
            "score": round(score, 3),
            "expert": round(exp, 2), "crowd": round(crowd, 2),
            "near": round(near, 2), "unnoticed": round(un, 2),
            "risk": round(risk, 2), "tag_bonus": tag_bonus,
            "why_easy": why,
        })

    state_order = {"A": 0, "B": 2, "C": 1}
    scored.sort(key=lambda x: (state_order.get(x["time_state"], 3), -x["score"]))
    top30 = scored[:30]

    # WP69-3g: 산출 = RUNTIME/watchlist (서버) 또는 docs/watchlist (로컬)
    out_dir = _P.out_dir("watchlist") if _P.RUNTIME_DIR else (_P.PROJECT_ROOT / "docs" / "plans" / "biotech" / "watchlist")
    out_dir.mkdir(parents=True, exist_ok=True)
    today_dash = _P.today_kst_str("%Y-%m-%d")
    md_path = out_dir / f"radar-v1.3-{today_str}.md"
    lines = [
        f"# 레이더 리스트 v1.4 · {today_dash} (Phase C 1 · expert 채널 5/5 완비 · 가중치 동일)",
        "",
        "> 📖 [`GLOSSARY.md`](GLOSSARY.md) · 코드 · 상태 · 가설 뜻",
        "",
        "> ⚠️ **알파 (초과 수익) 미확정 · 소액 전향용 · 매수 신호 아님**",
        "",
        f"- 후보 우주 (관찰 종목 모음): {len(cands)}종목 (WP49 (뉴스 예정/통과/없음 상태 분리) 정제 후)",
        f"- **v1.4 (Phase C 1)**: expert (전문가 채널 점수) = 13D + h6 membership + **PubMed 게재 yoY (h57)** + **Preprint yoY (h58)** · **채널 5/5 완비 · 가중치 동일** · 8-K (보도자료) 미사용",
        f"- PubMed 인덱스 커버: {len(pub_idx)} CIK · Preprint 인덱스 커버: {len(pre_idx)} CIK",
        "- **v1.3 유지 (WP46-5)**: A 상태 (뉴스 예정) 예정일 월 단위 → 'YYYY년 M월 중 (D-lo~hi 추정)' 형식",
        "- 동일 가중 (0.25×4) · 태그 +0.1 · 위험 -0.10 · 60일 전 조정 금지",
        "",
        "## 상위 30",
        "",
        "| # | 상태 | 티커 | 회사 | 시총 | 점수 | 이유 (예정일 원본 포함) | expert / crowd / near / unnoticed / risk |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top30, 1):
        icon = {"A": "🟢 예정", "B": "🔴 통과", "C": "⚪"}.get(r["time_state"], "?")
        lines.append(f"| {i} | {icon} | **{r['ticker']}** | {r['name']} | {r['mcap']} | **{r['score']}** | {r['why_easy']} | {r['expert']}/{r['crowd']}/{r['near']}/{r['unnoticed']}/{r['risk']} |")

    lines += [
        "",
        "## 사전 커밋 (h_radar_params v1.4 · Phase C 1 채널 완비)",
        "",
        "- **expert (전문가 채널) · 5/5**: (a) 13D (5% 지분 신고) count · (b) h6 membership (테마 소속) · (c) **PubMed 게재 yoY** (h57 · 2026 > 2025) · (d) **Preprint yoY** (h58 · PubMed [SB=preprint]) · (e) F4_P (Form 4 임원 매수 · 있으면) · z-score 정규화 · **8-K 미사용**",
        "- **near (뉴스 임박도)**: A 상태 (뉴스 예정) 잔여일 함수 · YYYY-MM 원본 → 'YYYY년 M월 중 (D-lo~hi 추정)'",
        "- **crowd (군중 관심도)**: WP48v3 (커뮤니티 확인기 v3) 24h · baseline (기준선) < 7 = 0.5 중립",
        "- **unnoticed (미반영도)**: 최근 90일 종목 수익률 − XBI (바이오 ETF) 90일 수익률 · 시총 대체 금지",
        "- **risk (위험 감점)**: negative readout + dilution 키워드",
        "- **채널 추가는 정의 확장 (가중치 변경 아님) · 60일 전 조정 금지 유지**",
        "",
        "---",
        "",
        f"- CSV: (candidates 폴더 안 radar_v1_3_{today_str}.csv)",
        f"- 생성 UTC: {datetime.now(timezone.utc).isoformat()}",
    ]
    md_path.write_text("\n".join(lines))

    # WP69-3g: candidates 산출 폴더에 radar CSV 저장
    csv_path = _P.out_dir("candidates") / f"radar_v1_3_{today_str}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scored[0].keys()))
        w.writeheader()
        w.writerows(scored)

    state_dist = Counter(r["time_state"] for r in scored)
    top_state = Counter(r["time_state"] for r in top30)
    saturated = sum(1 for r in scored if r["expert"] >= 0.99)

    summary = {"git_sha": sha, "md": str(md_path), "csv": str(csv_path),
               "candidates": len(cands),
               "state_dist_all": dict(state_dist),
               "state_dist_top30": dict(top_state),
               "expert_saturated_ge_099": saturated,
               "xbi_90d_return": round(xbi_90, 4)}
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
