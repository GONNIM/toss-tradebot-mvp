"use client";

// 1110-02 · /vip 맨 위 탭 줄. 고른 탭은 주소 ?t=<market>:<symbol> 에 남긴다.
import { VipTab, tabKey, tabLabel } from "@/lib/vip-tabs";

export function VipTabBar({ tabs, current, onPick }: { tabs: VipTab[]; current: string; onPick: (key: string) => void }) {
  return (
    <div role="tablist" aria-label="VIP 종목 탭" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
      {tabs.map((t) => {
        const k = tabKey(t);
        const on = k === current;
        return (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={on}
            data-testid={`vip-tab-${k}`}
            onClick={() => onPick(k)}
            className={`min-h-[44px] shrink-0 rounded-lg border px-3 text-sm ${
              on ? "border-slate-800 bg-slate-800 font-semibold text-white" : "border-border bg-background hover:bg-muted"
            }`}
          >
            {tabLabel(t)}
          </button>
        );
      })}
    </div>
  );
}
