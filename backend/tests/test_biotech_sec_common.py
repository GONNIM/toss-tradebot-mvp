"""B106 · SEC 세션 공통 유틸 fixture pytest.

목표: SEC 200 확인 후 세션이 수신·저장만으로 완료되도록 로직 사전 검증.
- B106-1: B98 이벤트 추출기 (신규 13D/G · /A 제외 · subject 매핑)
- B106-2: B95 라벨 분류기 (Item 1.03 · DEFM14A/SC 14D9 · 그 외)
- B106-3: companyfacts 최근접 분기 shares
- B106-4: 체크포인트 이어받기 + 403 즉시 중단
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.scripts.biotech_sec_common import (
    Checkpoint,
    SecBlockedError,
    event_type_for,
    label_from_filings,
    nearest_shares_outstanding,
    sec_get,
    zip_recent,
)
from backend.scripts.biotech_sec_probe import check_interval


# ─ B106-1 · B98 이벤트 추출기 ────────────────────────────────────

def _fixture_submissions_2instituion() -> dict:
    """합성 fund submissions · SC 13D · SC 13D/A · SC 13G · SC 13G/A · Form 4 혼합."""
    return {
        "cik": "1000001",
        "name": "SYNTH ACTIVIST FUND ONE",
        "filings": {
            "recent": {
                "form":            ["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "4",       "SC 13D", "SC 13G", "8-K"],
                "filingDate":      ["2024-01-15", "2024-02-01", "2024-03-10", "2024-04-01", "2024-05-01", "2024-06-01", "2024-07-01", "2024-08-01"],
                "accessionNumber": ["0001-24-000001", "0001-24-000002", "0001-24-000003", "0001-24-000004", "0001-24-000005", "0001-24-000006", "0001-24-000007", "0001-24-000008"],
            },
            "files": [],
        },
    }


def test_b98_extract_new_13d_13g_only_amendments_excluded():
    """신규 13D · 신규 13G 만 이벤트 · /A 및 다른 form 은 이벤트 아님."""
    subs = _fixture_submissions_2instituion()
    recent = subs["filings"]["recent"]

    rows = zip_recent(recent)
    events = []
    for r in rows:
        et = event_type_for(r["form"])
        if et is None:
            continue
        events.append({"event_type": et, "form": r["form"], "date": r["date"], "acc": r["accession"]})

    assert len(events) == 4, f"이벤트 {len(events)}건 · 예상 4 (신규 13D 2 + 신규 13G 2)"
    types = [e["event_type"] for e in events]
    assert types.count("13D_new") == 2, f"13D_new {types.count('13D_new')} · 예상 2"
    assert types.count("13G_new") == 2, f"13G_new {types.count('13G_new')} · 예상 2"
    # /A 배제
    assert not any(e["form"].endswith("/A") for e in events), "amendment 배제 실패"
    # Form 4 · 8-K 배제
    assert not any(e["form"] in ("4", "8-K") for e in events)


def test_b98_subject_mapping_via_hit_ciks():
    """EFTS hit._source.ciks 관례: 첫 CIK = fund · 이후 = subject.

    fund CIK 세트에 없는 ciks 를 target 으로 채택.
    """
    fund_ciks = {"1000001", "1000099"}
    hits = [
        {"_source": {"ciks": ["1000001", "2000001"], "accession_no": "0001-24-000001"}},  # target 2000001
        {"_source": {"ciks": ["1000099", "2000002"], "accession_no": "0001-24-000006"}},  # target 2000002
        {"_source": {"ciks": ["1000001"], "accession_no": "0001-24-000005"}},  # subject 없음
    ]
    targets = []
    for h in hits:
        ciks = h["_source"]["ciks"]
        for c in ciks:
            if c not in fund_ciks:
                targets.append({"acc": h["_source"]["accession_no"], "target_cik": c})
    assert len(targets) == 2, f"target {len(targets)} · 예상 2"
    assert {t["target_cik"] for t in targets} == {"2000001", "2000002"}


# ─ B106-2 · B95 라벨 분류기 ─────────────────────────────────────

def test_b95_bankrupt_item_1_03():
    filings = [
        {"form": "8-K", "date": "2024-05-01", "item_codes": ["1.03"]},
        {"form": "10-K", "date": "2023-12-31", "item_codes": []},
    ]
    assert label_from_filings(filings) == "BANKRUPT"


def test_b95_acquired_defm14a():
    filings = [
        {"form": "DEFM14A", "date": "2024-06-01", "item_codes": []},
    ]
    assert label_from_filings(filings) == "ACQUIRED"


def test_b95_acquired_sc14d9():
    filings = [
        {"form": "SC 14D9", "date": "2024-07-01", "item_codes": []},
    ]
    assert label_from_filings(filings) == "ACQUIRED"


def test_b95_acquired_8k_item_2_01():
    """B107: form25_date 제공 · 120d 이내 → ACQUIRED."""
    filings = [
        {"form": "8-K", "date": "2024-08-01", "item_codes": ["2.01"]},
    ]
    assert label_from_filings(filings, form25_date="2024-09-15") == "ACQUIRED"


def test_b107_item_2_01_outside_120d_other_delisted():
    """B107: filing_date 이 form25_date 대비 3년 전 · Item 2.01 단독 증거 → OTHER_DELISTED (매수측 자산 인수 오분류 차단)."""
    filings = [
        {"form": "8-K", "date": "2020-05-01", "item_codes": ["2.01"]},
    ]
    assert label_from_filings(filings, form25_date="2023-08-01") == "OTHER_DELISTED"


def test_b107_item_2_01_no_form25_fail_closed():
    """B107 fail-closed: form25_date 부재 시 Item 2.01 단독 증거 불인정."""
    filings = [
        {"form": "8-K", "date": "2024-08-01", "item_codes": ["2.01"]},
    ]
    assert label_from_filings(filings) == "OTHER_DELISTED"


def test_b107_defm14a_unaffected_by_gate():
    """B107 게이트는 DEFM14A/SC 14D9 · Item 1.03 규칙에 영향 없음."""
    # DEFM14A 는 form25_date 없어도 ACQUIRED
    assert label_from_filings([{"form": "DEFM14A", "date": "2020-01-01", "item_codes": []}]) == "ACQUIRED"
    # SC 14D9 도 동일
    assert label_from_filings([{"form": "SC 14D9", "date": "2020-01-01", "item_codes": []}]) == "ACQUIRED"
    # Item 1.03 · form25_date 없어도 BANKRUPT
    assert label_from_filings([{"form": "8-K", "date": "2020-01-01", "item_codes": ["1.03"]}]) == "BANKRUPT"


def test_b95_other_delisted_form25_only():
    filings = [
        {"form": "25-NSE", "date": "2024-09-01", "item_codes": []},
        {"form": "10-Q", "date": "2024-03-01", "item_codes": []},
    ]
    assert label_from_filings(filings) == "OTHER_DELISTED"


def test_b95_bankrupt_takes_priority_over_acquired():
    """다중 매치 시 BANKRUPT > ACQUIRED 우선."""
    filings = [
        {"form": "8-K", "date": "2024-01-01", "item_codes": ["1.03"]},
        {"form": "DEFM14A", "date": "2024-02-01", "item_codes": []},
    ]
    assert label_from_filings(filings) == "BANKRUPT"


def test_b95_zip_recent_items_parsing():
    """items 배열이 'Item 1.03,2.01' 형태여도 파싱."""
    recent = {
        "form": ["8-K", "10-K"],
        "filingDate": ["2024-05-01", "2023-12-31"],
        "accessionNumber": ["A1", "A2"],
        "items": ["Item 1.03,2.01", ""],
    }
    rows = zip_recent(recent, wanted_forms={"8-K", "10-K"})
    assert len(rows) == 2
    assert rows[0]["item_codes"] == ["1.03", "2.01"]
    assert rows[1]["item_codes"] == []
    assert label_from_filings(rows) == "BANKRUPT"


# ─ B106-3 · companyfacts 최근접 분기 ────────────────────────────

def _fixture_companyfacts_quarterly() -> dict:
    """dei:EntityCommonStockSharesOutstanding · 4분기 · past-preferred 검증용."""
    return {
        "cik": 2000001,
        "entityName": "SYNTH BIOTECH",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2023-03-31", "val": 10_000_000, "accn": "acc-q1-23", "fy": 2023, "fp": "Q1"},
                            {"end": "2023-06-30", "val": 12_000_000, "accn": "acc-q2-23", "fy": 2023, "fp": "Q2"},
                            {"end": "2023-09-30", "val": 15_000_000, "accn": "acc-q3-23", "fy": 2023, "fp": "Q3"},
                            {"end": "2023-12-31", "val": 20_000_000, "accn": "acc-q4-23", "fy": 2023, "fp": "FY"},
                        ]
                    }
                }
            }
        },
    }


def test_b106_3_past_preferred_no_lookahead():
    """이벤트일 이하 최근접 (미래 참조 배제)."""
    facts = _fixture_companyfacts_quarterly()
    r = nearest_shares_outstanding(facts, "2023-07-15")
    assert r is not None
    assert r["asof"] == "2023-06-30", f"asof {r['asof']} · 예상 2023-06-30 (past-preferred)"
    assert r["shares"] == 12_000_000


def test_b106_3_exact_match():
    facts = _fixture_companyfacts_quarterly()
    r = nearest_shares_outstanding(facts, "2023-09-30")
    assert r["asof"] == "2023-09-30"
    assert r["shares"] == 15_000_000


def test_b106_3_fallback_future_when_no_past():
    """이벤트일 < 첫 분기 → future fallback (표시)."""
    facts = _fixture_companyfacts_quarterly()
    r = nearest_shares_outstanding(facts, "2022-12-01")
    assert r is not None
    assert r["asof"] == "2023-03-31", f"asof {r['asof']} · 예상 2023-03-31 (future fallback)"


def test_b106_3_empty_facts_none():
    facts = {"facts": {}}
    assert nearest_shares_outstanding(facts, "2024-01-01") is None


def test_b106_3_us_gaap_taxonomy():
    """us-gaap:CommonStockSharesOutstanding 도 인식."""
    facts = {
        "facts": {
            "us-gaap": {
                "CommonStockSharesOutstanding": {
                    "units": {"shares": [{"end": "2024-03-31", "val": 50_000_000, "accn": "a1"}]}
                }
            }
        }
    }
    r = nearest_shares_outstanding(facts, "2024-06-01")
    assert r is not None
    assert r["shares"] == 50_000_000
    assert "us-gaap" in r["concept"]


# ─ B106-4 · 체크포인트 + 403 즉시 중단 ────────────────────────────

def test_b106_4_checkpoint_roundtrip(tmp_path):
    cp = Checkpoint.load_or_new(tmp_path / "cp.json", task="B98")
    cp.mark("id1", bucket="ok")
    cp.mark("id2", bucket="ok")
    cp.mark("id3", bucket="fail")
    cp.save()

    cp2 = Checkpoint.load_or_new(tmp_path / "cp.json", task="B98")
    assert cp2.has("id1")
    assert cp2.has("id2")
    assert cp2.has("id3")
    assert not cp2.has("id4")
    assert cp2.counts == {"ok": 2, "fail": 1}


def test_b106_4_checkpoint_task_mismatch_returns_new(tmp_path):
    """task 이름이 다르면 새 체크포인트 (교차 오염 방지)."""
    cp = Checkpoint.load_or_new(tmp_path / "cp.json", task="B98")
    cp.mark("id1")
    cp.save()

    cp2 = Checkpoint.load_or_new(tmp_path / "cp.json", task="B95")
    assert not cp2.has("id1"), "task 다르면 loader 는 신규 반환"
    assert cp2.processed_ids == []


def test_b106_4_sec_get_403_raises_immediately():
    """403 응답에서 SecBlockedError 즉시 raise · 재시도·UA 순환 금지 원칙."""
    class _FakeClient:
        def get(self, url, params=None, timeout=None):
            r = httpx.Response(
                status_code=403,
                content=b"<html>SEC.gov | Your Request Originates from an Undeclared Automated Tool ...</html>",
                request=httpx.Request("GET", url),
            )
            return r
    with pytest.raises(SecBlockedError, match="403"):
        sec_get(_FakeClient(), "https://data.sec.gov/submissions/CIK0001392402.json")


def test_b106_4_sec_get_200_returns_json():
    class _FakeClient:
        def get(self, url, params=None, timeout=None):
            return httpx.Response(
                status_code=200,
                json={"cik": "1000001", "name": "OK"},
                request=httpx.Request("GET", url),
            )
    r = sec_get(_FakeClient(), "https://data.sec.gov/submissions/CIK0001000001.json")
    assert r["status"] == 200
    assert r["json"]["name"] == "OK"


def test_b106_4_sec_get_5xx_returns_non_json():
    class _FakeClient:
        def get(self, url, params=None, timeout=None):
            return httpx.Response(
                status_code=503,
                content=b"service unavailable",
                request=httpx.Request("GET", url),
            )
    r = sec_get(_FakeClient(), "https://data.sec.gov/x")
    assert r["status"] == 503
    assert r["json"] is None
    assert "service" in r["text_sig"]


# ─ B104 · 탐침 간격 가드 (단위 테스트 · 네트워크 없음) ──────────

def test_b104_probe_interval_first_call_allowed():
    ok, elapsed = check_interval([])
    assert ok is True
    assert elapsed == float("inf")


def test_b104_probe_interval_under_2h_blocked():
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    ok, elapsed = check_interval([{"utc": ts, "status": "BLOCKED_403"}])
    assert ok is False, "30분 경과 · 2h 미만 · 스킵 예상"
    assert elapsed < 2 * 3600


def test_b104_probe_interval_over_2h_allowed():
    from datetime import datetime, timezone, timedelta
    ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    ok, elapsed = check_interval([{"utc": ts, "status": "BLOCKED_403"}])
    assert ok is True, "3h 경과 · 2h 이상 · 허용 예상"
    assert elapsed >= 2 * 3600


def test_b104_probe_interval_skipped_entries_ignored():
    """SKIPPED_INTERVAL 항목은 실 요청 아님 · 2h 리셋 방지."""
    from datetime import datetime, timezone, timedelta
    real_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    skip_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    log = [
        {"utc": real_ts, "status": "BLOCKED_403"},
        {"utc": skip_ts, "status": "SKIPPED_INTERVAL"},
    ]
    ok, elapsed = check_interval(log)
    assert ok is True, "실 요청은 3h 전 · SKIPPED 5분 전은 무시 · 허용"
    assert elapsed >= 2 * 3600, f"elapsed {elapsed} · 실 요청 기준 3h ≈ 10800s 예상"
