// 1022-09 · 알림 설정 화면 표시 함수 (순수 함수 · notifications-display.check.ts 로 확인)
import type { NotificationLevel, NotificationMode, NotificationSettingRow, NotificationSettingPatch } from "./api";

export interface RowGroup {
  group: string;
  rows: NotificationSettingRow[];
}

/** 서버 순서를 지키며 묶음별로 나눈다. */
export function groupRows(rows: NotificationSettingRow[]): RowGroup[] {
  const out: RowGroup[] = [];
  for (const row of rows) {
    const g = out.find((x) => x.group === row.group);
    if (g) g.rows.push(row);
    else out.push({ group: row.group, rows: [row] });
  }
  return out;
}

const LEVEL_TEXT: Record<NotificationLevel, string> = { info: "모두", warning: "경고 이상만", critical: "긴급만" };

export function modeText(mode: NotificationMode): string {
  return mode === "digest" ? "하루 요약 (18:00)" : "바로 받기";
}

export function levelText(level: NotificationLevel): string {
  return LEVEL_TEXT[level];
}

export function intervalText(minutes: number): string {
  if (!minutes) return "제한 없음";
  if (minutes % 1440 === 0) return `${minutes / 1440}일`;
  if (minutes % 60 === 0) return `${minutes / 60}시간`;
  return `${minutes}분`;
}

/** 권고값을 한국어 한 줄로 (내부 코드값 노출 없음). */
export function recommendedText(rec: NotificationSettingPatch): string {
  const parts: string[] = [];
  if (rec.enabled === false) parts.push("끄기");
  if (rec.mode) parts.push(modeText(rec.mode));
  if (rec.min_level) parts.push(levelText(rec.min_level));
  if (rec.resend_minutes) parts.push(`같은 알림은 ${intervalText(rec.resend_minutes)}에 한 번`);
  return parts.length ? parts.join(" · ") : "지금 그대로";
}

/** UTC ISO 문자열 → 한국 시각 "MM/DD HH:mm". */
export function whenText(iso: string | null): string {
  if (!iso) return "없음";
  const d = new Date(iso);
  const kst = new Date(d.getTime() + 9 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(kst.getUTCMonth() + 1)}/${p(kst.getUTCDate())} ${p(kst.getUTCHours())}:${p(kst.getUTCMinutes())}`;
}

/** 서버가 허락한 칸인지 (Kill Switch·실주문은 없음 · 시스템 경고는 받는 방식만). */
export function canEdit(row: NotificationSettingRow, field: NotificationSettingRow["editable"][number]): boolean {
  return row.editable.includes(field);
}

/** 지금 설정이 권고값과 같은지. */
export function isRecommended(row: NotificationSettingRow): boolean {
  const target = { enabled: true, ...row.recommended };
  return (Object.keys(target) as (keyof NotificationSettingPatch)[]).every((k) => row[k] === target[k]);
}
