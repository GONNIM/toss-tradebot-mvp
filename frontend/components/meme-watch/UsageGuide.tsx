"use client";

import { useState } from "react";

export function UsageGuide() {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-semibold text-cyan-700 dark:text-cyan-300 hover:bg-cyan-500/10"
      >
        <span>📖 밈주 워치 사용 가이드 {open ? "▼" : "▶"}</span>
        <span className="text-xs text-muted-foreground">
          Score / 라벨 / 활성 시그널 의미
        </span>
      </button>

      {open && (
        <div className="px-4 py-3 space-y-3 border-t border-cyan-500/20 text-sm">
          {/* Score */}
          <div>
            <div className="font-semibold text-foreground mb-1">🎯 Score (0 ~ 1.5)</div>
            <p className="text-muted-foreground text-xs">
              5요소 시그널 가중합. 이론 최대 1.5 (한 시그널이 최대치일 때 다른 시그널도
              강한 이례적 경우). 실전 임계는 <strong>0.5 이상 워치</strong>.
            </p>
          </div>

          {/* 라벨 */}
          <div>
            <div className="font-semibold text-foreground mb-1">🏷️ 라벨 임계값</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 text-xs">
              <div>🔥🔥 <strong>BLAZING</strong> (≥1.00) — 4~5요소 동시 발현, 즉시 워치</div>
              <div>🔥 <strong>HOT</strong> (≥0.75) — 3~4요소 강력 발현</div>
              <div>⚠️ <strong>WATCH</strong> (≥0.50) — 2~3요소 발현, 모니터</div>
              <div>👀 <strong>OBSERVE</strong> (≥0.25) — 1~2요소 약한 신호</div>
              <div>💤 <strong>SLEEP</strong> (&lt;0.25) — 시그널 없음</div>
            </div>
          </div>

          {/* 활성 시그널 */}
          <div>
            <div className="font-semibold text-foreground mb-1">
              📊 활성 시그널 (N/5)
            </div>
            <p className="text-muted-foreground text-xs mb-1.5">
              5요소 중 <strong>normalized ≥ 0.5</strong> 인 시그널 개수. 많을수록 신뢰도 ↑.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-0.5 text-xs">
              <div>① <strong>공매도</strong> — 유동주식 대비 short 비율 (Phase 4)</div>
              <div>② <strong>소셜</strong> — Reddit(apewisdom) + Google Trends</div>
              <div>③ <strong>거래량</strong> — 20D 평균 대비 배수</div>
              <div>④ <strong>Momentum</strong> — RSI ≥ 70 + 1D ≥ +10%</div>
              <div>⑤ <strong>Catalyst</strong> — DART 공시 + 1D gap up</div>
            </div>
          </div>

          {/* 신뢰도 */}
          <div>
            <div className="font-semibold text-foreground mb-1">✔ 신뢰도</div>
            <div className="text-xs text-muted-foreground">
              가용 시그널 개수: <strong>strong</strong> (≥4) / <strong>medium</strong> (3) /
              <strong> weak</strong> (≤2). ⚠️ 배지는 시그널 부족 경고.
            </div>
          </div>

          {/* 최강 시그널 */}
          <div>
            <div className="font-semibold text-foreground mb-1">💪 최강 시그널</div>
            <div className="text-xs text-muted-foreground">
              5요소 중 가장 큰 contribution 을 낸 시그널. 이 종목이 <strong>왜 잡혔는지</strong>{" "}
              한눈에 확인 가능.
            </div>
          </div>

          {/* 시장 필터 */}
          <div>
            <div className="font-semibold text-foreground mb-1">🌐 시장 필터</div>
            <div className="text-xs text-muted-foreground">
              🇺🇸 미국 = Reddit(WSB 계열) + Google Trends 데이터 활용 · 🇰🇷 한국 = DART 공시 +
              거래량 위주 (한국은 apewisdom 미커버).
            </div>
          </div>

          {/* Meme-watch vs Sector Leaders */}
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-2">
            <div className="font-semibold text-amber-700 dark:text-amber-300 mb-1 text-xs">
              🔍 밈주 워치 vs 섹터별 주도주 Top 10
            </div>
            <div className="text-xs text-amber-700 dark:text-amber-300">
              밈주 워치는 <strong>사후 반응 시그널</strong>(폭등 감지)이라 forecast(예측 수익가,
              진입 시점)는 <strong>제공하지 않습니다</strong>. 예측이 필요하면 섹터별 주도주 페이지의
              Top 10 을 참고하세요. 여기 표시된 현재가는 마지막 일봉 종가입니다.
            </div>
          </div>

          {/* disclaimer */}
          <div className="text-xs text-rose-600 dark:text-rose-400 font-semibold">
            ⚠️ 밈주는 단시간 -50% 이상 손실 가능 — 투자 권유 아님, 카지노 머니로만 운영 권장.
          </div>
        </div>
      )}
    </div>
  );
}
