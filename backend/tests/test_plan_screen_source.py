"""1116-01 계획 화면 쉽게 만들기(A~I) · 화면 소스 대조 시험 (기존 관례: 소스 문자열 대조).

종목 · 보유 · 금액은 모두 가짜 값이다. 서버는 바꾸지 않았으므로 서버 쪽 기존 시험(test_plan_api 등)은 그대로 통과해야 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FE = ROOT / "frontend"


def _src(rel: str) -> str:
    return (FE / rel).read_text(encoding="utf-8")


ALL = [
    "app/plans/page.tsx", "app/plans/new/page.tsx", "app/plans/adopt/page.tsx", "app/plans/[id]/page.tsx",
    "components/plans/ModeBand.tsx", "components/plans/CodeDialog.tsx", "components/plans/PlanExecutorCard.tsx",
    "components/plans/UnknownOrders.tsx", "components/plans/planView.ts",
]


def test_a_top_line_reasons_and_unknown():
    v = _src("components/plans/planView.ts")
    body = v[v.index("export function orderLine"):]
    for needle in ["실거래 주문이 꺼져 있습니다", "새 주문 멈춤", "매도도 멈춤", "실행기 응답이 끊겼습니다", "토스 연결 오류입니다",
                   '"확인 못 함"', "주문 안 나감", "주문 나감"]:
        assert needle in body, needle
    assert "${KILL_NAME}가 작동 중입니다" in body  # 비상 정지 두 단계(새 주문 멈춤 / 매도도 멈춤)를 까닭으로
    # 상태를 못 읽으면(failed 또는 data 없음) 「주문 나감」이 아니라 「확인 못 함」
    assert re.search(r'if \(failed \|\| !st\) return \{ state: "unknown", head: "확인 못 함"', body)
    band = _src("components/plans/ModeBand.tsx")
    assert "승인 기다리는 초안" in band and 'p.state === "DRAFT"' in band
    # 칩 7개는 「자세히」 안
    details = band[band.index("<details"):]
    for tid in ["band-live", "band-paper", "band-kill", "band-heartbeat", "chip-ws", "chip-resync", "chip-toss"]:
        assert f'testid="{tid}"' in details, tid
    page = _src("app/plans/page.tsx")
    assert 'aria-label="실행기 상태 칩"' not in page and "chip-ws" not in page


def test_b_card_five_lines_no_dollar_stop():
    page = _src("app/plans/page.tsx")
    for k in ["row-symbol-", "row-buy-", "row-sell-", "row-stop-", "row-qty-"]:
        assert k in page, k
    assert "ladderLine(p.params)" in page and "PRICE_NOTE" in page
    v = _src("components/plans/planView.ts")
    assert "평균 매수가 기준" in v and "(기본 규칙)" in v
    # ladder_pcts 가 있으면 그 값 · 없을 때만 기본 규칙 · 달러 값 계산 없음
    body = v[v.index("export function ladderLine"):v.index("export const PRICE_NOTE")]
    assert "params?.ladder_pcts" in body and "isDefault: true" in body
    assert "usd(" not in body and "avg_price" not in body


def test_c_missing_list_fix_and_lock():
    v = _src("components/plans/planView.ts")
    for needle in ['"수량 0"', '"매수 감시가"', '"매수 주문가"', '"평균 단가"']:
        assert needle in v, needle
    d = _src("app/plans/[id]/page.tsx")
    assert "missingValues(p)" in d and 'testid="missing-values"' in d
    assert "plansApi.edit(id, values)" in d  # 서버에 이미 있는 초안 고치기 API
    assert 'p.state === "DRAFT" && fixOpen' in d  # 초안 단계에서만
    assert "앞서 받은 확인 코드는 쓸 수 없습니다" in d
    # 승인 단추 잠금: 모의 · 맡기기 계획 구분 없이 locked (isPaper 로 예외를 두지 않음)
    assert "const locked = p.state === \"DRAFT\" && missing.length > 0;" in d
    assert "disabled={locked}" in d and "if (!p || locked) return;" in d
    # 서버 승인 경로 · API 파일은 이번 단계에서 바꾸지 않음
    assert "edit: (id: number, values" in _src("lib/plans.ts")


def test_d_new_plan_four_fields_two_prices_sent_separately():
    n = _src("app/plans/new/page.tsx")
    head, more = n.split('data-testid="new-more"')
    for tid in ["in-symbol", "in-budget", "in-buy-watch", "in-buy-order"]:
        assert f'data-testid="{tid}"' in head, tid
    for tid in ["in-mode", "in-tp1-watch", "in-tp1-order", "in-announce", "in-close", "in-window-end"]:
        assert f'data-testid="{tid}"' in more and f'data-testid="{tid}"' not in head, tid
    # 보내는 값 모양 그대로: 두 가격을 따로 보낸다
    assert "budget_usd: b, buy_watch: w, buy_order: o, qty: q," in n
    # 손절은 입력 없음 · 보여 주기만
    assert "ladder_pcts" not in n and "손절" not in n.split("buildParams")[1].split("function")[0]
    assert 'data-testid="new-stop-rule"' in n and "ladderLine(undefined)" in n


def test_e_errors_only_after_save_click():
    for rel, tids in [("app/plans/new/page.tsx", ["new-problems", "new-error", "new-validate-error"]),
                      ("app/plans/adopt/page.tsx", ["adopt-problems", "adopt-error"])]:
        s = _src(rel)
        assert "setSubmitted(true)" in s
        for t in tids:
            line = next(l for l in s.splitlines() if t in l)
            assert "submitted" in line or "submitted" in s[s.index(t) - 200:s.index(t)], t
        assert "disabled={busy} " in s  # 입력 중 단추를 잠가 오류를 미리 알리지 않는다


def test_f_visible_words_only():
    for rel in ALL:
        for i, line in enumerate(_src(rel).splitlines(), 1):
            code = line.strip()
            if code.startswith("//") or code.startswith("/*") or code.startswith("*"):
                continue
            visible = re.sub(r'(aria-label|data-testid|testid|label)="[^"]*"', "", line)
            visible = re.sub(r"aria-label=\{[^}]*\}", "", visible)
            assert "Kill Switch" not in visible, (rel, i)
            assert not re.search(r">[^<{]*(?<![가-힣])다리", visible), (rel, i)
    # data-testid · 서버 기록 코드 해석(정규식)은 그대로
    d = _src("app/plans/[id]/page.tsx")
    assert 'testid="legs-expected"' in d and 'testid="legs-actual"' in d and 'testid="plan-band"' in _src("components/plans/ModeBand.tsx")
    assert "leg_missing" in d and r"/^(sl|tp1|buy)(\d+)$/" in d and "approved by" in d
    # 「비상 정지」와 「비상 손절」 구분
    v = _src("components/plans/planView.ts")
    assert 'KILL_NAME = "비상 정지"' in v and "정규장 밖 비상 손절" in v
    assert "이미 산 종목 맡기기" in v


def test_g_internal_values_in_details_but_request_values_kept():
    d = _src("app/plans/[id]/page.tsx")
    assert 'data-testid="plan-internal"' in d and "판 번호 {p.revision} · 내용 확인값" in d
    assert 'data-testid="halted-raw"' in d
    c = _src("components/plans/CodeDialog.tsx")
    # 코드를 요청한 순간의 값과 판 번호는 접지 않고, 내용 확인값만 자세히 안
    pre, det = c.split("<details", 1)
    assert "ch.revision" in pre and "renderValues(ch.values)" in pre
    assert "내용 확인값" in det and "ch.content_hash" in det and "ch.revision" not in det.split("</details>")[0]


def test_h_code_requested_only_on_click_in_all_dialogs():
    c = _src("components/plans/CodeDialog.tsx")
    eff = c[c.index("useEffect(() => {"):c.index("useEffect(() => {", c.index("useEffect(() => {") + 10)]
    assert "request()" not in eff and "requestCode" not in eff  # 창을 열 때 요청하지 않는다
    assert 'data-testid={`${testid}-request`}' in c and "onClick={() => void request()}" in c
    assert "새 코드를 받으면 앞의 코드는 쓸 수 없습니다. 틀린 코드를 5번 넣으면 그 코드는 무효가 됩니다." in c
    # CodeDialog 를 쓰는 곳(requestCode 를 넘기는 창) 4곳이 모두 같은 부품
    users = {rel: _src(rel).count("<CodeDialog") for rel in ALL if "CodeDialog" in _src(rel) and not rel.endswith("CodeDialog.tsx")}
    code_dialogs = sum(_src(rel).count("requestCode={") for rel in users)
    assert code_dialogs == 4, users  # 승인 · 재개 · 결과 모르는 주문 확정 · 실거래 켜기


def test_i_live_link_is_only_a_link():
    d = _src("app/plans/[id]/page.tsx")
    assert 'href="/admin/settings"' in d and "주문 안 나감 · 켜러 가기" in d
    assert "setLive" not in d and "setPaper" not in d  # 스위치를 계획 화면에 두지 않는다


def test_price_cards_have_basis_and_no_banned_words():
    v = _src("components/plans/planView.ts")
    assert "추정 · 보장 아님" in v and "규칙으로 계산" in v
    assert "추정 · 보장 아님" in _src("app/plans/new/page.tsx") or "PRICE_NOTE" in _src("app/plans/new/page.tsx")
    for rel in ALL:
        s = _src(rel)
        for w in ["골든", "데드", "크로스", "교차", "정배열", "역배열", "사십시오", "매수하십시오", "매도하십시오"]:
            assert w not in s, (rel, w)


def test_no_real_names_or_secrets_in_new_files():
    for rel in ALL + ["../backend/tests/test_plan_screen_source.py"]:
        s = _src(rel)
        assert not re.search(r"AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}", s), rel
