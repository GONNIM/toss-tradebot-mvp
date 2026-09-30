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

## 검수 v1 반영 · 2026-09-29 (WP79 · Fable 검수)

- 검수 원본: `docs/plans/biotech/verification/dictionaries/condition_categories_review_v1_reviewed.csv` · `docs/plans/biotech/verification/dictionaries/ko_terms_review_v1_reviewed.csv`
- 분류 변경 13건 · 한국어 변경 21건 · 분류 신설 1 ('미용') · 규칙 4

### 분류 변경

| 용어 | 이전 | 이후 |
|---|---|---|
| Urticaria Pigmentosa | 암 | 피부 |
| Diabetes Mellitus, Insulin-Dependent, 12 | 희귀 유전 | 비만·대사 |
| Pulmonary Eosinophilia | 면역·염증 | 호흡기 |
| Hepatic Impairment (HI) | 소화기 | 기타 |
| Hepatic Impairment | 소화기 | 기타 |
| Renal Impairments | 신장 | 기타 |
| Skin Roughness | 피부 | 미용 |
| Wrinkle | 피부 | 미용 |
| Fine Lines | 피부 | 미용 |
| Skin Thickness | 피부 | 미용 |
| Wrinkles in Decolletage | 피부 | 미용 |
| Pigmentation | 피부 | 미용 |
| Décolleté Wrinkles | 피부 | 미용 |

### 유지 (검수 설명)

| 용어 | 분류 | 검수 설명 |
|---|---|---|
| Hypoglycemia | 비만·대사 | 유지 · 위와 같음 |
| Hypoparathyroidism | 비만·대사 | 유지 · 내분비 질환은 비만·대사에 둠(분류 설명에 '내분비 포함' 명시) |
| Pain, Postoperative | 신경·정신 | 유지 · 통증 용어 3개 이상 쌓이면 '통증' 분류 신설 검토 |
| Renal Transplantation | 신장 | 유지(신장) · 이식 거부 억제제 시장 |
| Vasomotor Symptoms Associated With Menopause | 기타 | 유지(기타) · 여성 건강 용어 3개 이상 쌓이면 분류 신설 |

### 한국어 변경

| 영어 | 이전 | 이후 |
|---|---|---|
| NONE | 눈가림 없음 (공개) | 공개 시험(눈가림 없음) |
| GENETIC | 유전자 치료 | 유전자·세포 치료 |
| DIETARY_SUPPLEMENT | 건강기능식품 | 식이 보충제 |
| Epidermolysis Bullosa Dystrophica | 이영양물집표피박리증 | 이영양성 수포성 표피박리증 |
| Precursor Cell Lymphoblastic Leukemia-Lymphoma | 전구세포 림프모구백혈병-림프종 | 급성 림프모구 백혈병(ALL) |
| Protoporphyria, Erythropoietic | 적혈구조혈프로토포르피린증 | 적혈구조혈 프로토포르피린증(EPP) |
| Hidradenitis Suppurativa | 화농한선염 | 화농성 한선염 |
| Neurodegenerative Diseases | 신경퇴행질환 | 신경퇴행성 질환 |
| Carcinoma | 암종 | 암 |
| Motor Neuron Disease | 운동신경세포병 | 운동신경원 질환 |
| Geographic Atrophy | 지도모양위축 | 지도형 위축(황반변성 후기) |
| Leber Congenital Amaurosis | 레베르선천흑암시 | 레버 선천 흑암시 |
| Psychomotor Agitation | 정신운동초조 | 초조(정신운동성) |
| Waldenstrom Macroglobulinemia | 발덴스트룀마크로글로불린혈증 | 발덴스트롬 마크로글로불린혈증 |
| Supranuclear Palsy, Progressive | 진행핵상마비 | 진행성 핵상마비 |
| Primary Myelofibrosis | 일차골수섬유증 | 원발성 골수섬유증 |
| Acute Kidney Injury | 급성콩팥손상 | 급성 신장 손상 |
| Purpura, Thrombocytopenic, Idiopathic | 특발혈소판감소자색반병 | 면역 혈소판감소증(ITP) |
| Liver Cirrhosis | 간경화 | 간경변증 |
| Glioma | 신경아교종 | 신경교종 |
| Healthy | 건강인 | 건강한 사람 |

### 규칙 (검수 v1 · 사전 고정)

1. 분류 신설 조건: 같은 성격의 용어가 3개 이상일 때만 신설한다. 그 전에는 '기타' 로 둔다. (이번 신설: '미용' 7건)
2. 혈액암 (백혈병·림프종·골수종·골수형성이상·골수증식) 은 '암' · 악성이 아닌 혈액 질환은 '혈액'.
3. '비만·대사' 는 내분비 질환을 포함한다 (예: 부갑상선기능저하증 · 저혈당).
4. '유전 우선' 규칙 유지: 알려진 단일유전자 희귀질환은 장기 분류보다 '희귀 유전' 을 먼저 적용한다.

## v2 · 2026-09-29 (WP80 · 미등재 용어 검수 반영)

- 검수 원본: `docs/plans/biotech/verification/dictionaries/unmapped_terms_20260929_reviewed.csv` (183행 · reviewer_decision 그대로 · proposed_category 미사용)
- 추가 183건 · 행 수 303 → 486
- 분류 신설 3개: 건강인·약동학 (신규 21건) · 통증 (신규 5건) · 청각·이비인후 (신규 4건)
- 기존 항목 이동 5건:

| 용어 | 이전 | 이후 | 사유 |
|---|---|---|---|
| Pain, Postoperative | 신경·정신 | 통증 | '통증' 분류 신설 (v1 검수 설명 "통증 용어 3개 이상이면 신설 검토" 충족) |
| Osteoarthritis Pain | 근골격 | 통증 | 같은 사유 |
| Hepatic Impairment | 기타 | 건강인·약동학 | v1 시점에 해당 분류가 없어 기타로 두었음 |
| Hepatic Impairment (HI) | 기타 | 건강인·약동학 | v1 시점에 해당 분류가 없어 기타로 두었음 |
| Renal Impairments | 기타 | 건강인·약동학 | v1 시점에 해당 분류가 없어 기타로 두었음 |

- 규칙 추가 2개: (5) 전암 병변 (이형성증 · 상피내 병변 · neoplasms 표기) = '암' · (6) 참가 조건 용어 (건강인 · 간·신장 장애 참가자 · 약동학 · 약물상호작용) = '건강인·약동학'

## 한국어 v2 · 2026-09-30 (WP81) · 29건 추가 · 2건 표기 맞춤

- 검수 원본: `docs/plans/biotech/verification/dictionaries/ko_terms_new_categories_proposed_v2_reviewed.csv` (29행 · 유지 17 = proposed_ko · 변경 12 = reviewer_decision)
- `docs/plans/biotech/data/ko_terms.csv` 197 → 226행
- 표기 맞춤 2건: Hepatic Impairment 간기능장애 → 간 기능 저하 참가자 · Renal Impairments 신기능장애 → 신장 기능 저하 참가자 (Hepatic Impairment (HI) 검수 결과 "간 기능 저하 참가자" 와 맞춤)

## 어간 사전 v1 · 2026-09-30 (WP81-2) · 신설

- 파일: `docs/plans/biotech/data/auto_category_stems.json` (자동 분류 3순위 · 수동 사전 > MeSH 트리 > 어간 > 기타)
- 항목 수: 분류 17개 · 어간 207개 (정규식 대안 수) · 출처 = `docs/plans/biotech/verification/dictionaries/auto_category_design.md` 6절 초안
- 적용 순서 "암 → 건강인·약동학 → 나머지" 는 코드가 강제 (`backend/scripts/biotech_auto_category.py` load_stems)
- 규칙: 어간 추가·수정·삭제는 이 파일에 날짜 · 사유 · 건수를 기록한다 (사전과 같은 규칙) · 검수 후 확정
