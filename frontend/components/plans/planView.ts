// 1116-01 계획 화면 쉽게 만들기 · 화면 공용 규칙 (서버 값을 그대로 읽어 글로 바꾼다. 새로 계산해 서버로 보내는 값은 없다.)
import { HEARTBEAT_STALE_SEC, heartbeatText, num } from "@/lib/plans";
import type { ExecutorStatus, Plan, PlanParams } from "@/lib/plans";

/** 화면에서 보이는 글자만 바꾼 이름 (F) · 서버 기록 코드 · data-testid · aria-label 구조는 그대로 */
export const ADOPT_NAME = "이미 산 종목 맡기기";
export const KILL_NAME = "비상 정지";
/** 정규장 밖 비상 손절(−15% 걸린 주문)은 「비상 정지」와 다른 것이다 */
export const TAG_NAME: Record<string, string> = { regular: "정규장", emergency: "정규장 밖 비상 손절", pre: "장 시작 전", after: "장 마감 뒤" };

export const KILL_TEXT = (k: { active: boolean; sell_allowed: boolean }): string =>
  k.active ? (k.sell_allowed ? "작동 중 · 새 주문 멈춤" : "작동 중 · 매도도 멈춤") : "꺼짐";

/** 손절 줄 · 계획에 손절 폭(ladder_pcts)이 있으면 그 값, 없을 때만 기본 규칙. 기준은 평균 매수가이고 체결 전 달러 값은 계산하지 않는다. */
export function ladderLine(params: PlanParams | undefined): { text: string; isDefault: boolean } {
  const raw = params?.ladder_pcts;
  const nums = Array.isArray(raw) ? raw.map((x) => num(x)).filter((x): x is number => x !== null && x > 0) : [];
  if (nums.length > 0) {
    const t = nums.map((x) => `−${(x * 100).toFixed(1).replace(/\.0$/, "")}%`).join(" · ");
    return { text: `손절: 평균 매수가 기준 ${t}`, isDefault: false };
  }
  return { text: "손절: 평균 매수가 기준 −3 · −5 · −7% (기본 규칙)", isDefault: true };
}

export const PRICE_NOTE = "값은 규칙으로 계산한 것이며 추정 · 보장 아님. 손절 값은 체결된 평균 매수가가 정해진 뒤에 정해집니다.";

/** C · 승인 전에 채워져야 하는 값 · 이미 산 종목 맡기기 계획은 수량 · 평균 단가 */
export interface Missing { key: string; label: string }
export function missingValues(p: Plan): Missing[] {
  const out: Missing[] = [];
  if (p.source === "adopt") {
    const a = p.params.adopt;
    const q = num(a?.qty ?? p.params.qty ?? p.qty);
    if (q === null || q <= 0) out.push({ key: "qty", label: "수량" });
    const avg = num(a?.avg_price ?? p.avg_price);
    if (avg === null || avg <= 0) out.push({ key: "avg_price", label: "평균 단가" });
    return out;
  }
  const q = num(p.qty ?? p.params.qty);
  if (q === null || q <= 0) out.push({ key: "qty", label: "수량 0" });
  const w = num(p.params.buy_watch);
  if (w === null || w <= 0) out.push({ key: "buy_watch", label: "매수 감시가" });
  const o = num(p.params.buy_order);
  if (o === null || o <= 0) out.push({ key: "buy_order", label: "매수 주문가" });
  return out;
}

/** A · 「주문 나감 / 안 나감」 한 줄 */
export interface OrderLine { state: "go" | "stop" | "unknown"; head: string; reasons: string[]; note: string | null }
export function orderLine(st: ExecutorStatus | undefined, failed: boolean): OrderLine {
  if (failed || !st) return { state: "unknown", head: "확인 못 함", reasons: ["실행기 상태를 읽지 못했습니다"], note: null };
  const reasons: string[] = [];
  if (!st.switches.live) reasons.push("실거래 주문이 꺼져 있습니다");
  if (st.kill_switch.active) reasons.push(`${KILL_NAME}가 작동 중입니다 · ${st.kill_switch.sell_allowed ? "새 주문 멈춤" : "매도도 멈춤"}`);
  const stale = st.heartbeat_age_sec === null || st.heartbeat_age_sec > HEARTBEAT_STALE_SEC;
  if (stale) reasons.push(`실행기 응답이 끊겼습니다 (마지막 응답 ${heartbeatText(st.heartbeat_age_sec)})`);
  const toss = st.toss?.status;
  if (toss === "error") reasons.push("토스 연결 오류입니다");
  const note = toss === "ok" || toss === "error" ? null : "토스 연결 상태는 확인 못 함";
  if (reasons.length > 0) return { state: "stop", head: "주문 안 나감", reasons, note };
  return { state: "go", head: "주문 나감", reasons: ["실거래 켜짐 · 비상 정지 꺼짐 · 실행기 응답 정상"], note };
}
