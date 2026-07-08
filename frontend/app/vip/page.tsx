"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, VipStatus, VipConfig, VipConfigPatch } from "@/lib/api";

function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

function classPnL(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-muted-foreground";
  if (v > 0) return "text-emerald-500";
  if (v < 0) return "text-rose-500";
  return "text-muted-foreground";
}

function StatusBadge({ active }: { active: boolean }) {
  return (
    <span
      className={
        "inline-block rounded-full px-2 py-0.5 text-xs font-medium " +
        (active
          ? "bg-emerald-500/20 text-emerald-400"
          : "bg-muted text-muted-foreground")
      }
    >
      {active ? "ACTIVE" : "INACTIVE"}
    </span>
  );
}

function QuoteCard({ s }: { s: VipStatus }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">
          {s.company_name}{" "}
          <span className="text-sm text-muted-foreground">({s.ticker})</span>
        </h2>
        <div className="text-xs text-muted-foreground">
          {s.is_us_regular_hours ? "🇺🇸 정규장" : "AH/PM·마감"}
        </div>
      </div>
      {s.quote ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <div className="text-xs text-muted-foreground">현재가</div>
            <div className="text-2xl font-bold">
              {num(s.quote.close_price)}{" "}
              <span className="text-xs text-muted-foreground">USD</span>
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">정규장 등락률</div>
            <div className={`text-lg font-semibold ${classPnL(s.quote.fluctuations_ratio / 100)}`}>
              {s.quote.fluctuations_ratio >= 0 ? "+" : ""}
              {s.quote.fluctuations_ratio.toFixed(2)}%
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">AH/PM 등락률</div>
            <div className={`text-lg font-semibold ${classPnL((s.quote.over_market_ratio ?? 0) / 100)}`}>
              {s.quote.over_market_ratio === null
                ? "—"
                : (s.quote.over_market_ratio >= 0 ? "+" : "") +
                  s.quote.over_market_ratio.toFixed(2) +
                  "%"}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted-foreground">P&L (매수가 대비)</div>
            <div className={`text-2xl font-bold ${classPnL(s.pnl)}`}>
              {pct(s.pnl)}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">
          quote 미수신 — 감시 비활성 또는 네트워크 이슈
        </div>
      )}
      {s.qty > 0 && s.quote && (
        <div className="mt-3 text-sm text-muted-foreground">
          진입 {num(s.avg_price)} · 수량 {s.qty} · 손익{" "}
          <span className={classPnL(s.pnl)}>
            {((s.quote.close_price - s.avg_price) * s.qty >= 0 ? "+" : "") +
              ((s.quote.close_price - s.avg_price) * s.qty).toFixed(2)}{" "}
            USD
          </span>
        </div>
      )}
    </div>
  );
}

function ThresholdsCard({ s }: { s: VipStatus }) {
  const t = s.thresholds;
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-lg font-semibold">임계값 (읽기 전용)</h2>
      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
        <div>
          <div className="text-xs text-muted-foreground">TP1</div>
          <div className="font-medium">{pct(t.tp1_pct)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">TP2</div>
          <div className="font-medium">{pct(t.tp2_pct)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">STOP</div>
          <div className="font-medium">{pct(t.stop_pct)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">TRAIL ARM</div>
          <div className="font-medium">{pct(t.trail_arm_pct)}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">TRAIL GIVEBACK</div>
          <div className="font-medium">{pct(t.trail_giveback_pct)}</div>
        </div>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        평균가·수량·임계값 변경은 서버 <code>.env</code> 편집 후 <code>systemctl restart tradebot-cron</code>.
      </p>
    </div>
  );
}

function ActivistCard({
  s,
  onEdit,
}: {
  s: VipStatus;
  onEdit: () => void;
}) {
  const a = s.activist;
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold">🕵️ Activist 감시</h2>
        <div className="flex items-center gap-2">
          <StatusBadge active={s.activist_active} />
          <button
            onClick={onEdit}
            className="rounded border border-border bg-background px-3 py-1 text-xs hover:bg-muted"
          >
            편집
          </button>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div>
          <div className="text-xs text-muted-foreground">이름</div>
          <div>{a.name || "—"}</div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">CIK</div>
          <div className="font-mono">{a.cik || "—"}</div>
        </div>
        <div className="sm:col-span-2">
          <div className="text-xs text-muted-foreground">대상 키워드</div>
          <div className="flex flex-wrap gap-1">
            {a.keywords.length ? (
              a.keywords.map((k) => (
                <span
                  key={k}
                  className="rounded bg-muted px-2 py-0.5 text-xs font-mono"
                >
                  {k}
                </span>
              ))
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
        </div>
      </div>

      {a.latest_target ? (
        <div className="mt-4 border-t border-border pt-3">
          <div className="text-xs text-muted-foreground">최신 대상 필링</div>
          <div className="mt-1 text-sm">
            <span className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-amber-400">
              {a.latest_target.form}
            </span>{" "}
            <span className="font-medium">{a.latest_target.filing_date}</span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {a.latest_target.primary_desc || "(desc 없음)"} ·{" "}
            <span className="font-mono">{a.latest_target.accession}</span>
          </div>
        </div>
      ) : a.enabled ? (
        <div className="mt-4 border-t border-border pt-3 text-xs text-muted-foreground">
          대상 매치 필링 없음. 아래 최근 이력에서 수동 확인 가능.
        </div>
      ) : null}

      {a.recent_forms && a.recent_forms.length > 0 && (
        <details className="mt-3 border-t border-border pt-3">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            최근 필링 10건 (activist 관점 전체)
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {a.recent_forms.map((f) => (
              <li key={f.accession} className="flex justify-between gap-2">
                <span className="font-mono text-muted-foreground">
                  {f.date}
                </span>
                <span className="w-32 truncate">{f.form}</span>
                <span className="flex-1 truncate text-muted-foreground">
                  {f.desc || "—"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ActivistEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: VipConfig;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(initial.activist.enabled);
  const [cik, setCik] = useState(initial.activist.cik);
  const [name, setName] = useState(initial.activist.name);
  const [keywords, setKeywords] = useState(initial.activist.keywords.join(", "));
  const [saveError, setSaveError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: (body: VipConfigPatch) => api.memeWatch.vip.patchConfig(body),
    onSuccess: () => {
      onSaved();
    },
    onError: (err: Error) => {
      setSaveError(err.message);
    },
  });

  const submit = () => {
    setSaveError(null);
    const kw = keywords
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    mut.mutate({
      activist: { enabled, cik: cik.trim(), name: name.trim(), keywords: kw },
    });
  };

  const reset = () => {
    mut.mutate({
      activist: { enabled: false, cik: "", name: "", keywords: [] },
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Activist 설정 편집</h3>
          <button
            onClick={onClose}
            className="rounded border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            닫기
          </button>
        </div>

        <div className="space-y-3">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span>Activist tracker 활성</span>
          </label>

          <div>
            <label className="text-xs text-muted-foreground">CIK</label>
            <input
              type="text"
              value={cik}
              onChange={(e) => setCik(e.target.value)}
              placeholder="예: 0001345471 (Trian)"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              SEC EDGAR CIK — 10자리 zero-padding 자동. 편집 후 저장 즉시 반영 (재시작 불필요).
            </p>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">이름 (알림 표기용)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: Trian Partners"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">
              대상 키워드 (콤마 구분)
            </label>
            <input
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="예: WEN, WENDY"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
            />
            <p className="mt-1 text-xs text-muted-foreground">
              SEC 필링 description 에 이 문자열이 포함되면 매치.
            </p>
          </div>

          {saveError && (
            <div className="rounded border border-rose-500/50 bg-rose-500/10 p-2 text-xs text-rose-400">
              저장 실패: {saveError}
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-between gap-2">
          <button
            onClick={reset}
            disabled={mut.isPending}
            className="rounded border border-rose-500/50 px-3 py-1.5 text-xs text-rose-400 hover:bg-rose-500/10 disabled:opacity-50"
          >
            override 초기화 (env 기본값 복귀)
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              취소
            </button>
            <button
              onClick={submit}
              disabled={mut.isPending}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {mut.isPending ? "저장 중…" : "저장"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function VipPage() {
  const qc = useQueryClient();
  const [editorOpen, setEditorOpen] = useState(false);

  const statusQ = useQuery({
    queryKey: ["vip", "status"],
    queryFn: () => api.memeWatch.vip.status(),
    refetchInterval: 30_000,
  });

  const configQ = useQuery({
    queryKey: ["vip", "config"],
    queryFn: () => api.memeWatch.vip.getConfig(),
    enabled: editorOpen,
  });

  useEffect(() => {
    // 편집기 열 때 최신 config 강제 로드
    if (editorOpen) qc.invalidateQueries({ queryKey: ["vip", "config"] });
  }, [editorOpen, qc]);

  const s = statusQ.data;

  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">🕵️ VIP 개별 감시</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            매수가 기반 알림(TP/STOP/TRAIL) + Activist SEC 필링 추적. 30초 폴링(정규장) / 5분(AH·PM).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {s && <StatusBadge active={s.active} />}
          <button
            onClick={() => statusQ.refetch()}
            className="rounded border border-border bg-background px-3 py-1 text-xs hover:bg-muted"
          >
            새로고침
          </button>
        </div>
      </header>

      {statusQ.isLoading && (
        <div className="rounded border border-border bg-card p-4 text-sm text-muted-foreground">
          로딩 중…
        </div>
      )}

      {statusQ.isError && (
        <div className="rounded border border-rose-500/50 bg-rose-500/10 p-4 text-sm text-rose-400">
          상태 조회 실패: {(statusQ.error as Error).message}
        </div>
      )}

      {s && !s.active && (
        <div className="rounded border border-amber-500/50 bg-amber-500/10 p-4 text-sm">
          <div className="font-medium text-amber-400">감시 비활성</div>
          <p className="mt-1 text-muted-foreground">
            서버 <code>.env</code> 에 <code>VIP_ENABLED=true</code> 와{" "}
            <code>VIP_AVG_PRICE</code> (0 초과) 설정 후{" "}
            <code>systemctl restart tradebot-cron</code>. 그때까지 폴링·알림 태스크는 tick 진입 즉시 skip.
          </p>
        </div>
      )}

      {s && (
        <>
          <QuoteCard s={s} />
          <ThresholdsCard s={s} />
          <ActivistCard s={s} onEdit={() => setEditorOpen(true)} />

          {Object.keys(s.sent_events).length > 0 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-lg font-semibold">최근 발송 이벤트 (24h cooldown)</h2>
              <ul className="text-sm">
                {Object.entries(s.sent_events).map(([evt, ts]) => (
                  <li key={evt} className="flex justify-between py-1">
                    <span className="font-mono">{evt}</span>
                    <span className="text-muted-foreground">
                      {new Date(ts * 1000).toLocaleString("ko-KR")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {editorOpen && configQ.data && (
        <ActivistEditor
          initial={configQ.data}
          onClose={() => setEditorOpen(false)}
          onSaved={() => {
            setEditorOpen(false);
            qc.invalidateQueries({ queryKey: ["vip", "status"] });
            qc.invalidateQueries({ queryKey: ["vip", "config"] });
          }}
        />
      )}
    </div>
  );
}
