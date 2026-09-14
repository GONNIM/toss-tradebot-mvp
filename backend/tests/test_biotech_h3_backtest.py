"""B97 · H3 백테스트 엔진 합성 데이터 pytest.

5개 테스트:
(a) 알파 심은 합성 → CI 하한 > 0 검출
(b) 무알파 랜덤워크 → CI 하한 ≤ 0 (비검출)
(c) 비용 차감 정확성 (net excess = raw excess - 1.0%)
(d) D+1 진입의 미래 참조 부재 (event_date 이전 데이터 미사용)
(e) 이벤트 적격 [D-30, D+180] 미충족 시 제외 카운트 정확
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from backend.scripts.biotech_h3_backtest import (
    HORIZONS, COST_BPS, BOOTSTRAP_ITER, ENTRY_OFFSET_DAYS,
    check_eligibility, compute_return, compute_bench_return,
    bootstrap_ci, run_backtest,
)


def _gen_price_series(start: str, days: int, start_price: float, daily_drift_pct: float, seed: int = 42, noise_std: float = 0.01) -> dict:
    """일별 종가 생성 · 주말 스킵 · noise_std=0 이면 drift 만."""
    rng = random.Random(seed)
    out = {}
    d = datetime.strptime(start, "%Y-%m-%d")
    price = start_price
    for _ in range(days):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out[d.strftime("%Y-%m-%d")] = round(price, 4)
        r = daily_drift_pct / 100 + (rng.gauss(0, noise_std) if noise_std > 0 else 0)
        price *= (1 + r)
        d += timedelta(days=1)
    return out


def test_a_alpha_planted_ci_positive():
    """(a) 알파 심은 합성 · CI 하한 > 0 검출."""
    # 30 이벤트 · 이벤트 후 +5% 알파 · 30일 창
    events = []
    prices_by_tkr = {}
    for i in range(30):
        tkr = f"ALPHA{i}"
        # 이벤트 전 안정 · 이벤트 후 +5% 즉시
        pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=100+i)
        post = _gen_price_series("2024-04-15", 60, 105.0, 0.0, seed=200+i)  # +5% jump
        prices_by_tkr[tkr] = {**pre, **post}
        events.append({"event_id": f"e{i}", "target_cik": f"C{i}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    # bench 은 편평
    bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=99)

    result = run_backtest(events, prices_by_tkr, bench, {}, {}, seed=42)
    s30 = result["summary"]["horizons"]["h_30d"]
    assert s30["n"] > 0, f"n={s30['n']}"
    # 5% 알파 - 1% 비용 = ~4% net excess · CI 하한 > 0 이어야
    assert s30["ci_iid_95_lo"] > 0, f"CI 하한 {s30['ci_iid_95_lo']} · 알파 심은 데이터에서 CI>0 실패"
    assert s30["mean_net_excess"] > 2.0, f"mean_net_excess {s30['mean_net_excess']} < 2%"


def test_b_no_alpha_random_walk_ci_not_positive():
    """(b) 무알파 랜덤워크 · CI 하한 ≤ 0 (비검출)."""
    events = []
    prices_by_tkr = {}
    for i in range(30):
        tkr = f"NOISE{i}"
        series = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=300+i)
        prices_by_tkr[tkr] = series
        events.append({"event_id": f"e{i}", "target_cik": f"D{i}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=99)
    result = run_backtest(events, prices_by_tkr, bench, {}, {}, seed=42)
    s30 = result["summary"]["horizons"]["h_30d"]
    # 비용 -1% 만큼 mean_ne 음수 예상 · CI 하한 확실히 ≤ 0
    assert s30["ci_iid_95_lo"] <= 0, f"CI 하한 {s30['ci_iid_95_lo']} · 무알파에서 CI>0 = 오검출"


def test_c_cost_subtraction():
    """(c) 비용 차감 정확성 · 알파 정확히 비용만큼 감소 (노이즈 제거)."""
    # 이벤트 후 +2% 심음 · 노이즈 0 · net excess = 2 - 0 - 1 = ~1%
    events = []; prices = {}
    for i in range(30):
        tkr = f"C{i}"
        pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=400+i, noise_std=0)
        post = _gen_price_series("2024-04-15", 60, 102.0, 0.0, seed=500+i, noise_std=0)
        prices[tkr] = {**pre, **post}
        events.append({"event_id": f"e{i}", "target_cik": f"E{i}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=99, noise_std=0)
    result = run_backtest(events, prices, bench, {}, {}, seed=42)
    s30 = result["summary"]["horizons"]["h_30d"]
    # 정확히 2% - 0% (bench) - 1% (cost) = 1% net excess
    assert 0.95 < s30["mean_net_excess"] < 1.05, f"mean_net_excess {s30['mean_net_excess']} · 정확 1% 예상"


def test_d_no_lookahead():
    """(d) D+1 진입 · event_date 이전 가격 미참조."""
    prices = _gen_price_series("2024-01-01", 200, 100.0, 0.0)
    entry_d, entry_p = None, None
    # compute_return 은 D+1 부터 참조 · event_date 자체는 진입가 아님
    ret, meta = compute_return(prices, "2024-04-10", 30)
    assert meta["entry_date"] is not None
    # entry_date > event_date 확인
    assert meta["entry_date"] > "2024-04-10", f"entry_date {meta['entry_date']} 가 event 이전"


def test_e_eligibility_exclusion_count():
    """(e) 이벤트 적격 미충족 시 excluded 카운트 증가."""
    events = []; prices = {}
    # 3 이벤트: 1 정상 · 2 부적격 (가격 없음 · 창 미충족)
    tkr1 = "GOOD"; tkr2 = "EMPTY"; tkr3 = "SHORT"
    prices[tkr1] = _gen_price_series("2024-01-01", 200, 100.0, 0.0)
    prices[tkr2] = {}  # 없음
    prices[tkr3] = _gen_price_series("2025-01-01", 10, 100.0, 0.0)  # 다른 시기 · [D-30,D+180] 미충족

    for tkr in [tkr1, tkr2, tkr3]:
        events.append({"event_id": f"e_{tkr}", "target_cik": f"CIK_{tkr}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0)
    result = run_backtest(events, prices, bench, {}, {}, seed=42)
    excluded = result["summary"]["excluded"]
    # tkr2 no_prices · tkr3 not_eligible
    assert excluded["no_prices"] == 1, f"no_prices={excluded['no_prices']} · 예상 1 (EMPTY)"
    assert excluded["not_eligible"] == 1, f"not_eligible={excluded['not_eligible']} · 예상 1 (SHORT · 2025년 가격)"
    assert result["summary"]["per_event_count"] == 1, f"per_event={result['summary']['per_event_count']} · GOOD 1건만"


def test_f_acquisition_shortened_window():
    """(f) B99 · 인수 60일 후 +40% 에서 시계열 종료 · 180d 통계 포함 · shortened=1 · net excess 양수."""
    events = []; prices = {}
    for i in range(20):
        tkr = f"ACQ{i}"
        # 이벤트 전 안정 · 이벤트 후 40% 점프 후 60일 만에 시계열 종료
        pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=800+i, noise_std=0)
        post = _gen_price_series("2024-04-15", 60, 140.0, 0.0, seed=900+i, noise_std=0)
        prices[tkr] = {**pre, **post}
        events.append({"event_id": f"e{i}", "target_cik": f"F{i}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    bench = _gen_price_series("2024-01-01", 500, 100.0, 0.0, seed=99, noise_std=0)
    result = run_backtest(events, prices, bench, {}, {}, seed=42)
    # 180d 창 · 시계열 60일에 끝났으므로 shortened 발생
    s180 = result["summary"]["horizons"]["h_180d"]
    assert s180["n"] == 20, f"180d n={s180['n']} · 모두 shortened 로 포함되어야"
    assert result["summary"]["shortened_counts"]["h_180d"] == 20, \
        f"shortened h_180d={result['summary']['shortened_counts']['h_180d']} · 20 예상"
    # 40% - bench 0% - 1% cost = ~39% net excess 양수
    assert s180["mean_net_excess"] > 30, f"180d mean_ne={s180['mean_net_excess']} · 양수 예상"


def test_h_date_cluster_bootstrap_works():
    """WP31 · date-cluster bootstrap = block_key 를 event_date 로 넘기면 동작.

    동일 event_date 이벤트 다건 → 통째 재추출 · 단일 event_date 만 있으면 CI 이론상 폭 확대.
    """
    values = [0.05, 0.03, 0.10, -0.02, 0.08, 0.06, 0.04, 0.07]
    # 동일 날짜 클러스터: 4일 (각 2건)
    dates = ["2024-01-15", "2024-01-15", "2024-02-20", "2024-02-20",
             "2024-03-10", "2024-03-10", "2024-04-05", "2024-04-05"]
    # iid vs date-cluster CI 폭 비교 (클러스터는 4 unique dates 재추출 → 다양성 감소 → 폭 확대)
    lo_iid, mid_iid, hi_iid = bootstrap_ci(values, iterations=2000, seed=42, block_key=None)
    lo_clu, mid_clu, hi_clu = bootstrap_ci(values, iterations=2000, seed=42, block_key=dates)
    # 유효 반환 (0.0 이 아닌 실제 값)
    assert isinstance(lo_iid, float) and isinstance(hi_iid, float)
    assert isinstance(lo_clu, float) and isinstance(hi_clu, float)
    # 클러스터 CI 는 iid 와 상이 (동일 재추출 규칙이 다르므로)
    assert (lo_iid, hi_iid) != (lo_clu, hi_clu)


def test_g_alpha_threshold_alignment():
    """(g) B100 · H3 커밋 임계 정합.
    +6%/40%/CI>0 → 30d alpha=True · +4%(임계 미달) → False.
    """
    # 시나리오 1: +6% 심음 · noise 없음 → mean ~5%~ · 임계 5% 통과
    # 시나리오 2: +4% 심음 · noise 없음 → mean ~3% · 임계 미달
    for planted, expected in [(6.0, True), (4.0, False)]:
        events = []; prices = {}
        for i in range(30):
            tkr = f"T{planted}_{i}"
            pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=1000+i, noise_std=0)
            post = _gen_price_series("2024-04-15", 60, 100.0 * (1 + planted/100), 0.0, seed=1100+i, noise_std=0)
            prices[tkr] = {**pre, **post}
            events.append({"event_id": f"e{i}", "target_cik": f"G{i}_{planted}", "ticker": tkr,
                           "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
        bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=99, noise_std=0)
        result = run_backtest(events, prices, bench, {}, {}, seed=42)
        alpha = result["summary"]["alpha_confirmed"]
        got = alpha.get("h_30d_alpha_confirmed", False)
        assert got == expected, \
            f"planted={planted}% expected alpha={expected} but got {got} · mean_ne={result['summary']['horizons']['h_30d']['mean_net_excess']}"


def test_i_wp64_extreme_value_isolation():
    """(i) WP64 · 극단값 격리 (net_excess > +300% or < -95%) 통계 제외 + 목록 출력."""
    events = []; prices = {}
    # 정상 20건 (+3% drift · 30d 창 · net excess 정상 범위)
    for i in range(20):
        tkr = f"NORM{i}"
        pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=2000+i, noise_std=0)
        post = _gen_price_series("2024-04-15", 60, 103.0, 0.0, seed=2100+i, noise_std=0)
        prices[tkr] = {**pre, **post}
        events.append({"event_id": f"n{i}", "target_cik": f"N{i}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    # 극단 1건: 이벤트 후 400% 급등 (400% > +300% 임계 → 격리)
    tkr_ext = "EXT400"
    pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=2200, noise_std=0)
    post = _gen_price_series("2024-04-15", 60, 500.0, 0.0, seed=2201, noise_std=0)  # 100 → 500 = +400%
    prices[tkr_ext] = {**pre, **post}
    events.append({"event_id": "e_ext", "target_cik": "EXT", "ticker": tkr_ext,
                   "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=99, noise_std=0)

    result = run_backtest(events, prices, bench, {}, {}, seed=42)
    # 격리 발생 확인
    extreme = result["summary"]["extreme_review"]
    assert extreme["count"] >= 1, f"extreme count={extreme['count']} · 400% 이벤트 최소 1건 격리 예상"
    # 격리 대상 티커 확인
    ext_tickers = {i["ticker"] for i in extreme["items"]}
    assert tkr_ext in ext_tickers, f"EXT400 격리 예상 · 실제 {ext_tickers}"
    # 통계는 격리 제외 (20건만 · 21건 아님)
    s30 = result["summary"]["horizons"]["h_30d"]
    assert s30["n"] == 20, f"h_30d n={s30['n']} · 격리 후 20 예상 (총 21 - 극단 1)"
    # extreme_count 필드 존재
    assert s30.get("extreme_count", 0) >= 1


def test_j_wp64_held_for_review_alpha_pass():
    """(j) WP64 · 격리 발생 시 alpha_pass_machine=held_for_review (True 출력 금지)."""
    events = []; prices = {}
    # 30 이벤트 · 이벤트 후 +6% 알파 심음 (평균 통과 조건) + 극단 1건 (+400%)
    for i in range(30):
        tkr = f"ALP{i}"
        pre = _gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=3000+i, noise_std=0)
        post = _gen_price_series("2024-04-15", 60, 106.0, 0.0, seed=3100+i, noise_std=0)
        prices[tkr] = {**pre, **post}
        events.append({"event_id": f"a{i}", "target_cik": f"A{i}", "ticker": tkr,
                       "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    # 극단 1건
    prices["EXTREME"] = {**_gen_price_series("2024-01-01", 100, 100.0, 0.0, seed=3200, noise_std=0),
                          **_gen_price_series("2024-04-15", 60, 600.0, 0.0, seed=3201, noise_std=0)}
    events.append({"event_id": "e_ext", "target_cik": "EX", "ticker": "EXTREME",
                   "event_type": "13D_new", "event_date": "2024-04-10", "accession": "", "institution": "T"})
    bench = _gen_price_series("2024-01-01", 200, 100.0, 0.0, seed=99, noise_std=0)

    result = run_backtest(events, prices, bench, {}, {}, seed=42)
    alpha = result["summary"]["alpha_confirmed"]
    # 격리 발생 시 alpha_pass_machine = 'held_for_review' (True 출력 금지)
    apm = alpha.get("h_30d_alpha_pass_machine")
    assert apm == "held_for_review", f"alpha_pass_machine={apm} · 격리 있으면 held_for_review 예상"
    # 기존 필드 alpha_confirmed 는 False 로 강제
    assert alpha.get("h_30d_alpha_confirmed") is False, "alpha_confirmed 는 격리 시 False 강제"
    assert "extreme_review_note" in alpha
