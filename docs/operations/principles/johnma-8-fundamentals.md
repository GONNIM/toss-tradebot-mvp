---
title: 존마 주식 기초 강의 · 3원칙 (Toss Tradebot Rulebook 원본)
type: principle
source_kind: video-notes
source_author: 묘하다 (@official_myohada)
source_url: https://www.tiktok.com/@official_myohada/video/7667782611628051720
source_published: 2026-07-29
ingested_at: 2026-08-01
ingested_by: z.ai GLM-5.2 (Groq Whisper STT)
raw_notes:
  - /Users/gonnim/GON-LLM-Wiki/Clippings/summaries/2026-08-01-022135-주린이-보육교사-존마의-주식-기초-강의-810편-몰아보기-08.md
  - /Users/gonnim/GON-LLM-Wiki/Clippings/summaries/2026-08-01-112643-주린이-보육교사-존마의-주식-기초-강의-810편-몰아보기-08.md
sync_target: /Users/gonnim/GON-LLM-Wiki/Works/Trading/Toss-Tradebot-MVP/Rulebook/johnma-8.md
adoption_status: partial
integration_plan: docs/plans/toss-tradebot-tobe/rulebook-integration.md
---

# 존마 주식 기초 강의 · 3원칙

> **원본**: TikTok · @official_myohada · 341초 · 8~10편 몰아보기 #08
> **수집일**: 2026-08-01 · 인입 2회 (동일 내용)
> **정체성 관점**: Toss Tradebot 은 급등주 사전 예측 봇. 강의는 우량주 중장기 관점.
> 원칙 2·3(손익비·물타기 금지)은 완전 부합. 원칙 1(종목 선별)은 정체성 불일치 →
> `/lab` 벤치마크로만 활용.

---

## 원칙 1 · 종목 선별 5단계 체크리스트 (우량주 중장기 · Toss Tradebot 정체성 불일치)

투자 실패 확률을 낮추는 필터 순서. **각 단계 통과한 종목만 다음 단계로.**

1. **시가총액 ≥ 5조원** (권장 ≥ 10조)
2. **업종 미래 밝음** (섹터 성장성)
3. **매출·순이익 상승 추세** (최근 재무제표)
4. **연봉 차트 턴어라운드** (하향세 → 상승세 전환 확인)
5. **월봉 5MA 돌파 후 3개월+ 유지** (단기 추세선 위 안착)

**Toss Tradebot 적용**: 급등주/화약고 정체성과 상충. 도입 시 소형주·급등 후보 배제되어 반정체성.
→ 도입 방식: `/lab/blue-chip-filter` 실험 페이지로 격리 · **판정 벤치마크 대조용** (급등주 판정 vs 우량주 필터 통과 여부).

---

## 원칙 2 · 손익비 > 승률 (Toss Tradebot 즉시 적용)

주식 성과는 승률이 아니라 **손익비**로 결정.

- **손절 라인 -5% 고정**
- **3번 손절(-15%) + 1번 +30% 수익 = 순 +15%** · 흑자 유지
- 목표 R:R (Reward:Risk) ≥ 2.0 (권장 ≥ 6.0 · 강의 예시 기준)

**Toss Tradebot 적용**:
- Sniper `hard_stop_loss_pct` -5% 기본값 · 이미 부합
- **Rulebook R:R 계산기** — JudgmentDialog 저장 시 R:R < 2 경고
- **Journal baseline `avg_rr_ratio`** — 판정별 자동 계산 · Stage 2 진입 KPI 확장

---

## 원칙 3 · 물타기 절대 금지 (Toss Tradebot 즉시 적용)

하락 종목은 **빠른 손절** 후 **우량 종목으로 이체**.

- "차선 옮겼더니 더 막힌다" 회피 논리 배제
- 연애 비유: 사기꾼 만나고도 헤어지지 않는 것과 동일 · 매몰비용 오류

**Toss Tradebot 적용**:
- Judgment `invalidation_price` 필수 (이미 배선 완결 · Phase B)
- **outcome 자동 계산 확장** — T+N 기간 내 저가가 invalidation 이하 이탈했는지 감지 (`invalidation_hit_ts`)
- **Journal 카드 "🚨 invalidation 이탈" 배지** · baseline **"물타기율"** 지표 신설
- Rulebook `/rulebook` 페이지의 **물타기 감지 로그** 탭

---

## Toss Tradebot 적용 매핑 (요약)

| 원칙 | 정체성 부합 | Toss Tradebot 이식 |
|---|---|---|
| 1 · 종목 선별 5단계 | ✗ (급등주 정체성 불일치) | `/lab/blue-chip-filter` 벤치마크만 |
| 2 · 손익비 > 승률 | ✓ | Sniper 손절 · Judgment R:R baseline · Rulebook R:R 계산기 |
| 3 · 물타기 금지 | ✓ | invalidation_hit 감지 · 물타기율 · Rulebook 감지 로그 |

---

## 참조

- Rulebook 통합 계획: [[docs/plans/toss-tradebot-tobe/rulebook-integration]]
- 원본 스크립트 인입 노트: `Clippings/summaries/2026-08-01-*.md`
- 프로젝트 정체성: `docs/plans/toss-tradebot-tobe/identity.md`
- Phase E 사용 정착 로드맵: `docs/plans/toss-tradebot-tobe/roadmap-12week.md`
