"""WP46 · 레이더 점수 v1.1 · 리스트 v1 (탐색 트랙 · 알파 미확정).

5요소 (사전 커밋 · 각 0~1):
- 전문가 소문 (readout events count · CT.gov 소속 · WP39 direction=positive 가중)
- 대중 열기 (StockTwits 24h 정규화 · WP48v2 stage)
- 뉴스 근접 (CT.gov 완료 예정일 D-day 근접도 · 자문위 회의일)
- 미반영 (mcap 작을수록 · 50M~300M 최고)
- 위험 (WP39 direction=negative or dilution 키워드 → 감점)

점수 = 0.30 * expert + 0.20 * crowd + 0.25 * near_news + 0.15 * unnoticed - 0.10 * risk
"""
from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging  # noqa: F401

import csv
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path("backend/data")
sha = "add7af7"

today = datetime.now(timezone.utc).strftime("%Y%m%d")
candidates = list(csv.DictReader((DATA / "biotech" / "candidates" / f"biotech_candidates_{today}.csv").open()))
confirm_path = DATA / "biotech" / "community_daily" / f"community_confirm_{today}.csv"
confirm_map = {}
if confirm_path.exists():
    for r in csv.DictReader(confirm_path.open()):
        confirm_map[r["ticker"]] = r

# WP39 readout events (CIK 별 count · direction 분포)
readout_by_cik = {}
cp = DATA / "h39_readouts_checkpoint.json"
if cp.exists():
    for e in json.loads(cp.read_text()).get("events", []):
        c = e["cik"].zfill(10)
        d = readout_by_cik.setdefault(c, {"count": 0, "positive": 0, "negative": 0, "mixed": 0})
        d["count"] += 1
        dr = e.get("direction", "unclassified")
        if dr in d:
            d[dr] += 1

def score(cand):
    tk = cand.get("ticker", "")
    cik = (cand.get("cik", "") or "").zfill(10)
    conf = confirm_map.get(tk, {})
    def _i(v, default=0):
        try:
            return int(v or 0)
        except Exception:
            return default
    def _f(v, default=0.0):
        try:
            return float(v or 0)
        except Exception:
            return default

    # 전문가 소문 = readout count 정규화 (0~1)
    rd = readout_by_cik.get(cik, {})
    rd_count = rd.get("count", 0)
    rd_pos = rd.get("positive", 0)
    expert = min(1.0, rd_count / 20.0)
    expert += 0.1 * min(1.0, rd_pos / 5.0)
    expert = min(1.0, expert)

    # 대중 열기 = ST 24h 정규화 (log scale · 100 msgs = 1.0)
    st_24h = _i(conf.get("st_24h"), 0)
    import math
    crowd = min(1.0, math.log10(max(1, st_24h)) / 2.0)  # log10(100)=2 → 1.0

    # 뉴스 근접 = reasons 안에 D-day 있으면 D-day 계산 (근사)
    near = 0.0
    sources = cand.get("sources", "")
    if "d_adcom" in sources:
        near += 0.5
    if "a_readout" in sources:
        near += 0.3
    if "b_ctgov" in sources:
        near += 0.2
    near = min(1.0, near)

    # 미반영 = mcap 작을수록 · unknown 은 0.5
    mcap_b = cand.get("mcap_bucket", "")
    if mcap_b == "50M-300M":
        unnoticed = 1.0
    elif mcap_b == "300M-1B":
        unnoticed = 0.6
    elif mcap_b == "1B-5B":
        unnoticed = 0.3
    else:
        unnoticed = 0.5

    # 위험 = direction negative or dilution 키워드
    risk = 0.0
    kws = conf.get("keywords", "")
    if "dilution" in kws:
        risk += 0.5
    if "squeeze" in kws:
        risk += 0.3
    rd_neg = rd.get("negative", 0)
    if rd_neg > 0:
        risk += min(0.5, rd_neg / 5.0)
    risk = min(1.0, risk)

    total = 0.30 * expert + 0.20 * crowd + 0.25 * near + 0.15 * unnoticed - 0.10 * risk

    # 검증 꼬리표
    tags = []
    tags.append(f"소스 {len(sources.split('|'))}")
    if rd_count:
        tags.append(f"readout {rd_count}건")
    if st_24h > 0:
        tags.append(f"ST 24h {st_24h}")
    if kws:
        tags.append(f"kw {kws}")

    # 쉬운 말 이유
    if near >= 0.5:
        why_easy = "곧 뉴스 예정"
    elif expert >= 0.5:
        why_easy = "전문가 소문 강함"
    elif crowd >= 0.5:
        why_easy = "대중 열기 상승"
    elif unnoticed >= 0.8:
        why_easy = "작은 시총 · 미반영"
    else:
        why_easy = "복합 관측 대상"

    return {
        "ticker": tk,
        "name": cand.get("name", "")[:35],
        "mcap": cand.get("mcap_bucket", ""),
        "score": round(total, 3),
        "expert": round(expert, 2),
        "crowd": round(crowd, 2),
        "near": round(near, 2),
        "unnoticed": round(unnoticed, 2),
        "risk": round(risk, 2),
        "why_easy": why_easy,
        "tags": " · ".join(tags),
    }

scored = sorted([score(c) for c in candidates], key=lambda x: -x["score"])
top30 = scored[:30]

out_dir = Path("docs/plans/biotech/watchlist")
out_dir.mkdir(parents=True, exist_ok=True)
md_path = out_dir / f"radar-v1-{datetime.now(timezone.utc).strftime('%Y%m%d')}.md"
lines = [
    f"# 레이더 리스트 v1.1 · {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (WP46)",
    "",
    "> ⚠️ **알파 미확정 · 소액 전향용** · 매수 신호 아님",
    "",
    f"- 후보 우주: {len(candidates)}종목 (WP48v2 후보 선정)",
    "- 5요소: expert 0.30 · crowd 0.20 · near 0.25 · unnoticed 0.15 · risk -0.10",
    "",
    "## 상위 30 (레이더 점수순)",
    "",
    "| # | 티커 | 회사 | 시총 | 점수 | 이유 | expert / crowd / near / unnoticed / risk | 꼬리표 |",
    "|---|---|---|---|---|---|---|---|",
]
for i, r in enumerate(top30, 1):
    lines.append(f"| {i} | **{r['ticker']}** | {r['name']} | {r['mcap']} | **{r['score']}** | {r['why_easy']} | {r['expert']}/{r['crowd']}/{r['near']}/{r['unnoticed']}/{r['risk']} | {r['tags'][:60]} |")

lines += [
    "",
    "## 하단 고정",
    "",
    "- 레이더 점수 = 탐색 트랙 관측 지표 · 알파 확증 아님",
    "- 소액 전향용 (실 매수 신호 아님)",
    "- 매주 재산출 · CSV 로 전향 평가",
    "",
    "---",
    "",
    f"- 생성 UTC: {datetime.now(timezone.utc).isoformat()}",
]
md_path.write_text("\n".join(lines))

# CSV
csv_path = DATA / "biotech" / "candidates" / f"radar_v1_{today}.csv"
with csv_path.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(top30[0].keys()))
    w.writeheader()
    w.writerows(scored)

print(f"REPORT: {md_path}")
print(f"CSV: {csv_path}")
print(f"top 30 scored (total {len(scored)})")
print("\ntop 10:")
for r in top30[:10]:
    print(f"  {r['ticker']:6s} · {r['name']:30s} · score {r['score']:.3f} · {r['why_easy']}")
