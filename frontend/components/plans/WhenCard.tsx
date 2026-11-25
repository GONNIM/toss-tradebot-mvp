"use client";

// 1116-01 「언제」 칸 · 목록 카드 칩(WhenChips)과 상세 맨 위 세로 줄(WhenPanel).
// 날짜는 서버가 준 `when` 만 읽는다 (화면이 날짜를 계산하지 않는다 · 엔진과 같은 함수 한 곳: backend/execution/plan/when.py).
// 사실 표기만 한다: 시킴 말 없음 · 신호 낱말 없음 · 근거와 「추정 · 보장 아님」을 같은 칸에 둔다.
import type { ReactNode } from "react";

import type { PlanWhen, WhenKind, WhenStepKey } from "@/lib/plans";
import { Chip } from "@/components/plans/ui";

export const WHEN_NOTE = "추정 · 보장 아님 · 날짜는 한국 날짜 기준이며 미국 정규장 휴장일을 반영해 계산한 값입니다.";

const STEP_LABEL: Record<WhenStepKey, string> = {
  window_open: "진입 창 열림",
  entry_close: "매수 마감",
  announce: "발표",
  timestop: "시간 손절 시작",
};

const KIND_LABEL: Record<WhenKind, string> = {
  confirmed: "확정",
  estimated: "추정",
  unknown: "확인 못 함",
  manual: "직접 입력",
  edited: "고친 날짜",
};

/** YYYY-MM-DD → MM/DD (글자만 자른다 · 날짜 계산 아님) */
export function md(d: string | null | undefined): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(d ?? "");
  return m ? `${m[1]}/${m[2]}` : "—";
}

export function dDay(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  if (n > 0) return `D-${n}`;
  if (n === 0) return "발표일";
  return `${-n}일 지남`;
}

/** 목록 카드 맨 위 칩 두 줄 */
export function WhenChips({ when, id }: { when: PlanWhen | null | undefined; id: number }) {
  if (!when) return <span className="block text-xs text-muted-foreground" data-testid={`row-when-${id}`}>날짜는 확인 못 함</span>;
  const hasAnnounce = !!when.announce_date;
  const close = when.entry_close_date ? `매수 마감 ${md(when.entry_close_date)}` : null;
  const stop = hasAnnounce && when.timestop_from_date ? `시간 손절 ${md(when.timestop_from_date)}쯤부터` : null;
  const line2 = [close, stop].filter(Boolean).join(" · ");
  return (
    <span className="block space-y-1" data-testid={`row-when-${id}`}>
      <span className="flex flex-wrap items-center gap-1.5">
        {hasAnnounce ? (
          <Chip tone={when.catalyst_kind === "estimated" || when.catalyst_kind === "edited" ? "warn" : "on"} testid={`chip-announce-${id}`}>
            <span className="tabular-nums">발표 {md(when.announce_date)} · {dDay(when.d_day)} · {KIND_LABEL[when.catalyst_kind]}</span>
          </Chip>
        ) : (
          <Chip testid={`chip-announce-${id}`}>발표 시각 없음 · 시간 손절 없음</Chip>
        )}
      </span>
      {line2 && <span className="block text-xs tabular-nums text-muted-foreground" data-testid={`row-when2-${id}`}>{line2}</span>}
    </span>
  );
}

/** 상세 맨 위 「언제」 칸 · children 은 발표 시각 입력(있을 때만) */
export function WhenPanel({ when, children }: { when: PlanWhen | null | undefined; children?: ReactNode }) {
  if (!when) {
    return (
      <section aria-label="언제" data-testid="when-panel" className="space-y-2 rounded-[14px] border border-border bg-card p-3">
        <h3 className="text-base font-bold">언제</h3>
        <p className="text-sm text-muted-foreground">날짜는 확인 못 함</p>
        {children}
      </section>
    );
  }
  const steps = when.steps;
  const firstFuture = steps.findIndex((s) => !s.passed);
  const todayAt = firstFuture === -1 ? steps.length : firstFuture;
  const rows: ReactNode[] = [];
  steps.forEach((s, i) => {
    if (i === todayAt) rows.push(<TodayRow key="today" date={when.today} />);
    rows.push(
      <li key={s.key} data-testid={`when-step-${s.key}`} className="flex items-baseline justify-between gap-3 py-2">
        <span className={`text-sm ${s.passed ? "text-muted-foreground" : "font-semibold"}`}>{STEP_LABEL[s.key]}</span>
        <span className="text-sm font-semibold tabular-nums">
          {md(s.date)}
          {s.key === "timestop" ? "쯤" : ""}
          {s.key === "announce" && when.d_day !== null ? <span className="ml-2 text-muted-foreground">{dDay(when.d_day)}</span> : null}
        </span>
      </li>,
    );
  });
  if (todayAt === steps.length) rows.push(<TodayRow key="today" date={when.today} />);
  const kindTone = when.catalyst_kind === "estimated" || when.catalyst_kind === "edited" ? "warn" : "on";
  return (
    <section aria-label="언제" data-testid="when-panel" className="space-y-2 rounded-[14px] border border-border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-bold">언제</h3>
        <Chip tone={kindTone} testid="when-kind">발표 날짜 · {KIND_LABEL[when.catalyst_kind]}</Chip>
      </div>
      {steps.length === 0 || !when.announce_date ? (
        <p data-testid="when-no-announce" className="text-sm font-semibold">발표 시각 없음 · 시간 손절 없음</p>
      ) : null}
      {steps.length > 0 && <ol data-testid="when-steps" className="divide-y divide-border/60">{rows}</ol>}
      {when.warnings.length > 0 && (
        <ul data-testid="when-warnings" className="space-y-1 text-sm text-warn">
          {when.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      <details className="text-sm" data-testid="when-basis">
        <summary className="min-h-[44px] cursor-pointer py-2 text-muted-foreground" aria-label="날짜의 근거 펼치기">자세히 · 근거</summary>
        <div className="space-y-1 pb-1">
          <p><span className="text-muted-foreground">발표 날짜 근거 </span>{when.basis}</p>
          {when.window_text && <p><span className="text-muted-foreground">진입 창 </span>{when.window_text}</p>}
          <p data-testid="when-applies"><span className="text-muted-foreground">시간 손절 </span>{when.timestop_applies.text}</p>
        </div>
      </details>
      <p className="text-xs text-muted-foreground" data-testid="when-note">{WHEN_NOTE}</p>
      {children}
    </section>
  );
}

function TodayRow({ date }: { date: string }) {
  return (
    <li data-testid="when-today" aria-label="오늘 위치" className="flex items-center gap-2 py-1 text-xs font-semibold text-primary">
      <span aria-hidden className="h-px flex-1 bg-primary/40" />
      <span className="tabular-nums">오늘 {md(date)}</span>
      <span aria-hidden className="h-px flex-1 bg-primary/40" />
    </li>
  );
}
