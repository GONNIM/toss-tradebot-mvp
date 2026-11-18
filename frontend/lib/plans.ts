// 1116-01 계획 실행기 화면 · 서버 계약: backend/api/routes/plans.py (응답 모양의 진리)
// 화면 서버는 토스를 부르지 않는다. 쿠키 전용 동작(승인 · 인수 · 재개 · 스위치)은 같은 주소의 로그인 쿠키로만 된다.
// 화면에 예시로 쓰는 종목 · 금액은 가짜 값(TESTA)뿐이다. 실제 종목 · 금액 · 계좌 값은 쓰지 않는다.

import { fmtKstDateTime } from "@/lib/time";

const BASE = "/api/v1/plans";

export type PlanMode = "live" | "test" | "paper";

export interface PlanParams {
  budget_usd?: number | string | null;
  buy_watch?: number | string | null;
  buy_order?: number | string | null;
  qty?: number | string | null;
  tp1_watch?: number | string | null;
  tp1_order?: number | string | null;
  ladder_pcts?: (number | string)[] | null;
  announce_at?: string | null;
  entry_close_at?: string | null;
  entry_window_end?: string | null;
  adopt?: { qty?: number | string; avg_price?: number | string; trailing?: boolean; peak?: number | string } | null;
  [k: string]: unknown;
}

export interface Plan {
  id: number;
  mode: PlanMode;
  source: "manual" | "adopt";
  symbol: string;
  state: string;
  revision: number;
  halted_reason: string | null;
  approved_by: string | null;
  avg_price: number | null;
  peak_price: number | null;
  timestop_stage: string;
  params: PlanParams;
  created_at: string | null;
  updated_at: string | null;
  approved_at?: string | null;
  qty?: number | string | null;
}

/** 목록 한 줄 · 서버가 더해 준 칸 (live_cond_count · tp1_mode · price · price_at) */
export interface PlanRow extends Plan {
  live_cond_count?: number;
  tp1_mode?: "register" | "watch" | null;
  price?: number | null;
  price_at?: string | null;
}

export interface TossState {
  status: string;
  last_ok_at: string | null;
}

export interface Leg {
  id: number;
  role: "buy" | "sl" | "tp1" | string;
  seq: number;
  kind: string;
  qty: number;
  watch: number | null;
  order: number | null;
  status: string;
  tag: string;
}

export interface PlanEventRow {
  ts: string;
  kind: string;
  detail: string;
}

export interface ActualLeg {
  toss_id?: string;
  role?: string;
  qty: number;
  watch: number | null;
  order: number | null;
}

export interface ForeignCond {
  toss_id?: string;
  qty: number;
  watch: number | null;
  order: number | null;
  side?: string;
}

export interface PlanLive {
  price: number | null;
  price_at: string | null;
  pnl: { usd: number; pct: number; estimate: boolean } | null;
  next_swap_at: string | null;
  tp1_gap_pct: number | null;
  trailing: { peak: number | null; stop: number | null } | null;
  tp1_mode: "register" | "watch" | null;
  plan_qty: number | null;
  account_qty: number | null;
  account_qty_at: string | null;
  outside_qty: number | null;
}

export interface AdoptWait {
  foreign_conds: ForeignCond[];
  checked_at: string | null;
  seconds_left: number | null;
  max_gap_sec: number;
  waiting_minutes: number | null;
}

export interface ValidateCheck {
  key: string;
  label: string;
  status: "ok" | "warn" | "fail" | "unknown" | string;
  message: string;
}

export interface ValidateResult {
  ok: boolean;
  checks: ValidateCheck[];
  values: { order_usd: number; qty: number; qty_source?: "server" | "given"; qty_given?: number | null };
}

export interface PlanDetail {
  plan: Plan;
  approval_values: Record<string, unknown>;
  content_hash: string;
  legs: Leg[];
  events: PlanEventRow[];
  invariant: { status: "ok" | "shortage" | "excess" | string; plan_qty: number; accepted_sell: number; sl_sum: number; target: number };
  /** 실행기가 토스에서 마지막으로 읽은 다리 · null 이면 확인 못 함 */
  actual_legs?: ActualLeg[] | null;
  actual_at?: string | null;
  live?: PlanLive;
  adopt?: AdoptWait | null;
}

export interface ExecutorStatus {
  switches: { live: boolean; paper: boolean };
  last_change: { actor: string; ts: string; reason: string; switch: string; new: boolean } | null;
  kill_switch: { active: boolean; sell_allowed: boolean };
  heartbeat_age_sec: number | null;
  ws_status: string | null;
  last_resync_at: string | null;
  /** PLAN_PAPER_TEST_ENABLED 이거나 모의 스위치가 켜졌을 때만 true */
  paper_test_enabled?: boolean;
  toss?: TossState;
}

export interface Challenge {
  challenge_id: number;
  expires_in_sec: number;
  revision?: number;
  content_hash?: string;
  values?: Record<string, unknown>;
}

export class PlanApiError extends Error {
  status: number;
  reason: string;
  constructor(status: number, reason: string, message: string) {
    super(message);
    this.status = status;
    this.reason = reason;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    let reason = "";
    let message = `요청이 실패했습니다 (${res.status})`;
    try {
      const j = (await res.json()) as { detail?: unknown };
      const d = j?.detail;
      if (typeof d === "string") message = d;
      else if (d && typeof d === "object") {
        const o = d as { reason?: string; message?: string };
        reason = o.reason ?? "";
        if (o.message) message = o.message;
      }
    } catch {
      // 본문이 없으면 기본 문구
    }
    if (res.status === 401) message = "관리자 로그인이 필요합니다. 오른쪽 위 「관리자 로그인」 에서 로그인한 뒤 다시 하십시오.";
    if (res.status === 403) message = "이 동작은 같은 주소에서 로그인한 브라우저(쿠키)로만 됩니다.";
    throw new PlanApiError(res.status, reason, message);
  }
  return (await res.json()) as T;
}

export const plansApi = {
  list: () => call<{ plans: PlanRow[]; toss?: TossState }>("GET", ""),
  detail: (id: number) => call<PlanDetail>("GET", `/${id}`),
  status: () => call<ExecutorStatus>("GET", "/executor/status"),
  create: (b: { symbol: string; mode: PlanMode; source: "manual" | "adopt"; params: PlanParams }) =>
    call<{ plan: Plan }>("POST", "", b),
  edit: (id: number, values: Record<string, unknown>) => call<{ plan: Plan }>("PATCH", `/${id}`, { values }),
  stop: (id: number) => call<{ halted: boolean; plan: Plan }>("POST", `/${id}/stop`),
  adoptCancel: (id: number) => call<{ queued: number }>("POST", `/${id}/adopt-cancel`),
  timestopStop: (id: number) => call<{ queued: number }>("POST", `/${id}/timestop-stop`),
  confirmChallenge: (action: "approve" | "adopt" | "resume", plan_id: number) =>
    call<Challenge>("POST", "/confirm/challenge", { action, plan_id }),
  validate: (b: { symbol: string; mode: PlanMode; source: "manual" | "adopt"; params: PlanParams }) =>
    call<ValidateResult>("POST", "/validate", b),
  resync: (id: number) => call<{ queued: number }>("POST", `/${id}/resync`),
  approve: (
    id: number,
    b: {
      challenge_id?: number; code?: string; approver: string;
      ticker?: string; thesis?: string; invalidation_price?: number | null; target_price?: number | null;
    },
  ) => call<{ plan: Plan; judgment_saved?: boolean }>("POST", `/${id}/approve`, b),
  resume: (id: number, b: { challenge_id?: number; code?: string }) =>
    call<{ queued: number }>("POST", `/${id}/resume`, { approver: "대표", ...b }),
  liveChallenge: () => call<Challenge>("POST", "/switches/live/challenge"),
  setLive: (b: { on: boolean; reason: string; challenge_id?: number; code?: string }) =>
    call<{ live: boolean; previous: boolean }>("POST", "/switches/live", b),
  setPaper: (b: { on: boolean; reason: string }) => call<{ paper: boolean; previous: boolean }>("POST", "/switches/paper", b),
};

export const TP1_MODE_LABEL: Record<string, string> = { register: "조건주문 등록", watch: "감시 모드" };

export function pct(v: unknown, digits = 2): string {
  const n = num(v);
  return n === null ? "확인 못 함" : `${n > 0 ? "+" : ""}${n.toFixed(digits)}%`;
}

export const MODE_LABEL: Record<string, string> = {
  live: "실전",
  test: "실제 주문 시험",
  paper: "모의 시험 · 토스 주문 없음",
};

export const STATE_LABEL: Record<string, string> = {
  DRAFT: "초안",
  APPROVED: "승인됨",
  ENTRY_ARMED: "매수 대기",
  ENTRY_RETRY: "매수 다시 시도",
  HOLDING: "보유 중",
  TP1_WAIT: "1차 익절 대기",
  TRAILING: "고점 따라 손절 올림",
  CLOSED: "끝남",
  CANCELLED: "취소됨",
  ADOPT_PENDING: "인수 대기",
  HALTED: "정지됨",
};

/** 상세 화면 단계 표시줄 순서 (정지 · 인수 대기는 별도 표시) */
export const STATE_FLOW = ["DRAFT", "APPROVED", "ENTRY_ARMED", "HOLDING", "TP1_WAIT", "TRAILING", "CLOSED"];

export const TERMINAL_STATES = ["CLOSED", "CANCELLED"];

export const ROLE_LABEL: Record<string, string> = { buy: "매수", sl: "손절", tp1: "1차 익절" };
/** 손절 다리에 붙는 시간대 이름표 (regular = 정규장 사다리 · emergency = 정규장 밖 비상 손절) */
export const TAG_LABEL: Record<string, string> = { regular: "정규장", emergency: "정규장 밖 비상", pre: "장 시작 전", after: "장 마감 뒤" };
export const WS_LABEL: Record<string, string> = { connected: "연결됨", down: "끊김", none: "확인 못 함" };
export const PLAN_SOURCE_LABEL: Record<string, string> = { manual: "직접 입력", adopt: "보유 인수" };
export const VALUE_LABEL: Record<string, string> = {
  symbol: "종목", mode: "종류", budget_usd: "예산", buy_watch: "매수 감시가", buy_order: "매수 주문가", qty: "수량",
  tp1_watch: "1차 익절 감시가", tp1_order: "1차 익절 주문가", announce_at: "발표 시각", entry_close_at: "매수 마감",
  entry_window_end: "진입 창 끝", ladder_pcts: "손절 폭 목록", adopt: "인수 값",
};
export const LEG_STATUS_LABEL: Record<string, string> = {
  WATCHING: "감시 중",
  TRIGGERED: "조건 닿음",
  FILLED: "체결",
  CANCELED: "취소",
  EXPIRED: "만료",
};

export function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function usd(v: unknown, digits = 2): string {
  const n = num(v);
  return n === null ? "—" : `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function shares(v: unknown): string {
  const n = num(v);
  return n === null ? "—" : `${n.toLocaleString("ko-KR")}주`;
}

export function kst(iso: string | null | undefined): string {
  return iso ? fmtKstDateTime(iso) : "—";
}

export function heartbeatText(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "기록 없음";
  if (sec < 90) return `${Math.round(sec)}초 전`;
  if (sec < 5400) return `${Math.round(sec / 60)}분 전`;
  return `${Math.round(sec / 3600)}시간 전`;
}

/** 실행기가 멈춘 것으로 보는 기준 (초) · 화면 표시용 · 서버 기준과 같지 않을 수 있다 */
export const HEARTBEAT_STALE_SEC = 120;

/** 낙관적 잠금: 화면과 실행기가 같은 계획을 동시에 고치면 서버가 409 stale 을 준다 (자동 재시도 없음) */
export const STALE_MSG = "다른 곳에서 값이 바뀌어 새로 읽었습니다 · 확인 뒤 다시 눌러 주십시오";
export function isStale(e: unknown): boolean {
  return e instanceof PlanApiError && e.status === 409 && e.reason === "stale";
}

/** 서버 오류 반응이 확인 코드 거부일 때 쓰는 문구 보강 */
export function errText(e: unknown): string {
  if (e instanceof PlanApiError) return e.message;
  return e instanceof Error ? e.message : "알 수 없는 오류";
}
