# Toss Tradebot FE 스타일 규칙 (WP70-1 · 2026-09-18)

> Biotech Radar 화면이 기존 `/activist-radar` · `/powderkeg` 등과 구분되지 않게 정합하기 위한 규칙 요약. 원본 조사: `frontend/app/globals.css` · `tailwind.config.ts` · `frontend/app/{activist-radar,powderkeg}/page.tsx`.

## 1. 전역 · 컨테이너

| 항목 | 규칙 |
|---|---|
| CSS | **Tailwind + shadcn/ui** · CSS 변수 (HSL) · `dark:` prefix class 토글 |
| 색 팔레트 | slate (중성) · **sky** (정보 · 활성 탭/링크) · amber (경고) · rose/orange (위험) · emerald (성공) |
| 컨테이너 | `container mx-auto px-4 py-6` (Tailwind default max-w) · 섹션 간격 `space-y-4` |
| 배경 | `bg-background` (root) · dark 자동 |
| **indigo 미사용** | 기존 페이지는 indigo 대신 **sky** 계열 · gray 대신 **slate** |

## 2. 페이지 헤더

| 요소 | 클래스 |
|---|---|
| 제목 (h1) | `text-2xl font-bold` 또는 `text-3xl` · **이모지 좌측 필수** (예: `🐺 Activist Radar`) |
| 제목 배지 | `rounded bg-{color}-500/20 px-2 py-0.5 text-[10px] font-semibold text-{color}-400` |
| 서브 텍스트 | `text-sm text-muted-foreground` |
| 헤더 래퍼 | `flex items-center gap-2` (제목+배지) |

## 3. 배너 (알림/경고)

| 타입 | 라이트 | 다크 |
|---|---|---|
| **정보/성공** | `rounded border-2 border-sky-300 bg-sky-50` | `dark:border-sky-800 dark:bg-sky-950/40` |
| **경고/주의** | `rounded border-l-4 border-amber-500 bg-amber-50` | `dark:border-amber-600 dark:bg-amber-950` |
| **오류/위험** | `rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800` | `dark:border-red-800 dark:bg-red-950 dark:text-red-200` |

## 4. 탭 (페이지 내부)

- 컨테이너: `flex flex-wrap gap-2 border-b border-border pb-2`
- 활성: `px-3 py-1.5 rounded-t text-sm border-b-2 border-sky-600 font-bold`
- 비활성: `px-3 py-1.5 rounded-t text-sm bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300`

## 5. 표 (Table)

- 래퍼: `overflow-x-auto rounded border border-border` (모바일 가로 스크롤)
- 표 자체: `w-full text-xs` · `border-collapse`
- thead: `bg-slate-50 dark:bg-slate-900` · th `p-2 text-left font-semibold`
- tbody tr: `border-b border-border last:border-0`
- td: `p-2` · 숫자는 `text-right font-mono`

## 6. 드롭다운 · 버튼 · 링크

- 드롭다운: `border rounded px-2 py-1 text-sm` (dark 자동)
- 기본 버튼: `rounded border px-2 py-1 text-xs hover:bg-muted`
- 주 버튼: `bg-emerald-600 text-white rounded px-3 py-1.5 text-sm hover:bg-emerald-700`
- 링크: `text-sky-700 dark:text-sky-300 hover:underline`

## 7. 타이포·강조

- h1 `text-2xl font-bold` · h2 `text-lg font-semibold` · h3 `text-sm font-medium`
- 라벨: `text-[10px] font-bold uppercase tracking-wider`
- 숫자 (표): `text-right font-mono`
- 인용문: `border-l-4 border-slate-300 dark:border-slate-700 pl-3 text-slate-600 dark:text-slate-400`
- 인라인 코드: `bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded font-mono text-xs`

## 8. 이모지

- 페이지 제목 필수 (Biotech = `🧬`)
- 상태 표시: `✓` `⚠️` `🔒` · 배너 좌측
- 남용 금지 · 기능 명시용만

## 9. 반응형·다크

- Breakpoint: `md:` (768px) · mobile-first
- 다크: 모든 배경/텍스트 쌍 `dark:` 필수
- 표: `overflow-x-auto` 래퍼로 가로 스크롤

## 10. Biotech 화면 매핑 규칙

| 요소 | 이전 (v1 WP69) | 재스타일 (WP70) |
|---|---|---|
| 컨테이너 | `mx-auto max-w-6xl` | **`container mx-auto`** |
| 제목 배지 | (없음) | `bg-sky-500/20 text-sky-400 · Phase A 종결` |
| 탭 활성 | `bg-indigo-600 text-white` | **`border-b-2 border-sky-600 font-bold`** |
| 탭 비활성 | `bg-gray-100 hover:bg-gray-200 text-gray-700` | **`bg-slate-100 dark:bg-slate-800 ...`** |
| 경고 배너 | `bg-amber-50 border-amber-500` (dark 없음) | + **`dark:bg-amber-950 dark:border-amber-600`** |
| 오류 배너 | `bg-red-50 border-red-200 text-red-800` (dark 없음) | + **`dark:bg-red-950 dark:text-red-200`** |
| md HTML 스타일 | `biotech-md` 자체 CSS (200줄) | **인라인 tailwind 클래스** · gray → slate · indigo → sky |

**결론**: `frontend/app/biotech/page.tsx` 만 수정 · 기존 페이지 · 백엔드 · 접점 무접촉.
