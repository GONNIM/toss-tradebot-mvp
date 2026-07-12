"use client";

import { useEffect, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  api,
  SniperCandidateRow,
  SniperParams,
  SniperSignalRow,
  SniperStatus,
  SniperUniverseItem,
} from "@/lib/api";
import {
  fmtKrw,
  fmtKrwPrice,
  fmtKstDateTime,
  fmtKstTime,
  fmtPct,
  fmtPriceForTicker,
  fmtShares,
} from "@/lib/time";

const TOKEN_KEY = "sniper_api_token";

export default function SniperPage() {
  const [token, setToken] = useState<string>("");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setToken(localStorage.getItem(TOKEN_KEY) || "");
    }
  }, []);
  const saveToken = (v: string) => {
    setToken(v);
    if (typeof window !== "undefined") localStorage.setItem(TOKEN_KEY, v);
  };

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">🚀 급등주 스나이퍼</h1>
        <p className="text-sm text-muted-foreground">
          정체성: 급등주 사전 예측 (안정 수익 X) · 시드 100만원 · 100% 손실 감내 루틴 완결
        </p>
      </header>
      <SetupGuide token={token} />
      <TokenBar token={token} onSave={saveToken} />
      <StatusPanel />
      <CandidatesPanel />
      <SignalsPanel />
      <UniversePanel token={token} />
      <ParamsEditor token={token} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// 온보딩 · 사용법 가이드 (닫을 수 있음)
// ═══════════════════════════════════════════════════════════════
const GUIDE_DISMISS_KEY = "sniper_guide_dismissed";

function SetupGuide({ token }: { token: string }) {
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined") {
      setDismissed(localStorage.getItem(GUIDE_DISMISS_KEY) === "1");
    }
  }, []);
  const q = useQuery<SniperStatus>({
    queryKey: ["sniper", "status"],
    queryFn: api.sniper.status,
    refetchInterval: 10_000,
  });
  const s = q.data;

  const step1Done = !!s?.live_enabled;                    // env 완료?
  const step2Done = token.length > 0;                      // 토큰 저장?
  const step3Done = !!s?.sniper_enabled;                   // enabled On?

  if (dismissed) {
    return (
      <button
        type="button"
        onClick={() => {
          setDismissed(false);
          localStorage.removeItem(GUIDE_DISMISS_KEY);
        }}
        className="text-xs text-sky-600 hover:underline"
      >
        ↺ 시작 가이드 다시 보기
      </button>
    );
  }

  return (
    <section className="rounded border-2 border-sky-200 bg-sky-50 p-4 dark:border-sky-900 dark:bg-sky-950">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <h2 className="text-base font-bold text-sky-900 dark:text-sky-100">
            📖 시작하기 — 3단계 준비
          </h2>
          <p className="mt-0.5 text-xs text-sky-800 dark:text-sky-200">
            자동매매를 시작하기 전에 아래 3단계를 완료해야 합니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setDismissed(true);
            localStorage.setItem(GUIDE_DISMISS_KEY, "1");
          }}
          className="text-xs text-sky-700 hover:underline"
        >
          닫기
        </button>
      </div>

      <div className="space-y-3">
        <GuideStep
          num={1}
          done={step1Done}
          title="서버 env 준비 (SNIPER_LIVE_ENABLED + SNIPER_API_TOKEN)"
          summary={
            step1Done
              ? "✅ 완료 — LIVE_ENABLED=true 감지"
              : "⛔ 대기 — SOPS 편집 후 백엔드 재기동 필요"
          }
        >
          <p className="mb-1">터미널에서 실행:</p>
          <pre className="rounded bg-slate-900 p-2 text-[10px] text-slate-100">
            {`# 32자 랜덤 토큰 생성
openssl rand -base64 32

# SOPS 암호화 env 편집
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp
sops edit backend/.env.sops.yaml

# 다음 두 줄 추가/수정 후 저장
#   SNIPER_LIVE_ENABLED: "true"
#   SNIPER_API_TOKEN: "<위에서 생성한 토큰>"

# 백엔드 재기동 (사용자에게 승인 요청)`}
          </pre>
        </GuideStep>

        <GuideStep
          num={2}
          done={step2Done}
          title="브라우저에 토큰 저장 (localStorage)"
          summary={step2Done ? "✅ 완료 — 토큰 저장됨" : "⛔ 대기 — 아래 🔐 카드에 입력"}
        >
          <p>Step 1에서 생성한 토큰을 아래 🔐 X-API-Token 입력창에 붙여넣고 "저장" 클릭.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            브라우저 로컬 저장 · 페이지 새로고침 후에도 유지 · 편집·실행 요청에 자동 첨부.
          </p>
        </GuideStep>

        <GuideStep
          num={3}
          done={step3Done}
          title="Sniper 활성 On (필요 시 파라미터 조정 후)"
          summary={step3Done ? "✅ 활성 중 — 자동 스캔·매수 실행" : "⛔ 비활성 — ⚙️ 하드 파라미터에서 On 토글"}
        >
          <p>
            <strong>⚙️ 하드 파라미터 편집기</strong> 최상단 <code>Sniper 활성 (enabled)</code> 토글을 On →
            💾 저장. 정규장 시간(10:00~15:00 KST)에 자동 스캔 시작.
          </p>
          <p className="mt-1 text-xs text-red-600">
            ⚠️ 시드 100만원 100% 손실 가능. 안전장치(Kill Switch -3% · 종목당 상한 · 정규장 게이팅)는
            존재하지만 실현손실 자체는 감내 대상.
          </p>
        </GuideStep>
      </div>
    </section>
  );
}

function GuideStep({
  num,
  done,
  title,
  summary,
  children,
}: {
  num: number;
  done: boolean;
  title: string;
  summary: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(!done);
  return (
    <div
      className={`rounded border ${
        done
          ? "border-emerald-200 bg-white/50 dark:border-emerald-900 dark:bg-slate-900/40"
          : "border-amber-300 bg-white dark:border-amber-800 dark:bg-slate-900"
      } p-2`}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
              done
                ? "bg-emerald-500 text-white"
                : "bg-amber-500 text-white"
            }`}
          >
            {done ? "✓" : num}
          </span>
          <div>
            <p className="text-sm font-semibold">{title}</p>
            <p className={`text-xs ${done ? "text-emerald-700" : "text-amber-700"}`}>
              {summary}
            </p>
          </div>
        </div>
        <span className="text-xs text-muted-foreground">{open ? "▲" : "▼"}</span>
      </button>
      {open && <div className="mt-2 text-xs text-slate-700 dark:text-slate-300">{children}</div>}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function TokenBar({ token, onSave }: { token: string; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState(token);
  const [showHelp, setShowHelp] = useState(false);
  useEffect(() => setDraft(token), [token]);
  const hasToken = token.length > 0;
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          🔐 X-API-Token
          {hasToken ? (
            <span className="ml-2 rounded bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
              저장됨
            </span>
          ) : (
            <span className="ml-2 rounded bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700">
              미저장 · 편집·실주문 불가
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={() => setShowHelp(!showHelp)}
          className="text-xs text-sky-600 hover:underline"
        >
          {showHelp ? "설명 닫기" : "❓ 이게 뭐예요?"}
        </button>
      </div>
      {showHelp && (
        <div className="mb-3 rounded bg-slate-50 p-2 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-300">
          <p className="mb-1">
            <strong>왜 필요한가?</strong> 이 백엔드는 로그인 시스템이 없습니다. 파라미터 편집·자동매매 On/Off·실주문 등
            자금이 움직일 수 있는 요청을 아무나 못 하도록 <strong>토큰 인증</strong>을 뒀습니다.
          </p>
          <p className="mb-1">
            <strong>어디서 발급받나?</strong> 최초 1회 터미널에서{" "}
            <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">openssl rand -base64 32</code> 실행해 랜덤 32자
            생성 → SOPS 편집 (<code className="rounded bg-slate-200 px-1 dark:bg-slate-800">sops edit backend/.env.sops.yaml</code>) 에{" "}
            <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">SNIPER_API_TOKEN</code> 저장.
          </p>
          <p>
            <strong>저장하면?</strong> 브라우저 localStorage에 저장 · 이 페이지 새로고침해도 유지 · 편집·실주문 요청 시 자동
            <code className="rounded bg-slate-200 px-1 dark:bg-slate-800">X-API-Token</code> 헤더 부착.
          </p>
        </div>
      )}
      <div className="flex gap-2">
        <input
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="예: kJ8Nz2mQ7xY5pL9vR3sT6wA4bC1dE0fG="
          className="flex-1 rounded border border-border bg-background px-2 py-1 text-sm font-mono"
        />
        <button
          type="button"
          onClick={() => onSave(draft.trim())}
          disabled={draft.trim() === token}
          className="rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          저장
        </button>
        {hasToken && (
          <button
            type="button"
            onClick={() => {
              onSave("");
              setDraft("");
            }}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-muted"
          >
            지우기
          </button>
        )}
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function StatusPanel() {
  const q = useQuery<SniperStatus>({
    queryKey: ["sniper", "status"],
    queryFn: api.sniper.status,
    refetchInterval: 5000,
  });
  if (q.isLoading || !q.data) return null;
  const s = q.data;
  // 종합 활성 여부: LIVE_ENABLED AND sniper_enabled AND NOT kill_switch
  const isRunning = s.live_enabled && s.sniper_enabled && !s.kill_switch_active;
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">📊 전역 상태</h2>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${
              isRunning
                ? "bg-emerald-100 text-emerald-700"
                : s.kill_switch_active
                ? "bg-red-100 text-red-700"
                : "bg-slate-200 text-slate-700"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                isRunning ? "animate-pulse bg-emerald-500" : "bg-slate-400"
              }`}
            />
            {isRunning ? "실행 중" : s.kill_switch_active ? "Kill Switch 발동" : "대기 중"}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-4">
        <Stat
          label="LIVE_ENABLED (env)"
          value={s.live_enabled ? "✅ 켜짐" : "⛔ 꺼짐"}
          tone={s.live_enabled ? "good" : "muted"}
          hint="서버 env SNIPER_LIVE_ENABLED · 실주문/편집 라우트 전역 스위치"
        />
        <Stat
          label="Sniper enabled (params)"
          value={s.sniper_enabled ? "✅ 활성" : "⛔ 비활성"}
          tone={s.sniper_enabled ? "good" : "muted"}
          hint="ParamsEditor 최상단 토글 · UI에서 On/Off 가능"
        />
        <Stat
          label="Kill Switch"
          value={s.kill_switch_active ? "🚨 발동" : "대기"}
          tone={s.kill_switch_active ? "bad" : "good"}
          hint="일일 손실 -3% 도달 시 자동 발동 · 신규 매수 차단 · 수동 해제 필요"
        />
        <Stat
          label="유니버스"
          value={`${s.universe_size} 종목`}
          hint="KOSDAQ 필터 통과 종목 수 · 매일 22:00 KST 재싱크"
        />
        <Stat
          label="Seed 상한"
          value={fmtKrwPrice(s.seed_cap_krw)}
          hint="봇에 할당한 최대 자본 · 100% 손실 감내"
        />
        <Stat
          label="주문당 상한"
          value={fmtKrwPrice(s.per_order_krw)}
          hint="단일 매수 최대 금액 · 하드 상한"
        />
        <Stat
          label="Trailing / Hard SL"
          value={`${(s.trailing_giveback_pct * 100).toFixed(1)}% / ${(s.hard_stop_loss_pct * 100).toFixed(1)}%`}
          hint="Trailing: 최고가 대비 되돌림 시 매도 · Hard SL: 진입가 대비 손실 시 즉시 매도"
        />
        <Stat
          label="활성창 KST"
          value={`${s.active_window_kst.start}~${s.active_window_kst.end}`}
          hint="이 시간에만 신규 매수 · 주말 자동 차단"
        />
        <Stat
          label="강제 청산"
          value={s.force_close_enabled ? `On · ${s.force_close_kst} KST` : "Off"}
          tone={s.force_close_enabled ? "good" : "muted"}
          hint="On: 지정 시각에 미청산 포지션 자동 매도 (오버나이트 회피) · Off: 사용자 선택"
        />
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad" | "muted";
  hint?: string;
}) {
  const color =
    tone === "good" ? "text-emerald-600" : tone === "bad" ? "text-red-600" : "text-foreground";
  return (
    <div title={hint} className={hint ? "cursor-help" : ""}>
      <p className="text-xs text-muted-foreground">
        {label}
        {hint && <span className="ml-1 text-[9px] text-slate-400">ⓘ</span>}
      </p>
      <p className={`text-sm font-semibold ${color}`}>{value}</p>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
function CandidatesPanel() {
  const q = useQuery<SniperCandidateRow[]>({
    queryKey: ["sniper", "candidates"],
    queryFn: () => api.sniper.candidates(15),
    refetchInterval: 30_000,
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">🎯 실시간 candidate 스캔 (Top 15)</h2>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          30초 주기 · 유니버스 상위 종목의 tape_score 산출 · 임계 초과 시 자동 매수 (Sniper 활성 필요)
          · 컬럼 rank_z/trades_z/book_z 는 3개 소스 z-score
        </p>
      </div>
      {q.isLoading ? (
        <p className="text-sm">스캔 중…</p>
      ) : q.data && q.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">티커</th>
                <th className="py-1">이름</th>
                <th className="py-1 text-right" title="종합 점수 · 3소스 가중합">tape</th>
                <th className="py-1 text-right" title="순위 이동 z-score">순위 z</th>
                <th className="py-1 text-right" title="초당 체결 z-score">체결 z</th>
                <th className="py-1 text-right" title="매수 우세 z-score">호가 z</th>
                <th className="py-1 text-right">현재가</th>
                <th className="py-1 text-right">전일대비</th>
                <th className="py-1">판정</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.ticker} className="border-b border-border/60">
                  <td className="py-1 font-mono">{r.ticker}</td>
                  <td className="py-1">{r.name}</td>
                  <td className="py-1 text-right">{r.tape_score.toFixed(2)}</td>
                  <td className="py-1 text-right">{r.rank_velocity_score.toFixed(1)}</td>
                  <td className="py-1 text-right">{r.trades_intensity_score.toFixed(1)}</td>
                  <td className="py-1 text-right">{r.orderbook_score.toFixed(1)}</td>
                  <td className="py-1 text-right font-semibold">
                    {fmtPriceForTicker(r.ticker, r.last_price)}
                  </td>
                  <td
                    className={`py-1 text-right ${
                      (r.return_pct ?? 0) >= 0 ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {fmtPct(r.return_pct)}
                  </td>
                  <td className="py-1">
                    {r.candidate ? (
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                        ✓ candidate
                      </span>
                    ) : (
                      <span className="text-[10px] text-muted-foreground">
                        {r.reject_reason ?? "reject"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">candidate 없음</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function SignalsPanel() {
  const q = useQuery<SniperSignalRow[]>({
    queryKey: ["sniper", "signals"],
    queryFn: () => api.sniper.signals({ hours: 24, limit: 30 }),
    refetchInterval: 15_000,
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">📜 최근 24h 진입·청산 이력</h2>
        <p className="mt-0.5 text-[10px] text-muted-foreground">
          자동 매매가 실제로 실행되면 여기 기록됩니다. PnL 초록/빨강 · 상태 open/closed · 사유 trailing/hard_sl/force_close
        </p>
      </div>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data && q.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="py-1">감지 (KST)</th>
                <th className="py-1">티커</th>
                <th className="py-1 text-right" title="종합 점수">tape</th>
                <th className="py-1 text-right">진입가</th>
                <th className="py-1 text-right" title="보유 중 최고가">최고가</th>
                <th className="py-1 text-right">청산가</th>
                <th className="py-1 text-right">손익</th>
                <th className="py-1">사유</th>
                <th className="py-1">상태</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((r) => (
                <tr key={r.id} className="border-b border-border/60">
                  <td className="py-1 font-mono">{fmtKstDateTime(r.detected_at)}</td>
                  <td className="py-1 font-semibold">{r.ticker}</td>
                  <td className="py-1 text-right">{r.tape_score?.toFixed(2) ?? "—"}</td>
                  <td className="py-1 text-right">{fmtPriceForTicker(r.ticker, r.entry_price)}</td>
                  <td className="py-1 text-right">{fmtPriceForTicker(r.ticker, r.peak_price)}</td>
                  <td className="py-1 text-right">{fmtPriceForTicker(r.ticker, r.exit_price)}</td>
                  <td
                    className={`py-1 text-right font-semibold ${
                      (r.pnl_pct ?? 0) >= 0 ? "text-emerald-600" : "text-red-600"
                    }`}
                  >
                    {fmtPct(r.pnl_pct)}
                  </td>
                  <td className="py-1">{r.reason ?? "—"}</td>
                  <td className="py-1">
                    <span
                      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        r.exit_order_uuid
                          ? "bg-slate-100 text-slate-700"
                          : "bg-sky-100 text-sky-700"
                      }`}
                    >
                      {r.exit_order_uuid ? "closed" : "open"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">이력 없음 · 스나이퍼 활성 후 채워짐</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function UniversePanel({ token }: { token: string }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["sniper", "universe"],
    queryFn: () => api.sniper.universe({ limit: 30 }),
    refetchInterval: 60_000,
  });
  const refresh = useMutation({
    mutationFn: () => api.sniper.refreshUniverse(token),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sniper", "universe"] }),
  });
  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">🗂 유니버스 (Top 30 · nightly 22:00 KST 재싱크)</h2>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            스나이퍼가 감시할 KOSDAQ 종목 목록 · 매일 22:00 KST 자동 재싱크 · 즉시 재싱크는 토큰 필요
          </p>
        </div>
        <button
          type="button"
          onClick={() => token && refresh.mutate()}
          disabled={!token || refresh.isPending}
          className="rounded bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
        >
          {refresh.isPending ? "재싱크 중…" : "🔄 지금 재싱크 (토큰 필요)"}
        </button>
      </div>
      {q.isLoading ? (
        <p className="text-sm">로드 중…</p>
      ) : q.data && q.data.items.length > 0 ? (
        <>
          <p className="mb-2 text-xs text-muted-foreground">총 {q.data.size} 종목</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className="py-1">티커</th>
                  <th className="py-1">이름</th>
                  <th className="py-1 text-right">시가총액</th>
                  <th className="py-1 text-right">종가</th>
                  <th className="py-1 text-right">발행주식수</th>
                  <th className="py-1 text-right">당일 거래대금</th>
                  <th className="py-1">squeeze</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((r: SniperUniverseItem) => (
                  <tr key={r.ticker} className="border-b border-border/60">
                    <td className="py-1 font-mono">{r.ticker}</td>
                    <td className="py-1">{r.name}</td>
                    <td className="py-1 text-right">{fmtKrw(r.market_cap_krw)}</td>
                    <td className="py-1 text-right font-semibold">{fmtKrwPrice(r.close_price)}</td>
                    <td className="py-1 text-right">{fmtShares(r.shares)}</td>
                    <td className="py-1 text-right">{fmtKrw(r.amount_today)}</td>
                    <td className="py-1">
                      {r.is_squeeze && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                          🎯 squeeze
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="text-xs text-muted-foreground">유니버스 비어있음 · 재싱크 필요</p>
      )}
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
function ParamsEditor({ token }: { token: string }) {
  const qc = useQueryClient();
  const q = useQuery<SniperParams>({
    queryKey: ["sniper", "params"],
    queryFn: api.sniper.params,
  });
  const [draft, setDraft] = useState<Partial<SniperParams>>({});
  const save = useMutation({
    mutationFn: (updates: Partial<SniperParams>) =>
      api.sniper.updateParams(token, updates),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sniper"] });
      setDraft({});
    },
  });

  if (q.isLoading || !q.data) return null;
  const merged: SniperParams = { ...q.data, ...draft };
  const dirty = Object.keys(draft).length > 0;

  const setField = <K extends keyof SniperParams>(k: K, v: SniperParams[K]) =>
    setDraft({ ...draft, [k]: v });

  return (
    <section className="rounded border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">⚙️ 하드 파라미터 편집</h2>
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            33개 파라미터 UI 편집 · 토큰 필요 · 저장 시 백엔드 hot reload · 다음 폴부터 즉시 반영
            {!token && (
              <span className="ml-1 rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-700">
                🔐 토큰 미저장 · 저장 불가
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-amber-600">변경사항 있음</span>}
          <button
            type="button"
            onClick={() => token && save.mutate(draft)}
            disabled={!token || !dirty || save.isPending}
            className="rounded bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
            title={!token ? "먼저 🔐 X-API-Token 저장 필요" : ""}
          >
            {save.isPending ? "저장 중…" : "💾 저장"}
          </button>
        </div>
      </div>
      {save.error && (
        <p className="mb-2 text-xs text-red-500">
          실패: {(save.error as Error).message}
        </p>
      )}

      {/* On/Off 토글 · 가장 중요 */}
      <h3 className="mb-2 text-xs font-semibold text-red-700">🚦 실행 스위치 (가장 중요)</h3>
      <div className="mb-4 grid grid-cols-2 gap-3">
        <ToggleField
          label="Sniper 활성 (enabled)"
          hint="On: 자동 스캔·매수 시작 · Off: 대기 (모든 잡 스킵)"
          value={merged.enabled}
          onChange={(v) => setField("enabled", v)}
        />
        <ToggleField
          label="장 마감 강제 청산"
          hint="On: force_close_kst 시각에 미청산 자동 매도 (오버나이트 회피) · Off: 오버나이트 hold 감내"
          value={merged.force_close_enabled}
          onChange={(v) => setField("force_close_enabled", v)}
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">💰 시드·주문 상한</h3>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <NumField
          label="Seed cap (KRW)"
          hint="봇에 할당하는 최대 자본 · 100% 손실 감내"
          v={merged.seed_cap_krw}
          on={(v) => setField("seed_cap_krw", v)}
        />
        <NumField
          label="Per order (KRW)"
          hint="단일 매수 최대 금액 · 하드 상한 (초과 시 InsufficientBalance)"
          v={merged.per_order_krw}
          on={(v) => setField("per_order_krw", v)}
        />
        <NumField
          label="동시 보유"
          hint="이 수를 초과하면 신규 매수 스킵"
          v={merged.max_concurrent_positions}
          on={(v) => setField("max_concurrent_positions", v)}
          int
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">📉 Trailing · 손절 · 손실 캡</h3>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <PctField
          label="Trailing giveback"
          hint="최고가 대비 이 %만큼 하락 시 즉시 매도"
          v={merged.trailing_giveback_pct}
          on={(v) => setField("trailing_giveback_pct", v)}
        />
        <PctField
          label="Hard Stop Loss"
          hint="진입가 대비 이 % (음수) 도달 시 즉시 매도"
          v={merged.hard_stop_loss_pct}
          on={(v) => setField("hard_stop_loss_pct", v)}
        />
        <PctField
          label="Daily loss limit"
          hint="일일 실현손실 이 % (음수) 초과 시 Kill Switch 자동 발동 (신규 매수 차단)"
          v={merged.daily_loss_limit_pct}
          on={(v) => setField("daily_loss_limit_pct", v)}
        />
        <PctField
          label="Weekly loss limit"
          hint="주간 누적 손실 캡 (Sprint 2 반영 예정)"
          v={merged.weekly_loss_limit_pct}
          on={(v) => setField("weekly_loss_limit_pct", v)}
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">⏰ 활성 시간 (KST · HH:MM)</h3>
      <div className="mb-4 grid grid-cols-3 gap-3">
        <StrField
          label="신규 매수 시작"
          hint="개장 후 노이즈 회피 · 기본 10:00 (개장 1시간 후)"
          v={merged.active_start_kst}
          on={(v) => setField("active_start_kst", v)}
        />
        <StrField
          label="신규 매수 종료"
          hint="이 시각 이후 신규 매수 스킵 · 기본 15:00"
          v={merged.active_end_kst}
          on={(v) => setField("active_end_kst", v)}
        />
        <StrField
          label="강제 청산 시각"
          hint="강제 청산 On 일 때 이 시각에 전량 매도 · 기본 15:00 (마감 30분 전)"
          v={merged.force_close_kst}
          on={(v) => setField("force_close_kst", v)}
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">🎯 Composite Score 임계</h3>
      <p className="mb-2 text-[10px] text-muted-foreground">
        tape_score = 0.5×rank_z + 0.3×trades_z + 0.2×book_z (가중 합) · 다음 임계 전부 통과해야 candidate 승격
      </p>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <NumField
          label="tape 임계"
          hint="종합 z-score 최소값 · 기본 2.0 (2 표준편차)"
          v={merged.tape_score_threshold}
          on={(v) => setField("tape_score_threshold", v)}
        />
        <NumField
          label="rank z 임계"
          hint="rank velocity z-score · 기본 2.0 (5분 window rank 이동)"
          v={merged.rank_velocity_z_min}
          on={(v) => setField("rank_velocity_z_min", v)}
        />
        <NumField
          label="trades z 임계"
          hint="초당 체결 건수 z-score · 기본 2.5"
          v={merged.trades_intensity_z_min}
          on={(v) => setField("trades_intensity_z_min", v)}
        />
        <NumField
          label="orderbook z 임계"
          hint="매수 우세 z-score · 기본 2.5 (bid ratio 0.5 대비)"
          v={merged.orderbook_z_min}
          on={(v) => setField("orderbook_z_min", v)}
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">📥 진입 조건</h3>
      <div className="mb-4 grid grid-cols-4 gap-3">
        <PctField
          label="return 최소"
          hint="상승률이 이 % 이상일 때만 진입 (초기 관심 유입 확인)"
          v={merged.entry_return_min_pct}
          on={(v) => setField("entry_return_min_pct", v)}
        />
        <PctField
          label="return 최대"
          hint="상승률이 이 % 이하일 때만 진입 (상투 회피)"
          v={merged.entry_return_max_pct}
          on={(v) => setField("entry_return_max_pct", v)}
        />
        <NumField
          label="상승 지속 (초)"
          hint="이 초 이상 지속 상승해야 진입 (세력 유도 회피)"
          v={merged.sustained_rise_min_sec}
          on={(v) => setField("sustained_rise_min_sec", v)}
          int
        />
        <NumField
          label="종목당 하루 진입"
          hint="같은 종목 하루 최대 진입 횟수 (통정매매 오인 회피)"
          v={merged.same_ticker_daily_limit}
          on={(v) => setField("same_ticker_daily_limit", v)}
          int
        />
      </div>

      <h3 className="mb-2 text-xs font-semibold">폴링 주기 (초)</h3>
      <div className="grid grid-cols-4 gap-3">
        <NumField
          label="rankings"
          v={merged.poll_rankings_sec}
          on={(v) => setField("poll_rankings_sec", v)}
          int
        />
        <NumField
          label="trades"
          v={merged.poll_trades_sec}
          on={(v) => setField("poll_trades_sec", v)}
          int
        />
        <NumField
          label="orderbook"
          v={merged.poll_orderbook_sec}
          on={(v) => setField("poll_orderbook_sec", v)}
          int
        />
        <NumField
          label="trailing"
          v={merged.poll_trailing_price_sec}
          on={(v) => setField("poll_trailing_price_sec", v)}
          int
        />
      </div>
      <p className="mt-3 text-[10px] text-muted-foreground">
        저장 시 백엔드 hot reload · 다음 폴링부터 즉시 반영. 유니버스 필터 변경 시 재싱크 필요.
      </p>
    </section>
  );
}

function ToggleField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      title={hint}
      className={`flex items-start gap-2 rounded border p-2 text-sm cursor-pointer ${
        value
          ? "border-emerald-400 bg-emerald-50 dark:bg-emerald-950"
          : "border-border bg-background"
      }`}
    >
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4"
      />
      <div className="flex-1">
        <div className="flex items-center gap-1">
          <span className="font-semibold">{label}</span>
          {hint && <span className="text-[9px] text-slate-400">ⓘ</span>}
        </div>
        {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
      </div>
      <span
        className={`ml-auto rounded px-2 py-0.5 text-[10px] font-bold ${
          value ? "bg-emerald-500 text-white" : "bg-slate-300 text-slate-700"
        }`}
      >
        {value ? "ON" : "OFF"}
      </span>
    </label>
  );
}

function LabelWithHint({ label, hint }: { label: string; hint?: string }) {
  return (
    <label
      className={`mb-0.5 block text-[10px] font-semibold text-muted-foreground ${
        hint ? "cursor-help" : ""
      }`}
      title={hint}
    >
      {label}
      {hint && <span className="ml-1 text-[9px] text-slate-400">ⓘ</span>}
    </label>
  );
}

function NumField({
  label,
  hint,
  v,
  on,
  int,
}: {
  label: string;
  hint?: string;
  v: number;
  on: (v: number) => void;
  int?: boolean;
}) {
  return (
    <div>
      <LabelWithHint label={label} hint={hint} />
      <input
        type="number"
        value={v}
        step={int ? 1 : "any"}
        onChange={(e) => on(int ? parseInt(e.target.value, 10) || 0 : parseFloat(e.target.value) || 0)}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
      />
    </div>
  );
}

function PctField({
  label,
  hint,
  v,
  on,
}: {
  label: string;
  hint?: string;
  v: number;
  on: (v: number) => void;
}) {
  return (
    <div>
      <LabelWithHint label={`${label} (%)`} hint={hint} />
      <input
        type="number"
        step="0.001"
        value={(v * 100).toFixed(2)}
        onChange={(e) => {
          const pct = parseFloat(e.target.value);
          on(Number.isNaN(pct) ? 0 : pct / 100);
        }}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs"
      />
    </div>
  );
}

function StrField({
  label,
  hint,
  v,
  on,
}: {
  label: string;
  hint?: string;
  v: string;
  on: (v: string) => void;
}) {
  return (
    <div>
      <LabelWithHint label={label} hint={hint} />
      <input
        type="text"
        value={v}
        onChange={(e) => on(e.target.value)}
        className="w-full rounded border border-border bg-background px-2 py-1 text-xs font-mono"
      />
    </div>
  );
}
