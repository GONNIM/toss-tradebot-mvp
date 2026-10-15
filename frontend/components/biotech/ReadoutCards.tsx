"use client";

// P4-4 · 새 8-K 확인 카드 (PRD FR-6b · 봉인 설계 2.2절) · 확정은 사용자 · 한 번만 저장
import { useState } from "react";
import { DIRECTION_KO, READOUT_NOTE, candidateLabel, readoutStatusLine, readoutTitle } from "@/lib/biotech-fr6c";
import type { ReadoutRow } from "@/lib/biotech-fr6c";

async function postConfirm(accession: string, clinical: boolean, direction: string | null) {
  const res = await fetch("/api/v1/biotech/fr6c/confirm", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accession, clinical, direction }),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(`${j.detail ?? res.statusText} (status=${res.status})`);
  }
  return res.json();
}

function ReadoutCard({ r, onSaved }: { r: ReadoutRow; onSaved: () => void }) {
  const [dir, setDir] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const decided = !!r.decision;

  async function save(clinical: boolean) {
    if (clinical && !dir) {
      setErr("방향을 먼저 고르세요.");
      return;
    }
    if (!window.confirm(clinical ? `임상 발표로 확정하고 방향을 "${DIRECTION_KO[dir]}"(으)로 저장합니다. 한 번 저장하면 바꿀 수 없습니다.` : "임상 발표가 아닌 것으로 저장합니다. 한 번 저장하면 바꿀 수 없습니다.")) return;
    setBusy(true);
    setErr(null);
    try {
      await postConfirm(r.accession, clinical, clinical ? dir : null);
      onSaved();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-slate-100 px-2 py-0.5 font-mono font-bold dark:bg-slate-800">{r.ticker || "-"}</span>
        <span className="font-semibold">{readoutTitle(r)}</span>
      </div>
      <div className="mt-1 text-muted-foreground">{readoutStatusLine(r)}</div>
      <div className="mt-1">
        {candidateLabel(r.candidate_direction)}
        {(r.keywords ?? []).length > 0 && <span className="text-muted-foreground"> · 검색어 {(r.keywords ?? []).join(", ")}</span>}
      </div>
      {r.quote && <div className="mt-1 rounded bg-slate-50 p-2 text-muted-foreground dark:bg-slate-900/60">…{r.quote}…</div>}
      <div className="mt-1">
        원문:{" "}
        <a href={r.sec_url} target="_blank" rel="noopener noreferrer" className="text-sky-700 hover:underline dark:text-sky-300">
          SEC {r.accession} ↗
        </a>
      </div>
      {!decided && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1">
            방향
            <select value={dir} onChange={(e) => setDir(e.target.value)} className="rounded border bg-background px-2 py-1 text-xs" disabled={busy}>
              <option value="">고르기</option>
              <option value="positive">긍정</option>
              <option value="mixed">혼재</option>
              <option value="negative">부정</option>
            </select>
          </label>
          <button type="button" disabled={busy} onClick={() => save(true)} className="rounded border border-sky-600 px-2 py-1 font-semibold text-sky-700 hover:bg-sky-50 disabled:opacity-50 dark:text-sky-300 dark:hover:bg-sky-950/40">
            임상 발표 확정
          </button>
          <button type="button" disabled={busy} onClick={() => save(false)} className="rounded border border-border px-2 py-1 text-muted-foreground hover:bg-muted disabled:opacity-50">
            임상 발표 아님
          </button>
          {err && <span className="text-rose-600 dark:text-rose-300">{err}</span>}
        </div>
      )}
    </div>
  );
}

export function ReadoutCards({ rows, onSaved }: { rows: ReadoutRow[]; onSaved: () => void }) {
  if (rows.length === 0) {
    return <div className="text-xs text-muted-foreground">최근 30일 동안 후보 회사의 새 8-K 가 없습니다.</div>;
  }
  return (
    <div className="space-y-2">
      <div className="text-xs text-muted-foreground">{READOUT_NOTE}</div>
      {rows.map((r) => <ReadoutCard key={r.accession} r={r} onSaved={onSaved} />)}
    </div>
  );
}
