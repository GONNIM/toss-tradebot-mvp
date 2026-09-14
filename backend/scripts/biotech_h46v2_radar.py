"""WP46-2 · 레이더 점수 v1.1 정정 · 사전 커밋 (h_radar_params.json).

정정 요지:
- expert = 과학 채널만 (8-K 사용 금지) · z-score 정규화 (포화 방지)
- near = 예정일 함수 (A 상태 잔여일 · B 상태 = 0)
- 동일 가중 (각 0.25) + 꼬리표 +0.1 - 위험 -0.10
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import csv
import json
import logging
import math
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h46v2_radar")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def z_clip(vals: list[float]) -> list[float]:
    if not vals:
        return []
    m = mean(vals); s = pstdev(vals) or 1.0
    return [max(0.0, min(1.0, 0.5 + (v - m) / s / 4)) for v in vals]  # z/4 + 0.5 → [0,1] 근사


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    cands = list(csv.DictReader((DATA_DIR / "biotech" / "candidates" / f"biotech_candidates_v2_{today_str}.csv").open()))
    confirm = {r["ticker"]: r for r in csv.DictReader((DATA_DIR / "biotech" / "community_daily" / f"community_confirm_{today_str}.csv").open())}

    # H3 events (13D/13G count · expert 재료)
    ev_by_cik = defaultdict(int)
    p = DATA_DIR / f"h3_events_{sha}.csv"
    if p.exists():
        with p.open() as f:
            for r in csv.DictReader(f):
                ev_by_cik[(r.get("target_cik") or "").zfill(10)] += 1

    # H6 membership 소속 여부 (CT.gov 활동 근사)
    memb_tk = set()
    mp = DATA_DIR / f"h6_membership_{sha}.csv"
    if mp.exists():
        with mp.open() as f:
            for r in csv.DictReader(f):
                for t in (r.get("tiingo_matched_tickers") or "").split("|"):
                    if t.strip():
                        memb_tk.add(t.strip())

    # H39 negative readout count (risk)
    neg_by_cik = defaultdict(int)
    cp = DATA_DIR / "h39_readouts_checkpoint.json"
    if cp.exists():
        for e in json.loads(cp.read_text()).get("events", []):
            if e.get("direction") == "negative":
                neg_by_cik[(e.get("cik") or "").zfill(10)] += 1

    # expert 재료 raw · z-score
    raw_expert = []
    for c in cands:
        cik = (c.get("cik") or "").zfill(10)
        tk = c.get("ticker", "")
        raw = ev_by_cik.get(cik, 0) + (1 if tk in memb_tk else 0) * 3  # membership 가중 3
        raw_expert.append(raw)
    expert_norm = z_clip(raw_expert)

    scored = []
    for c, exp in zip(cands, expert_norm):
        tk = c.get("ticker", "")
        cik = (c.get("cik") or "").zfill(10)
        conf = confirm.get(tk, {})
        state = c.get("time_state", "C")

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
        if state == "A":
            note = c.get("state_note", "")
            # "자문위 회의 예정 D-N (..."
            import re
            m = re.search(r"D-(\d+)", note)
            days = int(m.group(1)) if m else 999
            if 90 <= days <= 180:
                near = 1.0
            elif 0 <= days < 90:
                near = 0.7
            elif 180 < days <= 365:
                near = 0.5
        elif state == "B":
            near = 0.0

        # crowd
        st_24h = _i(conf.get("st_24h"))
        bn = _i(conf.get("st_baseline_n"))
        if bn < 7:
            crowd = 0.5
        else:
            crowd = min(1.0, math.log10(max(1, st_24h)) / 2.0)

        # unnoticed
        mcap_b = c.get("mcap_bucket", "")
        unnoticed = {"50M-300M": 1.0, "300M-1B": 0.6, "1B-5B": 0.3}.get(mcap_b, 0.5)

        # risk
        risk = 0.0
        kws = conf.get("keywords", "")
        if "dilution" in kws:
            risk += 0.5
        neg_n = neg_by_cik.get(cik, 0)
        if neg_n > 0:
            risk += min(0.5, neg_n / 5.0)
        risk = min(1.0, risk)

        # 태그 보너스
        tag_bonus = 0.0
        sources = c.get("sources", "")
        if len(sources.split("|")) >= 2:
            tag_bonus = 0.1

        score = 0.25 * (exp + crowd + near + unnoticed) + tag_bonus - 0.10 * risk

        # 이유 1줄
        if state == "A":
            why = f"뉴스 예정 · {c.get('state_note', '')[:40]}"
        elif state == "B":
            why = f"뉴스 통과 · {c.get('state_note', '')[:40]}"
        elif exp >= 0.6:
            why = "전문가 채널 신호 강함"
        elif unnoticed >= 0.8:
            why = "작은 시총 · 미반영"
        else:
            why = "복합 관측"

        scored.append({
            "ticker": tk,
            "name": (c.get("name") or "")[:35],
            "mcap": mcap_b,
            "time_state": state,
            "score": round(score, 3),
            "expert": round(exp, 2),
            "crowd": round(crowd, 2),
            "near": round(near, 2),
            "unnoticed": round(unnoticed, 2),
            "risk": round(risk, 2),
            "tag_bonus": tag_bonus,
            "why_easy": why,
        })

    # A 상태 우선 정렬 · 그 다음 score 순
    state_order = {"A": 0, "B": 2, "C": 1}
    scored.sort(key=lambda x: (state_order.get(x["time_state"], 3), -x["score"]))
    top30 = scored[:30]

    out_dir = PROJECT_ROOT / "docs" / "plans" / "biotech" / "watchlist"
    out_dir.mkdir(parents=True, exist_ok=True)
    today_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md_path = out_dir / f"radar-v1.1-{today_str}.md"
    lines = [
        f"# 레이더 리스트 v1.1 (정정) · {today_dash} (WP46-2 · Fable 검수 반영)",
        "",
        "> ⚠️ **알파 미확정 · 소액 전향용 · 매수 신호 아님**",
        "",
        f"- 후보 우주: {len(cands)}종목 (WP49 정제 후 · 시간 상태 분리)",
        "- 사전 커밋 (h_radar_params.json v1.1): 동일 가중 · expert 과학 채널만 · 8-K 미사용",
        "- 정렬: A(뉴스 예정) 우선 → C → B(뉴스 통과)",
        "",
        "## 상위 30 (레이더 v1.1)",
        "",
        "| # | 상태 | 티커 | 회사 | 시총 | 점수 | 이유 | expert / crowd / near / unnoticed / risk |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(top30, 1):
        state_icon = {"A": "🟢 예정", "B": "🔴 통과", "C": "⚪ 없음"}.get(r["time_state"], "?")
        lines.append(f"| {i} | {state_icon} | **{r['ticker']}** | {r['name']} | {r['mcap']} | **{r['score']}** | {r['why_easy']} | {r['expert']}/{r['crowd']}/{r['near']}/{r['unnoticed']}/{r['risk']} |")

    lines += [
        "",
        "## 사전 커밋 (h_radar_params v1.1)",
        "",
        "- 가중치 = 동일 (각 0.25) · 60일 전 조정 금지",
        "- expert = 과학 채널 (13D + membership · 8-K 미사용) · z-score 정규화",
        "- near = 예정일 함수 (A 상태만 유효 · B 상태 = 0)",
        "- crowd = ST 24h + apewisdom (baseline < 7 = 0.5 중립)",
        "- unnoticed = 시총 작을수록 · risk = negative readout + dilution",
        "",
        "---",
        "",
        f"- CSV: `backend/data/biotech/candidates/radar_v1_1_{today_str}.csv`",
        f"- 생성 UTC: {datetime.now(timezone.utc).isoformat()}",
    ]
    md_path.write_text("\n".join(lines))

    csv_path = DATA_DIR / "biotech" / "candidates" / f"radar_v1_1_{today_str}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scored[0].keys()))
        w.writeheader()
        w.writerows(scored)

    state_dist = Counter(r["time_state"] for r in scored)
    top_state = Counter(r["time_state"] for r in top30)
    saturated = sum(1 for r in scored if r["expert"] >= 0.99)

    summary = {
        "git_sha": sha, "md": str(md_path), "csv": str(csv_path),
        "candidates": len(cands),
        "state_dist_all": dict(state_dist),
        "state_dist_top30": dict(top_state),
        "expert_saturated_ge_099": saturated,
    }
    LOG.info("summary=%s", json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
