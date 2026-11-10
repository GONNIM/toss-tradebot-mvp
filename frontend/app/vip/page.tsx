"use client";

// 1110-02 · VIP 탭 — 적자 종목 + 흑자 전환 5거래일 + 설정 종목. 계획: docs/plans/vip-tabs/2026-11-10-plan.md
// 계좌 조회 60초. 30초 시세 조회(기존 VIP 칸)는 설정 종목 탭을 열었을 때만 (VipConfigPanels).

import { Suspense } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { VipTabBar } from "@/components/vip/VipTabs";
import { VipTabBody } from "@/components/vip/VipTabBody";
import { LOGIN_REQUIRED_MESSAGE } from "@/lib/auth";
import { EMPTY_TEXT, pickTab, tabKey } from "@/lib/vip-tabs";

function isUnauthorized(err: unknown): boolean {
  return /failed: 401\b/.test((err as Error | null)?.message ?? "");
}

function VipView() {
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const q = useQuery({
    queryKey: ["vip", "tabs"],
    queryFn: () => api.account.vip(),
    retry: false,
    refetchInterval: (query) => (isUnauthorized(query.state.error) ? false : 60_000),
  });

  const data = q.data;
  const tabs = data?.ok ? data.tabs : [];
  const cur = pickTab(tabs, params.get("t"));

  function pick(key: string) {
    const next = new URLSearchParams(params.toString());
    next.set("t", key);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-3xl font-bold">VIP 종목 탭</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          지금 손익이 0 아래인 종목 · 흑자로 바뀐 지 5거래일 이내인 종목 · 설정 종목. 사실만 보여 드리며 매매 지시가 아닙니다.
        </p>
      </header>

      {/* 1028-03 · 설정 변경은 관리자 로그인 필요 */}
      <AdminSessionBar scope="vip" onSessionChange={() => qc.invalidateQueries({ queryKey: ["vip"] })} />

      {q.isLoading && <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">로딩 중…</div>}

      {q.isError && isUnauthorized(q.error) && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">{LOGIN_REQUIRED_MESSAGE}</div>
      )}

      {q.isError && !isUnauthorized(q.error) && (
        <div className="rounded-lg border border-warn/50 bg-warn/10 p-4 text-sm text-warn">
          탭 조회 실패: {(q.error as Error).message}
        </div>
      )}

      {data && !data.ok && (
        <div className="rounded-lg border border-warn/50 bg-warn/10 p-4 text-sm text-warn">
          토스 보유 조회에 실패했습니다: {data.error_reason}
        </div>
      )}

      {data?.ok && tabs.length === 0 && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm" data-testid="vip-empty">
          {EMPTY_TEXT}
        </div>
      )}

      {cur && (
        <>
          <VipTabBar tabs={tabs} current={tabKey(cur)} onPick={pick} />
          <VipTabBody key={tabKey(cur)} t={cur} />
        </>
      )}

      {data?.ok && data.limits.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
          {data.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function VipPage() {
  return (
    <Suspense fallback={null}>
      <VipView />
    </Suspense>
  );
}
