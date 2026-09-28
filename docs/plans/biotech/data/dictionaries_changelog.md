# 사전 변경 기록 (condition_categories.csv · ko_terms.csv)

규칙: 사전은 사전 고정이다. 항목을 추가·수정할 때마다 이 파일에 날짜 · 사유 · 건수를 적는다. 임의 번역 금지 · 미등재 용어는 화면에서 영어 원문 유지 ("기타 (원문)").

## v1 · 2026-09-28 (WP76-2)

- `condition_categories.csv` 303행 = MeSH 용어 252 (AACT 2026-09-28 후보 매칭 시험 458건의 mesh-list 전량 · 일반어 9개 제외: Recurrence · Chronic Disease · Disease · Genetic Diseases, Inborn · Congenital Abnormalities · Neoplasms by Site · Neoplasms by Histologic Type · Lymphatic Abnormalities · Bites and Stings) + MeSH 없는 시험의 질환명 원문 51
- 분류 규칙: 알려진 단일유전자 희귀질환은 장기보다 "희귀 유전" 우선 · 건강인·약물상호작용 시험은 등재하지 않음 (화면 "기타 (원문)")
- `ko_terms.csv` 200행 = 설계·약물 유형 18 + 질환 182 (빈도순) · 약물 이름은 등재하지 않음 (영어 원문 유지)
- 작성: Claude · 관례 의학용어 표기 · **사람 검수 전** (검수 후 이 기록에 검수일 추가)

## 규칙 기록 · 2026-09-28 (WP78) · 급등 경보 조건

- 사전 항목 변경은 아니지만 사용자 지시로 표시 규칙 변경을 여기에도 기록한다.
- 변경 전: apewisdom 평소 대비 ≥ 5배 OR 레딧 RSS 매치 ≥ 3건
- 변경 후: 기준선 7일 이상 종목만 · (≥ 5배 AND 오늘 언급 ≥ 5건) OR 레딧 매치 ≥ 3건 · 기준선 7일 미만은 "수집 중"
- 근거: 2026-09-28 IOVA (어제 1 · 오늘 1 · 6.0배) · 정의 위치 `backend/data/h_radar_params.json` alerts_definition_wp78 · 코드 `backend/scripts/biotech_alert_rule.py`
