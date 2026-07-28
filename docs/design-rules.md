# 시각 디자인 기초 규칙 · Design Rules

**출처**: [Anthony Hobday · 28 rules of visual design](https://anthonyhobday.com/sideprojects/saferules/)
**목적**: 프로젝트 전 페이지 UI 일관성 · 눈에 편한 디자인 · 이질감 방지
**적용**: `frontend/app/**` 전 페이지 · 신규 페이지 추가 시 이 규칙 준수 필수
**정체성 참조**: `docs/plans/powderkeg-screener/identity.md` v2.0 (투자 이익 창출 · 신뢰 우선)

---

## 📐 28 Safe Rules (전문 + 한국어)

| # | 원문 | 한국어 요약 | 프로젝트 실 예시 |
|---|------|------------|----------------|
| 1 | Use near-black and near-white instead of pure black and white | 순수 흑/백 대신 준-흑/준-백 | `#000` `#fff` 금지 · `slate-50` `slate-900` |
| 2 | Saturate your neutrals | 중성색에 채도 추가 | `gray-` 대신 `slate-` (블루 편향) |
| 3 | Use high contrast for important elements | 중요 요소만 높은 명도 대비 | Tier 1 배지 amber-900 vs bg-slate-50 |
| 4 | Everything in your design should be deliberate | 모든 요소 의도적 선택 | 여백·정렬·크기·간격·색 근거 있는 결정 |
| 5 | Optical alignment is often better than mathematical | 시각적 정렬 우선 | 아이콘+텍스트 · 광학 중앙 |
| 6 | Lower letter spacing and line height with larger text | 큰 텍스트 · 자간·행간 감소 | h1 tracking-tight · body leading-relaxed |
| 7 | Container borders should contrast with both container and background | 테두리 대비 · 배경·컨테이너 양쪽 대비 | border-slate-200 (bg-white 위) |
| 8 | Everything should be aligned with something else | 요소 정렬 관계 | flex/grid · items-center |
| 9 | Colours in a palette should have distinct brightness values | 팔레트 명도 다양 | 50 · 200 · 500 · 800 골고루 |
| 10 | If you saturate your neutrals use warm OR cool, not both | 색온 통일 · warm or cool | amber+orange (warm) · sky+indigo (cool) |
| 11 | Measurements should be mathematically related | 수학적 비례 · 8의 배수 | Tailwind 기본 space-2/4/6/8 |
| 12 | Elements should go in order of visual weight | 시각 무게 순 배열 · 무거운 것을 가장자리 | 헤더·푸터 짙게 · 본문 밝게 |
| 13 | If you use a horizontal grid, use 12 columns | 12열 그리드 | `md:grid-cols-12` |
| 14 | Spacing should go between points of high contrast | 대비 지점 사이 간격 측정 | text-to-border · border-to-text |
| 15 | Closer elements should be lighter | 앞쪽 요소 밝게 | 모달 > 카드 > 배경 |
| 16 | Make drop shadow blur values double their distance values | 그림자 blur = distance × 2 | shadow-md (blur 6px · offset 3px) |
| 17 | Put simple on complex or complex on simple | 복잡 vs 단순 조화 | 강한 색 배지 · 단순 배경 위 |
| 18 | Keep container colours within brightness limits | 컨테이너 명도 한계 · 다크 12% · 라이트 7% 이내 | `bg-slate-50` on `bg-white` (~5%) |
| 19 | Make outer padding the same or more than inner padding | 외부 패딩 ≥ 내부 패딩 | section p-6 > card p-4 |
| 20 | Keep body text at 16px or above | 본문 최소 16px | `text-base` (16px) · text-sm(14) 은 캡션만 |
| 21 | Use a line length around 70 characters | 줄 길이 약 70자 | max-w-prose (~65ch) |
| 22 | Make horizontal padding twice the vertical padding in buttons | 버튼 가로 padding = 세로 × 2 | `py-2 px-4` |
| 23 | Use two typefaces at most | 서체 최대 2개 | sans (Inter) · mono (JetBrains) |
| 24 | Nest corners properly | 중첩 모서리 · 내부 = 외부 - 간격 | outer rounded-lg (8px) · inner rounded-md (4px) |
| 25 | Don't put two hard divides next to each other | 하드 디바이드 연속 배치 금지 | border + ring + 다른 bg 삼중 지양 |
| 26 | Don't use shadows in dark interfaces | 다크 UI 그림자 금지 | 다크 모드 · shadow 대신 border |
| 27 | Don't mix depth techniques | 깊이 표현 기법 통일 | shadow OR border-heavier · 혼용 X |
| 28 | Lower the contrast of icons paired with text | 아이콘-텍스트 대비 낮춤 | text-slate-700 · icon text-slate-500 |

---

## 🎨 프로젝트 정체성 팔레트 (powderkeg 기준 · 정합 필수)

**Warm 계열 (강조 · Tier 1 · 매수 후보)**
- amber-50/100/200 · bg
- amber-500/700/900 · text/icon

**Cool 계열 (관찰 · 정보)**
- sky-50/100 · bg
- sky-500/700 · text/icon
- slate-50/100/200 · 중성 (bg)
- slate-500/700/900 · 중성 (text)

**성공/실패 (신중히 사용 · 임팩트 있는 곳만)**
- emerald-100/500/700 · 통과 · 긍정
- rose-100/500/700 · 실패 · 부정

**금지 팔레트** (activist-radar 이질감 원인)
- ❌ pink-500 · fuchsia-500 · cyan-500 · indigo-500 강한 채도
- ❌ ring-2 ring-*-500 (하드 디바이드 · 그림자·border 혼용)
- ❌ bg-*-950/30 (반투명 다크 · 라이트 UI에 부적합)

---

## 💡 shadcn 토큰 자동 다크 대응 (판정 오탐 방지)

프로젝트는 shadcn/ui 기반 · `globals.css`의 CSS 변수가 라이트/다크 자동 반전. **`dark:` variant grep 통계 0회여도 이슈 아님** (아래 토큰 사용 시 자동 대응).

**자동 대응 shadcn 토큰**:
- `bg-card` · `bg-background` · `bg-primary` · `bg-secondary` · `bg-muted` · `bg-accent`
- `text-foreground` · `text-muted-foreground` · `text-primary-foreground` 등
- `border-border` · `border-input`

**정합 판정 순서** (경직된 grep 대신):
1. `bg-*-950` 등 다크 하드코딩 실 위치 있는지
2. `pink/fuchsia/cyan-500` 등 금지 팔레트 있는지
3. `ring-2` · `shadow-lg` 있는지
4. shadcn 토큰 총 사용 회수 (10+ 이면 자동 대응 충분)
5. 위 4개 모두 클린이면 **정합 완결** — `dark:` variant 0회여도 무해

**실측 예 (2026-07-28)**:
- execution (896줄, dark: 0회, shadcn 61회) → ✅ 정합 완결 (리팩터 불필요)
- backtest / super-signals / dashboard / moonshot → 모두 동일

---

## 🔧 백엔드 데이터 정합성 안티패턴 (v1.53~v1.55 사고 근거)

### 패턴 X · empty-string substring 매칭 버그
```python
# ❌ 위험 · target_desc == "" 이면 "" in x == True → 모든 이벤트 매칭 폭발
if user_var.upper() in (row.target_desc or "").upper():
    ...
```
**가드**:
```python
# ✅ 안전
val = (user_var or "").strip()
if val and val.upper() in (row.target_desc or "").upper():
    ...
```
**실 사례**: activist-radar Wolf Pack에 SNN 이벤트에 무관 10명 허위 표시 (v1.53 P2-5 · KR 대칭 v1.55 P2-5b).

### 패턴 Y · XML 네임스페이스 하드코딩
```python
# ❌ 위험 · 스키마 URI 편차 시 모든 XPath 실패
_NS = {"s13": "http://www.sec.gov/edgar/schedule13D"}   # 대문자만
root.find(".//s13:issuerName", _NS)
```
**개선**:
```python
# ✅ URI-agnostic · Python 3.8+
root.find(".//{*}issuerName")

# iter() 는 wildcard 미지원 · 로컬네임 수동 매칭
for elem in root.iter():
    if elem.tag == local_name or elem.tag.endswith("}" + local_name):
        ...
```
**실 사례**: SC 13G 5건 파싱 실패 · "회사명 미확인" (v1.53) · Form 4 잠재 리스크 (v1.55 P2-5b 예방).

### 패턴 Z · 동일 데이터 이원 계산 (신뢰성 파괴)
- 두 API가 같은 지표를 다른 축·다른 함수로 계산 → 사용자 관점 어긋남
- 예: `/summary`는 DB `status="passed"` 카운트 vs `/list`는 `_compute_tier` 재계산 → 스키마 진화 시 불일치
- **원칙**: 단일 계산 함수 · single source of truth · 다른 위치는 그 함수 재사용
- 실 사례: Wolf Pack 요약(0) vs 이벤트 필드(10) (v1.53 P2-5) · Powderkeg tier 이원화 (v1.55 P2-5b)

### 코드 리뷰 체크리스트
1. `<var>.upper() in (...)` 발견 시 · `<var>` empty 가드 확인
2. `xml.etree` 신규 사용 · `{*}` URI-agnostic 강제
3. 동일 지표 2군데 계산 · 하나의 함수로 위임 (DRY)
4. `if x.something or y:` · empty 문자열이 `y`로 위장 못하는지 확인

---

## 🚫 프로젝트 안티패턴 (재발 방지)

1. **다크/라이트 혼재**: 한 페이지에 `bg-slate-50` + `bg-slate-900` 혼용 시 어느 하나로 통일
2. **채도 폭발**: 한 카드에 3개 이상의 500 톤 색상 (cyan+rose+pink 등) 금지
3. **삼중 디바이드**: `border + ring + bg-color-950/30` 동시 사용 (규칙 25 · 27 위반)
4. **아이콘 강조**: 텍스트와 같은 색·같은 굵기 아이콘 (규칙 28 위반)
5. **하드코딩 개수**: `10/10` 같이 조건 개수 하드코딩 (v1.50 hotfix에서 겪음)

---

## 📚 참고 페이지 (정체성 기준)

**정체성 준수 페이지**:
- `frontend/app/powderkeg/page.tsx` — 화약고 스크리너 · 기준 페이지
- 파스텔 톤 (amber-50/sky-50 배경)
- border만 사용 · ring 없음
- warm(amber) + cool(sky) 명확 분리

**리팩터 대상 (2026-07-27 확증)**:
- `frontend/app/activist-radar/page.tsx` — Regime Change/Critical/Strong 등 강한 채도 남용 · 다크 톤 + 500 강채도 혼재

---

## 📖 개정 이력

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-07-27 | v1.0 | 신규 · Anthony Hobday 28 rules 수집 · 프로젝트 팔레트/안티패턴 규약 · activist-radar 리팩터 근거 |
