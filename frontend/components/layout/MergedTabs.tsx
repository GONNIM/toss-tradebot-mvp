"use client";

// 1120-01 단계 3 (2026-11-22) · 합친 화면의 탭 줄.
// - 고른 탭은 주소 `?view=<key>` 로 나타낸다 (첫 탭은 view 없음). `view` 는 다른 화면이 쓰지 않는 이름이다
//   (/vip 는 `t` · /journal 은 `ticker` · /biotech/docs 는 `tab`).
// - useSearchParams 는 이 부품 안 Suspense 안에서만 쓴다 (Next 14 빌드 규칙).
// - 고른 탭 하나만 그린다 (다른 탭의 조회 · 로그인 줄이 함께 돌지 않게).
// - 옛 주소(/vip · /logs 등)는 그대로 자기 화면을 그린다. 이 부품은 받을 화면에만 쓴다.

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import type { ReactNode } from "react";

export interface MergedTab {
  key: string;
  label: string;
  render: () => ReactNode;
}

export function MergedTabs({ tabs, label }: { tabs: MergedTab[]; label: string }) {
  return (
    <Suspense fallback={<p className="text-xs text-muted-foreground">불러오는 중…</p>}>
      <MergedTabsInner tabs={tabs} label={label} />
    </Suspense>
  );
}

/** ?view= 값으로 고른 탭. 모르는 값 · 없으면 첫 탭. */
export function pickView(tabs: { key: string }[], view: string | null): number {
  const i = view ? tabs.findIndex((t) => t.key === view) : -1;
  return i >= 0 ? i : 0;
}

function MergedTabsInner({ tabs, label }: { tabs: MergedTab[]; label: string }) {
  const pathname = usePathname();
  const sp = useSearchParams();
  const cur = pickView(tabs, sp.get("view"));
  return (
    <div className="space-y-4">
      <TabBar tabs={tabs} label={label} pathname={pathname} current={cur} />
      {cur === 0 ? (
        <div key={tabs[cur].key}>{tabs[cur].render()}</div>
      ) : (
        // 1120-01 단계 4 · 제목 겹침 다듬기. 둘째 탭부터는 옛 화면을 그대로 불러 그리는데, 그 화면의 큰 제목(h1)이
        // 탭 이름과 겹쳐 두 번 보이고 화면에 제목이 둘이 된다. 탭 안에서만 옛 h1 을 숨기고(display:none · 보조 기기에서도 빠짐)
        // 탭 이름을 화면 제목(h1) 하나로 둔다 (눈에는 탭 줄이 제목 구실). 옛 주소로 바로 열면 옛 제목이 그대로 보인다.
        <div key={tabs[cur].key} className="[&_h1]:hidden" data-testid="merged-tab-original">
          <h1 className="sr-only">{tabs[cur].label}</h1>
          {tabs[cur].render()}
        </div>
      )}
    </div>
  );
}

/** 탭 줄만 (종목 상세처럼 내용은 따로 그리는 화면에서도 쓴다 · current 가 -1 이면 켜진 탭 없음). */
export function TabBar({
  tabs,
  label,
  pathname,
  current,
}: {
  tabs: { key: string; label: string }[];
  label: string;
  pathname: string;
  current: number;
}) {
  return (
    <nav aria-label={label} className="flex gap-1 overflow-x-auto border-b border-border text-sm" data-testid="merged-tabs">
      {tabs.map((t, i) => {
        const active = i === current;
        return (
          <Link
            key={t.key}
            href={i === 0 ? pathname : `${pathname}?view=${t.key}`}
            aria-current={active ? "page" : undefined}
            scroll={false}
            className={
              "flex min-h-[44px] shrink-0 items-center whitespace-nowrap px-3 " +
              (active ? "border-b-2 border-primary font-semibold text-primary" : "text-muted-foreground hover:text-foreground")
            }
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
