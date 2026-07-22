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
      localStorage.removeItem("powderkeg_report_onboarding_dismissed");
      localStorage.removeItem("powderkeg_events_onboarding_dismissed");
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
      <WorkflowFlowchart />
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
  const [open, setOpen] = useState(false);   // v1.37 · 기본 접기
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

/** v1.37 · 사용법 4단계 워크플로우 · 접기 가능 · 항상 최상단 · 설명은 tooltip. */
function WorkflowFlowchart() {
  const [open, setOpen] = useState(false);   // 기본 접기 · 헤더는 항상 보임
  const steps = [
    { n: "①", label: "자동 감지", desc: "APScheduler · DART 공시 3분 폴링 · Type A/B 이벤트 자동 검출" },
    { n: "②", label: "알림 수신", desc: "Telegram 알림 자동 전송 · Type A 매수 후보 · Type B DO NOT TOUCH" },
    { n: "③", label: "재평가", desc: "'🔄 지금 재평가' 버튼 · 사용자 트리거 · 스크리너 자동 재실행 없음" },
    { n: "④", label: "종목 검토", desc: "종목명 클릭 → 상세 팝업 · 재무·조건·이벤트·외부링크 확인 후 판단" },
  ];
  return (
    <section className="rounded border-2 border-sky-300 bg-sky-50 p-2 dark:border-sky-800 dark:bg-sky-950">
      <button type="button" onClick={() => setOpen(!open)} className="w-full text-left">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 text-xs font-bold text-sky-900 dark:text-sky-100">
            🗺 사용법 · 자동 감지 → 알림 → 재평가 → 종목 검토
          </div>
          <span className="text-[10px] text-sky-700">{open ? "▼ 접기" : "▶ 상세"}</span>
        </div>
      </button>
      <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px]">
        {steps.map((s, i) => (
          <div key={s.n} className="flex items-center gap-1">
            <div
              title={s.desc}
              className="rounded border border-sky-400 bg-white px-2 py-1 font-medium text-sky-900 dark:bg-slate-900 dark:text-sky-100"
            >
              <b>{s.n}</b> {s.label}
            </div>
            {i < steps.length - 1 ? <span className="text-sky-500">→</span> : null}
          </div>
        ))}
      </div>
      {open && (
        <div className="mt-2 space-y-1 rounded border bg-white p-2 text-[11px] text-slate-700 dark:bg-slate-900 dark:text-slate-300">
          {steps.map(s => (
            <div key={s.n}>
              <b className="text-sky-800 dark:text-sky-200">{s.n} {s.label}</b> · {s.desc}
            </div>
          ))}
          <div className="mt-2 rounded bg-amber-50 p-1.5 text-[10px] text-amber-900 dark:bg-amber-950 dark:text-amber-100">
            ⚠️ 스크리너 자동 재평가 없음 (설계 원칙) · 새 재무·최대주주 반영은 사용자가 <b>③ 재평가</b> 트리거해야 함.
          </div>
        </div>
      )}
    </section>
  );
}

function IdentityBanner() {
  const [open, setOpen] = useState(false);   // v1.37 · 기본 접기
  return (
    <section className="rounded border-2 border-red-200 bg-red-50 p-2 text-xs dark:border-red-900 dark:bg-red-950">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full text-left font-bold text-red-900 hover:underline dark:text-red-100"
      >
        {open ? "▼" : "▶"} ⚠️ 이 화면은 백테스트 검증 전 hypothesis 상태입니다.
      </button>
      {open && (
        <ul className="mt-2 space-y-0.5 text-red-800 dark:text-red-200">
          <li>
            · <b>validated</b>=true 이벤트만 반자동 티켓 생성 가능
            <span className="text-[10px]"> · 게이트 4조건 · 표본 ≥ 50 · t-stat &gt; 2 · 승률 &gt; 50% · 평균 수익 &gt; 0</span>
          </li>
          <li>· 오너 개인 이벤트 표기는 공시/기사 원문 링크만 · 판단 문구 표시 X (§7-6-3 명예훼손 방지)</li>
          <li>· Type B (횡령·감사부적정·거래정지) 발생 시 자동 리스트 제거 + 최우선 알림</li>
        </ul>
      )}
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
  const [detailTicker, setDetailTicker] = useState<string | null>(null);   // v1.36 · P5-2 · 팝업
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
            <option value="tier_2_near">🥈 Tier 2 · 실패 1건 (경계)</option>
            <option value="tier_2_needs_data">🥈 Tier 2 · 데이터 부족</option>
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
                {/* v1.37 · 컬럼 폭 고정 · 종목 min-w-64 (256px) · 사유 max-w-80 (320px) truncate */}
                <th className="p-2 text-left min-w-64">종목</th>
                <th className="p-2 text-center">상태</th>
                <th className="p-2 text-right">순현금/시총</th>
                <th className="p-2 text-right">F-Score</th>
                <th className="p-2 text-right">지분율</th>
                <th className="p-2 text-right">PBR</th>
                <th className="p-2 text-right">자사주</th>
                <th className="p-2 text-left max-w-80">사유</th>
                <th className="p-2 text-center">액션</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className={`border-b hover:bg-sky-50/30 ${it.locked ? "bg-amber-50/40 dark:bg-amber-950/20" : ""}`}>
                  <td className="p-2 min-w-64 align-top">   {/* v1.37 · 종목 컬럼 고정 폭 */}
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setDetailTicker(it.ticker)}
                        className="font-medium text-left hover:underline hover:text-sky-700 dark:hover:text-sky-300"
                        title="종목 상세 팝업 열기 (재무 3년·조건·이벤트·외부 링크)"
                      >
                        {it.name || "-"}
                      </button>
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
                    {it.auto_note ? (
                      <div className="mt-0.5 rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">
                        {it.auto_note}
                      </div>
                    ) : null}
                    {it.tier === "tier_2_near" || it.tier === "tier_2_needs_data" || it.tier === "tier_3_watch" ? (
                      <div className="mt-0.5 text-[9px]">
                        {(it.failed_conditions?.length ?? 0) > 0 ? (
                          <span className="text-orange-700 dark:text-orange-300">
                            📌 실패 · {(it.failed_conditions || []).map(f => CONDITION_LABEL_SHORT[f] || f).join(" · ")}
                          </span>
                        ) : null}
                        {(it.missing_conditions?.length ?? 0) > 0 ? (
                          <span className="ml-1 text-slate-600 dark:text-slate-400">
                            🕳 데이터 부족 · {(it.missing_conditions || []).map(f => CONDITION_LABEL_SHORT[f] || f).join(" · ")}
                          </span>
                        ) : null}
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
                  <td className="p-2 max-w-80 text-[10px] text-muted-foreground align-top">
                    {/* v1.37 · 사유 max-w-80 · truncate · hover 시 tooltip */}
                    <div className="line-clamp-2 break-words" title={it.reject_reasons || "-"}>
                      {it.reject_reasons || "-"}
                    </div>
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
      {detailTicker ? (
        <TickerDetailModal ticker={detailTicker} onClose={() => setDetailTicker(null)} />
      ) : null}
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
// 탭 2 · 불꽃 피드 (Type A/B 타임라인) · v1.28 UX 개선
// ═══════════════════════════════════════════════════════════════
function EventsTab() {
  const [hours, setHours] = useState(72);
  const [kindFilter, setKindFilter] = useState<string>("");   // A/B/""
  const [tickerFilter, setTickerFilter] = useState<string>("");
  const q = useQuery({
    queryKey: ["powderkeg", "events", hours],
    queryFn: () => api.powderkeg.events({ hours, limit: 100 }),
    refetchInterval: 30_000,
  });
  const rawItems: PowderKegEventItem[] = q.data?.items || [];
  const items = rawItems.filter(e => {
    if (kindFilter && e.kind !== kindFilter) return false;
    if (tickerFilter && !e.ticker.includes(tickerFilter)) return false;
    return true;
  });
  const countA = rawItems.filter(e => e.kind === "A").length;
  const countB = rawItems.filter(e => e.kind === "B").length;

  return (
    <section className="space-y-3 rounded border p-4">
      <EventsOnboardingCard />
      <div className="flex flex-wrap items-center gap-2 rounded border bg-slate-50 p-2 text-xs dark:bg-slate-900">
        <div className="flex-1 text-sm">
          <span className="font-bold">최근 {hours < 168 ? `${hours}시간` : hours === 168 ? "7일" : "30일"}</span>
          <span className="ml-2 text-muted-foreground">
            · 총 <b>{q.data?.count || 0}건</b> · 🟠 매수 후보 (Type A) {countA}건 · 🔴 회피 (Type B) {countB}건
          </span>
        </div>
        <select
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className="rounded border px-2 py-1"
          title="조회 기간"
        >
          <option value={24}>최근 24시간</option>
          <option value={72}>최근 72시간</option>
          <option value={168}>최근 7일</option>
          <option value={720}>최근 30일</option>
        </select>
        <select
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
          className="rounded border px-2 py-1"
          title="이벤트 종류 필터"
        >
          <option value="">전체 종류</option>
          <option value="A">🟠 매수 후보만 (Type A)</option>
          <option value="B">🔴 회피만 (Type B)</option>
        </select>
        <input
          type="text"
          value={tickerFilter}
          onChange={(e) => setTickerFilter(e.target.value)}
          placeholder="종목코드 필터"
          className="w-28 rounded border px-2 py-1"
        />
      </div>
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : rawItems.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          최근 {hours}시간 · 이벤트 없음 · 자동 감시 (3분 주기) 대기 중.
        </div>
      ) : items.length === 0 ? (
        <div className="rounded border-2 border-dashed p-6 text-center text-xs text-muted-foreground">
          필터 조건에 맞는 이벤트 없음 · 상단 필터 조정.
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((e) => (
            <EventRow key={e.id} event={e} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** 이벤트 행 · v1.28 · 사용자 관점 재설계. */
function EventRow({ event }: { event: PowderKegEventItem }) {
  const info = EVENT_TYPE_INFO[event.event_type];
  const isTypeB = event.kind === "B";
  const bg = isTypeB
    ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950"
    : "border-orange-300 bg-orange-50 dark:border-orange-900 dark:bg-orange-950";
  return (
    <li className={`rounded border-2 p-3 ${bg}`}>
      {/* 상단 · 판정 라벨 + 시각 */}
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="flex-1">
          {isTypeB ? (
            <div className="mb-1 rounded bg-red-800 px-2 py-1 text-sm font-bold text-white">
              🚫 DO NOT TOUCH · 매수 금지 · 자동 리스트 제거
            </div>
          ) : (
            <div className="mb-1 rounded bg-orange-500 px-2 py-1 text-sm font-bold text-white">
              🎯 매수 후보 이벤트 · 검토 필요
            </div>
          )}
        </div>
        <span className="text-[10px] text-muted-foreground whitespace-nowrap">
          {event.detected_at ? fmtKstDateTime(event.detected_at) : "-"}
        </span>
      </div>
      {/* 종목명 + 이벤트 타입 */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-lg font-bold">{event.ticker}</span>
        <span className={`rounded px-2 py-0.5 text-xs font-bold ${isTypeB ? "bg-red-600 text-white" : "bg-orange-500 text-white"}`}>
          {info?.icon} {info?.short || event.event_type}
        </span>
        {event.validated ? (
          <span className="rounded bg-emerald-200 px-1.5 py-0.5 text-[10px] text-emerald-900" title="백테스트 통과 · 매수 신호 사용 가능">
            ✅ Validated
          </span>
        ) : null}
        {event.needs_human_review ? (
          <span className="rounded bg-amber-200 px-1.5 py-0.5 text-[10px] text-amber-900" title="LLM confidence < 0.8 · 사람 판단 필요">
            🟡 사람 확인 필요
          </span>
        ) : null}
      </div>
      {/* 공시 제목 */}
      <div className="mb-1 text-sm">{event.title}</div>
      {info?.long ? (
        <div className="mb-1 text-[10px] text-muted-foreground">
          <b>이 이벤트 뜻</b>: {info.long}
        </div>
      ) : null}
      {/* 원문 + 처리 결과 */}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
        {event.url ? (
          <a
            href={event.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded bg-white px-2 py-0.5 text-sky-700 hover:bg-sky-50 dark:bg-slate-800"
          >
            📄 원문 공시 →
          </a>
        ) : null}
        {event.action_taken ? (
          <span className="rounded bg-white px-2 py-0.5 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            시스템 처리 · <b>{actionToKorean(event.action_taken)}</b>
            {event.confidence != null ? ` (신뢰도 ${(event.confidence * 100).toFixed(0)}%)` : ""}
          </span>
        ) : null}
      </div>
    </li>
  );
}

/** action_taken 한국어화. */
function actionToKorean(action: string): string {
  const map: Record<string, string> = {
    list_removed: "리스트에서 자동 제거 · 매수 금지",
    notified: "Telegram 알림 전송 · 매수 후보 (검토)",
    notified_negative: "Telegram 알림 · 백테스트 음수 · 신중 검토",
    needs_human_review: "사람 판단 필요 (LLM 불명확)",
    skip: "처리 완료 · 재처리 X",
  };
  return map[action] || action;
}

/** 불꽃 피드 · 온보딩 카드 · v1.28. */
function EventsOnboardingCard() {
  const KEY = "powderkeg_events_onboarding_dismissed";
  const [dismissed, setDismissed] = useState(false);
  const [open, setOpen] = useState(false);   // v1.37 · 기본 접기
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
          {open ? "▼" : "▶"} 📖 이 피드가 뭐하는 건가요?
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(KEY, "1");
            setDismissed(true);
          }}
          className="rounded border border-purple-300 px-2 py-0.5 text-[10px] text-purple-700 hover:bg-purple-100"
        >
          다시 안 보기
        </button>
      </div>
      {open && (
        <div className="mt-2 space-y-2 text-[11px] text-purple-900 dark:text-purple-100">
          <div className="rounded border bg-white p-2 dark:bg-slate-900">
            <div className="mb-1 font-bold">🔥 불꽃 (Fire) 이란?</div>
            <p>
              화약고 종목 (Tier 1/2) 에서 <b>중요한 공시가 발생한 순간</b> · DART 자동 감시가 3분마다 검출.
              오너에게 현금 필요한 사건 (담보제공·상속) 또는 회사 위험 신호 (횡령·거래정지) 등.
            </p>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            <div className="rounded border-2 border-orange-300 bg-orange-50 p-2 dark:border-orange-800 dark:bg-orange-950">
              <div className="mb-1 font-bold text-orange-900 dark:text-orange-100">🟠 Type A · 매수 후보 이벤트</div>
              <ul className="space-y-0.5 text-[10px]">
                <li>· A1 ⚖️ 오너 사법 (구속·기소)</li>
                <li>· A2 🕊 오너 상속 (별세)</li>
                <li>· A3 💰 담보제공 (현금 수요)</li>
                <li>· A4 📄 5% 보고 (경영권 압박)</li>
                <li>· A5 💸 자사주 소각·배당</li>
                <li>· A6 🏛 정책 압박 (저PBR)</li>
              </ul>
              <div className="mt-1 text-[10px]">→ Telegram 알림 · 검토 후 개별 판단</div>
            </div>
            <div className="rounded border-2 border-red-300 bg-red-50 p-2 dark:border-red-800 dark:bg-red-950">
              <div className="mb-1 font-bold text-red-900 dark:text-red-100">🔴 Type B · 즉시 회피</div>
              <ul className="space-y-0.5 text-[10px]">
                <li>· B1 🚨 횡령·배임 혐의</li>
                <li>· B2 🚨 감사의견 비적정</li>
                <li>· B3 🚨 거래정지·상장폐지 심사</li>
              </ul>
              <div className="mt-1 rounded bg-red-800 px-1 text-[10px] font-bold text-white">
                → 🚫 리스트 자동 제거 · 매수 금지 · 원금 60% 손실 위험
              </div>
            </div>
          </div>
          <div className="rounded border bg-white p-2 dark:bg-slate-900">
            <div className="mb-1 font-bold">📅 어떻게 활용하나요?</div>
            <ul className="space-y-0.5">
              <li>· <b>Telegram 알림</b> 을 받고 이 페이지에서 원문 공시 확인</li>
              <li>· <b>Type A</b> · 원문 공시 → 화약고 리스트 (탭 1) 종목 상태 재확인 → 매수 결정 (개별 판단)</li>
              <li>· <b>Type B</b> · 이미 자동 처리됨. 사용자 액션 X · 확인만.</li>
              <li>· <b>필터</b> · 종목코드 or 종류로 좁혀서 확인 가능</li>
              <li>· <b>자동 새로고침</b> · 30초 주기</li>
            </ul>
          </div>
        </div>
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
  const [open, setOpen] = useState(false);   // v1.37 · 기본 접기
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
            <a
              href="https://github.com/GONNIM/toss-tradebot-mvp/blob/main/docs/plans/powderkeg-screener/user-guide.md"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1 text-sky-700 underline hover:text-sky-500"
            >
              📖 상세 사용법 문서 →
            </a>
          </div>
        </div>
      )}
    </section>
  );
}

/** v1.36 · P5-2 · 종목 상세 팝업 (옵션 A · 예측 없음).
 *   재무 3년 · 조건별 실측 · 이벤트 이력 · 외부 링크 (KRX·네이버·다음·DART).
 *   지시서 "hypothesis 유지 · 자동매매 금지" 원칙 정합 · 사용자 판단 근거 제공만. */
function TickerDetailModal({ ticker, onClose }: { ticker: string; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["powderkeg", "detail", ticker],
    queryFn: () => api.powderkeg.tickerDetail(ticker),
  });
  const d = q.data;
  const fmtInt = (v: number | null | undefined) => v == null ? "-" : new Intl.NumberFormat("ko-KR").format(Math.round(v));
  const fmtEok = (v: number | null | undefined) => v == null ? "-" : `${(v / 1e8).toFixed(1)}억`;
  const fmtPct = (v: number | null | undefined, d = 1) => v == null ? "-" : `${(v * 100).toFixed(d)}%`;
  const fmtNum = (v: number | null | undefined, d = 3) => v == null ? "-" : v.toFixed(d);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg border-2 border-slate-300 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b bg-white px-4 py-3 dark:bg-slate-900">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold">{d?.name || ticker}</span>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300">{ticker}</span>
            {d?.market ? (
              <span className="rounded bg-sky-100 px-2 py-0.5 text-xs text-sky-800 dark:bg-sky-900 dark:text-sky-100">{d.market.market}</span>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border px-3 py-1 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            ✕ 닫기
          </button>
        </div>

        {q.isLoading ? (
          <div className="p-6 text-center text-sm text-muted-foreground">불러오는 중...</div>
        ) : !d ? (
          <div className="p-6 text-center text-sm text-rose-600">데이터 로드 실패</div>
        ) : (
          <div className="space-y-4 p-4">
            {/* 시장·리스트 요약 */}
            <section className="grid grid-cols-2 gap-3 rounded border bg-sky-50 p-3 dark:bg-sky-950 md:grid-cols-4">
              <div>
                <div className="text-[10px] text-muted-foreground">현재가</div>
                <div className="text-sm font-bold">{fmtInt(d.market?.close_price)}원</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">시가총액</div>
                <div className="text-sm font-bold">{fmtEok(d.market?.market_cap)}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">PBR</div>
                <div className="text-sm font-bold">{fmtNum(d.market?.pbr)}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">60일 거래대금</div>
                <div className="text-sm font-bold">{fmtEok(d.market?.avg_daily_amount_60d)}</div>
              </div>
            </section>

            {/* 리스트 상태 · 조건 */}
            {d.list_item ? (
              <section className="rounded border p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-bold">
                  🎯 화약고 스크리너 판정 <span className="text-[10px] font-normal text-muted-foreground">run {d.list_item.run_id}</span>
                </div>
                <div className="grid grid-cols-2 gap-1 text-xs md:grid-cols-5">
                  {d.list_item.conditions ? Object.entries(d.list_item.conditions).map(([k, v]) => {
                    const label = CONDITION_LABEL_SHORT[k] || k;
                    const cls = v === true ? "bg-emerald-100 text-emerald-800"
                      : v === false ? "bg-rose-100 text-rose-800"
                      : "bg-slate-100 text-slate-600";
                    const mark = v === true ? "✅" : v === false ? "❌" : "🕳";
                    return (
                      <div key={k} className={`rounded px-2 py-1 ${cls}`}>
                        {mark} {label}
                      </div>
                    );
                  }) : null}
                </div>
                {d.list_item.reject_reasons ? (
                  <div className="mt-2 rounded bg-rose-50 p-2 text-[10px] text-rose-800 dark:bg-rose-950 dark:text-rose-100">
                    📌 {d.list_item.reject_reasons}
                  </div>
                ) : null}
                {d.list_item.user_note ? (
                  <div className="mt-2 rounded bg-amber-50 p-2 text-[10px] text-amber-900 dark:bg-amber-950 dark:text-amber-100">
                    📝 {d.list_item.user_note}
                  </div>
                ) : null}
              </section>
            ) : null}

            {/* 재무 3년 */}
            {d.financials_3y.length > 0 ? (
              <section className="rounded border p-3">
                <div className="mb-2 text-sm font-bold">📊 재무 3년 (DART 사업보고서)</div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-100 dark:bg-slate-800">
                      <tr>
                        <th className="p-1 text-left">기준일</th>
                        <th className="p-1 text-right">현금</th>
                        <th className="p-1 text-right">단기금융</th>
                        <th className="p-1 text-right">총차입금</th>
                        <th className="p-1 text-right">계약부채</th>
                        <th className="p-1 text-right">자본총계</th>
                        <th className="p-1 text-right">매출</th>
                        <th className="p-1 text-right">영업이익</th>
                        <th className="p-1 text-right">순이익</th>
                        <th className="p-1 text-center">감사</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.financials_3y.map((f) => (
                        <tr key={f.reference_date} className="border-b">
                          <td className="p-1">{f.reference_date}</td>
                          <td className="p-1 text-right">{fmtEok(f.cash_and_equivalents)}</td>
                          <td className="p-1 text-right">{fmtEok(f.short_term_investments)}</td>
                          <td className="p-1 text-right">{fmtEok(f.total_debt)}</td>
                          <td className="p-1 text-right">{fmtEok(f.contract_liabilities)}</td>
                          <td className="p-1 text-right">{fmtEok(f.total_equity)}</td>
                          <td className="p-1 text-right">{fmtEok(f.revenue)}</td>
                          <td className={`p-1 text-right ${(f.operating_income || 0) < 0 ? "text-rose-700" : "text-emerald-700"}`}>
                            {fmtEok(f.operating_income)}
                          </td>
                          <td className="p-1 text-right">{fmtEok(f.net_income)}</td>
                          <td className="p-1 text-center text-[10px]">{f.audit_opinion || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}

            {/* 최대주주 */}
            {d.shareholder ? (
              <section className="rounded border p-3">
                <div className="mb-1 text-sm font-bold">👥 최대주주 · 지배구조 <span className="text-[10px] font-normal text-muted-foreground">{d.shareholder.reference_date}</span></div>
                <div className="grid grid-cols-3 gap-3 text-xs">
                  <div>최대주주: <b>{fmtPct(d.shareholder.major_pct)}</b></div>
                  <div>특수관계인: <b>{fmtPct(d.shareholder.related_pct)}</b></div>
                  <div>자사주: <b>{fmtPct(d.shareholder.treasury_pct)}</b></div>
                </div>
              </section>
            ) : null}

            {/* 이벤트 이력 */}
            <section className="rounded border p-3">
              <div className="mb-2 text-sm font-bold">🔥 이벤트 이력 <span className="text-[10px] font-normal text-muted-foreground">({d.events.length}건)</span></div>
              {d.events.length === 0 ? (
                <div className="text-xs text-muted-foreground">이벤트 없음 · Type A 트리거 대기 상태</div>
              ) : (
                <div className="max-h-48 space-y-1 overflow-y-auto">
                  {d.events.map((e) => (
                    <div key={e.id} className={`flex items-center gap-2 rounded px-2 py-1 text-[11px] ${e.kind === "A" ? "bg-orange-50 dark:bg-orange-950" : "bg-rose-50 dark:bg-rose-950"}`}>
                      <span className="rounded bg-white/50 px-1 font-mono text-[9px]">{e.event_type}</span>
                      <span className="text-[9px] text-muted-foreground">{e.release_date?.slice(0, 10) || e.detected_at?.slice(0, 10)}</span>
                      {e.url ? (
                        <a href={e.url} target="_blank" rel="noreferrer" className="flex-1 truncate hover:underline">{e.title}</a>
                      ) : (
                        <span className="flex-1 truncate">{e.title}</span>
                      )}
                      {e.action_taken ? (
                        <span className="rounded bg-slate-200 px-1 text-[9px] text-slate-700 dark:bg-slate-700 dark:text-slate-200">{e.action_taken}</span>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* 외부 링크 */}
            <section className="rounded border-2 border-dashed border-sky-300 p-3">
              <div className="mb-2 text-sm font-bold">🔗 외부 참조 (예측 없음 · 사용자 직접 판단)</div>
              <div className="flex flex-wrap gap-2 text-xs">
                <a href={d.external_links.krx_chart} target="_blank" rel="noreferrer" className="rounded border px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800">📊 KRX 차트</a>
                <a href={d.external_links.naver_finance} target="_blank" rel="noreferrer" className="rounded border px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800">🟢 네이버 금융</a>
                <a href={d.external_links.daum_finance} target="_blank" rel="noreferrer" className="rounded border px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800">🟡 다음 금융</a>
                <a href={d.external_links.dart_corp} target="_blank" rel="noreferrer" className="rounded border px-2 py-1 hover:bg-slate-50 dark:hover:bg-slate-800">📄 DART 공시</a>
              </div>
              <div className="mt-2 text-[10px] text-muted-foreground">
                ⚠️ 이 스크리너는 매수 후보 발굴만 · 매수 판단·주가 예측 없음 · 반드시 사용자 직접 확인 후 판단.
              </div>
            </section>

            <div className="text-[10px] text-muted-foreground">{d.disclaimer}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Tier 뱃지 · v1.20 리뷰어 Priority 4 · v1.29 3차 리뷰 P1 · 3상태 분리
 *   (True/False/None → passed/failed/missing 반영). */
function TierBadge({ tier, passed }: { tier?: string; passed?: number }) {
  if (!tier) return null;
  const cfg: Record<string, { icon: string; label: string; cls: string }> = {
    tier_1_passed:     { icon: "🥇", label: "Tier 1",              cls: "bg-amber-100 text-amber-900 dark:bg-amber-900 dark:text-amber-100" },
    tier_2_near:       { icon: "🥈", label: "Tier 2 · 경계",       cls: "bg-slate-200 text-slate-900 dark:bg-slate-700 dark:text-slate-100" },
    tier_2_needs_data: { icon: "🥈", label: "Tier 2 · 데이터부족", cls: "bg-sky-100 text-sky-900 dark:bg-sky-900 dark:text-sky-100" },
    tier_3_watch:      { icon: "🥉", label: "Tier 3",              cls: "bg-orange-100 text-orange-900 dark:bg-orange-900 dark:text-orange-100" },
    cash_suspect:      { icon: "⚠️", label: "현금 의심",           cls: "bg-yellow-100 text-yellow-900 dark:bg-yellow-900 dark:text-yellow-100" },
    rejected:          { icon: "❌", label: "탈락",                cls: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300" },
  };
  const m = cfg[tier] || cfg.rejected;
  const title = tier === "tier_2_needs_data"
    ? `실 통과 ${passed ?? "-"}/10 · 데이터 부족 조건 채우면 통과 가능`
    : passed != null ? `조건 통과: ${passed}/10` : tier;
  return (
    <span
      title={title}
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
            <div className="mb-1 flex items-center justify-between text-[10px] font-semibold text-muted-foreground">
              <span>조건별 통과/실패/결측 (총 {d.evaluable}개 대비)</span>
              <span className="flex gap-2 text-[9px] font-normal">
                <span className="text-emerald-700">■ 통과</span>
                <span className="text-rose-700">■ 실패</span>
                <span className="text-slate-500">■ 결측</span>
              </span>
            </div>
            {d.per_condition.map((c) => {
              const total = c.passed + (c.failed ?? 0) + (c.missing ?? 0);
              const pctP = total > 0 ? Math.round((c.passed / total) * 100) : 0;
              // v1.35 · 4차 리뷰 P4-4 · 3색 분리 (통과·실패·결측)
              // 리뷰어 지적 · 결측이 실패로 합산되는 가짜 진단 해소.
              const wP = total > 0 ? Math.round((c.passed / total) * 100) : 0;
              const wF = total > 0 ? Math.round(((c.failed ?? 0) / total) * 100) : 0;
              const wM = total > 0 ? Math.round(((c.missing ?? 0) / total) * 100) : 0;
              return (
                <div key={c.id} className="flex items-center gap-2">
                  <div className="w-52 truncate text-[10px]">{c.label}</div>
                  <div className="flex h-3 flex-1 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
                    <div className="h-full bg-emerald-400 dark:bg-emerald-600" style={{ width: `${wP}%` }} title={`통과 ${c.passed}`} />
                    <div className="h-full bg-rose-400 dark:bg-rose-600" style={{ width: `${wF}%` }} title={`실패 ${c.failed ?? 0}`} />
                    <div className="h-full bg-slate-400 dark:bg-slate-500" style={{ width: `${wM}%` }} title={`결측 ${c.missing ?? 0}`} />
                  </div>
                  <div className="w-32 text-right font-mono text-[9px]">
                    <span className="text-emerald-700">{c.passed}</span>
                    <span className="text-muted-foreground">/</span>
                    <span className="text-rose-700">{c.failed ?? 0}</span>
                    <span className="text-muted-foreground">/</span>
                    <span className="text-slate-500">{c.missing ?? 0}</span>
                    <span className="ml-1 text-muted-foreground">({pctP}%)</span>
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

/** 이벤트 타입 · 사용자 친화 라벨 · v1.27 · 백테스트 리포트 이해도 개선. */
const EVENT_TYPE_INFO: Record<string, { icon: string; short: string; long: string; expected: string }> = {
  A1: { icon: "⚖️", short: "오너 사법", long: "최대주주 개인 · 구속·기소·검찰 등", expected: "매수 후보 가설" },
  A2: { icon: "🕊", short: "오너 상속", long: "최대주주 사망·상속 관련 공시", expected: "매수 후보 가설" },
  A3: { icon: "💰", short: "담보제공", long: "최대주주 주식담보제공 계약 (현금 수요 신호)", expected: "매수 후보 가설 (실측 반박)" },
  A4: { icon: "📄", short: "5% 보고", long: "행동주의 펀드 · 대량보유 5% 보고", expected: "매수 후보 가설" },
  A5: { icon: "💸", short: "자사주 소각", long: "배당 확대 · 자기주식 소각 · 기업가치 제고", expected: "매수 후보 가설" },
  A6: { icon: "🏛", short: "저PBR 압박", long: "정책 발표 · 상법 개정 등 정책 압박", expected: "매수 후보 가설" },
  B1: { icon: "🚨", short: "횡령·배임", long: "횡령·배임 혐의발생 공시", expected: "즉시 회피 (검증)" },
  B2: { icon: "🚨", short: "감사 비적정", long: "감사의견 한정·부적정·의견거절", expected: "즉시 회피" },
  B3: { icon: "🚨", short: "거래정지", long: "거래정지·상장적격성 실질심사 대상", expected: "즉시 회피 (검증)" },
};

function ReportTab({ token }: { token: string }) {
  const [type, setType] = useState<string>("A3");
  const [expandStats, setExpandStats] = useState(false);
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
  const info = EVENT_TYPE_INFO[type];

  return (
    <section className="space-y-3 rounded border p-4">
      <ReportOnboardingCard />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-bold">이벤트 타입 선택:</span>
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border px-2 py-1 text-xs font-mono"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {EVENT_TYPE_INFO[t]?.icon} {t} · {EVENT_TYPE_INFO[t]?.short}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => runBacktest.mutate()}
          disabled={!token || runBacktest.isPending}
          className="ml-auto rounded border px-2 py-0.5 text-xs hover:bg-sky-50 disabled:opacity-30"
          title="백테스트 재실행 · 5년 표본 · 수 분 소요"
        >
          {runBacktest.isPending ? "⏳ 계산 중..." : "🔄 재계산"}
        </button>
      </div>
      {info && (
        <div className="rounded border bg-slate-50 p-2 text-xs dark:bg-slate-900">
          <div className="font-bold">{info.icon} {type} · {info.long}</div>
          <div className="text-muted-foreground">지시서 가설: {info.expected}</div>
        </div>
      )}
      {noCache ? (
        <div className="rounded border-2 border-dashed border-sky-300 bg-sky-50 p-3 text-xs dark:border-sky-800 dark:bg-sky-950">
          <div className="font-bold">📊 캐시 없음 · 백테스트 실행 필요</div>
          <div className="mt-1 text-muted-foreground">
            상단 재계산 버튼 클릭 · 5년 이벤트 표본으로 계산 (수 분 소요) · 결과 저장 후 자동 표시.
          </div>
        </div>
      ) : null}
      {q.isLoading ? (
        <div className="text-xs text-muted-foreground">불러오는 중...</div>
      ) : !r ? (
        <div className="text-xs text-muted-foreground">데이터 없음</div>
      ) : (
        <>
          <VerdictCard type={type} report={r} />
          <PlainSummary type={type} report={r} />
          <CarChart perWindow={r.aggregate.per_window} />
          <div className="rounded border bg-white p-2 text-xs dark:bg-slate-900">
            <button
              type="button"
              onClick={() => setExpandStats(!expandStats)}
              className="mb-1 flex w-full items-center justify-between font-bold hover:text-sky-600"
            >
              <span>📉 상세 통계 (전문가용)</span>
              <span>{expandStats ? "▼" : "▶"}</span>
            </button>
            {expandStats && (
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="border-b bg-slate-50 dark:bg-slate-900">
                      <th className="p-2 text-left" title="이벤트 발생 후 며칠·개월 후 측정">기간</th>
                      <th className="p-2 text-right" title="이 기간의 유효 표본 수 (가격 데이터 있는 케이스)">표본 n</th>
                      <th className="p-2 text-right" title="평균 수익률 (양수=이익 · 음수=손실)">평균</th>
                      <th className="p-2 text-right" title="중앙값 (극단값 영향 배제)">중앙값</th>
                      <th className="p-2 text-right" title="양수 수익 케이스 비율 (승률)">승률</th>
                      <th className="p-2 text-right" title="표준편차 (변동성)">변동성</th>
                      <th className="p-2 text-right" title="t-통계량 · 절대값 > 2 이면 통계적 유의 · +는 양수 유의 · -는 음수 유의">t-값</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(r.aggregate.per_window).map(([k, w]) => (
                      <tr key={k} className="border-b">
                        <td className="p-2 font-mono">{k === "1d" ? "1일" : k.replace("m", "개월")}</td>
                        <td className="p-2 text-right font-mono">{w.n}</td>
                        <td className={`p-2 text-right font-mono ${w.mean_return >= 0 ? "text-emerald-700" : "text-red-700"}`}>
                          {(w.mean_return * 100).toFixed(2)}%
                        </td>
                        <td className="p-2 text-right font-mono">{(w.median_return * 100).toFixed(2)}%</td>
                        <td className="p-2 text-right font-mono">{(w.win_rate * 100).toFixed(1)}%</td>
                        <td className="p-2 text-right font-mono">{(w.std * 100).toFixed(2)}%</td>
                        <td className={`p-2 text-right font-mono ${Math.abs(w.t_stat) > 2 ? "font-bold" : ""}`}>
                          {w.t_stat.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="mt-2 text-[10px] text-muted-foreground">
                  <b>매수 승격 조건 (4가지 모두 충족)</b> · 표본 ≥ 50 · t-값 &gt; 2 · 승률 &gt; 50% · 평균 수익 &gt; 0 · 대상 기간 (1개월 or 3개월)
                </div>
                {r.decision.reasons.length > 0 ? (
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    <b>미달 사유</b>: {r.decision.reasons.map(reasonToKorean).join(" · ")}
                  </div>
                ) : null}
                {Object.keys(r.aggregate.error_counts).length > 0 ? (
                  <div className="mt-1 text-[10px] text-red-600">
                    <b>데이터 gap</b>: {Object.entries(r.aggregate.error_counts).map(([k, v]) => `${errorToKorean(k)} ${v}건`).join(" · ")}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

/** 판정 큰 카드 · 사용자에게 답변 · v1.27. */
function VerdictCard({ type, report }: { type: string; report: PowderKegReport }) {
  const passed = report.decision.validated;
  const window12m = report.aggregate.per_window["12m"];
  const info = EVENT_TYPE_INFO[type];
  const isTypeB = type.startsWith("B");

  let icon = "🔬";
  let title = "가설 상태 · 매수 신호 아직 아님";
  let color = "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900";
  let subtitle = "5년 데이터로 통계적으로 확인 안 됨. 자동매매 연결 불가.";

  if (passed) {
    icon = "✅";
    title = "매수 신호로 사용 가능 (Validated)";
    color = "border-emerald-300 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950";
    subtitle = "5년 통계 · 매수 후보 확인. 반자동 티켓 생성 가능.";
  } else if (isTypeB) {
    icon = "🚫";
    title = "즉시 회피 · 매수 금지";
    color = "border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950";
    subtitle = "이 이벤트 발생 종목은 리스트에서 자동 제거 · DO NOT TOUCH.";
  } else if (window12m && window12m.mean_return < -0.05 && window12m.n >= 50) {
    icon = "🔬";
    title = "관찰 후보 · 백테스트 음수 · 단독 매수 금지";
    color = "border-orange-300 bg-orange-50 dark:border-orange-800 dark:bg-orange-950";
    subtitle = "가설과 반대로 · 이 이벤트 발생 후 평균 손실. 다른 조건과 조합 필요.";
  }

  return (
    <div className={`rounded border-2 p-3 text-sm ${color}`}>
      <div className="text-lg font-bold">{icon} {title}</div>
      <div className="mt-1 text-xs">{subtitle}</div>
      <div className="mt-2 text-[11px] text-muted-foreground">
        이벤트 타입 · {info?.icon} <b>{type} · {info?.long}</b>
      </div>
    </div>
  );
}

/** 평이한 언어 요약 · v1.27. */
function PlainSummary({ type, report }: { type: string; report: PowderKegReport }) {
  const w12 = report.aggregate.per_window["12m"];
  const w6 = report.aggregate.per_window["6m"];
  const w1 = report.aggregate.per_window["1m"];
  const wPrimary = w12 || w6 || w1;
  if (!wPrimary) {
    return (
      <div className="rounded border bg-yellow-50 p-2 text-xs dark:bg-yellow-950">
        📊 <b>표본 부족</b> · 이 이벤트는 5년 데이터로 계산할 수 있는 케이스가 부족합니다.
        (전체 {report.aggregate.total_events}건 · 유효 {report.aggregate.valid_events}건)
      </div>
    );
  }
  const label12 = w12 ? "12개월" : w6 ? "6개월" : "1개월";
  const meanPct = ((wPrimary.mean_return || 0) * 100).toFixed(1);
  const winPct = ((wPrimary.win_rate || 0) * 100).toFixed(0);
  const tstat = (wPrimary.t_stat || 0).toFixed(2);
  const significance = Math.abs(wPrimary.t_stat || 0) > 2 ? "통계적으로 유의미" : "통계적으로 애매";
  const direction = (wPrimary.mean_return || 0) >= 0 ? "이익" : "손실";
  const info = EVENT_TYPE_INFO[type];

  return (
    <div className="grid gap-2 md:grid-cols-2">
      <div className="rounded border bg-white p-3 text-xs dark:bg-slate-900">
        <div className="mb-2 font-bold">📊 이 이벤트 · 5년 총계</div>
        <ul className="space-y-1">
          <li>· <b>{info?.short}</b> · 5년간 발생 {report.aggregate.total_events}건</li>
          <li>· 이 중 가격 데이터 있는 케이스 · {report.aggregate.valid_events}건</li>
          <li>· 이벤트 후 <b>{label12}</b> 평균 <b className={(wPrimary.mean_return || 0) >= 0 ? "text-emerald-700" : "text-red-700"}>{meanPct}%</b> {direction}</li>
          <li>· 100번 중 <b>{winPct}번</b> 이익 · {100 - Number(winPct)}번 손실</li>
          <li>· 통계 유의성 · <b>{significance}</b> (t = {tstat})</li>
        </ul>
      </div>
      <div className="rounded border bg-white p-3 text-xs dark:bg-slate-900">
        <div className="mb-2 font-bold">💡 이게 무슨 뜻인가요?</div>
        <p className="mb-1">
          지난 5년 · 이 이벤트가 <b>{report.aggregate.total_events}번</b> 발생.
          만약 매번 발생 후 다음 날 매수 · <b>{label12} 뒤 정리</b>했다면:
        </p>
        <p>
          평균 <b className={(wPrimary.mean_return || 0) >= 0 ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}>{meanPct}%</b> {direction}을 봤을 것.
          {Math.abs(wPrimary.t_stat || 0) > 2 ? (
            <> 이 결과는 <b>우연이 아닐 가능성 큼</b> (t = {tstat} · |t| &gt; 2).</>
          ) : (
            <> 하지만 표본 편차 크고 · <b>결론 내리기 어려움</b> (t = {tstat}).</>
          )}
        </p>
      </div>
    </div>
  );
}

/** 통계 게이트 미달 사유 한국어화. */
function reasonToKorean(reason: string): string {
  if (reason.startsWith("insufficient_samples")) {
    const m = reason.match(/\((\d+)<(\d+)\)/);
    return m ? `표본 부족 (${m[1]}/${m[2]})` : "표본 부족";
  }
  if (reason.includes("t_stat=")) {
    const m = reason.match(/(\w+)\.t_stat=([-\d.]+)/);
    return m ? `${m[1]} 통계 유의성 낮음 (t=${m[2]})` : reason;
  }
  if (reason.includes("win_rate=")) {
    const m = reason.match(/(\w+)\.win_rate=([-\d.]+)/);
    return m ? `${m[1]} 승률 부족 (${Math.round(Number(m[2]) * 100)}%)` : reason;
  }
  if (reason.includes("mean_return=")) {
    const m = reason.match(/(\w+)\.mean_return=([-\d.]+)/);
    return m ? `${m[1]} 평균 손실 (${(Number(m[2]) * 100).toFixed(2)}%)` : reason;
  }
  if (reason === "no_cache_run_backtest") return "캐시 없음 · 재계산 필요";
  if (reason === "no_gate_window_available") return "게이트 기간 데이터 없음";
  if (reason.startsWith("passed_on_")) return `승격 · ${reason.replace("passed_on_", "")} 통과`;
  return reason;
}

/** 데이터 gap 에러 한국어화. */
function errorToKorean(err: string): string {
  if (err.includes("entry_price_zero")) return "시가 부재 (거래정지·상폐)";
  if (err.includes("no_price_data")) return "가격 데이터 없음";
  if (err.includes("no_next_trading_day")) return "이후 거래일 없음 (상폐)";
  if (err.includes("fdr_")) return "가격 조회 실패";
  return err;
}

/** 백테스트 리포트 사용법 안내 · v1.27. */
function ReportOnboardingCard() {
  const KEY = "powderkeg_report_onboarding_dismissed";
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
          {open ? "▼" : "▶"} 📖 이 리포트가 뭐하는 건가요?
        </button>
        <button
          type="button"
          onClick={() => {
            localStorage.setItem(KEY, "1");
            setDismissed(true);
          }}
          className="rounded border border-purple-300 px-2 py-0.5 text-[10px] text-purple-700 hover:bg-purple-100"
        >
          다시 안 보기
        </button>
      </div>
      {open && (
        <ul className="mt-2 space-y-1 text-[11px] text-purple-900 dark:text-purple-100">
          <li>
            · <b>목적</b> · 이 이벤트 (예: <b>담보제공</b>) 가 매수 신호로 쓸 만한지 · 지난 5년 데이터로 검증.
          </li>
          <li>
            · <b>계산 방법</b> · 과거 5년간 이 이벤트가 발생한 모든 케이스 수집 → 이벤트 다음 날 매수 후 1개월/3개월/6개월/12개월 뒤 수익 측정 → 평균/승률/통계 유의성 계산.
          </li>
          <li>
            · <b>결과 판정</b> · <b>✅ validated</b> = 매수 신호로 쓸 수 있음 (지금은 모두 hypothesis). <b>🔬 hypothesis</b> = 아직 통계로 확인 안 됨 · 자동매매 X.
          </li>
          <li>
            · <b>Type B 종목</b> (횡령·감사비적정·거래정지) · 실측 결과 · <b>매수 시 손실 확실</b> · 무조건 회피.
          </li>
          <li>
            · <b>이벤트 타입 바꿔가며 확인</b> · A1~B3 상단 드롭다운에서 선택.
          </li>
        </ul>
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
