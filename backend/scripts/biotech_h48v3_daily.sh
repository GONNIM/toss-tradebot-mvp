#!/bin/bash
# WP48v3 · 하루 1회 자동 실행 (KST 07:00 = UTC 22:00 전날)
#
# 운영 구조: 로컬 cron 실행 · 결과 파일 → git commit/push → 열람 시 뷰어가 파일 읽기
# (별도 서버 미보유 · Phase B 는 로컬 FastAPI 뷰어 biotech_h55_viewer.py)
#
# crontab -e:
# 0 22 * * * /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily.sh >> /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/data/biotech/community_daily/cron.log 2>&1
#
# 필요한 .env 키 (backend/.env · TIINGO_API_KEY 는 h48v3 는 미사용 · Phase C 확장 시 참조):
#   - 없음 (외부 API 무인증 · SEC · CT.gov · StockTwits · apewisdom · Reddit RSS)
# 확장 파이프 (H1a/H6/H41 등) 사용 키: TIINGO_API_KEY · SIMFIN_API_KEY · DART_API_KEY · EODHD_API_KEY

set -euo pipefail
cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp
VENV=backend/venv/bin/python

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) biotech daily start ==="

# 1. 후보 우주 갱신 (biotech_candidates_v3_YYYYMMDD.csv)
$VENV -m backend.scripts.biotech_h48v3_candidates

# 2. 커뮤니티 확인 (community_confirm_YYYYMMDD.csv)
$VENV -m backend.scripts.biotech_h48v3_confirm

# 3. 소문 확인 일일 리포트 (rumor-daily/YYYY-MM-DD.md)
$VENV -m backend.scripts.biotech_h48v3_report

# 4. 레이더 리스트 v1.3/v1.4 (watchlist/radar-v1.X-YYYYMMDD.md)
$VENV -m backend.scripts.biotech_h46v3_radar

# 5. Form 4 증분 수집 · 표 4 CSV 생성 (WP65 · 55 CIK · 최근 30일)
$VENV -m backend.scripts.biotech_h65_form4_daily || echo "WP65 skip (SEC 403 등 · 다음 실행에서 재시도)"

# 6. STATUS.md 자동 생성 (WP57 · 매일 갱신 · '가능성 지도 (수동)' 절만 보존)
$VENV -m backend.scripts.biotech_h57b_status_gen

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) biotech daily done ==="
