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

## v3 · 2026-09-30 (WP82 · 자동 분류 검수 + 미분류 검수 반영)

- 검수 원본: `docs/plans/biotech/verification/dictionaries/auto_category_review_20260930_reviewed.csv` (12행 · 희귀 유전 10 · 유지 2) · `docs/plans/biotech/verification/dictionaries/unmapped_after_auto_20260930_reviewed.csv` (150행)
- 추가 162건 · 행 수 486 → 648
- "유지" 2건은 자동 분류가 맞았으므로 그 값으로 수동 등재: Eczema, Atopic → 피부 · Wilms Tumor → 암
- 새 분류 값 "무시" 37건 (일반어 · 시술 · 약물명 · 증상 · 시험 단계 · 비특이 표지자) · 시험 분류를 정할 때 건너뜀 · 화면에 표시하지 않음
- 분포 (추가분): 암 66 · 무시 37 · 희귀 유전 33 · 신경·정신 7 · 면역·염증 6 · 감염 6 · 혈액 2 · 피부 1 · 근골격 1 · 통증 1 · 신장 1 · 건강인·약동학 1
- 규칙 추가 2개: (7) 무시 등재 · 건너뛰기 · (8) 암 시험 전용 종양 표지자·변이 = 암
- 새 용어의 한국어는 이번에 만들지 않음 (카드는 분류만 바뀌고 원문 유지 · 다음 검수 때 목록 제안)

## 어간 사전 v2 · 2026-09-30 (WP82-3) · 약어 42건 · 어간 3건 이동

- 파일: `docs/plans/biotech/data/auto_category_stems.json` · 새 구역 `abbreviations` (어간과 분리)
- 검수 원본: `docs/plans/biotech/verification/dictionaries/abbreviations_proposed_v1_reviewed.csv` (45행 · 등재 42 · 제외 3 = MM · MS · RA · 두 글자 약어)
- 약어 42건 = 검수 등재분 · 분류는 제안 값 그대로
- 어간에서 지운 3건 (암 어간 정규식에서 삭제 → 약어 구역으로 이동): `\baml\b` · `\bcll\b` · `\bmds\b` (기존: 대소문자 무시 → 이동 후: 대소문자 구분 AML · CLL · MDS)
- 일치 규칙: 단어 경계에서만 · 대소문자 구분 · 괄호 안과 하이픈 앞도 단어 경계
- 적용 순서 (코드 강제): 암 어간 → 건강인·약동학 어간 → 약어 → 나머지 어간

## 규칙 기록 · 2026-09-30 (WP86) · 급등 경보 배수 기준선 하한

- 변경 전: 평소 대비 배수 = 오늘 apewisdom 언급 / 기준선 평균 · 평균 0 이면 배수 없음 (None → "collecting")
- 변경 후: 평소 대비 배수 = 오늘 apewisdom 언급 / max(1.0, 기준선 평균) · 평균 0 이어도 계산
- 경보 조건 무변경: 기준선 7일 이상 · (≥ 5배 AND 오늘 ≥ 5건) OR 레딧 매치 ≥ 3건 (`backend/scripts/biotech_alert_rule.py` 그대로)
- 근거: IOVA 9/30 기준선 평균 0.25 (이전 8일 0·0·0·0·0·1·1·0) → 오늘 32건이 128배로 표시 · KOD 9/29 기준선 평균 0 (7일 0건) → 오늘 14건인데 배수 없음으로 경보 누락
- 코드: `backend/scripts/biotech_h48v3_confirm.py` baseline_multiple() · 정의: `backend/data/h_radar_params.json` alerts_definition_wp86

최근 9일 재판정 (서버 기준선 파일 · 실행일 기준 · 기준선 7일 이상 종목만):

| 실행일 | 변경 전 경보 | 변경 후 경보 | 차이 |
|---|---|---|---|
| 9/21 | 없음 | 없음 | 없음 |
| 9/22 | 없음 | 없음 | 없음 |
| 9/24 | 없음 | 없음 | 없음 |
| 9/25 | 없음 | 없음 | 없음 |
| 9/26 | 없음 | 없음 | 없음 |
| 9/27 | 없음 | 없음 | 없음 |
| 9/28 | 없음 | 없음 | 없음 |
| 9/29 | ENTX | ENTX · KOD | KOD 추가 (평균 0 → 14배) |
| 9/30 | IOVA | IOVA | 없음 (128배 → 32배 · 여전히 경보) |

(9/21~9/28 은 모든 종목의 기준선이 7일 미만이라 판정 대상 없음 · 9/23 은 UTC 날짜 결함으로 파일 없음)

## 규칙 기록 · 2026-10-02 실행부터 (WP93) · 레이더 점수 v3 · H6 소속 +3 제거

- 변경 전 (v2 · 2026-10-01 실행까지): 전문가 채널 (a)+(b) 원점수 = 13D 신규 건수 × 1.0 + H6 소속이면 +3
- 변경 후 (v3 · 2026-10-02 실행부터): 전문가 채널 (a)+(b) 원점수 = 13D 신규 건수 × 1.0 (H6 소속 가점 제거) · PubMed · Preprint · Form 4 채널 · z 정규화 · 4요소 가중치는 그대로
- 근거: H6 (테마 관심도 → 주가) 관문 2 폐기 확정 (`docs/plans/biotech/verification/H6/H6-gate2-request-20261001.md` · 1차 판정 1분기 CI −4.3% ~ +5.7% · 4분기 CI −19.3% ~ +15.8%)
- 영향 (로컬 입력 기준 · 2026-10-01 서버 런타임 복사본 + 로컬 `backend/data` 의 13D · H6 소속 · PubMed · Preprint · 가격 파일 · 같은 입력 v2 대 v3): 점수 80개 중 78개 변경 · 순위 52종목 이동 · 상위 30 ARTV 진입 · AVBP 탈락
- **정정 (2026-10-01 · 배포 후 확인)**: 서버에는 `h6_membership_*.csv` · `h3_events_*.csv` · `h57_pubmed_index_*.json` · `h58_preprint_index_*.json` · `h3_prices_merged_*.csv` 가 없음 (서버 daily.log 10/1 레이더 줄 "prices tickers: 0 · xbi 90d ret: 0.0000" · "pub_idx: 0 · pre_idx: 0"). 그래서 서버 점수에서는 H6 소속 +3 이 원래부터 0 이었고, v3 변경의 **서버 점수 영향은 0** 입니다. 위 78/80 · 52종목 · ARTV/AVBP 는 로컬 입력 기준 값입니다. 서버 전문가 채널 입력 부재는 별건 (점수 입력 변경이라 승인 필요).
- 코드: `backend/scripts/biotech_h46v3_radar.py` expert_channel_1_2() · SCORE_VERSION · 정의: `backend/data/h_radar_params.json` score_version · score_versions (v2 보존)
- 전향 평가: 11/15 첫 채점표는 10/1 까지 v2 · 10/2 이후 v3 판정을 나누어 적는다 · 재계산 = `python -m backend.scripts.biotech_h46v3_radar --score-version v2 --date YYYYMMDD` (산출 `radar_v1_3_<날짜>_scorev2.csv`)

## 규칙 기록 · 2026-10-01 (WP94) · 서버 레이더 점수 입력 0 상태 (v2-부분)

- 사실: 서버 레이더 점수는 2026-09-22 첫 실행 (`/root/toss-tradebot-mvp/var/biotech/logs/daily.log` 첫 줄 `=== 2026-09-21T22:00:01Z biotech daily start (server · KST 07:00) ===`) 부터 전문가 채널 입력 0 상태였습니다. 10회 실행 모두 "prices tickers: 0 · xbi 90d ret: 0.0000" · "pub_idx: 0 · pre_idx: 0".
- 없는 설계 입력 5개: `h6_membership_*.csv` · `h3_events_*.csv` · `h57_pubmed_index_*.json` · `h58_preprint_index_*.json` · `h3_prices_merged_*.csv` (git 에도 없음 · 로컬 `backend/data` 에만 있음).
- 그래서 서버 판정은 설계 v2 의 일부 (v2-부분) 입니다. 전문가 채널은 모든 종목 같은 값 · 미반영 채널은 중립이라 점수는 근접도 · 언급 · 위험 · 꼬리표로 정해졌습니다.
- 11/15 채점표: 서버 실제 판정 기준으로 하되 이 사실을 머리에 적습니다.
- 가시화 (WP94): 레이더가 입력을 못 찾으면 WARNING 1줄씩 · 텔레그램 warning 하루 1회 · 산출 CSV `inputs_missing` 열 · kpi.json · radar.json `inputs_missing` · 화면 순위표 머리 "점수 입력 부족: 전문가 채널 미반영(파일 N개 없음)".
- 확인: 2026-10-01 서버 런타임 복사본을 서버와 같은 조건 (5개 입력 없음) 으로 v3 실행 → 서버 실제 10/1 v2 산출과 80행 순서·점수 모두 같음 (v3 의 서버 영향 0 재확인).

## 규칙 기록 · 2026-10-01 (WP95) · 레이더 입력 복구 (v3-전체 준비)

- 설계 입력 목록: h6_membership 제외 (v3 은 쓰지 않음). 남은 입력 4개 = h3_events · h57_pubmed_index · h58_preprint_index · iex_daily_history.
- 13D (전문가 a): 주간 (화 06:00) `backend/scripts/biotech_radar_inputs_weekly.py 13d` · b98 과 같은 범위 = 활동가 등록부 55곳 (`docs/plans/biotech/data/h3_activist_cik_registry_v2.csv`) 의 신규 13D/13G (5년 창) + 펀드 55곳 Form 4 매수 (h65 캐시) · 등록부마다 submissions 1회 (55회) + 새 신고만 신고서 헤더 1회 (대상 회사 확인) · b98 산출을 씨앗으로 (`docs/plans/biotech/data/h3_seed_events_b98.csv`) 다시 묻지 않음 · 하루 SEC 상한에 닿으면 남은 헤더는 다음 주. **고친 점**: b98 은 "SC 13D/13G" 만 찾아 2024-12 양식 변경 ("SCHEDULE 13D/13G") 이후 기록이 없었음 → 두 이름 모두 셈. **쓰지 않은 방식**: 후보 회사 기준 submissions (2026-10-01 시험 994건 중 915건이 수동 13G · 잡음).
- PubMed · Preprint (전문가 c · d): 주간 (수 06:00) 같은 모듈 `nlm` · 올해·작년 2개 연도 · 검색식은 h57 · h58 그대로 · 캐시 (결과 0 포함 · 작년 값 다시 받지 않음).
- 가격 (미반영): mcap 일일 IEX 응답을 `<RUNTIME>/prices/iex_daily_history.csv` 에 누적 (100일 보관 · XBI 포함) · 90일 창을 못 덮은 종목은 하루 최대 50개 Tiingo 일봉 120일 백필. 레이더 90일 수익률 계산식은 그대로이고 입력 경로만 바뀜. XBI 가 90일 창 안에 55거래일 이상일 때 "갖춰짐".
- 지시 조정: "90거래일 미만이면 120일 일봉" 은 120 달력일 ≈ 83 거래일이라 끝나지 않으므로, 레이더 창 (90 달력일) 을 덮는지로 판정 (창 시작 이전 기록이 있고 창 안 55거래일 이상).
- v3-전체 시작일: inputs_missing 이 빈 첫 실행일을 `<RUNTIME>/radar_v3_full_start.json` 에 한 번 기록 (텔레그램 info 1회).

## 규칙 기록 · 2026-10-01 (WP96) · 13D 검정 입력 누락 확정

- H3 검정 (`docs/plans/biotech/verification/H3/H3-report-20260912.md` · `H3-F4-report-v3-20260914.md`) 의 13D/13G 입력은 SEC 양식 이름 변경 (2024-12 · "SC 13D/13G" → "SCHEDULE 13D/13G") 때문에 2024-12-06 이후 기록이 누락된 상태로 확정됨.
- 11/15 까지 재실행 금지 · 재판정 시 이 누락을 고려 · 검정 산출물 무변경.

## 한국어 v4 · 2026-10-01 (WP97-2 · 화면 노출 용어 검수 반영) · 134건 · 무시 2건 추가

- 근거: 서버 화면 (A 카드 63장 + 순위표 30행) 에 한국어 없이 보이던 질환 용어 136개 제안 (`docs/plans/biotech/verification/dictionaries/ko_terms_visible_proposed_v3.csv`) · Fable 검수 원본 `docs/plans/biotech/verification/dictionaries/ko_terms_visible_proposed_v3_reviewed.csv`
- 반영 규칙: "채택" → proposed_ko · "제외" → 넣지 않음 · 그 밖 → 검수 값 그대로 (채택 112 · 수정 22 · 제외 2)
- `docs/plans/biotech/data/ko_terms.csv` 134건 추가 (226 → 360행) · 예: ALS → 루게릭병(ALS) · Multiple Sclerosis → 다발성 경화증
- `docs/plans/biotech/data/condition_categories.csv` "무시" 2건 추가 (648 → 650행): Lesion Skin · Neoplasms by Histologic Type (일반어)
- 화면 분류 보완: '무시' 용어는 자동 분류와 "기타 (원문)" 원문 자리에도 쓰지 않음 (`backend/api/routes/biotech.py` `_trial_display`)
- 앞으로 제안 파일의 category 열은 카드 분류가 아니라 용어의 사전 분류를 적음 (v3 예: "Central Nervous System Diseases · 암" 은 카드 분류였음)

## 규칙 기록 · 2026-10-02 (WP98) · 레딧 입력 부분 차단 (HTTP 429)

- 사실 (`/root/toss-tradebot-mvp/var/biotech/logs/daily.log` · 2026-09-22 ~ 2026-10-02 · 11일): 매일 레딧 RSS 4곳 요청 · r/biotechplays 만 200 (글 25개) · r/pennystocks · r/wallstreetbets · r/stocks 는 매일 HTTP 429 → 11일 동안 요청 44 · 429 33 · 성공 11 · 받은 글 275 (하루 25 · 같은 새 글 목록이 겹칠 수 있음).
- 레딧 매치가 0 이 아니었던 날: 11일 모두 (예: ENTX 2~4 · CRVO 1 · 10/1~2 IVVD 1 · KOD 1) · 매치는 r/biotechplays 글에서만 나옴.
- 요청 코드: `backend/scripts/biotech_h48v3_confirm.py` · User-Agent = SEC 헤더 상수 (`SEC_UA` · 67~72행) · 간격 3.5초 (139행) · 재시도 없음 (141~143행).
- 2026-10-02 로컬 시험 (고유 User-Agent "TossTradebot BiotechRadar/1.0 (contact: suauncle@gmail.com)" · 간격 3초 · 3건): pennystocks 200 (글 25) · wallstreetbets 429 · stocks 429 · 첫 응답부터 `x-ratelimit-remaining: 0.0` → User-Agent 만으로는 해결되지 않음 · 코드 변경 보류 (WP98 지시: 여전히 429 면 멈추고 보고).
- 소문 전향 평가 (11/15): 머리에 "레딧 입력은 2026-09-22 첫 실행부터 4곳 중 3곳 HTTP 429 · r/biotechplays 한 곳만 수집" 을 적는다.

## 사전 v5 · 2026-10-02 (WP99) · 자동 분류 검수 1,006건 (채택 924 · 수정 82)

- 근거: 서버 자동 분류 제안 `auto_category_proposals_20261002.csv` (1,006행) · Fable 검수 원본 `docs/plans/biotech/verification/dictionaries/auto_category_proposals_20261002_reviewed.csv`
- 반영: "채택" → auto_category · 그 밖 → 검수 값 (수정 82 · 그중 "무시" 24) · `docs/plans/biotech/data/condition_categories.csv` 650 → 1,656행 · source "auto-reviewed" · basis "auto-reviewed v5"
- 수동 사전이 자동 분류보다 먼저라 서버 `auto_categories.json` 의 같은 용어는 쓰이지 않음 · 다음 주간 실행부터는 수동 사전 용어라 자동 분류 대상에서 빠짐

## 자동 분류 규칙 · 2026-10-02 (WP99) · 순서 = 수동 사전 변형 → 얕은 트리 무시 → MeSH 트리 → 어간

- 수동 사전 변형: 용어를 정규화 (소문자 · 괄호 안 제거 · 구두점 제거) 한 뒤 수동 사전 용어 (5자 이상 · '무시' 제외) 가 단어 단위 부분 문자열이면 그 분류 · 가장 긴 일치 (예: Pediatric Lupus Nephritis → 면역·염증)
- 얕은 트리: 트리 번호가 모두 점 1개 이하 (예: C04 · C14 · F03 · C16.320) 면 "무시" · **지시 문구는 "점 2개 이하" 였으나 검수 1,006건 대조에서 점 2개 = 90.6% · 점 1개 = 93.8% 라 점 1개로 반영 (지시 예시는 모두 점 1개 이하)**
- 어간: 단어 시작에서만 일치 (retin 이 Transthyretin 에 걸리지 않음) · **암 어간만 단어 안에서도 일치 (Adenocarcinoma · Leiomyosarcoma 를 놓치지 않게 · 경계를 걸면 일치율 −1.7%p)**
- 1단계 예외 추가: C19.874.283 → 비만·대사 · C11.675.349.500.500 → 안과
- 어간 사전 v3: 비만·대사에 steatohepatitis 명시 (NASH · MASH · steatohepat 는 v2 부터 있음)
- NLM 요청 간격 0.34초 (초당 3회 이하) · 이미 같은 값
- 검수 대조 (서버 mesh_cache 1,012 · 수동 사전 v4 650행 기준): 이전 규칙 924/1,006 (91.8%) → 새 규칙 944/1,006 (93.8%) · 목표 97% 미달 · 남은 62건은 대부분 검수 판단 차이 (예: Rheumatoid Arthritis 근골격 ↔ 면역·염증)
- API: 자동 분류의 "무시" 도 화면에 쓰지 않음

## 규칙 기록 · 2026-10-04 (WP100) · 레딧 경보 조건

- 변경 전 (WP78 · WP86): 레딧 RSS 제목 매치 ≥ 3건이면 경보 · 매치는 받은 피드 전체 글 (작성 시각 무관)
- 변경 후: 레딧 매치 = 작성 시각 (Atom `<updated>`) 24시간 안의 글만 · 경보 = 24시간 매치 ≥ 3건 AND 레딧 7일 평균의 2배 이상 (평균 하한 1건) · 레딧 기준선 (일별 `reddit_24h` 기록) 7일 미만이면 레딧 조건은 "수집 중" (판정 제외) · apewisdom 배수 조건은 그대로
- 근거: 2026-10-03 · 10-04 ENTX 경보 · 레딧 매치 10건 · apewisdom 0 · 저장된 매치 5건의 작성일 9/18 · 8/31 · 8/18 · 8/10 · 8/04 (biotechplays · 매치는 최신순이라 나머지 5건은 더 오래됨) → 24시간 안 0건 · r/biotechplays 수집이 복구된 10/3 부터 오래된 글 매치로 매일 경보
- 일별 기록: 기준선 파일 (`<RUNTIME>/st_baseline/<종목>_<날짜>.json`) 에 `reddit_24h` 추가 · WP100 이전 `reddit_matches` 는 시간 한정이 없어 평균에 쓰지 않음 → 2026-10-05 실행부터 쌓아 앞선 기록 7일이 차는 2026-10-12 실행부터 레딧 조건 판정 (그 전에는 레딧 3건 이상이어도 "수집 중")
- 단계 판정 (frenzy 의 레딧 ≥5) 도 24시간 매치를 씀 · 화면 경보 기준 문구 · 브리핑 (b) 줄 ("레딧 24시간 매치 N건 · 평소 하루 X건") 맞춤
- 정의: `backend/data/h_radar_params.json` alerts_definition_wp100 (wp86 에 superseded_by)
