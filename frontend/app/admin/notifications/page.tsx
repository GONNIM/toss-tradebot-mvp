"use client";

/**
 * 알림 설정 (1022-09 · 2026-10-23) — 텔레그램 알림을 종류별로 켜고·끄고·하루 요약으로 돌린다.
 * 설계: docs/plans/alert-settings/design.md
 * 토글은 화면을 먼저 바꾸고 저장 실패 시 되돌린다. 성공 알림 띠는 5초 뒤 사라지고 실패는 닫을 때까지 남는다.
 */

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AdminSessionBar } from "@/components/admin/AdminSessionBar";
import { api } from "@/lib/api";
import type { NotificationLogItem, NotificationMode, NotificationSettingPatch, NotificationSettingRow } from "@/lib/api";
import { groupRows, intervalText, isRecommended, modeText, recommendedText, whenText } from "@/lib/notifications-display";

type Banner = { kind: "ok" | "error"; text: string } | null;

const INTERVALS = [0, 60, 360, 1440, 10080];
const RESULT_TEXT: Record<NotificationLogItem["result"], string> = {
  sent: "보냄",
  failed: "실패",
  skipped: "설정으로 건너뜀",
  queued: "하루 요약 대기",
};

export default function NotificationsPage() {
  const qc = useQueryClient();
  const [banner, setBanner] = useState<Banner>(null);
  const [busy, setBusy] = useState(false);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["notifications", "settings"],
    queryFn: () => api.notifications.list(),
    retry: false,
  });

  useEffect(() => {
    if (banner?.kind !== "ok") return;
    const t = setTimeout(() => setBanner(null), 5000);
    return () => clearTimeout(t);
  }, [banner]);

  async function save(row: NotificationSettingRow, patch: NotificationSettingPatch, what: string) {
    const key = ["notifications", "settings"];
    // 진행 중인 목록 조회가 화면을 먼저 바꾼 값을 덮지 않게 멈춘다
    await qc.cancelQueries({ queryKey: key });
    const before = qc.getQueryData<NotificationSettingRow[]>(key);
    qc.setQueryData<NotificationSettingRow[]>(key, (rows) => rows?.map((r) => (r.category === row.category ? { ...r, ...patch } : r)));
    try {
      await api.notifications.update(row.category, patch);
      setBanner({ kind: "ok", text: `${row.label} · ${what} 저장했습니다. 1분 안에 반영됩니다.` });
    } catch (e) {
      qc.setQueryData(key, before);
      setBanner({ kind: "error", text: `${row.label} 저장 실패 · 이전 설정으로 되돌렸습니다. 다시 시도해 주세요. (${errorText(e)})` });
    }
  }

  async function applyRecommended() {
    if (!window.confirm("모든 알림을 권고값으로 바꿉니다. 계속할까요?")) return;
    setBusy(true);
    try {
      const r = await api.notifications.applyRecommended();
      await refetch();
      setBanner({ kind: "ok", text: `권고값을 ${r.applied}개 종류에 적용했습니다. 1분 안에 반영됩니다.` });
    } catch (e) {
      setBanner({ kind: "error", text: `권고값 적용 실패 · 바뀐 것이 없습니다. 다시 시도해 주세요. (${errorText(e)})` });
    } finally {
      setBusy(false);
    }
  }

  const unauthorized = (error as (Error & { status?: number }) | null)?.status === 401;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold">🔔 알림 받는 방식</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          필요한 알림만 바로 받고, 나머지는 끄거나 하루 한 번(18:00) 모아 받습니다. 바꾸면 1분 안에 반영됩니다.
        </p>
      </header>

      <AdminSessionBar scope="notifications" onSessionChange={() => refetch()} />

      {banner && (
        <div
          role={banner.kind === "ok" ? "status" : "alert"}
          className={`flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${
            banner.kind === "ok" ? "border-teal-700/40 bg-teal-50 text-teal-900" : "border-red-700/40 bg-red-50 text-red-900"
          }`}
        >
          <span>{banner.text}</span>
          <button className="min-h-[44px] px-2" onClick={() => setBanner(null)} aria-label="알림 닫기">
            ✕
          </button>
        </div>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">알림 설정을 불러오는 중입니다…</p>}
      {unauthorized && (
        <p className="rounded-lg border border-border px-4 py-3 text-sm">
          관리자 로그인이 필요합니다. 위 칸에 관리자 토큰을 넣고 로그인하면 설정이 보입니다.
        </p>
      )}
      {error && !unauthorized && (
        <p role="alert" className="rounded-lg border border-red-700/40 px-4 py-3 text-sm">
          설정을 불러오지 못했습니다 · 서버 응답을 확인한 뒤 새로 고침해 주세요. ({errorText(error)})
        </p>
      )}

      {data && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={applyRecommended}
              disabled={busy}
              className="min-h-[48px] rounded-lg bg-teal-700 px-4 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy ? "적용 중…" : "권고값 한 번에 적용"}
            </button>
            <span className="text-sm text-muted-foreground">
              권고값은 지난 2주 알림을 직접 세어 정한 값입니다. 행마다 이유가 적혀 있습니다.
            </span>
          </div>

          {groupRows(data).map((g) => (
            <section key={g.group} className="rounded-xl border border-border">
              <h2 className="border-b border-border px-4 py-3 text-lg font-semibold">{g.group}</h2>
              <ul>
                {g.rows.map((row) => (
                  <SettingRow key={row.category} row={row} onSave={save} />
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </div>
  );
}

function SettingRow({
  row,
  onSave,
}: {
  row: NotificationSettingRow;
  onSave: (row: NotificationSettingRow, patch: NotificationSettingPatch, what: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const recommended = isRecommended(row);

  return (
    <li className="border-b border-border px-4 py-4 last:border-b-0" style={{ wordBreak: "keep-all" }}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium">{row.label}</div>
          <div className="mt-1 text-sm text-muted-foreground">
            권고: {recommendedText(row.recommended)} {recommended ? "· 지금 권고값과 같음" : ""}
            {row.reason ? ` — ${row.reason}` : ""}
          </div>
          <div className="mt-1 text-sm text-muted-foreground">
            마지막으로 보낸 때 {whenText(row.last_sent_at)}
            {row.skipped_today > 0 && ` · 오늘 설정으로 건너뜀 ${row.skipped_today}건`}
          </div>
          {row.last_failed_at && (
            <div className="mt-1 text-sm text-red-700">
              최근 실패 {whenText(row.last_failed_at)} · {row.last_error ?? "원인 기록 없음"}
            </div>
          )}
        </div>

        {row.configurable ? (
          <div className="flex flex-wrap items-center gap-2">
            {row.locked ? (
              <span className="rounded-full border border-border px-3 py-2 text-sm" title="안전을 위해 끌 수 없습니다">
                끌 수 없음
              </span>
            ) : (
              <label className="flex min-h-[44px] items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={row.enabled}
                  onChange={(e) => onSave(row, { enabled: e.target.checked }, e.target.checked ? "켜기" : "끄기")}
                  className="h-5 w-5 accent-teal-700"
                  aria-label={`${row.label} 받기`}
                />
                {row.enabled ? "받기" : "끔"}
              </label>
            )}
            <select
              value={row.mode}
              onChange={(e) => onSave(row, { mode: e.target.value as NotificationMode }, modeText(e.target.value as NotificationMode))}
              disabled={!row.enabled && !row.locked}
              className="min-h-[44px] rounded-lg border border-border bg-background px-2 text-base"
              aria-label={`${row.label} 받는 방식`}
            >
              <option value="immediate">{modeText("immediate")}</option>
              <option value="digest">{modeText("digest")}</option>
            </select>
            <select
              value={row.resend_minutes}
              onChange={(e) => onSave(row, { resend_minutes: Number(e.target.value) }, `재발송 간격 ${intervalText(Number(e.target.value))}`)}
              disabled={!row.enabled && !row.locked}
              className="min-h-[44px] rounded-lg border border-border bg-background px-2 text-base"
              aria-label={`${row.label} 같은 알림 다시 받는 간격`}
            >
              {Array.from(new Set([...INTERVALS, row.resend_minutes])).map((m) => (
                <option key={m} value={m}>
                  다시 받기: {intervalText(m)}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <span className="rounded-full border border-border px-3 py-2 text-sm">설정 대상 아님 · {row.reason}</span>
        )}
      </div>

      {row.configurable && (
        <div className="mt-2 flex flex-wrap gap-4 text-sm">
          <button className="min-h-[44px] text-teal-700 underline" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {open ? "최근 알림 접기" : "최근 알림 10건 보기"}
          </button>
          <a className="flex min-h-[44px] items-center text-teal-700 underline" href={row.page}>
            관련 화면 열기
          </a>
        </div>
      )}
      {open && <RecentLog category={row.category} />}
    </li>
  );
}

function RecentLog({ category }: { category: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["notifications", "log", category],
    queryFn: () => api.notifications.log(category, 10),
  });
  if (isLoading) return <p className="mt-2 text-sm text-muted-foreground">불러오는 중…</p>;
  if (error) return <p className="mt-2 text-sm text-red-700">최근 알림을 불러오지 못했습니다 · 다시 펼쳐 주세요.</p>;
  if (!data?.length) return <p className="mt-2 text-sm text-muted-foreground">기록된 알림이 아직 없습니다 (기록은 이번 배포부터 쌓입니다).</p>;
  return (
    <ul className="mt-2 border-t border-border">
      {data.map((it, i) => (
        <li key={i} className="flex flex-wrap gap-x-3 border-b border-border py-2 text-sm last:border-b-0">
          <span className="text-muted-foreground">{whenText(it.created_at)}</span>
          <span className={it.result === "failed" ? "text-red-700" : ""}>{RESULT_TEXT[it.result]}</span>
          <span className="min-w-0 flex-1">{it.title}</span>
          {it.error && <span className="w-full text-muted-foreground">{it.error}</span>}
        </li>
      ))}
    </ul>
  );
}

function errorText(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  return msg.replace(/X-API-Token[^·]*/g, "").slice(0, 160);
}
