"use client";

// 저평가 우량주 투자원칙 v1.0 · 헌장 페이지 (2026-08-17)
// 클라이언트 컴포넌트 · 상대 경로 fetch (nginx 프록시)
// charter.json SSOT · backend/principles/charter.json

import { useEffect, useState } from "react";

interface Threshold {
  [key: string]: number | boolean;
}

interface Principle {
  id: number;
  code: string;
  name: string;
  definition: string;
  thresholds: Threshold;
  supporting_condition?: string;
  sector_exception?: string;
  scope?: string;
  loss_handling?: string;
  buyback_definition?: string;
}

interface Revision {
  version: string;
  enacted_at: string;
  changed_by: string;
  summary: string;
  rationale?: string;
}

interface Charter {
  version: string;
  enacted_at: string;
  title: string;
  summary: string;
  units_convention?: string;
  principles: Principle[];
  sell_principle: { status: string; note: string };
  gate_policy: {
    mode: string;
    exempt_signal_types: string[];
    note: string;
  };
  screener_verdict?: { values: string[]; note: string };
  universe: { market: string; note: string };
  data_pipeline: {
    dart_financials: { cadence: string; note: string };
    daily_recompute: { cadence: string; note: string };
  };
  manual_overrides: {
    financial_sector: {
      entries: { ticker: string; value: boolean; reason: string }[];
    };
  };
  revision_history: Revision[];
  disclaimer: string;
}

function formatThreshold(value: number | boolean, key: string): string {
  if (typeof value === "boolean") return value ? "허용" : "불허";
  if (key.includes("ratio") || key.includes("weight")) {
    if (value < 1) return `${(value * 100).toFixed(0)}%`;
  }
  return value.toString();
}

export default function PrinciplesPage() {
  const [charter, setCharter] = useState<Charter | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/principles/charter")
      .then((r) => {
        if (!r.ok) throw new Error(`charter ${r.status}`);
        return r.json();
      })
      .then((d: Charter) => {
        if (!cancelled) setCharter(d);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="text-sm text-red-600">⚠️ 헌장 로드 실패: {error}</p>;
  }
  if (!charter) {
    return <p className="text-sm text-muted-foreground">헌장 로드 중…</p>;
  }

  return (
    <div className="space-y-8">
      <header className="space-y-2 border-b border-border pb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold">📜 {charter.title}</h1>
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
            v{charter.version}
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          제정 {charter.enacted_at} · {charter.summary}
        </p>
        {charter.units_convention && (
          <p className="text-xs text-muted-foreground">
            <strong>단위 규약:</strong> {charter.units_convention}
          </p>
        )}
      </header>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">🎯 5원칙 (매수 필터)</h2>
        <div className="space-y-4">
          {charter.principles.map((p) => (
            <article
              key={p.code}
              className="space-y-2 rounded-lg border border-border bg-card p-4"
            >
              <div className="flex items-baseline justify-between gap-4">
                <h3 className="text-lg font-semibold">
                  <span className="text-muted-foreground">{p.id}.</span> {p.name}
                </h3>
                <code className="text-xs text-muted-foreground">{p.code}</code>
              </div>
              <p className="text-sm">{p.definition}</p>
              <dl className="grid grid-cols-1 gap-1 rounded bg-muted/40 p-3 text-xs font-mono sm:grid-cols-2">
                {Object.entries(p.thresholds).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className="font-semibold">{formatThreshold(v, k)}</dd>
                  </div>
                ))}
              </dl>
              {p.supporting_condition && (
                <p className="text-xs text-muted-foreground">
                  <strong>보조 조건:</strong> {p.supporting_condition}
                </p>
              )}
              {p.sector_exception && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  <strong>업종 예외:</strong> {p.sector_exception}
                </p>
              )}
              {p.buyback_definition && (
                <p className="text-xs text-muted-foreground">
                  <strong>자기주식 취득액 정의:</strong> {p.buyback_definition}
                </p>
              )}
              {p.loss_handling && (
                <p className="text-xs text-rose-600 dark:text-rose-400">
                  <strong>적자 처리:</strong> {p.loss_handling}
                </p>
              )}
              {p.scope && (
                <p className="text-xs text-muted-foreground">
                  <strong>적용 범위:</strong> {p.scope}
                </p>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="text-lg font-semibold">🚧 매도 원칙</h2>
        <p className="text-sm">
          <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800 dark:bg-amber-950 dark:text-amber-300">
            {charter.sell_principle.status}
          </span>{" "}
          {charter.sell_principle.note}
        </p>
      </section>

      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="text-lg font-semibold">🔒 게이트 정책</h2>
        <div className="space-y-1 text-sm">
          <p>
            <strong>모드:</strong>{" "}
            <code className="text-xs">{charter.gate_policy.mode}</code>
          </p>
          <p>
            <strong>면제 signal type:</strong>{" "}
            {charter.gate_policy.exempt_signal_types.length === 0 ? (
              <span className="text-muted-foreground">(없음)</span>
            ) : (
              charter.gate_policy.exempt_signal_types.map((s) => (
                <code
                  key={s}
                  className="ml-1 rounded bg-muted px-1.5 py-0.5 text-xs"
                >
                  {s}
                </code>
              ))
            )}
          </p>
          <p className="text-xs text-muted-foreground">{charter.gate_policy.note}</p>
        </div>
      </section>

      {charter.screener_verdict && (
        <section className="space-y-2 rounded-lg border border-border bg-card p-4">
          <h2 className="text-lg font-semibold">🧪 스크리너 판정 3값</h2>
          <div className="flex flex-wrap gap-2">
            {charter.screener_verdict.values.map((v) => (
              <code
                key={v}
                className="rounded bg-muted px-2 py-0.5 text-xs font-semibold"
              >
                {v}
              </code>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {charter.screener_verdict.note}
          </p>
        </section>
      )}

      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="text-lg font-semibold">📊 대상 종목 & 데이터 파이프라인</h2>
        <div className="space-y-2 text-sm">
          <p>
            <strong>대상:</strong> {charter.universe.market}{" "}
            <span className="text-xs text-muted-foreground">({charter.universe.note})</span>
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="rounded bg-muted/40 p-2 text-xs">
              <p className="font-semibold">DART 재무 수집</p>
              <p className="text-muted-foreground">
                주기: {charter.data_pipeline.dart_financials.cadence}
              </p>
              <p className="text-muted-foreground">
                {charter.data_pipeline.dart_financials.note}
              </p>
            </div>
            <div className="rounded bg-muted/40 p-2 text-xs">
              <p className="font-semibold">일일 재계산</p>
              <p className="text-muted-foreground">
                주기: {charter.data_pipeline.daily_recompute.cadence}
              </p>
              <p className="text-muted-foreground">
                {charter.data_pipeline.daily_recompute.note}
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-3 rounded-lg border border-border bg-card p-4">
        <h2 className="text-lg font-semibold">⚙️ 수동 보정 (Overrides)</h2>
        <p className="text-sm text-muted-foreground">
          금융업 자동 감지가 애매한 종목 (지주사·여전사·특수목적법인 등) 은
          <code className="mx-1 rounded bg-muted px-1 text-xs">
            manual_overrides.financial_sector
          </code>
          에 수동 등재.
        </p>
        {charter.manual_overrides.financial_sector.entries.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            등재된 override 없음 (전종목 자동 감지).
          </p>
        ) : (
          <ul className="space-y-1 text-xs font-mono">
            {charter.manual_overrides.financial_sector.entries.map((e) => (
              <li key={e.ticker}>
                <span className="text-emerald-600">{e.ticker}</span> · {String(e.value)} ·{" "}
                <span className="text-muted-foreground">{e.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">📜 개정 이력</h2>
        <ol className="space-y-3">
          {charter.revision_history.map((r) => (
            <li
              key={r.version}
              className="space-y-1 rounded-lg border border-border bg-card p-3"
            >
              <div className="flex items-baseline justify-between gap-3">
                <div>
                  <span className="rounded bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-700 dark:bg-sky-950 dark:text-sky-300">
                    v{r.version}
                  </span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {r.enacted_at} · {r.changed_by}
                  </span>
                </div>
              </div>
              <p className="text-sm">{r.summary}</p>
              {r.rationale && (
                <p className="text-xs text-muted-foreground">
                  <strong>근거:</strong> {r.rationale}
                </p>
              )}
            </li>
          ))}
        </ol>
      </section>

      <footer className="border-t border-border pt-4 text-xs text-muted-foreground">
        ⚠️ {charter.disclaimer}
      </footer>
    </div>
  );
}
