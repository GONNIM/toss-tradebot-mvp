"use client";

/**
 * R:R (Reward:Risk) 실시간 계산기 · Phase E · 2026-08-02.
 *
 * 존마 강의 원칙 2 · 손익비 > 승률.
 * 입력: entry · invalidation · target → 서버 /api/v1/rulebook/rr-calc 조회 → 색상 verdict.
 * DB 저장 없음 (판정 저장은 JudgmentDialog).
 */

import { useState } from "react";

type Calc = {
  entry: number;
  invalidation: number;
  target: number;
  direction: string;
  rr_ratio: number | null;
  risk_pct: number | null;
  reward_pct: number | null;
  verdict: string;
};

function color(rr: number | null): string {
  if (rr === null) return "text-slate-500";
  if (rr >= 2) return "text-emerald-500";
  if (rr >= 1) return "text-amber-500";
  return "text-red-500";
}

function bg(rr: number | null): string {
  if (rr === null) return "bg-slate-500/10 border-slate-500/40";
  if (rr >= 2) return "bg-emerald-500/10 border-emerald-500/40";
  if (rr >= 1) return "bg-amber-500/10 border-amber-500/40";
  return "bg-red-500/10 border-red-500/40";
}

export function RRCalculator() {
  const [entry, setEntry] = useState("");
  const [inv, setInv] = useState("");
  const [target, setTarget] = useState("");
  const [result, setResult] = useState<Calc | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function calc() {
    setError(null);
    const e = parseFloat(entry);
    const i = parseFloat(inv);
    const t = parseFloat(target);
    if (!(e > 0 && i > 0 && t > 0)) {
      setError("세 값 모두 양수여야 합니다.");
      return;
    }
    setBusy(true);
    try {
      const r = await fetch(
        `/api/v1/rulebook/rr-calc?entry=${e}&invalidation=${i}&target=${t}`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(`서버 오류 (${r.status})`);
      setResult(await r.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div>
        <h2 className="text-sm font-semibold">🧮 R:R 계산기 (Reward:Risk)</h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          존마 강의 권장 · R:R ≥ 2 · 3번 손절해도 1번 대박 = 흑자. Long/Short 자동 판별.
        </p>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <label className="block">
          <span className="text-xs text-muted-foreground">진입가 (entry)</span>
          <input
            type="number"
            step="any"
            value={entry}
            onChange={(e) => setEntry(e.target.value)}
            placeholder="예: 10000"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">손절 (invalidation)</span>
          <input
            type="number"
            step="any"
            value={inv}
            onChange={(e) => setInv(e.target.value)}
            placeholder="예: 9500"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">목표 (target)</span>
          <input
            type="number"
            step="any"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="예: 13000"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
          />
        </label>
      </div>

      <button
        type="button"
        onClick={calc}
        disabled={busy}
        className="mt-3 rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
      >
        {busy ? "계산 중…" : "R:R 계산"}
      </button>

      {error && (
        <p className="mt-2 text-xs text-red-500">⚠️ {error}</p>
      )}

      {result && (
        <div className={`mt-3 rounded border p-3 ${bg(result.rr_ratio)}`}>
          <div className="flex items-baseline justify-between">
            <div>
              <div className="text-xs text-muted-foreground">
                방향: <span className="font-mono uppercase">{result.direction}</span>
              </div>
              <div className={`mt-1 text-3xl font-bold ${color(result.rr_ratio)}`}>
                {result.rr_ratio !== null ? `R:R ${result.rr_ratio.toFixed(2)}` : "R:R —"}
              </div>
            </div>
            {result.risk_pct !== null && result.reward_pct !== null && (
              <div className="text-right text-xs">
                <div className="text-red-500">
                  손실 -{(result.risk_pct * 100).toFixed(2)}%
                </div>
                <div className="text-emerald-500">
                  목표 +{(result.reward_pct * 100).toFixed(2)}%
                </div>
              </div>
            )}
          </div>
          <p className="mt-2 text-xs font-semibold">{result.verdict}</p>
        </div>
      )}
    </section>
  );
}
