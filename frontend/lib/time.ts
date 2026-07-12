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

/** 한국식 원화 금액 · 조/억/만 단위 자동 (시총·거래대금 등) */
export function fmtKrw(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}조`;
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(0)}억`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(0)}만`;
  return `${sign}${Math.round(abs).toLocaleString("ko-KR")}`;
}

/** KRX 개별 종목 가격 · 정수 · 쉼표 · "원" (예: 72,700원) */
export function fmtKrwPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${Math.round(v).toLocaleString("ko-KR")}원`;
}

/** US 개별 종목 가격 · 소수 2자리 · "$" (예: $50.20) */
export function fmtUsdPrice(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toFixed(2)}`;
}

/** 티커 형식으로 자동 판정 (KRX 6자리 숫자 → 원 · 그 외 → USD) */
export function fmtPriceForTicker(ticker: string, v: number | null | undefined): string {
  const isKrx = /^\d{6}$/.test(ticker);
  return isKrx ? fmtKrwPrice(v) : fmtUsdPrice(v);
}

/** 발행주식수 · 만/억 단위 (예: 2,697만주) */
export function fmtShares(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(abs / 1e8).toFixed(2)}억주`;
  if (abs >= 1e4) return `${(abs / 1e4).toFixed(0)}만주`;
  return `${abs.toLocaleString("ko-KR")}주`;
}

/** % 표시 · 부호 명시 · 소수 2자리 (예: +3.25%) */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
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
