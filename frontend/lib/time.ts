/**
 * KST(Asia/Seoul) 시각 표시 통일 헬퍼.
 *
 * 백엔드는 UTC datetime 을 ISO 문자열로 반환하지만,
 * SQLite naive datetime 은 timezone 정보가 소실되어 `2026-07-11T05:12:34.567` 형태로 옴.
 * 이런 문자열을 브라우저 로컬 타임으로 오인하면 KST vs UTC 9시간 오차 발생.
 *
 * 규칙:
 *  - Z / +HH:MM / -HH:MM 접미가 없으면 → UTC 로 간주 (서버가 UTC 저장 원칙)
 *  - 모든 표시는 Asia/Seoul 타임존 강제
 */

const KST = "Asia/Seoul";

/** ISO 문자열을 Date 로 파싱 · 타임존 접미 없으면 UTC 로 간주. */
export function parseServerIso(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasTz = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  const raw = hasTz ? iso : iso + "Z";
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "14:32:05" (KST · HH:mm:ss) */
export function fmtKstTime(iso: string | null | undefined): string {
  const d = parseServerIso(iso);
  if (!d) return "—";
  return d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: KST,
    hour12: false,
  });
}

/** "14:32" (KST · HH:mm) */
export function fmtKstHm(iso: string | null | undefined): string {
  const d = parseServerIso(iso);
  if (!d) return "—";
  return d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: KST,
    hour12: false,
  });
}

/** "07-11" (KST · MM-dd) */
export function fmtKstDate(iso: string | null | undefined): string {
  const d = parseServerIso(iso);
  if (!d) return "—";
  return d.toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    timeZone: KST,
  });
}

/** "07-11 14:32" (KST · MM-dd HH:mm) */
export function fmtKstDateTime(iso: string | null | undefined): string {
  const d = parseServerIso(iso);
  if (!d) return "—";
  const date = d.toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    timeZone: KST,
  });
  const time = d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: KST,
    hour12: false,
  });
  return `${date} ${time}`;
}

/** "2026-07-11 14:32:05 KST" (풀 포맷 · 툴팁·상세용) */
export function fmtKstFull(iso: string | null | undefined): string {
  const d = parseServerIso(iso);
  if (!d) return "—";
  const s = d.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: KST,
    hour12: false,
  });
  return `${s} KST`;
}
