# Toss Tradebot 이용 가이드 (v1.0 · 2026-07-31)

> **정체성**: 개인 판단 도구 · **자동매매 절대 연결 금지** · 반자동 티켓까지만.
> **최종 게이트**: Stage 2 진입 = Judgment 30건+ · rejection criteria 100% · baseline 확정.

---

## 1. 접근

- 운영: **https://optimus8.cafe24.com** · 로컬 dev: `npm run dev -p 4000` + `uvicorn backend.api.main:app`
- 편집·실주문은 우측 상단 🔐 관리자 세션에 `SNIPER_API_TOKEN` 입력 → httpOnly 쿠키 (12h 유지)
- 세션 만료 시 재로그인. localStorage 쓰지 않음 (XSS 방어).

---

## 2. 하루 루틴 (개장 여정 시간축)

| 시각 | 액션 | 페이지 |
|---|---|---|
| 아침 진입 | Home 상단 **판정 축적 진행률** 확인 (30건 목표) | `/` |
| ~09:00 | 오늘 확정된 top 30 검토 · 편입 시 **수동 add** → 판정 팝업 자동 | `/watchlist` |
| 09:00~09:30 | 갭업 진입 조건 튜닝 · 필요 시 `enabled=true` 저장 → 판정 팝업 자동 | `/sniper` |
| 장중 | Kill Switch·포지션 모니터 | `/positions` `/dashboard` |
| 마감 후 | 오늘 판정 리뷰 · T+7 도래 판정의 outcome 재확인 | `/journal` |

**주말 리서치**: `/powderkeg` tier 이동 리스트 → 🔒 **lock** → 판정 팝업 자동. `/activist-radar` `/vip` `/sector-leaders` 보조.

---

## 3. 3계층 페이지 지도

- **L1 (매일)**: Journal · Watchlist · Sniper · Positions · Dashboard · Logs
- **L2 (주말)**: Powderkeg · Activist · VIP · Sector Leaders
- **L3 (실험)**: `/lab` — crazy · moonshot · meme-watch · super-signals · backtest · execution

---

## 4. 판정 팝업 (자동 트리거 3곳)

| 트리거 | 페이지 | hypothesis_id |
|---|---|---|
| 수동 add | `/watchlist` | `watchlist-manual-add` |
| 🔒 lock | `/powderkeg` | `powderkeg-v2-lock` |
| enabled false→true | `/sniper` | `sniper-enable-toggle` |

**필수 입력**: `thesis` (자유 서술) · **`invalidation_price` (반증 기준 · 없으면 판정 아님)** · `mood` (cool/neutral/revenge/fomo).
**선택**: target_price · horizon_days (기본 T+7). 저장 시 T+N 후 outcome 자동 계산.

---

## 5. Stage 2 진입 KPI (6항 · Journal Home 위젯 실시간)

- [ ] 판정 **30건+** · rejection criteria 100%
- [ ] baseline 확정 (T+7 outcome 자동 계산)
- [ ] page_source 편중 ≤ 60% (self-page 편애 방지)
- [x] 관리자 인증 100% (Phase D 완결)
- [ ] Obsidian sync 3경로 (Phase F 예정)
- [ ] T2 Cal.com 컨설팅 예약 1건 (Phase F 예정)

---

## 6. 안전 규칙 (예외 없음)

1. **자동매매 절대 연결 금지** — 반자동 티켓까지만.
2. **시드 상한 100만원 · 100% 손실 감내** — 넘지 말고 겁내지 말자.
3. **Kill Switch -3%** — 일일 손실 도달 시 자동 발동 · 수동 해제.
4. **가설 라벨 없이 표시 금지** — hypothesis / observing / validated / rejected.

---

## 7. 트러블슈팅

| 증상 | 조치 |
|---|---|
| 편집 버튼 401 | 관리자 세션 만료 · 재로그인 (🔐 카드) |
| 실주문 403 | `SNIPER_LIVE_ENABLED=false` · SOPS 확인 후 재기동 |
| Watchlist 비어있음 | 08:30 KST 자동 finalize 대기 · 또는 "🔄 지금 finalize" |
| Journal 판정 outcome 미계산 | T+7 도래 후 크론 자동 · 수동 재계산은 API PATCH |
| 배포 확증 | `curl https://optimus8.cafe24.com/health` |

---

## 8. 참조 문서

- 관측성 활성화 (Sentry/PostHog): `docs/operations/observability-setup.md`
- 스나이퍼 상세 설정: `docs/operations/sniper-setup.md`
- SOPS · 자격증명 관리: `docs/operations/secrets-management.md`
- 12주 로드맵: `docs/plans/toss-tradebot-tobe/roadmap-12week.md`
- 정체성·원칙: `docs/plans/toss-tradebot-tobe/identity.md`
