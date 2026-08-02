# 01 · UI Spec · Serenity Integration

> **의존**: [README.md](./README.md) 진입점 참조
>
> **범위**: Frontend (Next.js 14 · Tailwind · shadcn/ui) UI 변경 명세 · 코드 스켈레톤

## 1. Nav 요구사항 (사용자 명시)

### 1.1 상단 Nav (NAV_L1)
- 기존: `[Journal, Watchlist, Sniper, Positions, Dashboard, Logs]`
- **변경 후**: `[Journal, Watchlist, Sniper, Positions, Influencer, Dashboard, Logs]`
- **삽입 위치**: **Dashboard 좌측** (Influencer → Dashboard)

### 1.2 하단 Nav (NAV_L2)
- 기존: `[Rulebook, Powderkeg, Activist Radar, VIP, Sector Leaders]`
- **변경 후 (조건부)**:
  - 현재 pathname 이 `/influencer` 로 시작 시 → `[Serenity]` **단독 표시** · 기존 5개 hidden
  - 그 외 pathname → 기존 5개 유지

### 1.3 활성 표시
- 현재 pathname 매칭 시 텍스트 강조 (기존 hover 스타일과 구분)
- 예: `text-foreground font-medium` vs `text-muted-foreground`

## 2. 라우트 구조 (신규)

```
frontend/app/
├─ influencer/                    ← 신규 최상위 라우트
│  ├─ layout.tsx                  ← 좌측 nav 조건부 렌더 담당 (or layout.tsx에서 처리)
│  ├─ page.tsx                    ← /influencer 진입 시 → /influencer/serenity 리다이렉트
│  └─ serenity/
│     ├─ page.tsx                 ← Signal Feed + Ticker Grid 랜딩
│     ├─ methodology/
│     │  └─ page.tsx              ← 15원칙 프레임 열람
│     ├─ backtest/
│     │  └─ page.tsx              ← 백테스트 리포트 차트
│     └─ [ticker]/
│        └─ page.tsx              ← 개별 티커 상세 (checklist + backtest chart)
```

## 3. Nav 코드 스켈레톤 (`frontend/app/layout.tsx` 수정)

### 3.1 사전 확인
현재 layout.tsx 는 **Server Component** (function 이 async 없음). Nav 조건부 렌더링을 위해 `usePathname` 필요 → **client component 분리** 또는 **layout.tsx client 변환**.

**권장**: Nav 부분만 별도 client 컴포넌트로 분리 (`components/layout/AppNav.tsx`) · layout.tsx 는 server 유지.

### 3.2 `components/layout/AppNav.tsx` (신규)

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// L1 · 상단 대문 nav (Influencer 삽입 · Dashboard 좌측)
const NAV_L1 = [
  { href: "/journal", label: "📓 Journal" },
  { href: "/watchlist", label: "🌙 Watchlist" },
  { href: "/sniper", label: "🚀 Sniper" },
  { href: "/positions", label: "💼 Positions" },
  { href: "/influencer", label: "🎯 Influencer" },   // ← 신규
  { href: "/dashboard", label: "📊 Dashboard" },
  { href: "/logs", label: "📜 Logs" },
];

// L2 · 하단 심층 nav (기본)
const NAV_L2_DEFAULT = [
  { href: "/rulebook", label: "📏 Rulebook" },
  { href: "/powderkeg", label: "🧨 Powderkeg" },
  { href: "/activist-radar", label: "🐺 Activist" },
  { href: "/vip", label: "🕵️ VIP" },
  { href: "/sector-leaders", label: "🇰🇷 Sector" },
];

// L2 · Influencer 활성 시 (기존 5개 hidden · Serenity 만 표시)
const NAV_L2_INFLUENCER = [
  { href: "/influencer/serenity", label: "🧠 Serenity" },
];

export function AppNav() {
  const pathname = usePathname();
  const isInfluencer = pathname.startsWith("/influencer");
  const l2 = isInfluencer ? NAV_L2_INFLUENCER : NAV_L2_DEFAULT;

  return (
    <>
      <nav className="flex flex-wrap gap-4 text-sm">
        {NAV_L1.map((item) => {
          const active = pathname === item.href
            || (item.href !== "/" && pathname.startsWith(item.href + "/"))
            || (item.href === "/influencer" && pathname.startsWith("/influencer"));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={active
                ? "text-foreground font-medium"
                : "text-muted-foreground hover:text-foreground"}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <nav className="flex flex-wrap gap-4 border-t border-border/50 pt-2 text-xs">
        {l2.map((item) => {
          const active = pathname === item.href
            || pathname.startsWith(item.href + "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={active
                ? "text-foreground font-medium"
                : "text-muted-foreground/70 hover:text-foreground"}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
```

### 3.3 `frontend/app/layout.tsx` 수정 diff

```diff
 import type { Metadata } from "next";
 import Link from "next/link";
 import "./globals.css";
 import { Providers } from "./providers";
+import { AppNav } from "@/components/layout/AppNav";

 export const metadata: Metadata = { ... };

-const NAV_L1 = [ ... ];
-const NAV_L2 = [ ... ];
-
 export default function RootLayout({ children }: ...) {
   return (
     <html lang="ko" suppressHydrationWarning>
       <body className="min-h-screen bg-background font-sans antialiased">
         <Providers>
           <header className="sticky top-0 z-50 border-b border-border bg-card/95 backdrop-blur">
             <div className="container mx-auto flex flex-col gap-2 px-4 py-3">
               <div className="flex items-center justify-between">
                 <Link href="/" className="text-lg font-bold">🌙 Toss Tradebot</Link>
                 <div className="flex items-center gap-3 text-xs text-muted-foreground">
                   <Link href="/lab" ...>🧪 Lab</Link>
                   <Link href="/admin/settings" ...>⚙️</Link>
                 </div>
               </div>
-              <nav className="flex flex-wrap gap-4 text-sm">
-                {NAV_L1.map(...)}
-              </nav>
-              <nav className="flex flex-wrap gap-4 border-t border-border/50 pt-2 text-xs">
-                {NAV_L2.map(...)}
-              </nav>
+              <AppNav />
             </div>
           </header>
           <main className="container mx-auto px-4 py-6">{children}</main>
           <footer>...</footer>
         </Providers>
       </body>
     </html>
   );
 }
```

## 4. `/influencer` 랜딩 페이지

### 4.1 `frontend/app/influencer/page.tsx`

```tsx
import { redirect } from "next/navigation";

export default function InfluencerRoot() {
  // Influencer 하위 기본 = Serenity
  redirect("/influencer/serenity");
}
```

## 5. `/influencer/serenity` — 랜딩 (Signal Feed + Ticker Grid)

### 5.1 페이지 구조

```
┌───────────────────────────────────────────────────────────┐
│ 🧠 Serenity Stock Tracker                                 │
│ AI/반도체 supply-chain 특화 · @aleabitoreddit · 900K      │
├───────────────────────────────────────────────────────────┤
│ [Signal Feed] [Ticker Grid] [Backtest] [Methodology]     │
├───────────────────────────────────────────────────────────┤
│ Signal Feed (최근 14일 · sentiment 필터)                  │
│                                                            │
│ 2026-08-01 · $LITE · 🟢 Bullish · Contract Evidence      │
│  Lumentum CEO "InP laser supply gap more severe..."      │
│  → [상세]                                                  │
│                                                            │
│ 2026-07-31 · $AXTI · 🟢 Bullish · Earnings Validation    │
│  Record InP revenue $30.7M · capacity 2x in 2026·2027    │
│  → [상세]                                                  │
│                                                            │
│ ...                                                        │
├───────────────────────────────────────────────────────────┤
│ Ticker Grid (financing tier 별)                           │
│                                                            │
│ [S tier · 매수 지속]                                       │
│  ┌─────────────┐                                          │
│  │ 🧠 $NBIS    │ Base $200 · Bull $400                    │
│  │ Neocloud    │ 713 mentions · S tier                    │
│  └─────────────┘                                          │
│                                                            │
│ [A tier · Legacy]                                          │
│  ┌─────────────┐ ┌─────────────┐                          │
│  │ $AXTI       │ │ $CIFR       │                          │
│  │ InP flagship│ │ Colo · A    │                          │
│  │ NO buy, NO short│ Safest    │                          │
│  └─────────────┘ └─────────────┘                          │
│                                                            │
│ [B tier · Watchlist]                                       │
│  $SIVE · $LITE · $TSEM · $IQE                             │
│                                                            │
│ [Avoid]                                                    │
│  $IREN (ATM 51% overhang) · $CRWV (heavy debt · F-tier)   │
└───────────────────────────────────────────────────────────┘
```

### 5.2 카드 컴포넌트 (`components/serenity/TickerCard.tsx`)

```tsx
type TickerCardProps = {
  ticker: string;
  financingTier: "S" | "A" | "B" | "C" | "D" | "F";
  serenityTier: "S" | "A" | "B" | "C" | "D" | "F" | null;
  mentionCount: number;
  lastSignalDate: string;
  domainTags: string[];
  autoAvoid: boolean;
  totalScore: number;
  latestSummary: string;
};
```

- 카드 우상단: 총 스코어 뱃지 (S/A/B/C tier 색상)
- 좌하단: 도메인 태그 (optical_cpo, inp_substrates, memory_hbm, neocloud, ai_power, robotics)
- 우하단: `[15원칙]` `[Backtest]` `[상세]` 링크

## 6. `/influencer/serenity/[ticker]` — 상세 페이지

### 6.1 구조

```
┌───────────────────────────────────────────────────────────┐
│ $NBIS · Nebius Group                                       │
│ 🧠 Serenity S tier · 매수 지속 · Base $200 / Bull $400    │
├───────────────────────────────────────────────────────────┤
│ ▎최신 Signal (2026-07-14)                                  │
│  $1B+ Reflection AI contract for GB300 through 2029       │
│  [원문 링크 x.com/...]                                     │
├───────────────────────────────────────────────────────────┤
│ ▎15원칙 체크리스트 (Serenity Style Fit)                    │
│  ✅ 1. Bottleneck (GPU neocloud · 5 companies in 1)       │
│  ✅ 2. BOM (다운스트림 hyperscaler 다양)                    │
│  ✅ 3. Contract ARR ($46B+ 백로그)                         │
│  ✅ 4. Mag7 (META · MSFT · NVDA)                          │
│  ✅ 5. GAAP Margin (71.2% best-in-class)                  │
│  ⬜ 6. Pre-ramp (이미 volume · A tier)                     │
│  ✅ 7. Dilution (NVDA + convertibles · NOT ATM)           │
│  ✅ 8. Financing Tier S                                    │
│  ⬜ 9. Short Squeeze (일반적 상황 아님)                    │
│  ✅ 10. Tariff-Buy (2025-10 tariff 진입)                  │
│  ✅ 11. Institutional lag (Leopold 5.6% · Macron €8B)     │
│  ⬜ 12. IV mispricing (options 별도)                       │
│  ✅ 13. Conviction Tier S (Serenity 최대 포지션)           │
│  Serenity Style Fit: 9/14                                  │
├───────────────────────────────────────────────────────────┤
│ ▎Financing Quality Tier: S                                 │
│  NVDA $2B strategic + ~2% convertibles                     │
│  vs. CIFR/WULF (colo · A) > IREN (ATM · Avoid) > CRWV (F)│
├───────────────────────────────────────────────────────────┤
│ ▎Anti-Pattern Flags: 없음 ✅                               │
├───────────────────────────────────────────────────────────┤
│ ▎5-60일 Buffer (원칙 11)                                   │
│  최신 signal 후 경과: 19 거래일                            │
│  진입 timing bucket: [mid]                                 │
├───────────────────────────────────────────────────────────┤
│ ▎Backtest (실 주가 vs. signal 시점)                        │
│  [Chart · 5·10·30·60·180일 수익률]                        │
│  평균 return_30d: +12.3% (n=15)                            │
├───────────────────────────────────────────────────────────┤
│ ▎Recent Signals (최근 10건)                                │
│  2026-07-20 · Bullish · NVDA 9.3% ownership 공개          │
│  2026-07-14 · Bullish · Reflection AI $1B contract        │
│  ...                                                       │
├───────────────────────────────────────────────────────────┤
│ ▎References                                                │
│  · theses.md §NBIS (Nebius Group) — full-stack GPU neocloud│
│  · methodology.md §8 · Financing spectrum                  │
│  · track-record.md 2025 Retrospective                     │
└───────────────────────────────────────────────────────────┘
```

## 7. `/influencer/serenity/methodology` — 15원칙 프레임 열람

- markdown 렌더 (기존 rulebook 페이지 패턴 재사용)
- source: `~/GON-Dev/serenity-tracker/serenity-aleabitoreddit/references/methodology.md`
- 원칙별 앵커 링크 (예: `#원칙-8-financing-spectrum`)

## 8. `/influencer/serenity/backtest` — 백테스트 리포트

- Signal type 별 정확도 (new_bottleneck · reaffirmation · watchlist · victory_lap)
- 5/10/30/60/180일 후 평균 수익률
- Sentiment 별 (bullish · bearish · neutral) 분포
- Financing tier 별 성과 (S~F)
- Domain tag 별 성과 (optical_cpo · memory_hbm · neocloud · etc)

## 9. 접근 제어

- Influencer 페이지는 admin 페이지처럼 `NextAuth.js` 인증 필요 여부 결정
- 기존 Toss Tradebot 로그인 정책 정합 · 사용자 확인 필요

## 10. 반응형·다크모드

- 기존 shadcn/ui 카드·차트 컴포넌트 재사용
- 다크모드 지원 (기존 `bg-background`·`text-foreground` 토큰 사용)
- 모바일 nav 겹침 처리 (`flex-wrap` 유지)

## 11. i18n (선택 · 나중)

- Serenity 원문 영어 · UI 한국어
- 자연어 질의 (백엔드 z.ai LLM)는 한국어 입력 → 영어 처리 → 한국어 응답 (chain)

## 12. 미해결 결정 사항 (사용자 확인 필요)

- [ ] `/influencer` 접근 인증 여부 (기존 admin 게이트 재활용 or public)
- [ ] Ticker Grid 정렬 기본값 (총 스코어 desc · financing tier · mention count · last signal)
- [ ] Signal Feed 초기 필터 (전체 · bullish only · 도메인 필터)
- [ ] Backtest 차트 라이브러리 (recharts · chart.js · shadcn/ui chart)
- [ ] Methodology 페이지가 정적 렌더 vs. serenity-tracker 원문 실시간 fetch
