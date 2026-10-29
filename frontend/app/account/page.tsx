"use client";

// 1025-06 · 「내 계좌」 — 내 증권 계좌로 가는 길 · 토스 실계좌 요약 · 실주문 안전 한 줄 · 미국 종목 토스 주소 확인.
// 1025-08 · 토스 실계좌 보유 종목 표 (보유 일수 · 최고가 대비 · 청산 계획 · 토스증권으로 가기) — 사실만.
// 사이트는 주문을 넣지 않는다 (정체성 원칙 1). 주문은 토스증권 화면에서 직접 한다.
// 1022-10 2단계 (2026-10-29) · 옛 /dashboard (요약) · /positions (청산 계획 카드 #plan) 를 이 화면으로 합침.
//   옛 주소는 next.config redirect (307) · 보유 종목 표는 이 화면의 표 하나.

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AccountHolding, AccountHoldingsResponse, api, SniperStatus, TossStockCodeRow } from "@/lib/api";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { PositionPlans } from "@/components/account/PositionPlans";
import { TossSummary } from "@/components/account/TossSummary";
import { BROKER_LABEL, SEARCH_LABEL, TOSS_ACCOUNT, TOSS_HOME, friendlyError } from "@/lib/broker-link";
import { fxLabel, heldLabel, peakLabel, pctText, pnlTone, priceText, wonText } from "@/lib/holdings-display";
import { safetyConclusion } from "@/lib/sniper-safety";
import { fmtKstDateTime } from "@/lib/time";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function SafetyLine() {
  const q = useQuery<SniperStatus>({ queryKey: ["sniper", "status"], queryFn: api.sniper.status });
  if (!q.data) return <p className="text-sm text-muted-foreground">{q.error ? "실주문 상태를 불러오지 못했습니다" : "확인 중…"}</p>;
  const s = q.data;
  const c = safetyConclusion({
    live_enabled: s.live_enabled,
    sniper_enabled: s.sniper_enabled,
    watchlist_enabled: s.watchlist_execute?.enabled ?? false,
    router_enabled: s.signal_router_enabled,
    kill_switch_active: s.kill_switch_active,
    order_target: s.order_target,
  });
  return (
    <p className="text-sm">
      {c.text} · <Link href="/sniper" className="underline">자세히: /sniper</Link>
    </p>
  );
}

const TONE_CLASS = { up: "text-red-600 dark:text-red-400", down: "text-blue-600 dark:text-blue-400", flat: "text-muted-foreground" } as const;

function HoldingRow({ h }: { h: AccountHolding }) {
  const tone = TONE_CLASS[pnlTone(h.pnl)];
  return (
    <tr className="border-b border-border align-top last:border-0">
      <td className="p-2">
        <div className="font-medium">{h.name ?? h.symbol}</div>
        <div className="font-mono text-xs text-muted-foreground">{h.symbol} · {h.market === "KR" ? "국내" : "미국"}</div>
      </td>
      <td className="p-2 text-right">{h.qty.toLocaleString("ko-KR")}</td>
      <td className="p-2 text-right">
        <div>{priceText(h.current_price, h.currency)}</div>
        <div className="text-xs text-muted-foreground">평단 {priceText(h.avg_price, h.currency)}</div>
      </td>
      <td className={`p-2 text-right ${tone}`}>
        <div className="font-semibold">{pctText(h.pnl_pct)}</div>
        <div className="text-xs">{wonText(h.pnl_krw)}</div>
      </td>
      <td className="p-2 text-right">{wonText(h.market_value_krw)}</td>
      <td className="p-2">{peakLabel(h)}</td>
      <td className="p-2">{heldLabel(h)}</td>
      <td className="p-2">
        {h.has_exit_plan ? (
          "✓ 있음"
        ) : (
          <a href="#plan" className="text-red-600 underline dark:text-red-400">✗ 없음</a>
        )}
      </td>
      <td className="p-2">
        <a href={h.link.url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-xs underline">
          {h.link.kind === "order" ? BROKER_LABEL : SEARCH_LABEL}
        </a>
      </td>
    </tr>
  );
}

function HoldingsTable({ isAdmin }: { isAdmin: boolean }) {
  const q = useQuery<AccountHoldingsResponse>({
    queryKey: ["account", "holdings"],
    queryFn: api.account.holdings,
    enabled: isAdmin,
    retry: false,
  });
  if (!isAdmin) return null;
  if (q.isLoading) return <p className="text-sm text-muted-foreground">보유 종목 불러오는 중…</p>;
  if (q.error || !q.data) return <p className="text-sm text-muted-foreground">보유 종목을 불러오지 못했습니다.</p>;
  const d = q.data;
  if (!d.ok) return <p className="text-sm text-muted-foreground">보유 종목을 불러오지 못했습니다 ({d.error_reason ?? "이유 없음"}).</p>;
  if (d.holdings.length === 0) return <p className="text-sm text-muted-foreground">토스 실계좌에 보유 종목이 없습니다.</p>;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">보유 종목 {d.holdings.length}개</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[56rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="p-2">종목</th>
              <th className="p-2 text-right">수량</th>
              <th className="p-2 text-right">현재가</th>
              <th className="p-2 text-right">손익</th>
              <th className="p-2 text-right">평가 (원)</th>
              <th className="p-2">최고가 대비</th>
              <th className="p-2">보유 일수</th>
              <th className="p-2">청산 계획</th>
              <th className="p-2">토스증권</th>
            </tr>
          </thead>
          <tbody>{d.holdings.map((h) => <HoldingRow key={`${h.market}-${h.symbol}`} h={h} />)}</tbody>
        </table>
      </div>
      <ul className="space-y-0.5 text-xs text-muted-foreground">
        <li>{fxLabel(d.fx_rate, d.fx_source)}</li>
        <li>최고가 대비 = 보유 기준일 뒤 가장 높은 종가와 현재 가격의 차이입니다 (토스 일봉 · 장 열린 날 국내 15:50 · 미국 07:10 기록).</li>
        <li>보유 일수 기준일은 첫 저널 판단일, 없으면 이 사이트가 보유를 처음 기록한 날입니다. 실제 매수일과 다를 수 있습니다.</li>
        <li>
          청산 계획 「있음」 = 최근 저널 판단에 손절가나 목표가가 적혀 있을 때입니다 · 종목별 내용은 아래 <a href="#plan" className="underline">「종목별 청산 계획」</a> · {fmtKstDateTime(d.fetched_at)} 토스 응답 기준
        </li>
      </ul>
    </div>
  );
}

function CodeRow({ row }: { row: TossStockCodeRow }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const save = useMutation({
    mutationFn: () => api.brokerLinks.put(row.symbol, { toss_url: url.trim() || null, verified: true }),
    onSuccess: () => {
      setUrl("");
      qc.invalidateQueries({ queryKey: ["broker-links"] });
      qc.invalidateQueries({ queryKey: ["account", "codes"] });
    },
  });
  const tryUrl = row.toss_code ? `${TOSS_HOME}stocks/${row.toss_code}/order` : null;
  return (
    <tr className="border-b border-border align-top last:border-0">
      <td className="p-2 font-mono">{row.symbol}</td>
      <td className="p-2">
        {row.verified ? "확인함" : "확인 전"}
        {tryUrl && (
          <a href={tryUrl} target="_blank" rel="noopener noreferrer" className="ml-2 text-xs underline">
            후보 주소 열어 보기 ↗
          </a>
        )}
        <div className="text-xs text-muted-foreground">
          {row.toss_code ?? "코드 없음"} · 상장일 {row.list_date ?? "—"} · {row.source === "manual" ? "직접 고침" : "자동"}
        </div>
      </td>
      <td className="p-2">
        <div className="flex flex-col gap-1 sm:flex-row">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="토스증권 종목 주소 (비우면 후보 그대로 확인)"
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || (!url.trim() && !row.toss_code)}
            className="rounded-md bg-slate-800 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-200 dark:text-slate-900"
          >
            {save.isPending ? "저장 중…" : "확인함"}
          </button>
        </div>
        {save.error && <p className="mt-1 text-xs text-red-600">{friendlyError(save.error)}</p>}
      </td>
    </tr>
  );
}

function CodeTable({ isAdmin }: { isAdmin: boolean }) {
  const q = useQuery({ queryKey: ["account", "codes"], queryFn: api.brokerLinks.codes, enabled: isAdmin, retry: false });
  if (!isAdmin) return <p className="text-sm text-muted-foreground">로그인하면 미국 종목 주소를 확인할 수 있습니다.</p>;
  const rows = q.data?.codes ?? [];
  if (q.isLoading) return <p className="text-sm text-muted-foreground">불러오는 중…</p>;
  if (q.error) return <p className="text-sm text-muted-foreground">목록을 불러오지 못했습니다.</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">아직 목록이 없습니다. 매일 07:40 에 바이오 레이더 종목과 미국 보유 종목으로 채워집니다.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="p-2">티커</th>
            <th className="p-2">상태</th>
            <th className="p-2">토스 주소 붙여 넣기</th>
          </tr>
        </thead>
        <tbody>{rows.map((r) => <CodeRow key={r.symbol} row={r} />)}</tbody>
      </table>
    </div>
  );
}

export default function AccountPage() {
  const [isAdmin, setIsAdmin] = useState(false);
  const qc = useQueryClient();
  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">내 계좌</h1>
        <p className="text-sm text-muted-foreground">이 사이트는 주문을 넣지 않습니다. 주문은 각 증권사 화면에서 직접 하십시오.</p>
      </header>
      <AdminSessionBar
        scope="sniper"
        onSessionChange={(info) => {
          setIsAdmin(info.role === "admin");
          qc.invalidateQueries({ queryKey: ["account"] });
        }}
      />
      <Card title="토스증권">
        <div className="flex flex-wrap gap-2">
          <a href={TOSS_ACCOUNT} target="_blank" rel="noopener noreferrer" className="rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted">
            토스증권 내 계좌 열기 ↗
          </a>
          <a href={TOSS_HOME} target="_blank" rel="noopener noreferrer" className="rounded-md border border-border px-3 py-2 text-sm font-medium hover:bg-muted">
            토스증권 첫 화면 ↗
          </a>
        </div>
        <TossSummary isAdmin={isAdmin} />
        <HoldingsTable isAdmin={isAdmin} />
      </Card>
      <PositionPlans isAdmin={isAdmin} />
      <Card title="카카오페이증권">
        <p className="text-sm">휴대폰 카카오페이 앱 → 증권에서 ISA 계좌와 ETF 를 확인하세요. 카카오페이증권은 PC 웹 거래 화면이 없습니다.</p>
      </Card>
      <Card title="실주문 안전">
        <SafetyLine />
      </Card>
      <Card title="미국 종목 토스 주소 확인">
        <p className="text-xs text-muted-foreground">
          토스증권은 미국 종목을 자체 코드로 엽니다. 「후보 주소 열어 보기」로 맞는 종목이 열리는지 보고 「확인함」을 누르십시오. 다르면 토스증권에서 그 종목을 열고 주소창 주소를 붙여 넣으십시오. 확인한 종목만 「토스증권에서 열기」로 주문 화면이 바로 열립니다.
        </p>
        <CodeTable isAdmin={isAdmin} />
      </Card>
    </div>
  );
}
