"use client";

import { useQuery } from "@tanstack/react-query";

import {
  api,
  ActivistEventItem,
  ActivistIntensity,
  ActivistStatusResponse,
  ActivistUniverseResponse,
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
  return (
    <div className="rounded border border-border/60 p-3 text-sm">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="rounded bg-amber-500/20 px-2 py-0.5 font-mono text-xs text-amber-400">
          {e.form}
        </span>
        <span className="font-medium">{e.filer_name}</span>
        <span className="ml-auto text-xs font-mono text-muted-foreground">
          score {e.score}
        </span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        Filing: {e.filing_date} · Accession:{" "}
        <span className="font-mono">{e.accession}</span> · 감지 {relTime(e.detected_at)}
      </div>
      <div className="mt-1 text-sm">
        Target: <span>{e.target_desc || "(desc 없음)"}</span>
      </div>
      {e.wolf_pack.length > 0 && (
        <div className="mt-2 rounded border border-rose-500/50 bg-rose-500/10 p-1.5 text-xs text-rose-400">
          🐺 Wolf Pack (30d): {e.wolf_pack.join(", ")}
        </div>
      )}
      <div className="mt-2 flex gap-2 text-xs">
        <a
          href={`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${e.filer_key}&type=SC+13`}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded border border-border bg-background px-2 py-0.5 hover:bg-muted"
        >
          Filer EDGAR ↗
        </a>
        <a
          href={`https://www.sec.gov/Archives/edgar/data/${(e.accession || "").split("-")[0]?.replace(/^0+/, "")}/${(e.accession || "").replace(/-/g, "")}/`}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded border border-border bg-background px-2 py-0.5 hover:bg-muted"
        >
          Filing 상세 ↗
        </a>
      </div>
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

function UniverseCard({ u }: { u: ActivistUniverseResponse }) {
  const active = u.activists.filter((a) => a.enabled);
  const inactive = u.activists.filter((a) => !a.enabled);
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-2 text-lg font-semibold">
        🎯 감시 Universe ({active.length} active
        {inactive.length > 0 ? ` · ${inactive.length} inactive` : ""})
      </h2>
      <details>
        <summary className="cursor-pointer text-sm text-muted-foreground">
          전체 리스트 펼치기
        </summary>
        <div className="mt-3 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
          {u.activists.map((a) => (
            <div
              key={a.key}
              className={`flex justify-between rounded border border-border/60 px-2 py-1 ${
                a.enabled ? "" : "opacity-50"
              }`}
            >
              <span className="truncate">
                <span className="mr-1 rounded bg-muted px-1 text-[10px]">
                  T{a.tier}
                </span>
                {a.name}
              </span>
              <span className="font-mono text-muted-foreground">{a.cik || a.corp_code || "—"}</span>
            </div>
          ))}
        </div>
      </details>
      <p className="mt-2 text-xs text-muted-foreground">
        Universe 편집 API: <code>PATCH /api/v1/meme-watch/activist/universe</code> ·{" "}
        <code>DELETE /api/v1/meme-watch/activist/universe/{"{key}"}</code>
      </p>
    </div>
  );
}

export default function ActivistRadarPage() {
  const statusQ = useQuery({
    queryKey: ["activist", "status"],
    queryFn: () => api.memeWatch.activist.status(),
    refetchInterval: 60_000,
  });
  const universeQ = useQuery({
    queryKey: ["activist", "universe"],
    queryFn: () => api.memeWatch.activist.universe(),
  });

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

      {universeQ.data && <UniverseCard u={universeQ.data} />}

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
