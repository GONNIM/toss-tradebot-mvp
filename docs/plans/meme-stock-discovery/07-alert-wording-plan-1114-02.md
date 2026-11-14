# 1114-02 계획 초안: 밈 알림 문구·시각 고침 (작은 PR · 먼저)

## 목표
- 「오늘 … · 지금 …원」 → 「MM/DD 종가 기준 ±x.x% · …원」.
- 장 밖·주말에 같은 자료(같은 종목·같은 기준일)로 다시 알리지 않음.
- 「커뮤니티 언급·거래량 등 5가지」 → 종목마다 실제 입력 수.
- 1114-03 이 쓸 기준일(bar_date)·발송 결과(send_result)를 이번부터 남김.

## 사실 (file:line)
- 문구: alert.py:57-60(오늘·지금) · :65(5가지). 이력 저장 alert.py:186-205 (payload = score·intensity·name·market·retrigger).
- 재알림: cooldown 8h alert.py:27,103-104 · 점수 +0.3/강도 +3.0 이면 cooldown 안이라도 alert.py:31-32,158-162 · 장 시간·요일 확인 없음 · 잡 24시간 5분마다 scheduler.py:131-138.
- 스냅샷: KRX 16:00 매일(주말 포함) scheduler.py:75-82 · US 06:05 :64-72 · snapshot_at=now · 봉 날짜 저장 안 함 volume_snapshot.py:50,68,138-140 · models.py:763-781 → 토요일 16:00 스냅샷에 금요일 봉이 새 행.
- 봉 날짜는 네이버 df index(naver_quote/client.py:229-232,264-267) · yfinance 같음.
- 실제 입력 수 = MemeScore.contributions 길이 (confluence.py:39-48,286-396).
- 알림 설정 gate notifier.py:121-160 (resend 0 기본 · 하루 요약 queued 도 이력에 남음 alert.py:73).
- SignalHit buy 기록 alert.py:211-261 은 건드리지 않음.

## 바꿀 파일
- alert.py: 문구 3곳 · 같은 자료 재알림 막기 · payload bar_date·send_result · 시험용 now 인자.
- volume_snapshot.py: KRX·US 스냅샷에 bar_date = df.index[-1].date().
- models.py: MemeVolumeSnapshot.bar_date (Optional[date]) · db.py _ADDED_COLUMNS ("meme_volume_snapshot","bar_date","DATE").
- scheduler.py: 시각 그대로 (미국 사회 신호는 국내 장 밖에도 바뀜).
- tests/test_meme_alert_html.py 기대 문구 고침(:36,:45-46) + 새 시험 · api/main.py 버전 0.3.55 (1112-07 이 먼저 병합되면 다시 셈).

## 규칙
- 기준일: bar_date → 없으면 snapshot_at 현지 시각(KR 15:30 뒤 그날 · 앞 전날 · 주말 금요일 / US ET 16:00) (outcomes.base_date 와 같은 방식 · 휴장 보정 없음).
- 문구: f"{MM/DD} 종가 기준 {r1d:+.1f}% · {price}" · 모르면 「최근 종가 기준」. 「오늘」「지금」 없음.
- 입력 수: 「급등 전 단계 점수 1.22 (추정 · 입력 n가지: 라벨들 · 보장 아님)」 · contributions 없으면 수 안 씀.
- 같은 자료 막기: 장 밖 = KRX 평일 09:00~15:30 KST 밖 또는 주말 · US 평일 09:30~16:00 ET 밖 또는 주말 (시계 판정 · 토스 호출 0). 장 밖이면 같은 (ticker, bar_date) 이력이 있으면 안 보냄(종류·delta 무관 · stats skipped_same_data). 장 중은 지금 동작. 옛 이력은 triggered_at 으로 기준일 계산해 비교.
- 사용자 확인 후보: KRX 자료는 16:00 하루 1회라 장 중에도 같은 자료 → 「KRX 는 시각 무관 같은 bar_date 면 안 보냄」(선택지 B) · 초안은 스펙대로 A.

## 시험 (시각 고정 · 교훈 #5)
1 KRX bar_date 11/13 → 「11/13 종가 기준 +31.8% · 8,120원」 · 오늘·지금 없음 · violations []. 2 US 같은 꼴. 3 bar_date 없고 토 16:00 → 금요일. 4 contributions 3·4 → 입력 3·4가지 · 「5가지」 없음. 5 토 10:00 · 금 16:04 같은 (ticker,bar_date) 이력 → 안 보냄(점수 +0.5 라도). 6 평일 20:00 같은 bar_date 안 보냄 · 바뀌면 보냄. 7 평일 10:00 기존 동작(기존 시험 3개). 8 US 평일 11:00 ET 기존 · 토요일 막음. 9 payload bar_date·send_result(queued·skipped 포함). 10 스냅샷 bar_date = df 마지막 index. 11 ensure_columns 멱등. 12 test_job_watch 통과.

## 위험
- KR 휴장 평일 장 시간은 「장 중」 판정 → cooldown·delta 재알림 가능(bar_date 비교로 일부 줄어듦).
- 배포 직후 KRX 최대 하루 bar_date NULL → snapshot_at 추정.
- 종류 바뀐 알림(BLAZING→ERUPTING)도 장 밖이면 막힘.
- 막힌 알림은 SignalHit buy 기록도 안 생김(의도).

## 검토 반영 (Fable 2026-11-14-1114-02-01 조건부 GO · 막음 5)
- 막음 1 시각대: triggered_at·snapshot_at 은 서버 현지 naive(KST 추정 · 서버 시간대 KST+0900 은 11/14 사용자 명령으로 확인) → 장 판정·기준일 추정은 ZoneInfo("Asia/Seoul")·("America/New_York") 로 명시. outcomes.base_date(naive=UTC) 는 쓰지 않음.
- 막음 2 기준일 추정: 옛 행은 「그 알림 시각 이전 그 종목 마지막 스냅샷의 날짜」로 추정 (15:30 규칙 버림 · 16:00 잡 끝나야 바뀜 · 미국 여름 05:00 마감 · 06:05 수집).
- 막음 3 조회 범위: 같은 자료 막기용 이력 조회 10일 (금 16:04 → 월 09:00 · 연휴 덮음) · 시험.
- 막음 4 미국 장 밖: 사용자 선택 — 전부 막음 / 점수 +0.3 이상 오르면 「MM/DD 종가 기준」 문구로 보냄.
- 막음 5 승인 범위: 같은 자료 막기는 경보 규칙 변경(WP92) · 막힌 알림은 SignalHit 기록과 실행 계층 매수 신호 전달도 빠짐 → 사용자 요약에 따로.
- 권고: 「입력 n가지」 라벨 한국어 · 배포는 06:05·16:00~16:10 피함 · skipped_same_data 로그 · 성적판은 배포일 전후 나눔.

## 사용자 결정 (2026-11-14)
- 가 B: 국내(KRX)는 시각과 상관없이 같은 (종목, 기준일)이 이미 알려졌으면 다시 보내지 않는다.
- 나 ②: 미국은 장 밖·주말에 같은 기준일이면 막되, 직전 알림보다 점수가 +0.3 이상 오르면 「MM/DD 종가 기준」 문구로 보낸다. 장 중은 지금 동작.
- 다 ①: 막힌 알림은 SignalHit 기록·실행 계층 매수 신호 전달도 함께 빠진다.
