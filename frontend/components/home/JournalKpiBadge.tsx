"use client";

/**
 * Home 컨트롤 타워 · Judgment Journal 판정 축적 실시간 배지.
 * Phase E · 2026-07-31 · 사용 정착 유도.
 *
 * 매 진입 시 baseline 조회 · 30건 목표 대비 진행률·최근 판정 요약 표시.
 * 클릭 시 /journal 로 이동.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

type Baseline = {
  total_count: number;
  computed_count: number;
  win_rate: number | null;
  avg_return: number | null;
};

const TARGET = 30;

export function JournalKpiBadge() {
  const [b, setB] = useState<Baseline | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/v1/judgments/baseline?days=90", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j: Baseline | null) => setB(j))
      .catch(() => setB(null))
      .finally(() => setLoading(false));
  }, []);

  const total = b?.total_count ?? 0;
  const pct = Math.min(100, Math.round((total / TARGET) * 100));
  const passed = total >= TARGET;

  return (
    <Link
      href="/journal"
      className={`block rounded-lg border p-4 transition ${
        passed
          ? "border-emerald-500/40 bg-emerald-500/10 hover:border-emerald-500"
          : "border-primary/40 bg-primary/5 hover:border-primary"
      }`}
    >
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold uppercase tracking-wide">
          📓 Stage 2 진입 KPI · 판정 축적
        </span>
        <span
          className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
            passed
              ? "bg-emerald-500/20 text-emerald-500"
              : "bg-amber-500/20 text-amber-500"
          }`}
        >
          {passed ? "PASS" : "진행 중"}
        </span>
      </div>

      <div className="mt-2 flex items-baseline justify-between">
        <div className="text-2xl font-bold">
          {loading ? "…" : total}
          <span className="ml-1 text-sm text-muted-foreground">/ {TARGET}</span>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          {b?.computed_count ?? 0} outcome · 승률{" "}
          {b?.win_rate !== null && b?.win_rate !== undefined
            ? `${(b.win_rate * 100).toFixed(0)}%`
            : "—"}
        </div>
      </div>

      <div className="mt-2 h-1.5 overflow-hidden rounded bg-muted">
        <div
          className={`h-full transition-all ${passed ? "bg-emerald-500" : "bg-primary"}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <p className="mt-2 text-[10px] text-muted-foreground">
        Powderkeg lock · Watchlist add · Sniper enable 시 판정 팝업이 뜹니다. →{" "}
        <span className="underline">Journal 열기</span>
      </p>
    </Link>
  );
}
