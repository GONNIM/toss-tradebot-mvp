"""1122-01 배포 전 순위 전후 표 (로컬 전용 · 운영 DB 에 접속하지 않는다).

입력 CSV 두 개 (머리글 줄 있음):
  --meta      krx_stock_meta 내보내기:           ticker,market_cap_krw,fetched_at
  --snapshot  powderkeg_krx_snapshot 내보내기:   ticker,snapshot_date,market_cap

계산:
  옛 시총 = meta 의 market_cap_krw (지금 운영 점수가 쓰는 값)
  새 시총 = 종목마다 가장 최근 snapshot_date 의 market_cap (갱신 뒤 값의 대용 · 없는 종목은 meta 로 채움)
  점수    = log10(시총) × export_ratio_hint  (analysis._score 그대로)
  품목 안 순위 = 점수 내림차순 (같으면 매핑 순서)  (analysis.persist_sector_leaders 와 같음)
  대표 품목 = 여러 품목에 든 종목의 가장 높은 순위 품목 (같으면 품목 이름 순)

실행 (저장소 루트에서):
  backend/venv/bin/python -m backend.scripts.sector_mcap_before_after --meta ~/meta-1122.csv --snapshot ~/snap-1122.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from backend.discovery.data_sources.mapping import iter_all_tickers
from backend.discovery.sector_leaders.analysis import _score


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) and x > 0 else None


def read_meta(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = _f(r.get("market_cap_krw"))
            if v is not None:
                out[r["ticker"].strip()] = v
    return out


def read_snapshot(path: Path) -> dict[str, float]:
    """종목마다 가장 최근 snapshot_date 의 시총."""
    best: dict[str, tuple[str, float]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            v = _f(r.get("market_cap"))
            if v is None:
                continue
            t, d = r["ticker"].strip(), (r.get("snapshot_date") or "").strip()
            if t not in best or d > best[t][0]:
                best[t] = (d, v)
    return {t: v for t, (_d, v) in best.items()}


def rank_items(mcap: dict[str, float]):
    """-> (items: {item: [(ticker, name, score)] 순위순}, rank: {(item,ticker): (순위, 점수)})"""
    by_item: dict[str, list[tuple[str, str, float]]] = {}
    for mt in iter_all_tickers():
        by_item.setdefault(mt.item, []).append((mt.code, mt.name, _score(mcap.get(mt.code), mt.export_ratio_hint)))
    rank: dict[tuple[str, str], tuple[int, float]] = {}
    for item, lst in by_item.items():
        lst.sort(key=lambda x: x[2], reverse=True)  # 안정 정렬
        for i, (code, _n, sc) in enumerate(lst, start=1):
            rank[(item, code)] = (i, sc)
    return by_item, rank


def representative(rank: dict[tuple[str, str], tuple[int, float]]) -> dict[str, str]:
    best: dict[str, tuple[int, str]] = {}
    for (item, code), (r, _s) in rank.items():
        cur = best.get(code)
        if cur is None or (r, item) < cur:
            best[code] = (r, item)
    return {c: it for c, (_r, it) in best.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", required=True, type=Path)
    ap.add_argument("--snapshot", required=True, type=Path)
    a = ap.parse_args(argv)

    old_cap = read_meta(a.meta)
    snap_cap = read_snapshot(a.snapshot)
    new_cap = {**old_cap, **snap_cap}  # 스냅샷이 있으면 스냅샷 · 없는 종목만 meta
    only_meta = sorted(set(old_cap) - set(snap_cap))
    print(f"옛 시총(meta) {len(old_cap)}종목 · 스냅샷 {len(snap_cap)}종목 · 스냅샷에 없어 meta 로 채움 {len(only_meta)}종목")

    old_items, old_rank = rank_items(old_cap)
    new_items, new_rank = rank_items(new_cap)

    print("\n품목\t종목코드\t종목명\t옛순위\t새순위\t옛점수\t새점수")
    for item in sorted(new_items):
        for code, name, _s in new_items[item]:
            o, n = old_rank[(item, code)], new_rank[(item, code)]
            mark = "" if o[0] == n[0] else "  <- 순위 변화"
            print(f"{item}\t{code}\t{name}\t{o[0]}\t{n[0]}\t{o[1]:.3f}\t{n[1]:.3f}{mark}")

    print("\n[상위 3 구성 변화]")
    changed = 0
    for item in sorted(new_items):
        o3 = [c for c, _n, _s in old_items[item][:3]]
        n3 = [c for c, _n, _s in new_items[item][:3]]
        if o3 != n3:
            changed += 1
            print(f"{item}: {','.join(o3)} -> {','.join(n3)}")
    if not changed:
        print("변화 없음")

    print("\n[대표 품목 변화]")
    o_rep, n_rep = representative(old_rank), representative(new_rank)
    names = {mt.code: mt.name for mt in iter_all_tickers()}
    rc = 0
    for code in sorted(n_rep):
        if o_rep.get(code) != n_rep[code]:
            rc += 1
            print(f"{code} {names.get(code, '')}: {o_rep.get(code)} -> {n_rep[code]}")
    if not rc:
        print("변화 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
