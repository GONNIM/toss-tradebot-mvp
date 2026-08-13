"use client";

// 4 bucket 표 · sentiment · seed · market_cap_tier · confidence_tertile
// n<30 회색 처리 (Fable 5 3차 (3a) · 판정 불가 명시)

import type { BucketGroup, ConfidencePredictiveCheck } from "@/lib/serenity-hunter/types";

function _fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function _cls(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  return v >= 0 ? "text-emerald-500" : "text-red-500";
}

const BUCKET_LABELS: Record<string, string> = {
  sentiment: "Sentiment (bullish/bearish/neutral/calibration)",
  seed: "Seed 티커 유무",
  market_cap_tier: "시총 구간 (micro <1B / small 1-10B / mid+)",
  confidence_tertile: "Confidence 3분위 (bottom/mid/top)",
};

export function VerificationBucketTable({
  buckets,
  predictiveCheck,
}: {
  buckets: BucketGroup[];
  predictiveCheck: ConfidencePredictiveCheck;
}) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-sm font-semibold">📊 Bucket 분해 · 부분집합 알파 검증</h2>
      <p className="mt-1 text-[10px] text-muted-foreground">
        n &lt; 30 셀은 회색 "판정 불가" 처리 (Fable 5 · 통계적 신뢰 부족).
      </p>

      <div className="mt-3 space-y-4">
        {buckets.map((b) => (
          <div key={b.name}>
            <h3 className="text-xs font-semibold text-muted-foreground">
              {BUCKET_LABELS[b.name] ?? b.name}
            </h3>
            <table className="mt-1 w-full text-xs">
              <thead className="bg-muted/30">
                <tr>
                  <th className="px-2 py-1 text-left">key</th>
                  <th className="px-2 py-1 text-right">n</th>
                  <th className="px-2 py-1 text-right">hit% +10% 3d</th>
                  <th className="px-2 py-1 text-right">avg return 3d</th>
                  <th className="px-2 py-1 text-right">excess IWM 3d</th>
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r) => (
                  <tr
                    key={r.key}
                    className={`border-b border-border/40 ${
                      r.is_masked ? "opacity-50" : ""
                    }`}
                  >
                    <td className="px-2 py-1 font-mono">{r.key}</td>
                    <td className="px-2 py-1 text-right font-mono">{r.n}</td>
                    <td className="px-2 py-1 text-right font-mono">
                      {r.is_masked ? "판정 불가" : _fmtPct(r.hit_rate_10pct_3d, 2)}
                    </td>
                    <td className={`px-2 py-1 text-right font-mono ${_cls(r.avg_return_3d)}`}>
                      {r.is_masked ? "—" : _fmtPct(r.avg_return_3d, 2)}
                    </td>
                    <td className={`px-2 py-1 text-right font-mono font-bold ${_cls(r.excess_iwm_3d)}`}>
                      {r.is_masked ? "—" : _fmtPct(r.excess_iwm_3d, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {/* Confidence 3분위 예측력 상태 (Fable 5 4차 D2) */}
      <div className="mt-4 rounded border border-border/40 bg-background/40 px-3 py-2">
        <div className="text-xs font-semibold">Confidence 예측력 판정</div>
        <div className="mt-1 text-[11px] text-muted-foreground">
          top {predictiveCheck.top_hit_rate ?? "—"}% (n={predictiveCheck.top_n}) −
          bottom {predictiveCheck.bottom_hit_rate ?? "—"}% (n={predictiveCheck.bottom_n})
          {" = "}
          <span className="font-mono">
            {predictiveCheck.diff_pp === null ? "—" : `${predictiveCheck.diff_pp}pp`}
          </span>
          {" "}
          <StatusBadge status={predictiveCheck.predictive_status} />
        </div>
      </div>
    </section>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "pass") {
    return (
      <span className="ml-1 rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-500">
        ✓ 예측력 확인
      </span>
    );
  }
  if (status === "fail") {
    return (
      <span className="ml-1 rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-red-500">
        ⛔ 예측력 없음 · 컬럼 삭제 대상
      </span>
    );
  }
  return (
    <span className="ml-1 rounded bg-slate-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">
      ⏳ 표본 부족 (n≥30 필요)
    </span>
  );
}
