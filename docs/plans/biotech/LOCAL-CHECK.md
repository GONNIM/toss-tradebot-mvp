# 로컬 확인 절차서 (WP67-2 · 2026-09-14)

> 📖 [`GLOSSARY.md`](GLOSSARY.md) · 코드 · 상태 · 가설 뜻
> 🚫 **서버 (optimus8) 접근·변경 금지** · 이 절차는 로컬 (macOS) 전용

## 실행 (한 줄)

```bash
backend/scripts/biotech_local.sh start
```

→ 브라우저 자동 열기 · **http://localhost:4000/**

**포트 변경**: `BIOTECH_VIEWER_PORT=8080 backend/scripts/biotech_local.sh start`

## 상태 확인 · 종료

```bash
backend/scripts/biotech_local.sh status   # PID · 포트 확인
backend/scripts/biotech_local.sh stop     # 뷰어 종료
```

## 확인 순서 5줄 (첫 화면 = http://localhost:4000/)

| # | 순서 | 주소 | 확인 내용 |
|---|---|---|---|
| ① | **순위표** | http://localhost:4000/radar | 오늘 상위 30 · 뉴스 예정일 임박순 |
| ② | **소문 확인** | http://localhost:4000/rumor | 표 1 (살 자리) · 표 2 (통과) · 표 3 (언급 원값) · 표 4 (임원·대주주) |
| ③ | **상태판 결론 4줄** | http://localhost:4000/map | 오늘 알아낸 것 5줄 |
| ④ | **용어집** | http://localhost:4000/glossary | 코드·상태·가설 뜻 |
| ⑤ | **crontab** | 터미널 | `crontab -l \| grep biotech` · 2줄 확인 |

## 매일 10분 루틴

1. 브라우저 http://localhost:4000/ 열기 (뷰어 미실행 시 `biotech_local.sh start`)
2. 순위표에서 A 상태 (뉴스 예정) 상위 5 확인
3. 소문 확인 표 1~4 스캔 (baseline_n < 7 인 종목은 collecting)
4. 상태판 결론 4줄 · 오늘 알아낸 것 변화 여부
5. crontab 로그 (`tail backend/data/biotech/community_daily/cron.log`) · 자동 실행 성공/실패

## "오늘 파이프 확인해" 요청 방법 (사용자)

- 챗봇에 "오늘 파이프 확인해" 라고 하면:
  - `cron.log` 최근 실행 성공 여부 · 6단계 각 성공/실패
  - 산출 4종 mtime (rumor · radar · candidates · confirm)
  - 표 3 활성 (baseline_n ≥ 7 종목 수) 여부
  - 표 4 임원·대주주 매수 새 이벤트 여부

## 파일 6종 (매일 갱신 대상)

1. `docs/plans/biotech/rumor-daily/YYYY-MM-DD.md` — 소문 확인 리포트
2. `docs/plans/biotech/watchlist/radar-v1.3-YYYYMMDD.md` — 레이더 순위표
3. `docs/plans/biotech/STATUS.md` — 상태판 (자동 갱신 · WP57)
4. `backend/data/biotech/candidates/biotech_candidates_v3_YYYYMMDD.csv` — 후보 우주
5. `backend/data/biotech/community_daily/community_confirm_YYYYMMDD.csv` — 커뮤니티 확인
6. `backend/data/h65_form4_daily_table_{sha}.csv` — Form 4 표 4 (최근 20 거래일)

## 자동 실행 확인 3명령

```bash
# 1. crontab 등록 확인 (2줄 = daily · forward)
crontab -l | grep biotech

# 2. 최근 자동 실행 로그
tail -30 backend/data/biotech/community_daily/cron.log

# 3. 오늘 산출 4종 mtime
ls -la docs/plans/biotech/rumor-daily/$(date -u +%Y-%m-%d).md \
       docs/plans/biotech/watchlist/radar-v1.3-$(date -u +%Y%m%d).md
```

## 서버 접근 금지 · macOS 절전 대안 (선택)

- 서버 (optimus8) 접근·변경 금지 · 로컬 뷰어 전용
- 절전 시 07:00 KST cron 건너뛰기 우려 → **launchd 등록 대안** (필수 아님):
  - `~/Library/LaunchAgents/local.biotech.daily.plist` 로 절전 후 wake 시 자동 실행
  - 사용자 결정 · 지금은 cron 등록 (crontab 방식)

---

## 하단 고정

- ⚠️ **알파 (초과 수익) 미확정 · 소액 전향용 · 매수 신호 아님**
- 자동매매 없음 · 반자동 티켓 (매수 확인 버튼) 도 Phase C 1순위 보류
- 실전 기록 = `backend/data/biotech/trades/trades_manual.csv` 수동 CSV
