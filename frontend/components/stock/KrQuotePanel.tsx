"use client";

// 1128-01 · 국내 종목 가격 · 증권사 의견 칸 (관리자 전용). 순서는 바이오 QuotePanel 과 같다:
// ① 현재가 ② 그림(일봉 1년 · 주봉 5년 + 거래량 막대) ③ 숫자 칸 ④ 증권사 의견 ⑤ 출처 · 안내
// 표시 전용 — 점수 · 순위 · 경보에 쓰지 않는다. 의견은 받은 값 그대로 (해석 · 목표가까지 몇 % 같은 계산 없음). 명령문 없음.
// 자료 제공처(네이버) 약관 때문에 로그인 화면에서만 보인다 (사용자 결정 11/28 ㉢).
import { MaChart } from "@/components/account/MaChart";
import { KrQuoteError, useKrQuote } from "@/components/stock/useKrQuote";
import { BIOTECH_BASIS_LINE } from "@/lib/biotech-quote";
import { NO_DATA, krLiveLine, krw, md, pct1, rangeText, volumeKo, wonKo, type KrQuote } from "@/lib/stock-display";

function Cell({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-md border border-border bg-background p-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
      {note && <div className="text-[11px] text-muted-foreground tabular-nums">{note}</div>}
    </div>
  );
}

function OpinionBox({ v }: { v: KrQuote }) {
  const o = v.opinion;
  if (v.opinion_status === "ok" && o) {
    return (
      <div className="space-y-1 rounded-md border border-border p-2" data-testid="kr-opinion">
        <div className="font-semibold">증권사 의견</div>
        <div className="tabular-nums">평균 의견 값 {o.mean_rating ?? NO_DATA} · 평균 목표가 {krw(o.mean_target)}</div>
        <div className="text-[11px] text-muted-foreground tabular-nums">
          {o.created ? `${md(o.created)} 기준` : "기준일 없음"} · {o.source} · {o.grade_note}
        </div>
        <div className="text-[11px] font-semibold">{o.head}</div>
      </div>
    );
  }
  return (
    <div className="space-y-1 rounded-md border border-border p-2" data-testid="kr-opinion">
      <div className="font-semibold">증권사 의견</div>
      <div className="text-muted-foreground">{v.opinion_note ?? "증권사 의견 없음"}</div>
    </div>
  );
}

function Body({ v }: { v: KrQuote }) {
  const b = v.basics;
  return (
    <div className="space-y-3 text-xs">
      <div className="text-sm font-semibold tabular-nums" data-testid="kr-live">{krLiveLine(v)}</div>
      <MaChart chart={v.chart} initialView="daily" basisLine={BIOTECH_BASIS_LINE} showVolume />
      {b ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="kr-cells">
          <Cell label="종가 (저장)" value={krw(b.price_close)} note={v.asof ? `${md(v.asof)} 기준` : undefined} />
          <Cell label="거래량" value={volumeKo(b.volume)} />
          <Cell label="평균 거래량" value={volumeKo(b.avg_volume)} note={b.avg_volume_note ?? undefined} />
          <Cell label="시가총액" value={wonKo(b.market_cap)} />
          <Cell label="52주 범위 (낮음 ~ 높음)" value={rangeText(b.low_52w, b.high_52w)} />
          <Cell label="외국인 비율" value={pct1(b.foreign_rate)} note="상장 주식 중 외국인이 가진 몫" />
        </div>
      ) : (
        <p className="text-muted-foreground">기본 시세 자료를 받지 못했습니다.</p>
      )}
      <OpinionBox v={v} />
      {v.notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-[11px] text-muted-foreground">
          {v.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-muted-foreground tabular-nums">
        출처: {b?.source ?? "네이버 증권"} · 현재가는 네이버 실시간(60초 보관) · {v.asof ? `저장 일봉 ${md(v.asof)}까지` : "저장 일봉 없음"} · 의견이 나온 날은 위 기준일
      </p>
      <p className="text-[11px] text-muted-foreground">{v.use_note}</p>
    </div>
  );
}

export function KrQuotePanel({ code }: { code: string }) {
  const q = useKrQuote(code, true);
  const err = q.error instanceof KrQuoteError ? q.error : null;
  return (
    <div className="rounded-lg border border-primary/30 bg-white" data-testid={`kr-quote-panel-${code}`}>
      <div className="p-3">
        {q.isLoading && <p className="text-xs text-muted-foreground">불러오는 중입니다.</p>}
        {err && (
          <p className="text-xs text-warn" data-testid="kr-quote-error">
            {err.status === 401
              ? "다시 로그인하면 보입니다"
              : err.status === 404
                ? "이 사이트 종목 목록에 없는 코드여서 가격 자료를 모으지 않습니다"
                : "가격 자료를 불러오지 못했습니다. 잠시 뒤 다시 열어 주십시오"}
          </p>
        )}
        {q.data && <Body v={q.data} />}
      </div>
    </div>
  );
}
