"use client";

/**
 * 페이지 안 확인 코드 대화상자 (계획서 11절 · 4-2 · 4-2-1).
 * - 열리면 코드를 요청한다(휴대폰 텔레그램으로 6자리가 간다). 남은 시간이 줄어들고 「코드 다시 받기」가 있다.
 * - requireCode=false 면 코드 없이 확인만 받는다(모의 계획 승인).
 * - 브라우저 기본 confirm() 은 쓰지 않는다 (자동 조작 시험용).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Challenge } from "@/lib/plans";
import { errText } from "@/lib/plans";
import { BTN_LINE, BTN_PRIMARY, INPUT, Notice } from "@/components/plans/ui";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  /** 코드를 요청한다. requireCode=false 면 부르지 않는다. */
  requestCode?: () => Promise<Challenge>;
  requireCode?: boolean;
  /** 확인을 누르면 부른다. 던지면 대화상자에 오류가 보이고 열린 채로 둔다. */
  onConfirm: (c: { challenge_id?: number; code?: string }) => Promise<void>;
  /** 코드를 요청한 순간의 값(서버가 준 승인 값)을 보여 줄 때 */
  renderValues?: (values: Record<string, unknown> | undefined) => ReactNode;
  /** 확인 버튼 이름 */
  confirmLabel: string;
  /** 대화상자 위쪽에 더 넣을 입력(예: 종목 입력 · 판정 3줄) 이 비어 있으면 확인 막기 */
  extraReady?: boolean;
  children?: ReactNode;
  testid: string;
}

export function CodeDialog({
  open, onClose, title, requestCode, requireCode = true, onConfirm, renderValues, confirmLabel, extraReady = true, children, testid,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [ch, setCh] = useState<Challenge | null>(null);
  const [left, setLeft] = useState(0);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [reqErr, setReqErr] = useState<string | null>(null);

  const request = useCallback(async () => {
    if (!requestCode) return;
    setBusy(true);
    setReqErr(null);
    setErr(null);
    setCode("");
    try {
      const c = await requestCode();
      setCh(c);
      setLeft(c.expires_in_sec);
    } catch (e) {
      setCh(null);
      setReqErr(errText(e));
    } finally {
      setBusy(false);
    }
  }, [requestCode]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      setCh(null);
      setCode("");
      setErr(null);
      setReqErr(null);
      if (requireCode) void request();
    } else if (!open && el.open) {
      el.close();
    }
    // 열릴 때만 코드를 요청한다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open || !ch) return;
    const t = setInterval(() => setLeft((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [open, ch]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(requireCode ? { challenge_id: ch?.challenge_id, code } : {});
      onClose();
    } catch (e2) {
      setErr(errText(e2));
    } finally {
      setBusy(false);
    }
  }

  const mm = String(Math.floor(left / 60)).padStart(1, "0");
  const ss = String(left % 60).padStart(2, "0");
  const expired = requireCode && ch !== null && left === 0;
  const codeOk = !requireCode || /^\d{6}$/.test(code);
  const canSubmit = !busy && extraReady && codeOk && (!requireCode || (ch !== null && !expired));

  return (
    <dialog
      ref={ref}
      data-testid={testid}
      aria-label={title}
      onClose={onClose}
      onCancel={onClose}
      className="w-[min(92vw,30rem)] rounded-[14px] border border-border bg-card p-0 text-foreground backdrop:bg-black/40"
    >
      <form onSubmit={submit} className="space-y-3 p-4">
        <h2 className="text-lg font-bold">{title}</h2>
        {requireCode && ch && renderValues && (
          <div data-testid={`${testid}-values`} className="rounded-lg border border-border bg-background p-3 text-sm">
            <p className="mb-1 text-xs text-muted-foreground">
              코드를 요청한 순간의 값입니다. 판 번호 {ch.revision ?? "—"} · 내용 확인값 {ch.content_hash ?? "—"}
            </p>
            {renderValues(ch.values)}
          </div>
        )}
        {children}
        {requireCode && (
          <div className="space-y-2">
            <p className="text-sm">휴대폰 텔레그램으로 온 6자리를 넣어 주십시오 · 5분 유효</p>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              aria-label="텔레그램 확인 코드 6자리"
              data-testid={`${testid}-code`}
              disabled={ch === null}
              className={`${INPUT} text-center text-xl tracking-[0.4em]`}
              placeholder="000000"
            />
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span data-testid={`${testid}-left`} className="tabular-nums text-muted-foreground">
                {ch === null ? (busy ? "코드를 보내는 중입니다" : "코드가 아직 없습니다") : expired ? "시간이 지났습니다 · 코드를 다시 받아 주십시오" : `남은 시간 ${mm}:${ss}`}
              </span>
              <button
                type="button"
                onClick={() => void request()}
                disabled={busy}
                aria-label="확인 코드 다시 받기"
                data-testid={`${testid}-resend`}
                className={BTN_LINE}
              >
                코드 다시 받기
              </button>
            </div>
            <p className="text-xs text-muted-foreground">새 코드를 받으면 앞의 코드는 쓸 수 없습니다. 틀린 코드를 5번 넣으면 그 코드는 무효가 됩니다.</p>
          </div>
        )}
        {reqErr && <Notice tone="warn" testid={`${testid}-req-error`}>{reqErr}</Notice>}
        {err && <Notice tone="warn" testid={`${testid}-error`}>{err}</Notice>}
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} aria-label="닫기" data-testid={`${testid}-close`} className={BTN_LINE}>
            닫기
          </button>
          <button type="submit" disabled={!canSubmit} aria-label={confirmLabel} data-testid={`${testid}-submit`} className={BTN_PRIMARY}>
            {busy ? "처리 중" : confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}
