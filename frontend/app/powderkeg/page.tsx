"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  PowderKegEventItem,
  PowderKegListItem,
  PowderKegReport,
  PowderKegTicket,
} from "@/lib/api";
import { fmtKstDateTime } from "@/lib/time";

const TOKEN_KEY = "sniper_api_token";
type Tab = "list" | "events" | "report";

export default function PowderKegPage() {
  const [tab, setTab] = useState<Tab>("list");
  const [token, setToken] = useState<string>("");
  useEffect(() => {
    if (typeof window !== "undefined") {
      setToken(localStorage.getItem(TOKEN_KEY) || "");
    }
  }, []);

  const [guideNonce, setGuideNonce] = useState(0);
  const resetGuides = () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("powderkeg_onboarding_dismissed");
      localStorage.removeItem("powderkeg_usage_guide_dismissed");
      setGuideNonce(n => n + 1);
    }
  };
  return (
    <div className="space-y-4">
      <header className="flex items-start justify-between gap-2">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">🧨 화약고 스크리너</h1>
          <p className="text-sm text-muted-foreground">
            딥밸류 (그레이엄 net-net + 피오트로스키) × 지배구조 카탈리스트 (그린블라트 특수상황) ·
            hypothesis 모드 · 자동매매 미연결
          </p>
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={resetGuides}
            className="rounded border border-purple-300 bg-purple-50 px-2 py-1 text-xs text-purple-800 hover:bg-purple-100 dark:border-purple-800 dark:bg-purple-950 dark:text-purple-100"
            title="숨긴 가이드 카드 다시 보기"
          >
            📖 가이드 다시 보기
          </button>
          <a
            href="https://github.com/GONNIM/toss-tradebot-mvp/blob/main/docs/plans/powderkeg-screener/user-guide.md"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded border border-sky-300 bg-sky-50 px-2 py-1 text-xs text-sky-800 hover:bg-sky-100 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-100"
            title="GitHub 에서 상세 가이드 문서 보기"
          >
            📄 상세 문서 →
          </a>
        </div>
      </header>
      <OnboardingBanner key={`ob-${guideNonce}`} />
      <IdentityBanner />
      <Tabs tab={tab} setTab={setTab} />
      {tab === "list" && <ListTab token={token} guideNonce={guideNonce} />}
      {tab === "events" && <EventsTab />}
      {tab === "report" && <ReportTab token={token} />}
      <Disclaimer />
    </div>
  );
}

function OnboardingBanner() {
  const KEY = "powderkeg_onboarding_dismissed";
  const [dismissed, setDismissed] = useState(false);
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (typeof window !== "undefined") {
      setDismissed(!!localStorage.getItem(KEY));
    }
  }, []);
  if (dismissed) return null;
  return (
    <section className="rounded border-2 border-sky-300 bg-sky-50 p-3 text-sm dark:border-sky-800 dark:bg-sky-950">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="font-bold text-sky-900 dark:text-sky-100 hover:underline"
        >
          {open ? "▼" : "▶"} 🧨 이 페이지는 무엇인가요?
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(KEY, "1");
            setDismissed(true);
          }}
          className="rounded border border-sky-300 px-2 py-0.5 text-[11px] text-sky-700 hover:bg-sky-100"
        >
          다시 안 보기
        </button>
      </div>
      {open && (
        <ul className="mt-2 space-y-1 text-xs text-sky-900 dark:text-sky-100">
          <li>· <b>화약고 종목</b> · 재무·공시 데이터로 자동 발굴한 매수 관찰 후보</li>
          <li>· <b>왜 화약고?</b> · 오너에게 현금이 급해질 신호 (담보제공·상속·경영권분쟁) 가 나타난 저평가 종목</li>
          <li>· <b>이 페이지의 역할</b> · <b>실전 매매 X</b> · 관찰 후보만 제공 · 최종 결정은 사용자</li>
          <li>· <b>언제 재평가?</b> · 매 분기 사업보고서 공개 후 (5월 · 8월 · 11월 · 2월)</li>
          <li>· <b>탭 안내</b> · 🧨 리스트 (후보 종목) · 🔥 피드 (이벤트 알림) · 📊 리포트 (백테스트 결과)</li>
        </ul>
      )}
    </section>
  );
}

function IdentityBanner() {
  return (
    <section className="rounded border-2 border-red-200 bg-red-50 p-3 text-xs dark:border-red-900 dark:bg-red-950">
      <div className="font-bold text-red-900 dark:text-red-100">
        ⚠️ 이 화면은 백테스트 검증 전 hypothesis 상태입니다.
      </div>
      <ul className="mt-1 space-y-0.5 text-red-800 dark:text-red-200">
        <li>
          · <b>validated</b>=true 이벤트만 반자동 티켓 생성 가능
          <span className="text-[10px]"> · 게이트 4조건 · 표본 ≥ 50 · t-stat &gt; 2 · 승률 &gt; 50% · 평균 수익 &gt; 0</span>
        </li>
        <li>· 오너 개인 이벤트 표기는 공시/기사 원문 링크만 · 판단 문구 표시 X (§7-6-3 명예훼손 방지)</li>
        <li>· Type B (횡령·감사부적정·거래정지) 발생 시 자동 리스트 제거 + 최우선 알림</li>
      </ul>
    </section>
  );
}

function Tabs({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  const items: { key: Tab; label: string }[] = [
    { key: "list", label: "🧨 화약고 리스트" },
    { key: "events", label: "🔥 불꽃 피드" },
    { key: "report", label: "📊 백테스트 리포트" },
  ];
  return (
    <div className="flex gap-1 border-b">
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          onClick={() => setTab(it.key)}
          className={`px-3 py-1.5 text-sm ${
            tab === it.key
              ? "border-b-2 border-sky-600 font-bold text-sky-700"
              : "text-muted-foreground hover:text-sky-600"
          }`}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

function Disclaimer() {
  const q = useQuery<{ disclaimer: string }>({
    queryKey: ["powderkeg", "disclaimer"],
    queryFn: api.powderkeg.disclaimer,
    staleTime: Infinity,
  });
  return (
    <footer className="rounded border border-slate-300 bg-slate-50 p-3 text-xs text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
      📌 <strong>고지</strong>: {q.data?.disclaimer || "본 화면은 관찰 후보이며 투자 권유가 아닙니다."}
    </footer>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 1 · 화약고 리스트
// ═══════════════════════════════════════════════════════════════
function ListTab({ token, guideNonce = 0 }: { token: string; guideNonce?: number }) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [tierFilter, setTierFilter] = useState<string>("");
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["powderkeg", "list", statusFilter],
    queryFn: () =>
      api.powderkeg.list({ status: statusFilter || undefined, limit: 200 }),
    refetchInterval: 60_000,
  });
  const rawItems: PowderKegListItem[] = q.data?.items || [];
  const items: PowderKegListItem[] = tierFilter
    ? rawItems.filter(it => it.tier === tierFilter)
    : rawItems;

  const toggleLock = useMutation({
    mutationFn: ({ id, locked }: { id: number; locked: boolean }) =>
      api.powderkeg.toggleListLock(token, id, locked),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "list"] }),
  });
  const remove = useMutation({
    mutationFn: ({ ticker, reason }: { ticker: string; reason: string }) =>
      api.powderkeg.removeListItem(token, ticker, reason, q.data?.run_id || undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "list"] }),
  });
  const saveNote = useMutation({
    mutationFn: ({ id, note }: { id: number; note: string }) =>
      api.powderkeg.setListNote(token, id, note),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "list"] }),
  });

  return (
    <section className="space-y-3 rounded border p-4">
      <UsageGuideCard key={`ug-${guideNonce}`} />
      <FunnelCard runId={q.data?.run_id || null} />
      <LowPbrDiscoveryCard token={token} />
      <ReScreenGuide token={token} runId={q.data?.run_id || null} count={q.data?.count || 0} />
      <div className="flex items-center justify-between">
        <div className="text-sm">
          <span className="font-bold">마지막 갱신 · {fmtRunIdKst(q.data?.run_id)}</span>
          <span
            className="ml-2 text-muted-foreground"
            title="이 리스트에 담긴 종목 수"
          >
            · {q.data?.count || 0} 종목
          </span>
        </div>
        <div className="flex gap-1">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border px-2 py-1 text-xs"
            title="상태별 필터 · 전체 / 매수 후보 / 탈락 / 현금 의심"
          >
            <option value="">🔍 전체 상태</option>
            <option value="passed">✅ 매수 후보 (10/10 통과)</option>
            <option value="rejected">❌ 탈락</option>
            <option value="cash_suspect">⚠️ 현금 의심 (분식 가능)</option>
          </select>
          <select
            value={tierFilter}
            onChange={(e) => setTierFilter(e.target.value)}
            className="rounded border px-2 py-1 text-xs"
            title="티어별 필터 · v1.20 · 8~9/10 경계선 후보 발굴"
          >
            <option value="">🎖 전체 티어</option>
            <option value="tier_1_passed">🥇 Tier 1 · 10/10</option>
            <option value="tier_2_near">🥈 Tier 2 · 8~9/10</option>
            <option value="tier_3_watch">🥉 Tier 3 · 7/10</option>
          </select>
        </div>
      </div>
      <ManualAddForm token={token} runId={q.data?.run_id || undefined} />
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          매수 후보 종목 리스트가 비어있습니다. 상단 <b>🔄 지금 재평가</b> 버튼을 눌러 최신 데이터로 리스트를 만들어 보세요.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-slate-50 dark:bg-slate-900">
                <th className="p-2 text-left">종목</th>
                <th className="p-2 text-center">상태</th>
                <th className="p-2 text-right">순현금/시총</th>
                <th className="p-2 text-right">F-Score</th>
                <th className="p-2 text-right">지분율</th>
                <th className="p-2 text-right">PBR</th>
                <th className="p-2 text-right">자사주</th>
                <th className="p-2 text-left">사유</th>
                <th className="p-2 text-center">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className={`border-b hover:bg-sky-50/30 ${it.locked ? "bg-amber-50/40 dark:bg-amber-950/20" : ""}`}>
                  <td className="p-2">
                    <div className="flex items-center gap-1">
                      <span className="font-medium">{it.name || "-"}</span>
                      {it.locked ? (
                        <span
                          title={`🔒 lock · added_by=${it.added_by}`}
                          className="rounded bg-amber-200 px-1 py-0.5 text-[9px] text-amber-900"
                        >
                          🔒
                        </span>
                      ) : null}
                      {it.added_by === "user" ? (
                        <span
                          title="사용자 수동 추가"
                          className="rounded bg-sky-100 px-1 py-0.5 text-[9px] text-sky-800"
                        >
                          user
                        </span>
                      ) : null}
                      <RobustnessBadge score={it.robustness_score} grade={it.robustness_grade} />
                      <TierBadge tier={it.tier} passed={it.conditions_passed} />
                    </div>
                    {it.tier === "tier_2_near" || it.tier === "tier_3_watch" ? (
                      <div className="mt-0.5 text-[9px] text-orange-700 dark:text-orange-300">
                        📌 병목 · {(it.failed_conditions || []).map(f => CONDITION_LABEL_SHORT[f] || f).join(" · ")}
                      </div>
                    ) : null}
                    <div className="text-[10px] text-muted-foreground">{it.ticker}</div>
                    <NoteInput
                      item={it}
                      onSave={(note) => saveNote.mutate({ id: it.id, note })}
                      disabled={!token || saveNote.isPending}
                    />
                  </td>
                  <td className="p-2 text-center">
                    <StatusBadge status={it.status} />
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.net_cash_ratio)}</td>
                  <td className="p-2 text-right font-mono">
                    {it.piotroski_f_score ?? "-"}/9
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.owner_pct)}</td>
                  <td className="p-2 text-right font-mono">
                    {it.pbr != null ? it.pbr.toFixed(2) : "-"}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(it.treasury_pct)}</td>
                  <td className="p-2 text-[10px] text-muted-foreground">
                    {it.reject_reasons || "-"}
                  </td>
                  <td className="p-2 text-center">
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        disabled={!token || toggleLock.isPending}
                        onClick={() =>
                          toggleLock.mutate({ id: it.id, locked: !it.locked })
                        }
                        className="rounded border px-1.5 py-0.5 text-[10px] hover:bg-amber-50 disabled:opacity-30"
                        title={
                          it.locked
                            ? "unlock (다음 screener run 시 재평가)"
                            : "lock (다음 screener run 후에도 유지)"
                        }
                      >
                        {it.locked ? "🔓 unlock" : "🔒 lock"}
                      </button>
                      <button
                        type="button"
                        disabled={!token || remove.isPending}
                        onClick={() => {
                          const reason = prompt(
                            `삭제 · ${it.ticker} ${it.name || ""}\n사유 (감사 로그):`,
                            it.status === "cash_suspect" ? "cash_suspect · 사용자 판단 배제" : "",
                          );
                          if (reason !== null) {
                            remove.mutate({ ticker: it.ticker, reason });
                          }
                        }}
                        className="rounded border border-red-300 px-1.5 py-0.5 text-[10px] text-red-700 hover:bg-red-50 disabled:opacity-30"
                        title="화약고 리스트에서 완전 삭제 (snapshot 감사 저장)"
                      >
                        × 삭제
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function NoteInput({
  item,
  onSave,
  disabled,
}: {
  item: PowderKegListItem;
  onSave: (note: string) => void;
  disabled: boolean;
}) {
  const [val, setVal] = useState<string>(item.user_note || "");
  const dirty = val !== (item.user_note || "");
  return (
    <div className="mt-1 flex items-center gap-1">
      <input
        type="text"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        placeholder="분석 노트..."
        className="w-40 rounded border px-1 py-0.5 text-[10px]"
      />
      {dirty ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => onSave(val)}
          className="rounded bg-sky-600 px-1.5 py-0.5 text-[9px] text-white disabled:opacity-30"
        >
          저장
        </button>
      ) : null}
    </div>
  );
}

function ManualAddForm({ token, runId }: { token: string; runId?: string }) {
  const qc = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () =>
      api.powderkeg.addManualToList(token, {
        ticker,
        note: note || undefined,
        run_id: runId,
      }),
    onSuccess: () => {
      setTicker("");
      setNote("");
      qc.invalidateQueries({ queryKey: ["powderkeg", "list"] });
    },
  });
  return (
    <div className="rounded border border-dashed border-sky-300 bg-sky-50 p-2 text-xs dark:border-sky-900 dark:bg-sky-950">
      <div className="mb-1 font-bold text-sky-900 dark:text-sky-100">
        ➕ 수동 추가 (사용자 판단 · locked=True)
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.trim())}
          placeholder="티커 (예: 035890)"
          className="rounded border px-2 py-1 text-xs"
        />
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="분석 노트 (선택)"
          className="w-64 rounded border px-2 py-1 text-xs"
        />
        <button
          type="button"
          disabled={!token || !ticker || add.isPending}
          onClick={() => add.mutate()}
          className="rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-40"
        >
          {add.isPending ? "추가 중..." : "🔒 추가 + lock"}
        </button>
        {add.data ? (
          <span className="text-xs text-emerald-700">
            ✅ {add.data.ticker} {add.data.name} 추가됨
          </span>
        ) : null}
        {add.error ? (
          <span className="text-xs text-red-700">
            ⛔ {String((add.error as Error).message)}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    passed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100",
    rejected: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100",
    cash_suspect: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-100",
  };
  const cls = map[status] || "bg-slate-100 text-slate-700";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${cls}`}>
      {status}
    </span>
  );
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return "-";
  return `${(v * 100).toFixed(1)}%`;
}

// ═══════════════════════════════════════════════════════════════
// 탭 2 · 불꽃 피드 (Type A/B 타임라인)
// ═══════════════════════════════════════════════════════════════
function EventsTab() {
  const [hours, setHours] = useState(72);
  const q = useQuery({
    queryKey: ["powderkeg", "events", hours],
    queryFn: () => api.powderkeg.events({ hours, limit: 100 }),
    refetchInterval: 30_000,
  });
  const items: PowderKegEventItem[] = q.data?.items || [];

  return (
    <section className="space-y-3 rounded border p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm">
          <span className="font-bold">최근 {hours}시간</span>
          <span className="ml-2 text-muted-foreground">· {q.data?.count || 0} 건</span>
        </div>
        <select
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className="rounded border px-2 py-1 text-xs"
        >
          <option value={24}>24시간</option>
          <option value={72}>72시간</option>
          <option value={168}>7일</option>
          <option value={720}>30일</option>
        </select>
      </div>
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : items.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          이벤트 없음 · DART 폴링 필요.
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((e) => (
            <li key={e.id} className={`rounded border p-2 ${eventBg(e.kind)}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <EventTypeBadge event_type={e.event_type} kind={e.kind} />
                  {e.kind === "B" ? <DoNotTouchBadge /> : null}
                  <span className="font-bold">{e.ticker}</span>
                  {e.needs_human_review ? (
                    <span className="rounded bg-amber-200 px-1 py-0.5 text-[10px] text-amber-900">
                      🟡 사람 확인 필요
                    </span>
                  ) : null}
                  {e.validated ? (
                    <span className="rounded bg-emerald-200 px-1 py-0.5 text-[10px] text-emerald-900">
                      ✅ validated
                    </span>
                  ) : null}
                </div>
                <span className="text-[10px] text-muted-foreground">
                  {e.detected_at ? fmtKstDateTime(e.detected_at) : "-"}
                </span>
              </div>
              <div className="mt-1 text-sm">{e.title}</div>
              {e.url ? (
                <a
                  href={e.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] text-sky-600 hover:underline"
                >
                  원문 →
                </a>
              ) : null}
              {e.action_taken ? (
                <div className="mt-1 text-[10px] text-muted-foreground">
                  action: <code>{e.action_taken}</code>
                  {e.confidence != null ? ` · confidence ${e.confidence.toFixed(2)}` : ""}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function eventBg(kind: "A" | "B"): string {
  return kind === "B"
    ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950"
    : "border-orange-300 bg-orange-50 dark:border-orange-900 dark:bg-orange-950";
}

function EventTypeBadge({ event_type, kind }: { event_type: string; kind: "A" | "B" }) {
  const cls = kind === "B"
    ? "bg-red-600 text-white"
    : "bg-orange-500 text-white";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${cls}`}>
      {kind === "B" ? "🚨 " : ""}
      {event_type}
    </span>
  );
}

/** 사용법 가이드 카드 · v1.22 · 사용자가 리스트를 어떻게 활용할지 안내.
 *   티어별 액션 · 이벤트 대응 · 일일 워크플로우.
 */
function UsageGuideCard() {
  const KEY = "powderkeg_usage_guide_dismissed";
  const [dismissed, setDismissed] = useState(false);
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (typeof window !== "undefined") {
      setDismissed(!!localStorage.getItem(KEY));
    }
  }, []);
  if (dismissed) return null;
  return (
    <section className="rounded border-2 border-purple-300 bg-gradient-to-r from-purple-50 to-pink-50 p-3 text-xs dark:border-purple-800 dark:from-purple-950 dark:to-pink-950">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="font-bold text-purple-900 hover:underline dark:text-purple-100"
        >
          {open ? "▼" : "▶"} 📖 이 리스트를 어떻게 활용하나요?
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(KEY, "1");
            setDismissed(true);
          }}
          className="rounded border border-purple-300 px-2 py-0.5 text-[11px] text-purple-700 hover:bg-purple-100"
        >
          다시 안 보기
        </button>
      </div>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="rounded border bg-white p-2 dark:bg-slate-900">
            <div className="mb-1 font-bold">🎯 티어별 액션</div>
            <ul className="space-y-1">
              <li>
                <b className="text-amber-900 dark:text-amber-100">🥇 Tier 1 (10/10 통과)</b> ·
                <b>최상위 관찰 대상</b>. 이벤트 발생 시 (담보제공 등) Telegram 알림 도착 · 알림 확인 후 개별 판단.
                <span className="text-[10px] text-red-700"> ⚠️ 자동매매 X · 사용자 최종 결정</span>
              </li>
              <li>
                <b className="text-slate-800 dark:text-slate-100">🥈 Tier 2 (8~9/10)</b> ·
                <b>승격 후보 관찰</b>. 병목 조건 (예: F-Score) 개선 시 Tier 1 승격 가능. 다음 분기 사업보고서 공개 후 재평가 확인.
              </li>
              <li>
                <b className="text-orange-800 dark:text-orange-100">🥉 Tier 3 (7/10)</b> ·
                <b>지속 관찰</b>. 여러 조건 병목 · 개선 여지 낮음 · 참고용.
              </li>
              <li>
                <b className="text-yellow-800 dark:text-yellow-100">⚠️ 현금 의심</b> ·
                <b>분식 의심 · 회피</b>. 이자수익 부족 · 재무 신뢰도 낮음.
              </li>
              <li>
                <b className="text-slate-600">❌ 탈락</b> ·
                <b>이 카테고리 종목 아님</b>. 무시.
              </li>
            </ul>
          </div>
          <div className="rounded border bg-white p-2 dark:bg-slate-900">
            <div className="mb-1 font-bold">🔔 이벤트 발생 시 (자동 3분 주기 감시)</div>
            <ul className="space-y-1">
              <li>· <b>Type A</b> (담보제공 · 상속 · 배당 확대 등) · Tier 1/2 종목 이벤트 → Telegram 알림 · 매수 후보 or 관찰</li>
              <li>· <b>Type A · 백테스트 음수</b> (예: A3 담보제공 · 12M -11.7%) → 🔬 [관찰 후보 · 백테스트 음수] 라벨 · 신중 검토</li>
              <li>· <b>Type B</b> (횡령 · 감사비적정 · 거래정지) · 🚫 <b>DO NOT TOUCH</b> · 리스트 자동 제거 · 매수 금지</li>
            </ul>
          </div>
          <div className="rounded border bg-white p-2 dark:bg-slate-900">
            <div className="mb-1 font-bold">📅 일일/주간 사용 흐름</div>
            <ol className="space-y-1 pl-4" style={{ listStyleType: "decimal" }}>
              <li><b>매일 · Telegram 알림 확인</b> · Type A 매수 후보 · Type B DO NOT TOUCH</li>
              <li><b>주 1회 · 리스트 확인</b> · Tier 1 · Tier 2 변화 · 이벤트 이력 (탭 2 · 🔥 불꽃 피드)</li>
              <li><b>분기 1회 · 재평가</b> · 사업보고서 공개 (5·8·11·2월) 후 · 🔄 지금 재평가 버튼</li>
              <li><b>매수 결정 전</b> · 백테스트 리포트 (탭 3) 확인 · 강건성 뱃지 (🔴 위험 = 임계 코앞 · 신중)</li>
              <li><b>매수 후</b> · 무효화 조건 필수 (가격 -15% or 논리 무효 · 예: 담보 해제)</li>
            </ol>
          </div>
          <div className="rounded border-2 border-red-200 bg-red-50 p-2 text-red-900 dark:bg-red-950 dark:text-red-100">
            <b>⚠️ 중요</b> · 본 리스트는 <b>매수 추천 아님</b>. 관찰 후보만 제공. 최종 판단은 사용자 몫.
            자동매매 연결 안 됨 (hypothesis 모드).
            <a href="/docs/powderkeg-user-guide" className="ml-1 text-sky-700 underline hover:text-sky-500">
              📖 상세 사용법 문서 →
            </a>
          </div>
        </div>
      )}
    </section>
  );
}

/** Tier 뱃지 · v1.20 · 리뷰어 Priority 4 · 8~9/10 경계선 후보 노출. */
function TierBadge({ tier, passed }: { tier?: string; passed?: number }) {
  if (!tier) return null;
  const cfg: Record<string, { icon: string; label: string; cls: string }> = {
    tier_1_passed: { icon: "🥇", label: "Tier 1", cls: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100" },
    tier_2_near:   { icon: "🥈", label: "Tier 2", cls: "bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-slate-100" },
    tier_3_watch:  { icon: "🥉", label: "Tier 3", cls: "bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100" },
    cash_suspect:  { icon: "⚠️", label: "현금 의심", cls: "bg-yellow-100 text-yellow-900 dark:bg-yellow-900 dark:text-yellow-100" },
    rejected:      { icon: "❌", label: "탈락", cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  };
  const m = cfg[tier] || cfg.rejected;
  return (
    <span
      title={passed != null ? `조건 통과: ${passed}/10` : tier}
      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${m.cls}`}
    >
      {m.icon} {m.label} · {passed}/10
    </span>
  );
}

/** 조건별 라벨 매핑 · UI 병목 표시 · Tier 2 실패 조건 안내. */
const CONDITION_LABEL_SHORT: Record<string, string> = {
  "1_pbr": "PBR",
  "2_net_cash_ratio": "순현금",
  "3_owner_pct": "지분율",
  "4_not_big_biz": "비재벌",
  "5_audit_opinion": "감사의견",
  "6_cash_reality": "이자수익",
  "7_operating_profit": "영업흑자",
  "8_fscore": "F-Score",
  "9_adv60": "거래대금",
  "10_no_bad_history": "관리종목",
};

/** 저PBR 후보 발굴·대량 스크리닝 카드 · v1.19 · 리뷰어 Priority 2.
 *   "화약고 서식지는 KOSPI 중소형 + KOSDAQ 중형 · 지금은 반대 방향으로 편향"
 *   → KRX 스냅샷의 저PBR (< 0.5) 종목 대량 발굴 · 스크리너 원클릭 실행.
 */
function LowPbrDiscoveryCard({ token }: { token: string }) {
  const [open, setOpen] = useState(false);
  const [maxPbr, setMaxPbr] = useState<number>(0.5);
  const [market, setMarket] = useState<string>("ALL");
  const [minCapEok, setMinCapEok] = useState<number>(300);   // 300억
  const qc = useQueryClient();
  const candidates = useQuery({
    queryKey: ["powderkeg", "low_pbr", maxPbr, market, minCapEok],
    queryFn: () => api.powderkeg.lowPbrCandidates({
      max_pbr: maxPbr, market, min_market_cap: minCapEok * 100_000_000,
      limit: 1000,
    }),
    enabled: open,
  });
  const runBulk = useMutation({
    mutationFn: async () => {
      const tks = candidates.data?.items.map(x => x.ticker) || [];
      if (tks.length === 0) throw new Error("발굴된 저PBR 후보가 없습니다");
      return await api.powderkeg.runScreener(token, tks);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["powderkeg", "list"] });
      qc.invalidateQueries({ queryKey: ["powderkeg", "funnel"] });
    },
  });
  return (
    <section className="rounded border-2 border-emerald-200 bg-emerald-50 p-3 text-xs dark:border-emerald-900 dark:bg-emerald-950">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="font-bold text-emerald-900 dark:text-emerald-100">
          🔎 저PBR 후보 대량 발굴 · 스크리닝 <span className="text-[10px] text-emerald-700 dark:text-emerald-300">(리뷰어 Priority 2)</span>
        </div>
        <div className="text-emerald-700">{open ? "▼" : "▶"}</div>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="text-emerald-800 dark:text-emerald-200">
            💡 <b>화약고 서식지</b> · KOSPI 중소형 + KOSDAQ 중형 · 저PBR 대상 · 유니버스 전환.
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-[11px]">
              <div className="font-semibold">PBR 상한</div>
              <input
                type="number" step="0.05" min="0.1" max="1.0"
                value={maxPbr}
                onChange={(e) => setMaxPbr(Number(e.target.value))}
                className="w-16 rounded border px-1 py-0.5"
              />
            </label>
            <label className="text-[11px]">
              <div className="font-semibold">시장</div>
              <select
                value={market}
                onChange={(e) => setMarket(e.target.value)}
                className="rounded border px-1 py-0.5"
              >
                <option value="ALL">전체</option>
                <option value="KOSPI">KOSPI</option>
                <option value="KOSDAQ">KOSDAQ</option>
              </select>
            </label>
            <label className="text-[11px]">
              <div className="font-semibold">시총 하한 (억원)</div>
              <input
                type="number" step="50" min="50" max="10000"
                value={minCapEok}
                onChange={(e) => setMinCapEok(Number(e.target.value))}
                className="w-20 rounded border px-1 py-0.5"
              />
            </label>
            <button
              type="button"
              onClick={() => candidates.refetch()}
              disabled={!open || candidates.isFetching}
              className="rounded border border-emerald-300 bg-white px-2 py-1 text-[11px] hover:bg-emerald-100 disabled:opacity-30"
            >
              🔎 후보 다시 발굴
            </button>
          </div>
          {candidates.isLoading ? (
            <div className="text-emerald-700">불러오는 중...</div>
          ) : candidates.data ? (
            <div className="rounded border bg-white p-2 dark:bg-slate-900">
              <div className="flex items-center justify-between">
                <div className="text-[11px]">
                  📊 발굴 종목 · <b>{candidates.data.count}</b>개
                  <span className="ml-1 text-muted-foreground">({candidates.data.snapshot_date})</span>
                </div>
                <button
                  type="button"
                  onClick={() => runBulk.mutate()}
                  disabled={!token || runBulk.isPending || candidates.data.count === 0}
                  className="rounded bg-emerald-600 px-2 py-1 text-[11px] font-bold text-white hover:bg-emerald-700 disabled:bg-emerald-300"
                  title={`${candidates.data.count}개 종목을 화약고 10 조건으로 대량 스크리닝`}
                >
                  {runBulk.isPending ? "⏳ 스크리닝 중..." : `🧨 이 ${candidates.data.count}개 스크리닝`}
                </button>
              </div>
              {candidates.data.items.length > 0 && (
                <div className="mt-1 max-h-40 overflow-y-auto text-[10px]">
                  <div className="grid grid-cols-3 gap-1 font-mono">
                    {candidates.data.items.slice(0, 30).map((c) => (
                      <div key={c.ticker} className="truncate rounded bg-emerald-50 px-1 py-0.5 dark:bg-emerald-900">
                        {c.ticker} <span className="text-muted-foreground">PBR {c.pbr}</span>
                      </div>
                    ))}
                  </div>
                  {candidates.data.items.length > 30 && (
                    <div className="mt-1 text-muted-foreground">...외 {candidates.data.items.length - 30}개</div>
                  )}
                </div>
              )}
            </div>
          ) : null}
          {runBulk.isSuccess && runBulk.data ? (
            <div className="rounded bg-emerald-100 px-2 py-1 text-[11px] font-bold text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100">
              ✅ 스크리닝 완료 · 통과 {runBulk.data.passed} · 탈락 {runBulk.data.rejected} · 현금 의심 {runBulk.data.cash_suspect ?? 0}
            </div>
          ) : null}
          {runBulk.isError ? (
            <div className="rounded bg-red-100 px-2 py-1 text-[11px] text-red-900 dark:bg-red-900 dark:text-red-100">
              ❌ 스크리닝 실패 · {String((runBulk.error as Error)?.message)}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

/** 퍼널 워터폴 카드 · v1.18 · 리뷰어 진단 · "1개는 파이프라인의 답" 관측성.
 *   각 조건별 통과 수 표시 · 데이터 결측 분리 · 커버리지 명시.
 */
function FunnelCard({ runId }: { runId: string | null }) {
  const [open, setOpen] = useState(true);
  const q = useQuery({
    queryKey: ["powderkeg", "funnel", runId],
    queryFn: () => api.powderkeg.listFunnel(runId || undefined),
    enabled: !!runId,
  });
  const d = q.data;
  if (!runId || !d) return null;
  const maxPassed = Math.max(1, ...d.per_condition.map(c => c.passed));
  return (
    <section className="rounded border-2 border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <div className="text-sm font-bold text-amber-900 dark:text-amber-100">
          📊 퍼널 워터폴 · 왜 {d.final_passed}개인가?
        </div>
        <div className="text-xs text-amber-700 dark:text-amber-300">{open ? "▼" : "▶"}</div>
      </button>
      {open && (
        <div className="mt-2 space-y-1 text-xs">
          <div className="rounded border border-sky-300 bg-sky-50 p-1.5 dark:border-sky-700 dark:bg-sky-950">
            🎯 <b>이 런에서 스크리닝된 종목:</b> {d.universe_size} · 그 중 <b>{d.evaluable}개</b> 평가 가능 ·
            <span className="ml-1 text-orange-700 dark:text-orange-300">
              📊 데이터 결측 (미평가): {d.data_incomplete}개
            </span>
          </div>
          <div className="mt-2 space-y-0.5 rounded border bg-white p-2 dark:bg-slate-900">
            <div className="mb-1 text-[10px] font-semibold text-muted-foreground">조건별 통과 (총 {d.evaluable}개 대비)</div>
            {d.per_condition.map((c) => {
              const pct = d.evaluable > 0 ? Math.round((c.passed / d.evaluable) * 100) : 0;
              const barPct = Math.round((c.passed / maxPassed) * 100);
              return (
                <div key={c.id} className="flex items-center gap-2">
                  <div className="w-52 truncate text-[10px]">{c.label}</div>
                  <div className="flex-1 rounded bg-slate-100 dark:bg-slate-800">
                    <div
                      className="h-3 rounded bg-emerald-400 dark:bg-emerald-600"
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                  <div className="w-20 text-right font-mono text-[10px]">
                    {c.passed} <span className="text-muted-foreground">({pct}%)</span>
                  </div>
                </div>
              );
            })}
            <div className="mt-2 flex items-center justify-between rounded border-t pt-1 font-bold">
              <span className="text-emerald-800 dark:text-emerald-100">✅ 10/10 최종 통과</span>
              <span className="font-mono">{d.final_passed} 개</span>
            </div>
            {d.cash_suspect > 0 || d.rejected > 0 ? (
              <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
                <span>⚠️ 현금 의심: {d.cash_suspect}</span>
                <span>❌ 탈락: {d.rejected}</span>
              </div>
            ) : null}
          </div>
          <div className="mt-1 text-[10px] text-amber-800 dark:text-amber-300">
            💡 병목이 있는 조건 · 데이터 커버리지 or 임계 재검토 후보. {d.data_incomplete > 0
              ? `데이터 결측 ${d.data_incomplete}개 · 재무·시장·최대주주 미수집.` : ""}
          </div>
        </div>
      )}
    </section>
  );
}

/** run_id "20260716-145255K" 또는 "20260716-055255" (UTC) 를 사용자 친화 KST 문자열로 변환. */
function fmtRunIdKst(runId?: string | null): string {
  if (!runId) return "아직 실행 안 됨";
  const m = runId.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(K?)$/);
  if (!m) return runId;
  const [, y, mo, d, h, mi, s, k] = m;
  if (k === "K") {
    return `${y}-${mo}-${d} ${h}:${mi}:${s} KST`;
  }
  // UTC · +9 hr 변환
  const dt = new Date(Date.UTC(+y, +mo - 1, +d, +h, +mi, +s));
  const kst = new Date(dt.getTime() + 9 * 3600 * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${kst.getUTCFullYear()}-${pad(kst.getUTCMonth() + 1)}-${pad(kst.getUTCDate())} ${pad(kst.getUTCHours())}:${pad(kst.getUTCMinutes())}:${pad(kst.getUTCSeconds())} KST`;
}

/** 리스트 강제 재평가 가이드 카드 · 리뷰어 UX 지적 대응. */
function ReScreenGuide({ token, runId, count }: { token: string; runId: string | null; count: number }) {
  const qc = useQueryClient();
  // 기본 유니버스 · 사용자가 입력 안 하면 화약고 리스트 + 서희건설 (부트스트랩)
  const [tickers, setTickers] = useState<string>("035890");
  const runScreener = useMutation({
    mutationFn: async () => {
      const arr = tickers.split(/[,\s]+/).map(t => t.trim()).filter(Boolean);
      if (arr.length === 0) throw new Error("종목 티커를 최소 1개 입력하세요");
      return await api.powderkeg.runScreener(token, arr);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["powderkeg", "list"] });
    },
  });
  const disabled = !token || runScreener.isPending;
  return (
    <section className="rounded border-2 border-sky-200 bg-gradient-to-r from-sky-50 to-blue-50 p-3 text-xs dark:border-sky-800 dark:from-sky-950 dark:to-blue-950">
      <div className="flex items-center justify-between gap-2">
        <div className="flex-1 space-y-0.5">
          <div className="font-bold text-sky-900 dark:text-sky-100">
            🔄 리스트 강제 재평가
          </div>
          <div className="text-sky-800 dark:text-sky-200">
            마지막 갱신 · <b>{fmtRunIdKst(runId)}</b> · 현재 {count}개 종목
          </div>
          <div className="text-[10px] text-sky-700 dark:text-sky-300">
            💡 언제? · 사업보고서 공개 (5·8·11·2월) · 새 KRX 데이터 · 시장 급변 후
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <input
            type="text"
            value={tickers}
            onChange={(e) => setTickers(e.target.value)}
            placeholder="종목코드 (콤마·공백)"
            className="w-56 rounded border px-2 py-1 text-xs"
            title="예: 035890 또는 035890,032190,003800"
          />
          <button
            type="button"
            onClick={() => runScreener.mutate()}
            disabled={disabled}
            className="rounded bg-sky-600 px-2 py-1 text-xs font-bold text-white hover:bg-sky-700 disabled:bg-sky-300"
            title="입력한 종목을 10 조건으로 재평가 · X-API-Token 필요"
          >
            {runScreener.isPending ? "⏳ 계산 중..." : "🔄 지금 재평가"}
          </button>
        </div>
      </div>
      {runScreener.isSuccess && runScreener.data ? (
        <div className="mt-2 rounded bg-emerald-100 px-2 py-1 text-[11px] text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100">
          ✅ 재평가 완료 · 통과 {String(runScreener.data.passed ?? "?")} · 탈락 {String(runScreener.data.rejected ?? "?")} · 현금 의심 {String(runScreener.data.cash_suspect ?? "?")}
        </div>
      ) : null}
      {runScreener.isError ? (
        <div className="mt-2 rounded bg-red-100 px-2 py-1 text-[11px] text-red-900 dark:bg-red-900 dark:text-red-100">
          ❌ 재평가 실패 · {String((runScreener.error as Error)?.message || runScreener.error || "unknown")}
        </div>
      ) : null}
    </section>
  );
}

/** DO NOT TOUCH 뱃지 · 지시서 §7-3-B1 do_not_touch 라벨 · B 타입 (즉시 제외) 전반 표기. */
function DoNotTouchBadge() {
  return (
    <span className="rounded bg-red-800 px-1.5 py-0.5 text-[10px] font-bold text-white shadow-sm">
      🚫 DO NOT TOUCH
    </span>
  );
}

/** 강건성 뱃지 · v1.14 · 리뷰어 지적 #5 · 임계 여유 표시.
 *   strong 🟢 ≥20% · moderate 🟡 ≥10% · borderline 🟠 ≥5% · at_risk 🔴 <5%
 */
function RobustnessBadge({ score, grade }: { score?: number | null; grade?: string | null }) {
  if (score == null || !grade) return null;
  const pct = (score * 100).toFixed(1);
  const map: Record<string, { icon: string; cls: string; label: string }> = {
    strong:     { icon: "🟢", cls: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100", label: "강건" },
    moderate:   { icon: "🟡", cls: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100", label: "보통" },
    borderline: { icon: "🟠", cls: "bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100", label: "경계선" },
    at_risk:    { icon: "🔴", cls: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100", label: "위험" },
  };
  const m = map[grade] || { icon: "⚪", cls: "bg-slate-100 text-slate-800", label: grade };
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${m.cls}`}
      title={`강건성 · ${grade} · margin ${pct}% · 임계 대비 최소 여유`}
    >
      {m.icon} {m.label} {pct}%
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════
// 탭 3 · 백테스트 리포트
// ═══════════════════════════════════════════════════════════════
const EVENT_TYPES = ["A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2", "B3"];

function ReportTab({ token }: { token: string }) {
  const [type, setType] = useState<string>("A3");
  const qc = useQueryClient();
  const q = useQuery<PowderKegReport>({
    queryKey: ["powderkeg", "report", type],
    queryFn: () => api.powderkeg.report(type),
  });
  const r = q.data;
  const runBacktest = useMutation({
    mutationFn: () => api.powderkeg.runBacktest(token, type),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["powderkeg", "report", type] }),
  });
  const noCache = r?.decision?.reasons?.includes("no_cache_run_backtest");

  return (
    <section className="space-y-3 rounded border p-4">
      <div className="flex items-center gap-2 text-sm">
        <span>이벤트 타입:</span>
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border px-2 py-1 text-xs"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        {r ? (
          <span
            className={`ml-3 rounded px-2 py-0.5 text-xs ${
              r.decision.validated
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100"
                : "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
            }`}
          >
            {r.decision.validated ? "✅ validated" : "hypothesis"}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => runBacktest.mutate()}
          disabled={!token || runBacktest.isPending}
          className="ml-auto rounded border px-2 py-0.5 text-xs hover:bg-sky-50 disabled:opacity-30"
          title="백테스트 재실행 · 5년 표본 · 최대 수 분 소요"
        >
          {runBacktest.isPending ? "⏳ 계산 중..." : "🔄 재계산"}
        </button>
      </div>
      {noCache ? (
        <div className="rounded border-2 border-dashed border-sky-300 bg-sky-50 p-3 text-xs dark:border-sky-800 dark:bg-sky-950">
          <div className="font-bold">📊 캐시 없음 · 백테스트 실행 필요</div>
          <div className="mt-1 text-muted-foreground">
            상단 재계산 버튼 클릭 · 5년 이벤트 표본으로 CAR 계산 (수 분 소요) · 결과 저장 후 자동 표시.
          </div>
        </div>
      ) : null}
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : !r ? (
        <div className="text-xs text-muted-foreground">데이터 없음</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs md:grid-cols-3">
            <Stat label="전체 이벤트" value={String(r.aggregate.total_events)} />
            <Stat label="유효 (가격)" value={String(r.aggregate.valid_events)} />
            <Stat
              label="승격 결과"
              value={r.decision.validated ? "PASS · " + (r.decision.passing_window || "") : "미달"}
            />
          </div>
          <CarChart perWindow={r.aggregate.per_window} />
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-slate-50 dark:bg-slate-900">
                  <th className="p-2 text-left">Window</th>
                  <th className="p-2 text-right">n</th>
                  <th className="p-2 text-right">mean</th>
                  <th className="p-2 text-right">median</th>
                  <th className="p-2 text-right">win_rate</th>
                  <th className="p-2 text-right">std</th>
                  <th className="p-2 text-right">t-stat</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(r.aggregate.per_window).map(([k, w]) => (
                  <tr key={k} className="border-b">
                    <td className="p-2 font-mono">{k}</td>
                    <td className="p-2 text-right font-mono">{w.n}</td>
                    <td className="p-2 text-right font-mono">{(w.mean_return * 100).toFixed(2)}%</td>
                    <td className="p-2 text-right font-mono">{(w.median_return * 100).toFixed(2)}%</td>
                    <td className="p-2 text-right font-mono">{(w.win_rate * 100).toFixed(1)}%</td>
                    <td className="p-2 text-right font-mono">{(w.std * 100).toFixed(2)}%</td>
                    <td className="p-2 text-right font-mono">{w.t_stat.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="text-[10px] text-muted-foreground">
            게이트: 표본 ≥ 50 · t-stat &gt; 2 · win_rate ≥ 50% · mean_return &gt; 0 · window (1m or 3m)
          </div>
          {r.decision.reasons.length > 0 ? (
            <div className="mt-2 text-[10px] text-muted-foreground">
              사유: {r.decision.reasons.join(" · ")}
            </div>
          ) : null}
          {Object.keys(r.aggregate.error_counts).length > 0 ? (
            <div className="mt-2 text-[10px] text-red-600">
              에러: {Object.entries(r.aggregate.error_counts).map(([k, v]) => `${k}(${v})`).join(" · ")}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between rounded border bg-slate-50 px-2 py-1 dark:bg-slate-900">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-bold">{value}</span>
    </div>
  );
}

/**
 * CAR 곡선 · 지시서 §7-4 window 스펙 · 1d/1m/3m/6m/12m 평균 수익률 시각화.
 * 양(+): 초록 · 음(-): 빨강 · 0 기준선 표시.
 */
function CarChart({ perWindow }: { perWindow: PowderKegReport["aggregate"]["per_window"] }) {
  const ORDER = ["1d", "1m", "3m", "6m", "12m"] as const;
  const data = ORDER.filter((k) => perWindow[k]).map((k) => {
    const w = perWindow[k];
    return {
      window: k,
      mean_pct: +(w.mean_return * 100).toFixed(2),
      n: w.n,
      t_stat: w.t_stat,
    };
  });
  if (data.length === 0) return null;
  return (
    <div className="mt-3 rounded border p-2">
      <div className="mb-1 text-[11px] font-bold text-muted-foreground">
        📈 CAR 곡선 · window 별 평균 수익률 (%)
      </div>
      <div style={{ width: "100%", height: 200 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
            <XAxis dataKey="window" tick={{ fontSize: 11 }} />
            <YAxis
              tick={{ fontSize: 11 }}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{ fontSize: 11 }}
              formatter={(v: number, _n, item) => {
                const d = item.payload as (typeof data)[number];
                return [`${v}% (n=${d.n} · t=${d.t_stat.toFixed(2)})`, "mean"];
              }}
            />
            <ReferenceLine y={0} stroke="#666" strokeDasharray="3 3" />
            <Bar dataKey="mean_pct">
              {data.map((d, i) => (
                <Cell
                  key={`c-${i}`}
                  fill={d.mean_pct >= 0 ? "#10b981" : "#ef4444"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
