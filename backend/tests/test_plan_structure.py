"""1116-01 · 구조 시험: 토스 호출 한 곳 · 모의 격리 · 비밀값 없음 · 정해진 시각 작업 규칙."""
from __future__ import annotations

import ast
import re
from datetime import datetime
from pathlib import Path

import pytest

from backend.tests.plan_fakes import plan_db  # noqa: F401

BACKEND = Path(__file__).resolve().parents[1]
PLAN_DIR = BACKEND / "execution" / "plan"

TOSS_ORDER_CALLS = ("create_conditional_order", "modify_conditional_order", "cancel_conditional_order",
                    "list_conditional_orders", "get_conditional_order", "create_order", "cancel_order",
                    "modify_order", "get_order", "list_orders", "get_toss_client", "TossClient")


def test_toss_order_apis_are_called_only_in_brokers_py():
    """6-1 은 브로커 한 곳에서만 거친다 · 그 밖에서 토스 조건주문 · 주문 API 를 직접 부르는 코드 0."""
    offenders = []
    files = [p for p in PLAN_DIR.glob("*.py") if p.name != "brokers.py"] + [BACKEND / "api" / "routes" / "plans.py"]
    for path in files:
        src = path.read_text(encoding="utf-8")
        for name in TOSS_ORDER_CALLS:
            if re.search(rf"\b{name}\b", src):
                offenders.append(f"{path.name}:{name}")
    assert not offenders, offenders


def test_raw_order_calls_are_inside_direction_gate_only():
    """raw.cond_create · cond_modify · limit_create 는 DirectionGate 클래스 안에서만 부른다."""
    tree = ast.parse((PLAN_DIR / "brokers.py").read_text(encoding="utf-8"))
    guarded = {"cond_create", "cond_modify", "limit_create"}
    found = {"in_gate": 0, "outside": []}

    class V(ast.NodeVisitor):
        def __init__(self):
            self.cls = None

        def visit_ClassDef(self, node):
            prev, self.cls = self.cls, node.name
            self.generic_visit(node)
            self.cls = prev

        def visit_Call(self, node):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in guarded and isinstance(f.value, ast.Attribute) and f.value.attr == "raw":
                if self.cls == "DirectionGate":
                    found["in_gate"] += 1
                else:
                    found["outside"].append((self.cls, f.attr, node.lineno))
            self.generic_visit(node)

    V().visit(tree)
    assert found["in_gate"] >= 6 and not found["outside"], found
    # 다른 모듈은 raw 를 직접 만지지 않는다
    for path in list(PLAN_DIR.glob("*.py")) + [BACKEND / "api" / "routes" / "plans.py"]:
        if path.name in ("brokers.py",):
            continue
        assert not re.search(r"\.raw\.(cond_|limit_)", path.read_text(encoding="utf-8")), path.name


def test_paper_raw_has_no_toss_client():
    src = (PLAN_DIR / "brokers.py").read_text(encoding="utf-8")
    paper = src[src.index("class PaperRaw"):src.index("# ─── 감시 방향 문")]
    assert "toss" not in paper.lower().replace("토스", "")


async def test_paper_flow_never_calls_any_toss_http(plan_db, monkeypatch):
    """모의 계획 전 과정에서 TossClient 의 어떤 요청 함수도 한 번도 불리지 않는다."""
    from backend.execution.brokers import toss_client as tc
    from backend.execution.plan import state
    from backend.execution.plan.brokers import DirectionGate, PaperRaw
    from backend.execution.plan.engine import PlanEngine
    from backend.services.db import get_session
    from backend.tests.plan_fakes import Clock, D

    boom = lambda *a, **k: pytest.fail("모의 계획이 토스를 불렀습니다")           # noqa: E731
    for name in ("get", "post", "request_envelope", "create_order", "create_conditional_order",
                 "modify_conditional_order", "cancel_conditional_order", "list_conditional_orders", "prices", "holdings"):
        monkeypatch.setattr(tc.TossClient, name, boom, raising=False)
    monkeypatch.setattr(tc, "get_toss_client", boom)
    price = {"v": D("10")}

    async def px(symbol):
        return price["v"]

    raw = PaperRaw(px)

    async def notify(*a):
        return None

    reg = (datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 21, 0))
    eng = PlanEngine(DirectionGate(raw), notify=notify, clock=Clock(datetime(2026, 11, 20, 15)),
                     regular_window=lambda n: reg, switches=lambda: {"live": False, "paper": True})
    async with get_session() as s:
        plan = await eng.create_draft(s, symbol="TESTA", mode="paper", params={
            "buy_watch": 9.5, "buy_order": 9.5, "qty": 60, "ladder_pcts": [0.03, 0.05, 0.07],
            "tp1_watch": 11.0, "tp1_order": 11.0})
        await eng.approve(s, plan, by="대표")
        for p in ("10", "9.5", "9.5", "11", "11", "8"):
            price["v"] = D(p)
            await raw.on_price(s, "TESTA", price["v"])
            await eng.tick_plan(s, plan)
        assert plan.state in (state.HOLDING, state.TP1_WAIT, state.TRAILING, state.CLOSED, state.HALTED)


def test_new_files_have_no_secret_signatures_and_no_real_tickers():
    # 검출 모양은 이름을 쪼개 적는다 (이 시험 파일이 시그니처 검사에 걸리지 않게)
    sigs = [r"AK" + r"IA[0-9A-Z]{16}", r"s" + r"k-[A-Za-z0-9]{20,}", r"ey" + r"J[A-Za-z0-9_-]{20,}",
            r"gh" + r"p_[A-Za-z0-9]{20,}", r"-----BEGIN [A-Z ]*PRIV" + r"ATE KEY",
            r"pass" + r"word\s*[:=]\s*['\"][^'\"]+", r"client_" + r"secret\s*[:=]\s*['\"][^'\"]{6,}"]
    files = list(PLAN_DIR.glob("*.py")) + [BACKEND / "api" / "routes" / "plans.py"] + list(BACKEND.glob("tests/test_plan_*.py")) \
        + [BACKEND / "tests" / "plan_fakes.py"]
    bad = []
    for path in files:
        src = path.read_text(encoding="utf-8")
        for sg in sigs:
            if re.search(sg, src):
                bad.append(f"{path.name}:{sg}")
    assert not bad, bad
    # 시험 종목은 가상 이름만 (TESTA · TESTB)
    for path in BACKEND.glob("tests/test_plan_*.py"):
        syms = set(re.findall(r'symbol="([A-Z0-9]+)"', path.read_text(encoding="utf-8")))
        assert syms <= {"TESTA", "TESTB"}, (path.name, syms)


# ── 정해진 시각 작업 (교훈 #3) ────────────────────────────────────

def test_draft_jobs_register_only_with_issue_key_and_follow_job_rules(monkeypatch):
    from backend.scheduler import cron
    from backend.services import config
    from backend.services.job_watch import GRACE_DEFAULT
    from backend.tests.test_job_watch import _fixed_times, _too_close

    real = config.get
    monkeypatch.setattr(config, "get", lambda n, d=None: None if n == "TOSS_TOKEN_ISSUE" else real(n, d))
    assert cron.build_scheduler().get_job("plan_draft_a") is None                    # 키 없으면 등록 안 함
    monkeypatch.setattr(config, "get", lambda n, d=None: "1" if n == "TOSS_TOKEN_ISSUE" else real(n, d))
    s = cron.build_scheduler()
    a, b = s.get_job("plan_draft_a"), s.get_job("plan_draft_b")
    assert a and b
    for j in (a, b):
        assert j.misfire_grace_time == GRACE_DEFAULT and j.coalesce is True
    assert not _too_close(_fixed_times(s.get_jobs())), "같은 프로세스 정해진 시각 잡이 5분 안에 겹침"
    f = {x.name: str(x) for x in a.trigger.fields}
    assert (f["hour"], f["minute"]) == ("7", "15,25,35,45,55")
    g = {x.name: str(x) for x in b.trigger.fields}
    assert (g["hour"], g["minute"]) == ("8", "5")


def test_no_ws_connection_is_started_and_markers_exist():
    """웹소켓은 명세 확인 전 미구현 · 보고서 「안 함」 표시가 코드에 남아 있다."""
    src = (PLAN_DIR / "ws.py").read_text(encoding="utf-8")
    assert "미구현" in src and "NotImplementedError" in src
    assert "websockets" not in src and "wss://" not in src
