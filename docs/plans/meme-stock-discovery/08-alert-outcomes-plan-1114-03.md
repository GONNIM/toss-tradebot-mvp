# 1114-03 계획 초안: 밈 알림 성적판 (서버 장부 + /lab/meme-watch 「알림 뒤 결과」)

## 목표
알림 하나하나의 뒤 결과를 토스 일봉만으로 매일 쌓고 /lab/meme-watch 에 늘 보이게 해 사용자가 판단에 씀. 범위 밖: 알림 문구 숫자(정의 7절 변경 질의 뒤) · 비교 A(월 1회 로컬 문서) · 점수·알림 규칙 변경 · 발송 처리(사용자 「계속」 11/14).

## 확인한 사실
- 토스 공개 명세 openapi.json v1.2.28 (11/14 17시대 GET · 인증 없음): GET /api/v1/candles (symbol · interval 1m|1d · count ≤200 · before · adjusted 기본 true=수정주가) · Candle 필수 칸 timestamp(1d=거래일 현지 자정) · openPrice · highPrice · lowPrice · closePrice · volume · currency (문자열 decimal) · 최신순 · 그룹 MARKET_DATA_CHART. GET /api/v1/market-indicators/{symbol}/candles · 심볼 카탈로그 8종(KOSPI · KOSDAQ · KR_BOND_*) · 1d 지원 · 같은 칸 · 그룹 MARKET_INDICATOR_CHART. 응답 꼴 CandlePageResponse {candles, nextBefore} (result 감쌈 여부는 클라이언트 코드 기준).
- 선례 outcomes.py:1-12 (토스 일봉 200봉 cron · 없으면 계산 불가) · Bar(d, close, low, high) :36-41 · parse_bars 는 timestamp·closePrice·lowPrice·highPrice 만 :62-73 · _fetch 종목당 1호출 :132-148 · 모두 실패면 RuntimeError :203.
- toss_client.py:295-301 candles · rate_limiter MARKET_DATA_CHART 3/s :43,70 · market-indicators candles 는 resolve_group 에서 MARKET_INDICATOR(8/s) 로 잘못 감 :75,80-84 → 고침.
- 응답 꼴이 rank_signals.py:200-205(list) 와 outcomes.py:64(dict) 서로 다름 → 시험으로 가림.
- 알림 이력 models.py:711-722 · triggered_at 서버 로컬 naive(KST) · skipped·queued 도 남음 · 이력 목록 API 없음(today.py:298-326 만) · meme-watch 화면에 최근 알림 목록 없음(page.tsx 125줄).
- cron 프로세스 시각(backend/scheduler/cron.py:925-967): 06:00 · 06:30 · 07:10 · 07:40 · 08:10(outcomes) · 08:45 · 09:05 · 15:50 · 16:50 · 17:05 · 18:00. 시험 test_job_watch.py:44-59 · :104-112 · :186-191(5분 간격).
- 인증 moonshot.py:15-16 require_sniper_token · 화면 선례 moonshot/page.tsx · components/lab/PickResults.tsx(OutcomeSummary · LoginNotice).
- 새 표는 init_db create_all(main.py:90 · db.py:79-85).

## 바꿀 파일
outcomes.py(Bar 에 open·volume 기본 None · parse_bars openPrice·volume) · services/meme_outcomes.py(새: 묶기·기준일·계산·상태·요약) · models.py MemeAlertOutcome · toss_client.py indicator_candles(symbol,count) · rate_limiter.py resolve_group 고침 · scheduler/cron.py job_meme_outcomes 17:35 월~토 + CLI target · api/routes/meme_watch.py GET /outcomes/summary · /outcomes/recent (require_sniper_token) · schemas.py · frontend lib/api.ts · app/lab/meme-watch/page.tsx · components/meme-watch/AlertOutcomes.tsx(새) · tests/test_meme_outcomes.py(새) · 버전 서버 0.3.56 · 화면 0.3.49 (병합 순서 따라 다시 셈).

## 표 meme_alert_outcome (UNIQUE ticker, signal_date)
user_id · ticker · market · signal_date · first_alert_id · first_alert_at · alert_type · alerts_same_day · score · intensity · send_result · prev_close · signal_close · signal_day_ret · entry_date · entry_open · ret_1d/3d/5d/10d(비용 전 원값) · max_up · max_down · idx_ret_1d/3d/5d/10d(코스닥 · 진입일 시가 기준 · 지수도 openPrice 있음) · bars_after · status(ok · pending · not_buyable · no_trade · broken · unavailable) · status_note · fail_count · computed_at · created_at. 비용 0.25% 는 요약 때 뺌. cron 잡 시작 때 이 표만 create_all(멱등).

## 계산 규칙 (미리 고정)
1 대상 기준일 ≥ 2026-07-03. 2 기준일: payload.bar_date(1114-02 뒤) → 직전 스냅샷 bar_date/snapshot_at → triggered_at(KRX 16:10 전이면 전날) · 토스 봉으로 보정. 3 단위 (ticker, signal_date) 첫 알림. 4 진입 = 다음 봉 openPrice · 살 수 없음(KRX: open ≥ 상한가 = signal_close×1.30 호가 내림 · 호가 2023 규칙 <2천 1 · <5천 5 · <2만 10 · <5만 50 · <20만 100 · <50만 500 · 그 위 1,000) · 거래 없음 volume 0 → 수익률 비우고 건수. 5 끊김: 종목 마지막 봉 < 기준 최신일(KR 지수 최신 봉)이고 10봉 안 참 → 값 남기고 끝. 6 미완: 다음 실행 이어 채움. 7 계산 불가: 토스 없음 3회 · 기준일 봉 200봉 밖 · KRX 이웃 봉 ±30.5% 넘음 → 「계산 불가 N건」. 8 끝난 행 다시 안 부름.

## 잡
cron 프로세스 CronTrigger(mon-sat 17:35) · id meme_outcomes_daily · coalesce · misfire_grace_time=GRACE_DEFAULT · 17:05·18:00 과 25분+ · 실패 _alert_job_failure. 첫 실행이 7/03~ 모두 채움(약 781종목 추정 + 지수 1 ≈ 4.5분 · 3/s) · 매일 수십~100여 회. 수동 실행은 서버 일이라 사용자 승인.

## API (로그인 필요)
- /outcomes/summary?horizon=5: as_of · period · cost · kosdaq 등락 · verdict(국내 5일 n<30 「판정 보류 · 건수 부족」 / 순 5일 중앙값 > 코스닥 5일 중앙값 그리고 오른 비율 > 50% 「지난 값에서 코스닥보다 높았음」 / 그 밖 「없음 · 코스닥보다 낫다는 근거 없음」) · status_counts · overall(n · median · up_share · median_max_down · diff_vs_kosdaq) · breakdowns(종류 · 점수 <1.0/1.0~1.2/1.2~1.5/≥1.5 · 그날 등락 <10/10~20/20~29/≥29% · 10/23 전후 · 국내/미국) · n<30 칸 숫자는 서버가 null · 「설명용」 · 「지난 값 · 추정 · 보장 아님」 · 미국은 비교 지수 없음.
- /outcomes/recent?limit=50: 기준일 · 종목 · 시장 · 종류 · 점수 · 그날 등락 · 산 가격 · 1/3/5/10일(비용 뺀 값) · 최대 상승·하락 · 상태.

## 화면 (/lab/meme-watch header 아래)
판정 줄(판정 · 기간 · 같은 기간 코스닥 · 비용 뺌 · 상태별 건수) → 요약 타일 5 → 「나눠 본 값 · 설명용」 표 5 → 최근 알림 표. 로그인 안 되면 LoginNotice. DESIGN.md(상승 빨강 · 하락 파랑 · 틸 · tabular-nums · 그림자 없음 · 17px · 44px). 명령문·신호 낱말 금지. 곁가지: page.tsx:52-53 「5요소 confluence」 문구도 사실과 다름(이번에 같이 고칠지 사용자 확인).

## 시험
묶기 · 기준일(payload/스냅샷/시각) · 수익률·비용 · 살 수 없음 · 거래 없음 · 미완 이어 채움·끝난 행 재호출 없음 · 끊김 · 계산 불가(3회·±30.5%) · 모두 실패 RuntimeError · 지수만 실패면 kosdaq null 성공 · 기존 test_outcomes 통과(Bar 호환) · resolve_group · API 401·n<30 null·금지 낱말 · cron 17:35 · test_job_watch · tsc · 로컬은 BIOTECH_API_ONLY=1 TELEGRAM_BOT_TOKEN= 로만.

## 위험
기준일 추정(옛 행 · 16:00~16:10 · 스냅샷 보관 기간 미확인) · 상한가 예외(신규 상장 · 정리매매) · skipped·queued 포함(「보낸 것만」은 1114-02 뒤) · 첫 실행 약 780회 · 미국 분할은 adjusted=true 로 막힘(추정).

## 순서
1114-02 병합 뒤 → outcomes·toss_client·rate_limiter → 표·meme_outcomes·시험 → cron → API → 화면 → 버전 → PR → 사용자 승인 뒤 병합·배포 → 첫 17:35 실행이 채움.

## 검토 반영 (Fable 2026-11-14-1114-03-01 조건부 GO · 막음 4)
- 사실 고침: 지수 일봉은 currency 칸·adjusted 매개변수 없음 · 알림 저장 파일 backend/discovery/meme_watch/alert.py.
- 막음 1 진입 봉: 「첫 알림 시각 뒤에 처음 열리는 봉의 시가」로 고정 (기준일을 전날로 잡은 장중 알림이 이미 지난 시가를 쓰지 않게) · 시험 추가. 미국 기준일 = 현지(ET) 16:00 마감 기준을 규칙 2에 명시.
- 막음 2 생존 편향: 계산 불가·끊김 비율을 판정 줄에 함께 보임 · 그 비율이 10% 를 넘으면 「높았음」 판정을 내지 않고 「판정 보류 · 빠진 행 많음」(기준값은 사용자 확인). 미국 끊김 기준 최신일 = 그날 받은 미국 종목 최신 봉의 최댓값.
- 막음 3 덜 닫힌 봉: 현지 정규장 마감 뒤의 봉만 씀(KR 15:30 · US 16:00 ET) · 그날 봉이 마감 전이면 쓰지 않음 · 시험 추가.
- 막음 4 사용자 확인: ① 판정 값(30건 · 오른 비율 50% · 비용 0.25% · 빠진 행 10%) ② 보내지 않은 알림(skipped·queued) 포함 + 나눠 보기 ③ 운영 DB 새 표 + 첫 실행 약 780회 ④ 로그인 필요 ⑤ 1114-02 병합 전 알림은 기준일 추정.
- 권고: 판정 비교는 행마다 짝지은 지수 값 · 건수와 함께 서로 다른 기준일 수 표시 · resolve_group 은 「/candles 로 끝남」 따로 판별 · 새 경로마다 require_sniper_token + 401 시험.
- 승인 범위: 화면 판정 규칙은 WP92 승인 대상(사용자 승인) · 점수·발송 규칙 변경 없음 · 서버 수동 실행은 사용자 승인 뒤.

## 사용자 결정 (2026-11-14)
- 「㉠ 만듦 · ㉡ 계속」: 성적판을 만들고, 알림 발송은 계속한다.
- 가 「계획대로」: 30건 미만 칸 숨김 · 오른 비율 50% · 비용 왕복 0.25% · 계산 불가·끊김 비율 10% 넘으면 판정 보류.
- 나 「포함」: 보내지 않은 알림(skipped·queued)도 넣고, 보낸 것만 따로 나눠 본다.
- 1114-02 배포(2026-11-14 18:4x · aeaba2a) 전후를 나눠 본다.
