"use client";

// JudgmentDialog · Phase B 주 3-6 · 2026-07-30
// 참조: docs/plans/toss-tradebot-tobe/stage1-optimization.md §1
//
// 사용 예 (각 페이지에서):
//   <JudgmentDialog
//     open={showJudgment}
//     onOpenChange={setShowJudgment}
//     ticker="024830"
//     pageSource="watchlist"
//     hypothesisId="watchlist-v1.55-composite"
//     onSuccess={(j) => notify(`판정 저장 · id=${j.id}`)}
//   />

import { useEffect, useRef, useState } from "react";
import { capture } from "@/lib/observability";

type Judgment = {
  id: number;
  ticker: string;
  page_source: string;
};

type Mood = "cool" | "neutral" | "revenge" | "fomo";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticker: string;
  pageSource: string;
  hypothesisId: string;
  onSuccess?: (j: Judgment) => void;
  // L14+ · Serenity Hunter action-cards 프리필 (2026-08-05)
  // 지시서 §1.4 · 카드 클릭 시 폼이 매수/손절/TP 프리필 상태로 열림
  initialThesis?: string;
  initialEntry?: string;
  initialInvalidation?: string;
  initialTarget?: string;
  initialHorizon?: number;
};

const MOOD_OPTIONS: { value: Mood; label: string; hint: string }[] = [
  { value: "cool", label: "🧘 Cool", hint: "명료 · 계획 대로 판단" },
  { value: "neutral", label: "😐 Neutral", hint: "특별한 감정 없음" },
  { value: "revenge", label: "😡 Revenge", hint: "손실 후 복구 심리" },
  { value: "fomo", label: "🔥 FOMO", hint: "놓치면 안 될 것 같은 조급함" },
];

export function JudgmentDialog({
  open,
  onOpenChange,
  ticker,
  pageSource,
  hypothesisId,
  onSuccess,
  initialThesis = "",
  initialEntry = "",
  initialInvalidation = "",
  initialTarget = "",
  initialHorizon = 7,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [thesis, setThesis] = useState(initialThesis);
  const [entry, setEntry] = useState(initialEntry);
  const [invalidation, setInvalidation] = useState(initialInvalidation);
  const [target, setTarget] = useState(initialTarget);
  const [horizon, setHorizon] = useState(initialHorizon);
  const [mood, setMood] = useState<Mood>("neutral");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  // L14+ · open 시 initial* 로 재프리필 (다른 카드로 재열림 시 반영)
  useEffect(() => {
    if (open) {
      setThesis(initialThesis);
      setEntry(initialEntry);
      setInvalidation(initialInvalidation);
      setTarget(initialTarget);
      setHorizon(initialHorizon);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, ticker]);

  const reset = () => {
    setThesis(initialThesis);
    setEntry(initialEntry);
    setInvalidation(initialInvalidation);
    setTarget(initialTarget);
    setHorizon(initialHorizon);
    setMood("neutral");
    setError(null);
  };

  const handleClose = () => {
    onOpenChange(false);
    reset();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const inv = parseFloat(invalidation);
      if (isNaN(inv)) throw new Error("invalidation_price 필수 (숫자)");
      if (!thesis.trim()) throw new Error("thesis 필수");
      const payload = {
        ticker,
        page_source: pageSource,
        hypothesis_id: hypothesisId,
        thesis_md: thesis,
        invalidation_price: inv,
        target_price: target ? parseFloat(target) : null,
        horizon_days: horizon,
        mood,
        entry_price: entry ? parseFloat(entry) : null,
      };
      const res = await fetch("/api/v1/judgments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`POST /judgments ${res.status} · ${body.slice(0, 200)}`);
      }
      const j: Judgment = await res.json();
      // Phase D 주 8 · PostHog capture (KEY 없으면 no-op).
      void capture("judgment_created", {
        page_source: pageSource,
        hypothesis_id: hypothesisId,
        mood,
        horizon_days: horizon,
        has_target: !!target,
      });
      onSuccess?.(j);
      handleClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      onClose={handleClose}
      className="w-full max-w-lg rounded-lg border border-border bg-card p-0 text-foreground backdrop:bg-black/60"
    >
      <form onSubmit={handleSubmit} className="space-y-4 p-6">
        <header>
          <h2 className="text-lg font-bold">📓 판정 기록</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            <span className="font-mono">{ticker}</span> · {pageSource} · {hypothesisId}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            reject criteria (invalidation) 없으면 판정 아님 · Kahneman hot/cold state 기록
          </p>
        </header>

        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            판정 근거 (thesis · 마크다운)
          </span>
          <textarea
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            placeholder="왜 이 판단을 내렸나 (근거·기대·비교 사례)"
            required
            rows={4}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"
          />
        </label>

        <div className="grid grid-cols-3 gap-3">
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Entry (선택 · R:R)
            </span>
            <input
              type="number"
              step="0.01"
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
              placeholder="진입가"
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Invalidation (필수)
            </span>
            <input
              type="number"
              step="0.01"
              value={invalidation}
              onChange={(e) => setInvalidation(e.target.value)}
              required
              placeholder="반증가"
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Target (선택 · R:R)
            </span>
            <input
              type="number"
              step="0.01"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="목표가"
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"
            />
          </label>
        </div>
        <RRHint entry={entry} invalidation={invalidation} target={target} />

        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Horizon (T+N일)
          </span>
          <input
            type="number"
            min={1}
            max={365}
            value={horizon}
            onChange={(e) => setHorizon(parseInt(e.target.value, 10) || 7)}
            className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"
          />
        </label>

        <fieldset>
          <legend className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Mood (현재 감정 상태)
          </legend>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {MOOD_OPTIONS.map((m) => (
              <label
                key={m.value}
                className={`cursor-pointer rounded border px-3 py-2 text-sm ${
                  mood === m.value
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/40"
                }`}
              >
                <input
                  type="radio"
                  name="mood"
                  value={m.value}
                  checked={mood === m.value}
                  onChange={() => setMood(m.value)}
                  className="sr-only"
                />
                <div>{m.label}</div>
                <div className="text-[10px] text-muted-foreground">{m.hint}</div>
              </label>
            ))}
          </div>
        </fieldset>

        {error && (
          <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-400">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <button
            type="button"
            onClick={handleClose}
            className="rounded border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            취소
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting ? "저장 중..." : "저장"}
          </button>
        </div>
      </form>
    </dialog>
  );
}

/** R:R 실시간 힌트 · 존마 원칙 2 유도 · Phase E · 2026-08-02. */
function RRHint({
  entry,
  invalidation,
  target,
}: {
  entry: string;
  invalidation: string;
  target: string;
}) {
  const e = parseFloat(entry);
  const i = parseFloat(invalidation);
  const t = parseFloat(target);
  if (!(e > 0 && i > 0 && t > 0)) {
    return (
      <p className="text-[10px] text-muted-foreground">
        💡 Entry·Invalidation·Target 모두 입력하면 R:R 실시간 표시 (존마 강의 권장 ≥ 2).
      </p>
    );
  }
  let rr: number | null = null;
  let direction = "invalid";
  if (t > e && e > i) {
    rr = (t - e) / (e - i);
    direction = "long";
  } else if (t < e && e < i) {
    rr = (e - t) / (i - e);
    direction = "short";
  }
  if (rr === null || !isFinite(rr)) {
    return (
      <p className="rounded bg-red-500/10 px-2 py-1 text-[10px] text-red-500">
        ⚠️ Entry·Invalidation·Target 관계가 Long/Short 어느 쪽도 아닙니다.
      </p>
    );
  }
  const color =
    rr >= 2 ? "text-emerald-500" : rr >= 1 ? "text-amber-500" : "text-red-500";
  const bg =
    rr >= 2 ? "bg-emerald-500/10" : rr >= 1 ? "bg-amber-500/10" : "bg-red-500/10";
  const verdict =
    rr >= 2 ? "권장" : rr >= 1 ? "재검토 (강의 권장 2 미달)" : "위험 (손 > 보)";
  return (
    <p className={`rounded ${bg} px-2 py-1 text-xs ${color}`}>
      R:R <strong>{rr.toFixed(2)}</strong> · {direction} · {verdict}
    </p>
  );
}
