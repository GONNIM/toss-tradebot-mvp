"use client";

// 헬스 경고 1줄 · warn=true 시만 렌더 (v6 §2.1 · Fable 5 3차 (2))
// 정상 시 렌더링 안 함 (조건부 반환 null).

import type { HealthResponse } from "@/lib/serenity-hunter/types";

export function HealthWarningLine({ health }: { health: HealthResponse | null }) {
  if (!health || !health.warn) return null;
  const reasons = health.reasons.map((r) => r.message).join(" · ");
  return (
    <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-500">
      ⚠ 시스템 헬스 경고 · {reasons}
    </div>
  );
}
