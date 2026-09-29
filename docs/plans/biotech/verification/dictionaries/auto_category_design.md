# 질환 분류 자동화 설계서 (WP80-2 · 2026-09-29 · 구현은 별도 승인)

## 1. 목적

AACT 매칭이 넓어지면서 사전에 없는 질환명이 계속 들어옵니다. 사전에 없는 용어는 지금 화면에서 "기타 (원문)" 으로 보입니다. 이 설계는 사람이 검수한 수동 사전을 그대로 두고, 사전에 없는 용어에만 자동 분류를 붙이는 방법을 정합니다.

## 2. 원칙 (사용자 지시 · 고정)

1. 자동 분류는 `docs/plans/biotech/data/condition_categories.csv` 에 쓰지 않는다. 이 파일은 사람이 검수한 수동 사전만 담는다.
2. 자동 결과는 런타임 폴더 `/root/toss-tradebot-mvp/var/biotech/` 의 별도 파일에 근거 (`basis` = `auto-mesh` 또는 `auto-stem`) 와 함께 저장한다.
3. 화면에는 자동 분류 뒤에 "(자동)" 을 붙인다. 예: "호흡기(자동) · …"
4. 주간 AACT 잡 끝에 자동 분류된 용어를 검수 제안 파일로 내보낸다. 검수를 통과한 용어만 수동 사전으로 옮긴다.
5. NLM (미국 국립의학도서관) MeSH 조회 결과는 런타임 폴더에 캐시하고, 한 번 조회한 용어는 다시 요청하지 않는다.
6. 적용 순서: 수동 사전 > MeSH 트리 > 키워드 어간 > 기타. 자동 규칙은 수동 사전을 절대 덮어쓰지 않는다.

## 3. 파일 (런타임 · git 밖)

| 파일 | 내용 |
|---|---|
| `/root/toss-tradebot-mvp/var/biotech/mesh_cache.json` | 용어 → {descriptor · tree_numbers · 조회 방법 (descriptor / entry term) · 조회일} · 재요청 없음 |
| `/root/toss-tradebot-mvp/var/biotech/auto_categories.json` | 용어 → {category · basis (auto-mesh / auto-stem) · 근거 (tree_number 또는 어간) · 생성일} |
| `/root/toss-tradebot-mvp/var/biotech/auto_category_proposals_<YYYYMMDD>.csv` | 검수 제안 · term · auto_category · basis · evidence · n_trials · reviewer_decision (빈칸) |

## 4. 처리 흐름

1. 주간 AACT 잡 (`backend/scripts/biotech_h69_aact_weekly.py`) 이 스냅샷을 만든 뒤, 스냅샷의 질환 용어 가운데 수동 사전에 없는 것만 고른다.
2. 캐시에 없는 용어만 NLM 에 조회한다. 먼저 기술어 (descriptor) 이름 완전 일치, 없으면 정규화 (소문자 · 괄호 제거 · 공백 정리) 후 동의어 (entry term) 조회 → SPARQL 로 기술어 tree_number 조회.
3. 트리 규칙 (5절) 으로 분류한다. 결과가 없으면 키워드 어간 (6절) 을 적용한다. 그래도 없으면 "기타 (원문)" 으로 둔다.
4. `auto_categories.json` 과 검수 제안 CSV 를 쓴다.
5. API (`backend/api/routes/biotech.py` 의 카드 상세) 는 수동 사전을 먼저 보고, 없을 때만 `auto_categories.json` 을 읽어 `category_auto=true` 로 내보낸다. 화면은 "(자동)" 을 붙인다.

요청 규칙: NLM 요청은 초당 3회 이하 · 선언 User-Agent 상수 · 403·429 는 즉시 중단 (그 주는 캐시와 어간만 사용).

## 5. MeSH 트리 규칙 (검수 대상 · 확정 전)

2026-09-29 조사 결과 (용어 1,622개 · 매칭 71종목 · 수동 사전과 겹치는 326개 기준):

| 규칙 판 | 일치율 |
|---|---|
| 최초 대응표 (C16 → C04 → 표 순서) | 85.0% (277/326) |
| WP80-2 예외·우선순위 (사용자 지시) | 80.1% (261/326) |
| 참고안 (C04 → C01 → C10 을 앞당김 · 나머지는 WP80-2 와 같음) | 84.0% (274/326) |

WP80-2 규칙에서 일치율이 내려간 주된 이유는 세 가지입니다.

- 감염 (C01) 이 장기 트리보다 뒤에 있어, HIV · 간염 · 코로나19 가 신장 · 소화기 · 호흡기로 갔습니다 (15건).
- 신경 (C10) 이 대사 (C18) · 면역 (C20) 보다 뒤에 있어, 다발성 경화증 · 루게릭병 등이 다른 분류로 갔습니다.
- C16 표지어 목록에 없는 유전 질환 (겸상적혈구 · 헌팅턴 · 레트 등) 이 장기 분류로 갔습니다.

순서와 표지어 목록은 검수 뒤 확정합니다. 불일치 전체 목록은 WP80-2 보고에 있습니다.

## 6. 키워드 어간 규칙 (초안 · 검수 후 확정)

적용 순서: 암 어간 → 건강인 어간 → 나머지 (표 순서).

| 분류 | 어간 (정규식 · 대소문자 무시) |
|---|---|
| 암 | cancer · carcinom · tumo(u)r · neoplas · malignan · lymphom · leukemi/leukaemi · myelom · sarcom · melanom · gliom · glioblastom · blastoma · metasta · oncolog · dysplasi · myelodysplas · myelofibros · NSCLC · SCLC · HCC · AML · CLL · MDS |
| 건강인·약동학 | healthy · volunteer · pharmacokinetic · bioavailab · bioequival · drug-drug · drug interaction · food effect · hepatic impairment · renal impairment · PK · DDI |
| 감염 | infect · viral · virus · HIV · hepatitis · covid · sars-cov · influenza · bacteri · fungal · tubercul · sepsis · pneumoni · RSV · CMV · herpes |
| 비만·대사 | obes · overweight · diabet · metabolic · dyslipid · cholesterol · hyperlipid · NASH · MASH · fatty liver · steatohepat · weight · hypoglyc · thyroid · parathyroid · hyperuric |
| 신경·정신 | alzheimer · parkinson · dementia · depress · schizo · epilep · seizure · multiple sclerosis · migraine · psych · autism · ALS · amyotrophic · neuropath · huntington · bipolar · anxiety · insomnia · narcolep · ataxia · agitation |
| 안과 | retin · macula · ocular · eye · glaucom · uveit · cornea · vision · keratit · conjunctiv · blind |
| 청각·이비인후 | hearing · deaf · tinnitus · otitis · ear · cochlea · sinusit · rhinit |
| 미용 | wrinkle · fine line · glabellar · cellulite · skin rough · pigmentation |
| 피부 | dermat · psoria · eczem · acne · skin · alopeci · vitiligo · urticari · hidradenit · pruritus · ichthyos · epidermolys |
| 심혈관 | heart · cardi · hypertens · atrial · coronary · myocard · arrhythm · angina · thromb · stroke · vascular · aneurysm |
| 호흡기 | asthma · COPD · pulmonar · lung · cough · respirat · bronch · IPF · emphysem |
| 신장 | kidney · renal · nephr · dialys · glomerul · urinary · bladder · hyperphosphat |
| 혈액 | anemi/anaemi · hemophil · thalass · sickle · thrombocytop · neutropen · hemoglobin · bleeding · coagul |
| 근골격 | arthrit · osteo · bone · muscle · myopath · sarcopen · fracture · tendon · gout · spinal muscular |
| 면역·염증 | lupus · autoimmun · inflammat · sjogren · vasculit · myositis · scleroderma · rheumat · immunodefic · angioedema · allerg |
| 소화기 | crohn · colitis · bowel · gastr · liver · hepat · pancrea · constipat · IBS · esophag · celiac · cirrhos · biliary · cholang |
| 통증 | pain · neuralgi · analges |

조사 결과: 자유 기재 질환명 1,319개 중 1,087개 (82.4%) 가 어간에 걸렸습니다. 수동 사전에도 있는 258개로 확인한 일치율은 93.8% 입니다.

## 7. 테스트 계획 (구현 시)

- 수동 사전 용어는 자동 결과가 있어도 수동 값이 나온다.
- MeSH 캐시에 있는 용어는 NLM 요청이 0회다.
- 403·429 응답이면 즉시 중단하고 캐시·어간만 쓴다.
- 트리 규칙 표의 각 예외 (C17.300 · C15.378.190.625/.636 · F01 · M01.774 · C16 표지어) 가 기대 분류를 낸다.
- 화면 문장에 "(자동)" 이 붙는다.

## 8. 남은 결정 (검수)

1. 트리 우선순위 (WP80-2 안 · 참고안 · 다른 안 중 선택)
2. C16 표지어 목록 보완 여부 (Syndrome · -emia 등 이름 표지로는 잡히지 않는 유전 질환)
3. 어간 목록 확정
4. 동의어 조회 결과를 캐시에 포함할지 · 조사 결과 자유 기재 질환명 1,319개의 트리 커버율 = 기술어 이름 일치만 14.8% (195) → 동의어 조회를 더하면 34.1% (450) · 트리 (WP80-2 규칙) 와 어간을 함께 쓰면 88.5% (1,167) 가 분류 가능
