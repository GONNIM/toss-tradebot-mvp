# B1 · 엔진–알림–화면 잇기 (1025-03)

- 로드맵: `README.md` B1
- 결정: 2026-10-27 사용자 「1025-03 권고대로」 (①~⑥ 권고안 전부)
- 사전 질의: `docs/plans/biotech/fable-bundles/2026-10-27-1025-03-01.md` (Fable 조건부 GO · 막음 3 반영)
- 버전: 서버 0.3.11 · 화면 0.3.9 · PR 하나

## 결정

| # | 엔진·항목 | 결정 | 할 일 |
|---|---|---|---|
| ① | Crazy · Moonshot | 살림 | `crazy.py` · `moonshot.py` GET 등록 · 결과 요약 (중앙값 · 건수) · 라벨 「과거 실현 결과 · 미래 수익 보장 아님 · n건」 · 20건 미만이면 숫자 없이 건수만 |
| ② | 조회 인증 | 로그인 필수 | 두 라우터 GET 전부 `require_sniper_token` · 화면은 401 이면 로그인 안내 (텔레그램 링크로 들어와도 로그인 먼저) |
| ③ | Super Signal 5분 잡 | 끔 | `SUPER_SIGNAL_ENABLED` 코드 기본 false · `/sniper/status` 에 `super_signal_enabled` 노출 (배포 뒤 SSH 없이 확인) · 라우터 미등록 유지 |
| ④ | Backtest | 화면 퇴역 | /lab 항목 「쉬는 기능」 · 화면은 안내만 · 라우터 미등록 유지 (Super Signals 화면도 같음) |
| ⑤ | 「카지노」 문구 | 화면 세 곳 고침 | `settings.py:14` · `lab/page.tsx` (Moonshot · Meme) · `meme-watch/page.tsx:97` → 「고위험 시드」 · LLM 프롬프트 `llm.py:118` 은 그대로 (WP92 · 바꾸려면 따로 승인) |
| ⑥ | 「청산 계획 있음」 뜻 통일 | 미룸 | /account 와 `/positions/plan` has_plan (positions.py:115-118) 은 다른 PR |

함께 고칠 것: lab Crazy 설명 「Claude Haiku thesis」 → 실제 (Anthropic 1순위 · Z.ai 대체) · 라우트 인증 테스트 · `/crazy?limit` 307 리다이렉트 없앰 (라우트 경로 `""`).

## 결과 요약 API

- `GET /api/v1/crazy/summary` → `{ "1w": {n, median}, "1m": {n, median} }`
- `GET /api/v1/moonshot/summary` → `{ "1d": …, "3d": …, "5d": … }`
- n = 값이 채워진 전체 행 수 · n < 20 이면 median = null (화면은 「n건 · 20건부터 표시」)
- 값은 비율 (0.05 = +5%) · outcomes.py 가 채운 실현값 그대로

## 수용 기준

1. 인증 없이 crazy·moonshot GET 전부 401 · 토큰이면 200 (테스트)
2. `/api/v1/crazy?limit=3` 이 307 없이 200
3. summary 의 n<20 → median null · n≥20 → 중앙값 (테스트)
4. `SUPER_SIGNAL_ENABLED` 미설정이면 5분 잡 미등록 · `/sniper/status.super_signal_enabled` false
5. 화면: 401 이면 로그인 안내 · 요약 라벨 문구 · 「카지노」 화면 문구 0건 (llm.py 제외)
6. biotech 묶음 · 전체 pytest 기존 실패 외 새 실패 없음 · `tsc --noEmit` 통과

## 배포 뒤 확인

- `/api/v1/sniper/status` 의 `super_signal_enabled` false (true 면 서버 .env 에 명시된 것 → 사용자에게 보고)
- `/api/v1/crazy` 인증 없이 401
- 다음 06:30 Crazy · 16:50 Moonshot 알림 링크를 열면 로그인 안내 또는 목록
