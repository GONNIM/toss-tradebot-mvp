"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  ActivistEntry,
  ActivistEventItem,
  ActivistIntensity,
  ActivistStatusResponse,
  ActivistUniverseResponse,
  ActivistUpsert,
  ActivistWolfPacksResponse,
  WolfPackGroup,
} from "@/lib/api";

// ─────────────────────────────────────────────
// helpers
// ─────────────────────────────────────────────

function relTime(unixSec: number): string {
  const now = Date.now() / 1000;
  const diff = now - unixSec;
  if (diff < 60) return `${Math.floor(diff)}초 전`;
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

const INTENSITY_META: Record<
  ActivistIntensity,
  { icon: string; label: string; hint: string; className: string }
> = {
  REGIME_CHANGE: {
    icon: "🚨",
    label: "REGIME CHANGE (13G→13D 전환)",
    hint: "passive → active 태세 전환 · 최상 신호 · 즉시 검토",
    className: "border-pink-500/60 bg-pink-500/20 text-pink-200 ring-2 ring-pink-500/50",
  },
  CRITICAL: {
    icon: "🌋",
    label: "CRITICAL",
    hint: "즉시 검토 · 신규 SC 13D 또는 Wolf Pack",
    className: "border-rose-500/50 bg-rose-500/10 text-rose-300",
  },
  STRONG: {
    icon: "🔥",
    label: "STRONG",
    hint: "관심 · 지분 변동·수정본",
    className: "border-amber-500/50 bg-amber-500/10 text-amber-300",
  },
  INSIDER: {
    icon: "👤",
    label: "INSIDER (임원 매매)",
    hint: "activism 진입 종목의 임원·주요주주 매매 · 동조/이탈 방향 확인",
    className: "border-cyan-500/50 bg-cyan-500/10 text-cyan-300",
  },
  WATCH: {
    icon: "⚠️",
    label: "WATCH",
    hint: "참고 · passive 성 필링",
    className: "border-indigo-500/50 bg-indigo-500/10 text-indigo-300",
  },
  NOTE: {
    icon: "📝",
    label: "NOTE",
    hint: "기록만",
    className: "border-border bg-muted text-muted-foreground",
  },
};

function EventRow({ e }: { e: ActivistEventItem }) {
  const filerUrl = e.filer_search_url;
  const filingUrl = e.filing_detail_url;
  const searchQuery = e.target_desc || e.form;
  const websearchUrl = e.country === "KR"
    ? `https://search.naver.com/search.naver?query=${encodeURIComponent(searchQuery)}`
    : `https://www.google.com/search?q=${encodeURIComponent(searchQuery + " SEC filing")}`;

  return (
    <div className="rounded border border-border/60 p-3 text-sm">
      {/* 헤더 · 폼 배지 + 힌트 + 발신자 */}
      <div className="flex items-baseline gap-2 flex-wrap">
        <span
          className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-xs text-amber-400"
          title={e.form_hint || undefined}
        >
          {e.form}
        </span>
        {e.form_hint && (
          <span className="text-xs text-muted-foreground italic">
            {e.form_hint}
          </span>
        )}
        <span className="ml-auto text-xs font-mono text-muted-foreground">
          score {e.score}
        </span>
      </div>

      {/* Filer 이름 + Tier + country */}
      <div className="mt-1.5 flex items-baseline gap-2 flex-wrap">
        {e.filer_tier && (
          <span
            className={
              "rounded px-1.5 py-0.5 text-[10px] font-mono " +
              (e.filer_tier === 1
                ? "bg-emerald-500/20 text-emerald-300"
                : e.filer_tier === 2
                ? "bg-sky-500/20 text-sky-300"
                : "bg-muted text-muted-foreground")
            }
          >
            T{e.filer_tier}
          </span>
        )}
        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono">
          {e.country}
        </span>
        <span className="font-medium">{e.filer_name}</span>
        {e.filer_cik && (
          <span className="text-[10px] font-mono text-muted-foreground">
            CIK {e.filer_cik}
          </span>
        )}
      </div>

      {/* 메타 */}
      <div className="mt-1 text-xs text-muted-foreground">
        Filing {e.filing_date} · Accession{" "}
        <span className="font-mono">{e.accession}</span> · 감지 {relTime(e.detected_at)}
      </div>

      {/* 대상 회사·종목 · 지분 상세 (XML 파싱 결과) · 강한 대비 */}
      <div className="mt-3 rounded-lg border-2 border-cyan-500/60 bg-slate-950/70 p-3 text-sm shadow-lg">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-cyan-300">
            🎯 대상 종목
          </span>
          {e.details?.issuer_cik && (
            <span className="ml-auto text-[10px] font-mono text-slate-400">
              issuer CIK {e.details.issuer_cik}
              {e.details.issuer_cusip && ` · CUSIP ${e.details.issuer_cusip}`}
            </span>
          )}
        </div>

        <div className="flex items-baseline gap-2 flex-wrap">
          {e.target_ticker && (
            <span className="rounded-md bg-cyan-500 px-2.5 py-1 font-mono text-sm font-bold text-white shadow">
              {e.target_ticker}
            </span>
          )}
          <span className="text-lg font-bold text-white">
            {e.details?.issuer_name || e.target_desc || (
              <span className="text-slate-400 italic font-normal">
                회사명 미확인 — 원문 링크 확인 필요
              </span>
            )}
          </span>
        </div>

        {/* 지분 상세 grid — 컬러 톤 · 큰 폰트 · 강한 대비 */}
        {(e.details?.percent_of_class !== undefined ||
          e.details?.aggregate_amount_owned !== undefined ||
          e.details?.amendment_no !== undefined ||
          e.details?.date_of_event) && (
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {e.details?.percent_of_class !== null &&
             e.details?.percent_of_class !== undefined && (
              <div className="rounded-lg border border-cyan-400/50 bg-cyan-500/15 p-2">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-cyan-300">
                  지분율
                </div>
                <div className="mt-0.5 text-3xl font-black leading-none text-cyan-100">
                  {e.details.percent_of_class.toFixed(1)}
                  <span className="text-xl">%</span>
                </div>
              </div>
            )}
            {e.details?.aggregate_amount_owned !== null &&
             e.details?.aggregate_amount_owned !== undefined && (
              <div className="rounded-lg border border-emerald-400/50 bg-emerald-500/15 p-2">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">
                  보유 주식
                </div>
                <div className="mt-0.5 text-base font-bold font-mono text-emerald-100">
                  {e.details.aggregate_amount_owned.toLocaleString()}
                </div>
              </div>
            )}
            {e.details?.amendment_no !== null &&
             e.details?.amendment_no !== undefined && (
              <div className="rounded-lg border border-fuchsia-400/50 bg-fuchsia-500/15 p-2">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-fuchsia-300">
                  수정 차수
                </div>
                <div className="mt-0.5 text-base font-bold text-fuchsia-100">
                  Amendment #{e.details.amendment_no}
                </div>
              </div>
            )}
            {e.details?.date_of_event && (
              <div className="rounded-lg border border-indigo-400/50 bg-indigo-500/15 p-2">
                <div className="text-[10px] font-semibold uppercase tracking-wide text-indigo-300">
                  이벤트 발생일
                </div>
                <div className="mt-0.5 text-base font-bold text-indigo-100">
                  {e.details.date_of_event}
                </div>
              </div>
            )}
          </div>
        )}

        {e.details?.securities_class_title && (
          <div className="mt-3 rounded bg-slate-800/70 px-2 py-1 text-xs text-slate-200">
            <span className="font-semibold text-slate-400">증권 클래스:</span>{" "}
            {e.details.securities_class_title}
          </div>
        )}

        {e.details?.transaction_purpose && (
          <details className="mt-3 rounded border border-slate-700 bg-slate-900/60">
            <summary className="cursor-pointer px-2 py-1 text-xs font-semibold text-amber-300 hover:bg-slate-800/50">
              📝 Item 4 — 거래 목적/사유 (원문 발췌 · 클릭 펼치기)
            </summary>
            <div className="whitespace-pre-wrap border-t border-slate-700 p-2 font-mono text-[11px] text-slate-100">
              {e.details.transaction_purpose}
            </div>
          </details>
        )}
      </div>

      {/* 액션 힌트 */}
      {e.action_hint && (
        <div className="mt-2 rounded bg-primary/10 p-2 text-xs">
          <strong>추천 액션:</strong> {e.action_hint}
        </div>
      )}

      {/* Wolf Pack */}
      {e.wolf_pack.length > 0 && (
        <div className="mt-2 rounded border border-rose-500/50 bg-rose-500/10 p-1.5 text-xs text-rose-400">
          🐺 Wolf Pack (30d): 다른 activist {e.wolf_pack.length}명 동일 종목 진입 —{" "}
          {e.wolf_pack.join(", ")}
        </div>
      )}

      {/* 링크 */}
      <div className="mt-2 flex gap-2 text-xs flex-wrap">
        {filingUrl && (
          <a
            href={filingUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border border-border bg-background px-2 py-0.5 hover:bg-muted"
          >
            📄 원문 필링 ↗
          </a>
        )}
        {filerUrl && (
          <a
            href={filerUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border border-border bg-background px-2 py-0.5 hover:bg-muted"
          >
            🔍 {e.filer_name.split(" ")[0]} 다른 필링 ↗
          </a>
        )}
        <a
          href={websearchUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded border border-border bg-background px-2 py-0.5 hover:bg-muted"
        >
          {e.country === "KR" ? "🇰🇷" : "🌐"} 웹 검색 ↗
        </a>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Wolf Pack 시각화
// ─────────────────────────────────────────────

const PACK_STYLE: Record<
  WolfPackGroup["intensity_label"],
  { icon: string; label: string; className: string }
> = {
  CRITICAL_PACK: {
    icon: "🐺🐺",
    label: "CRITICAL PACK",
    className: "border-pink-500/60 bg-pink-500/10 ring-2 ring-pink-500/50",
  },
  STRONG_PACK: {
    icon: "🐺",
    label: "STRONG PACK",
    className: "border-orange-500/50 bg-orange-500/10",
  },
  PACK: {
    icon: "🐺",
    label: "PACK",
    className: "border-yellow-500/40 bg-yellow-500/5",
  },
};

function TierBadge({ tier }: { tier: number }) {
  const color =
    tier === 1
      ? "bg-emerald-500/20 text-emerald-300"
      : tier === 2
      ? "bg-sky-500/20 text-sky-300"
      : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${color}`}>
      T{tier}
    </span>
  );
}

function WolfPackEntryRow({
  e,
  isFirst,
  isLast,
}: {
  e: WolfPackGroup["entries"][number];
  isFirst: boolean;
  isLast: boolean;
}) {
  return (
    <div className="relative flex gap-3">
      <div className="flex flex-col items-center">
        <div className="h-3 w-3 rounded-full bg-pink-500 ring-2 ring-background" />
        {!isLast && <div className="w-px flex-1 bg-pink-500/40" />}
      </div>
      <div className="mb-3 flex-1 pb-2">
        <div className="flex items-baseline gap-2 flex-wrap">
          <TierBadge tier={e.tier} />
          <span className="font-medium">{e.filer_name}</span>
          <span className="rounded bg-amber-500/20 px-2 py-0.5 text-xs font-mono text-amber-400">
            {e.form}
          </span>
          {isFirst && (
            <span className="text-xs text-muted-foreground">🩸 최초 진입</span>
          )}
          {isLast && !isFirst && (
            <span className="text-xs text-pink-400">⚡ 최신 진입</span>
          )}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          Filing {e.filing_date} · Accession{" "}
          <span className="font-mono">{e.accession}</span>
        </div>
      </div>
    </div>
  );
}

function WolfPackCard({ g }: { g: WolfPackGroup }) {
  const style = PACK_STYLE[g.intensity_label];
  const yahooTicker = g.target_ticker;
  return (
    <div className={`rounded-lg border p-4 ${style.className}`}>
      <div className="mb-3 flex items-start justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-2xl">{style.icon}</span>
            <span className="rounded bg-pink-500/30 px-2 py-0.5 text-xs font-mono font-semibold text-pink-100">
              {g.country}
            </span>
            <span className="text-xl font-bold font-mono">{g.target_ticker}</span>
            <span className="text-xs text-muted-foreground">
              · {g.target_desc.split(" · ")[0].split(" - ")[0].slice(0, 50)}
            </span>
          </div>
          <div className="mt-1 text-xs">
            <span className="mr-2 font-semibold">{style.label}</span>
            <span className="text-muted-foreground">
              score {g.intensity_score} · {g.activist_count}명 activist ({g.tier1_count} T1)
              · {g.days_span}일 span
            </span>
          </div>
        </div>
        <div className="flex gap-1 text-xs">
          {g.country === "US" && (
            <a
              href={`https://finance.yahoo.com/quote/${yahooTicker}`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded border border-border bg-background/50 px-2 py-1 hover:bg-muted"
            >
              Yahoo ↗
            </a>
          )}
          {g.target_cik && g.country === "US" && (
            <a
              href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${g.target_cik}&type=SC+13`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded border border-border bg-background/50 px-2 py-1 hover:bg-muted"
            >
              SEC ↗
            </a>
          )}
        </div>
      </div>

      <div className="mt-2">
        <div className="mb-2 text-xs font-medium text-muted-foreground">
          진입 타임라인 (오래된 순)
        </div>
        {g.entries.map((e, i) => (
          <WolfPackEntryRow
            key={e.filer_key}
            e={e}
            isFirst={i === 0}
            isLast={i === g.entries.length - 1}
          />
        ))}
      </div>
    </div>
  );
}

function WolfPackSection({ data }: { data: ActivistWolfPacksResponse }) {
  if (data.total === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
        🐺 Wolf Pack — 최근 30일 안에 서로 다른 activist 가 2명 이상 진입한 종목이 아직
        없습니다. Universe activism 이 감지되면 자동 그룹핑됩니다.
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">
          🐺 Wolf Pack — 30일 window 종목별 다중 activist 진입
        </h2>
        <div className="text-xs text-muted-foreground">
          총 {data.total} · CRITICAL {data.critical_count} · STRONG {data.strong_count}
        </div>
      </div>
      {data.groups.map((g) => (
        <WolfPackCard key={g.target_ticker} g={g} />
      ))}
    </div>
  );
}

function BucketCard({
  intensity,
  events,
}: {
  intensity: ActivistIntensity;
  events: ActivistEventItem[];
}) {
  const meta = INTENSITY_META[intensity];
  if (!events || events.length === 0) return null;
  return (
    <div className={`rounded-lg border p-4 ${meta.className}`}>
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-lg font-bold">
          {meta.icon} {meta.label}
        </h2>
        <span className="rounded-full bg-background px-2 py-0.5 text-xs font-medium">
          {events.length}
        </span>
        <span className="text-xs">{meta.hint}</span>
      </div>
      <div className="space-y-2">
        {events.map((e) => (
          <EventRow key={e.id} e={e} />
        ))}
      </div>
    </div>
  );
}

function UniverseCard({
  u,
  onEdit,
  onAdd,
  onDelete,
}: {
  u: ActivistUniverseResponse;
  onEdit: (a: ActivistEntry) => void;
  onAdd: () => void;
  onDelete: (a: ActivistEntry) => void;
}) {
  const active = u.activists.filter((a) => a.enabled);
  const inactive = u.activists.filter((a) => !a.enabled);
  const [filter, setFilter] = useState<"all" | "US" | "KR">("all");
  const filtered = u.activists.filter(
    (a) => filter === "all" || a.country === filter,
  );

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">
          🎯 감시 Universe ({active.length} active
          {inactive.length > 0 ? ` · ${inactive.length} inactive` : ""})
        </h2>
        <div className="flex items-center gap-2">
          <div className="flex overflow-hidden rounded border border-border text-xs">
            {(["all", "US", "KR"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2 py-1 ${
                  filter === f ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
              >
                {f === "all" ? "전체" : f}
              </button>
            ))}
          </div>
          <button
            onClick={onAdd}
            className="rounded bg-emerald-600 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-700"
          >
            + Activist 추가
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-1 text-xs">
        {filtered.map((a) => (
          <div
            key={a.key}
            className={`flex items-center gap-2 rounded border border-border/60 px-2 py-1.5 ${
              a.enabled ? "" : "opacity-50"
            }`}
          >
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono">
              {a.country}·T{a.tier}
            </span>
            <span className="flex-1 truncate">{a.name}</span>
            <span className="hidden sm:inline font-mono text-[10px] text-muted-foreground">
              {a.cik || a.corp_code || "—"}
            </span>
            <button
              onClick={() => onEdit(a)}
              className="rounded border border-border bg-background px-2 py-0.5 hover:bg-muted"
            >
              편집
            </button>
            <button
              onClick={() => onDelete(a)}
              className="rounded border border-rose-500/50 bg-rose-500/10 px-2 py-0.5 text-rose-400 hover:bg-rose-500/20"
            >
              삭제
            </button>
          </div>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="mt-2 text-xs text-muted-foreground">필터 조건 항목 없음.</div>
      )}
    </div>
  );
}

function UniverseEditor({
  initial,
  isNew,
  onClose,
  onSaved,
}: {
  initial: ActivistEntry | null;
  isNew: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [key, setKey] = useState(initial?.key ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [country, setCountry] = useState<"US" | "KR">(
    (initial?.country as "US" | "KR") ?? "US",
  );
  const [tier, setTier] = useState<number>(initial?.tier ?? 2);
  const [cik, setCik] = useState(initial?.cik ?? "");
  const [corpCode, setCorpCode] = useState(initial?.corp_code ?? "");
  const [keywords, setKeywords] = useState((initial?.keywords ?? []).join(", "));
  const [enabled, setEnabled] = useState<boolean>(initial?.enabled ?? true);
  const [saveError, setSaveError] = useState<string | null>(null);

  const mut = useMutation({
    mutationFn: (body: ActivistUpsert) => api.memeWatch.activist.patchUniverse(body),
    onSuccess: () => {
      onSaved();
    },
    onError: (err: Error) => setSaveError(err.message),
  });

  const submit = () => {
    setSaveError(null);
    const trimmedKey = key.trim();
    if (!trimmedKey) {
      setSaveError("key 는 필수입니다 (snake_case 안정 식별자)");
      return;
    }
    const kw = keywords.split(",").map((s) => s.trim()).filter(Boolean);
    mut.mutate({
      key: trimmedKey,
      name: name.trim() || trimmedKey,
      country,
      tier,
      cik: country === "US" ? cik.trim().padStart(10, "0") : undefined,
      corp_code: country === "KR" ? corpCode.trim() : undefined,
      keywords: kw,
      enabled,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">
            {isNew ? "신규 Activist 추가" : `편집: ${initial?.name ?? ""}`}
          </h3>
          <button
            onClick={onClose}
            className="rounded border border-border px-2 py-1 text-xs hover:bg-muted"
          >
            닫기
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">
              key (snake_case 안정 식별자 · 필수)
            </label>
            <input
              type="text"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="예: elliott_investment_mgmt"
              disabled={!isNew}
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono disabled:opacity-60"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">이름 (알림 표기)</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="예: Elliott Investment Management L.P."
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-muted-foreground">국가</label>
              <select
                value={country}
                onChange={(e) => setCountry(e.target.value as "US" | "KR")}
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
              >
                <option value="US">US · SEC</option>
                <option value="KR">KR · DART</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Tier</label>
              <select
                value={tier}
                onChange={(e) => setTier(Number(e.target.value))}
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm"
              >
                <option value={1}>1 · 실행력 최상위</option>
                <option value={2}>2 · 중간</option>
                <option value={3}>3 · 소형·특화</option>
              </select>
            </div>
          </div>

          {country === "US" && (
            <div>
              <label className="text-xs text-muted-foreground">SEC CIK (10자리 zero-padding 자동)</label>
              <input
                type="text"
                value={cik}
                onChange={(e) => setCik(e.target.value)}
                placeholder="예: 0001345471"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                data.sec.gov/submissions/CIK{"{cik}"}.json 폴링에 사용됨
              </p>
            </div>
          )}

          {country === "KR" && (
            <div>
              <label className="text-xs text-muted-foreground">DART corp_code (8자리 · 선택)</label>
              <input
                type="text"
                value={corpCode}
                onChange={(e) => setCorpCode(e.target.value)}
                placeholder="예: 00126380"
                className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
              />
              <p className="mt-1 text-xs text-muted-foreground">
                이름 정규화 매칭 우선 · corp_code 는 참고용
              </p>
            </div>
          )}

          <div>
            <label className="text-xs text-muted-foreground">
              대상 키워드 (콤마 구분 · 선택)
            </label>
            <input
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="예: WEN, WENDY"
              className="mt-1 w-full rounded border border-border bg-background px-2 py-1 text-sm font-mono"
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span>활성 (감시 대상)</span>
          </label>

          {saveError && (
            <div className="rounded border border-rose-500/50 bg-rose-500/10 p-2 text-xs text-rose-400">
              저장 실패: {saveError}
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
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
  );
}

export default function ActivistRadarPage() {
  const qc = useQueryClient();
  const [editorTarget, setEditorTarget] = useState<ActivistEntry | null>(null);
  const [editorIsNew, setEditorIsNew] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);

  const statusQ = useQuery({
    queryKey: ["activist", "status"],
    queryFn: () => api.memeWatch.activist.status(),
    refetchInterval: 60_000,
  });
  const wolfPacksQ = useQuery({
    queryKey: ["activist", "wolf-packs"],
    queryFn: () => api.memeWatch.activist.wolfPacks(),
    refetchInterval: 60_000,
  });
  const universeQ = useQuery({
    queryKey: ["activist", "universe"],
    queryFn: () => api.memeWatch.activist.universe(),
  });

  const deleteMut = useMutation({
    mutationFn: (key: string) => api.memeWatch.activist.deleteUniverse(key),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["activist", "universe"] });
      qc.invalidateQueries({ queryKey: ["activist", "status"] });
    },
  });

  const openEdit = (a: ActivistEntry) => {
    setEditorTarget(a);
    setEditorIsNew(false);
    setEditorOpen(true);
  };

  const openNew = () => {
    setEditorTarget(null);
    setEditorIsNew(true);
    setEditorOpen(true);
  };

  const requestDelete = (a: ActivistEntry) => {
    if (confirm(`Universe 에서 "${a.name}" (${a.key}) 를 제거할까요? 감시 목록에서 완전 삭제됩니다.`)) {
      deleteMut.mutate(a.key);
    }
  };

  const s = statusQ.data;

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-3xl font-bold">🐺 Activist Radar</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          헤지펀드 경영권 매수 초기 신호 감시 · SEC 13D/G 필링 실시간 폴링 (5분) ·
          Wolf Pack 감지 (30일 window)
        </p>
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

      {s && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
          <StatBox
            label="Universe"
            value={`${s.universe_size} 개`}
            hint={`US ${s.universe_us} · KR ${s.universe_kr}`}
          />
          <StatBox label="누적 이벤트" value={`${s.events_total}`} />
          <StatBox
            label="CRITICAL"
            value={`${s.buckets.CRITICAL?.length ?? 0}`}
            hint="즉시 검토"
          />
          <StatBox
            label="STRONG"
            value={`${s.buckets.STRONG?.length ?? 0}`}
            hint="관심"
          />
        </div>
      )}

      {/* 🐺 Wolf Pack — 최상단 강조 */}
      {wolfPacksQ.data && <WolfPackSection data={wolfPacksQ.data} />}

      {s && (
        <>
          <BucketCard intensity="REGIME_CHANGE" events={s.buckets.REGIME_CHANGE || []} />
          <BucketCard intensity="CRITICAL" events={s.buckets.CRITICAL || []} />
          <BucketCard intensity="STRONG" events={s.buckets.STRONG || []} />
          <BucketCard intensity="INSIDER" events={s.buckets.INSIDER || []} />
          <BucketCard intensity="WATCH" events={s.buckets.WATCH || []} />
          {(s.insider_watchlist_kr || []).length > 0 && (
            <div className="rounded-lg border border-cyan-500/40 bg-cyan-500/5 p-3 text-sm">
              <div className="mb-1 font-medium text-cyan-300">
                👤 KR Insider Watchlist ({s.insider_watchlist_kr!.length} 종목 · 최근 90일 activism 진입 자동 추적)
              </div>
              <div className="flex flex-wrap gap-1 font-mono text-xs">
                {s.insider_watchlist_kr!.map((code) => (
                  <span key={code} className="rounded bg-cyan-500/20 px-2 py-0.5">
                    {code}
                  </span>
                ))}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                이 종목들의 임원·주요주주 소유상황보고서(D002) 를 5분 폴링 · 신규 감지 시 👤 INSIDER 이벤트로 기록
              </div>
            </div>
          )}
          {(s.insider_watchlist_us || []).length > 0 && (
            <div className="rounded-lg border border-cyan-500/40 bg-cyan-500/5 p-3 text-sm">
              <div className="mb-1 font-medium text-cyan-300">
                👤 US Insider Watchlist ({s.insider_watchlist_us!.length} 회사 · 최근 90일 activism 진입 자동 추적)
              </div>
              <div className="flex flex-col gap-1 text-xs">
                {s.insider_watchlist_us!.map((w) => (
                  <div key={w.cik} className="flex gap-2 items-baseline">
                    <span className="rounded bg-cyan-500/20 px-2 py-0.5 font-mono font-semibold">
                      {w.ticker}
                    </span>
                    <span className="text-muted-foreground truncate">{w.name}</span>
                    <span className="ml-auto font-mono text-[10px] text-muted-foreground">
                      CIK {w.cik}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                이 회사들의 SEC Form 4 (임원·주요주주 매매) 를 10분 폴링 · 방향(A 매수 / D 매도) XML 파싱 · 👤 INSIDER 이벤트
              </div>
            </div>
          )}
        </>
      )}

      {s && (s.events_total === 0) && (
        <div className="rounded border border-amber-500/50 bg-amber-500/10 p-4 text-sm text-amber-300">
          아직 감지된 신규 필링이 없습니다. 첫 tick 은 baseline (알림 없음), 다음 tick 부터 실 신규
          필링만 이벤트로 기록됩니다. 5분 간격 폴링이라 초기엔 이벤트가 없어도 정상입니다.
        </div>
      )}

      {universeQ.data && (
        <UniverseCard
          u={universeQ.data}
          onEdit={openEdit}
          onAdd={openNew}
          onDelete={requestDelete}
        />
      )}

      {editorOpen && (
        <UniverseEditor
          initial={editorTarget}
          isNew={editorIsNew}
          onClose={() => setEditorOpen(false)}
          onSaved={() => {
            setEditorOpen(false);
            qc.invalidateQueries({ queryKey: ["activist", "universe"] });
            qc.invalidateQueries({ queryKey: ["activist", "status"] });
          }}
        />
      )}

      <details className="rounded-lg border border-border bg-card p-4">
        <summary className="cursor-pointer text-lg font-semibold">
          📖 강도 등급·서식 의미
        </summary>
        <div className="mt-3 space-y-2 text-sm">
          <div>
            <strong>🚨 REGIME CHANGE (score 100)</strong> — 같은 filer 가 이전에 13G(passive) 를
            낸 대상에 이번에 13D(active) 를 낸 케이스. <em>가장 강한 초기 신호.</em>
          </div>
          <div>
            <strong>🌋 CRITICAL (80+)</strong> — 신규 SC 13D · Wolf Pack (Tier 1 activist × wolf bonus).
          </div>
          <div>
            <strong>🔥 STRONG (60~79)</strong> — SC 13D/A 지분 변동·수정본 · Tier 1 activist.
          </div>
          <div>
            <strong>👤 INSIDER (Phase E)</strong> — activism 진입 종목 (최근 90일 KR)의
            임원·주요주주 매매(D002). 동조/이탈 방향 판단용.
          </div>
          <div>
            <strong>⚠️ WATCH (40~59)</strong> — SC 13G (passive) · 참고 신호.
          </div>
          <hr className="border-border" />
          <div>
            <strong>SC 13D</strong> — 5% 이상 지분 · 경영 개입 목적 (강)
          </div>
          <div>
            <strong>SC 13G</strong> — 5% 이상 지분 · 재무 투자 목적 (약)
          </div>
          <div>
            <strong>/A 접미</strong> — Amendment (수정본 · 지분 변동)
          </div>
          <div>
            <strong>D001 · D002</strong> — 한국 DART · 대량보유(경영권) · 임원주주소유상황(insider)
          </div>
          <div className="rounded border border-amber-500/50 bg-amber-500/10 p-2 text-xs text-amber-400">
            ⚠️ 참고 신호이며 자동 매매 아님. 매매 결정은 사용자 판단.
          </div>
        </div>
      </details>
    </div>
  );
}

function StatBox({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
