# H6 검증 설계서 · point-in-time 분야 순위 (v2 · WP10 · 2026-09-08 · 사후 조정 금지)

**변경 이력**:
- v1 (WP5 · 2026-09-08) · 7 테마 + SF 감시 목록 = Selection Fatigue · 대조군을 SF 하위로 배치
- **v2 (WP10 · 2026-09-08)** · SF = **공상과학 (Sci-Fi)** 감시 목록으로 재정의 · "Selection Fatigue" 용어 폐기 · 대조군 별개 절 분리 · 주 테마 **6종** 명시 · 키워드 서로소 · **매핑 = CT.gov 스폰서 point-in-time** (수동 CSV 폐기) · **검증 = 분기 리밸런싱** (이벤트 창 방식 폐기)

**연계**: `README.md` §2 H6 · `H7-design.md` (H6 상위 3분위 = H7 진입 필터)

**상태**: 초안 · Fable 검수 대기 · 실행 없음

---

## 1. H6 정의 (v2 · README §2 승계)

이벤트일 **분기 종료 시점에 알려진** 바이오 서브분야 (테마) 순위 만 사용. **사후 관측 순위 사용 금지** (look-ahead bias 배제).

## 2. 테마 사전 v1 (사전 커밋 · 6종 · 사후 추가 금지)

**주 테마 (6종 · 키워드 서로소 · 사전 커밋)**:

| # | 테마 | 대표 키워드 (사전 커밋 · 서로소) |
|---|---|---|
| 1 | **비만·GLP-1** | obesity · GLP-1 · semaglutide · tirzepatide · liraglutide · Wegovy · Ozempic · Mounjaro |
| 2 | **탈모** | androgenetic alopecia · hair loss · finasteride · minoxidil · dutasteride · JAK inhibitor for alopecia |
| 3 | **장수·회춘** | longevity · rejuvenation · senolytics · epigenetic reprogramming · Yamanaka factor · anti-aging |
| 4 | **식사대용·대사** | meal replacement · metabolic health · GLP-1 combination therapy · caloric restriction · nutraceuticals |
| 5 | **동면·저체온** | hibernation · torpor · therapeutic hypothermia · TrkB agonist for hypothermia · induced torpor |
| 6 | **신경·기억** | memory enhancement · cognitive enhancer · nootropic · long-term potentiation · engram · memory reconsolidation |

**키워드 서로소 규칙 (v2 · 사전 커밋)**:
- 신경·기억 (6번) 에서 **alzheimer · dementia 제거** (아밀로이드 대조군 전용 · §4)
- 비만·GLP-1 (1번) 과 식사대용·대사 (4번) 은 GLP-1 겹치지 않도록: **"GLP-1 combination"** 만 4번 · 단일 GLP-1 는 1번
- 각 테마 키워드는 다른 테마 키워드 리스트와 교집합 없음

**소급 규칙 (v2 · 정정)**:
- **v1 사전 (본 문서 6 테마)** 은 2015Q1 부터 적용 (사전 정의된 것으로 간주)
- 추후 추가 테마만 **추가일 이후 시점부터** 유효 · 소급 사용 금지

## 3. 순위 산정 (v2 · point-in-time · 사전 커밋)

**분기별 신호량 산정**:
- 각 분기 종료 시점 = 랭킹 확정 시각 (t=분기말)
- **PubMed 게재 수** (분기 · 테마 키워드 OR 검색 · `datetype=pdat`) + **CT.gov 신규 등록 수** (분기 · `studyFirstPostDate` 범위) 로 신호량 산출
- **가중치 (사전 커밋)**: PubMed 60% · CT.gov 40% (분기별 z-점수 표준화 후 합산)

**티커 매핑 (v2 · CT.gov 스폰서 point-in-time · 사전 커밋 · 수동 CSV 폐기)**:
- 각 분기 t 에 각 테마 키워드 매치 CT.gov 임상의 `leadSponsor` 회사명 목록을 소속 회사군으로 사용
- 회사명 → 티커 매핑: (a) `biotech_ticker_set_{sha}.csv` (b) SEC EDGAR submissions 회사명 대조 (c) 매핑 실패 = 표본 제외
- 스폰서 명 정규화 (Inc/Corp/Ltd 등 제거) 후 매칭
- **사후 수동 CSV 폐기**: 룰만 사전 · 사후 종목 인입 금지 (H2 규약 승계)

**3분위 정렬 (v2)**:
- 각 분기 t 종료 시점: 각 티커의 소속 테마별 신호량 (분기 t-1 종료 시점 랭킹 기준) → 상 33% · 중 34% · 하 33%
- 다중 테마 매치 시 **최고 순위 테마** 로 배정

**부재 대응**:
- 새 테마는 정의일 (사전 커밋 문서 갱신일) 이후 t 부터만 유효 · 소급 사용 금지

## 4. 대조군 (v2 · 별개 절 · SF 아님)

**대조군 (2종 · 알파 검증 · 순위 후 별도 판정)**:

| # | 테마 | 대표 키워드 | 대조군 사유 |
|---|---|---|---|
| **C1** | **NASH 초기** | NASH · nonalcoholic steatohepatitis · MASH · resmetirom · obeticholic acid | 2010년대 활발한 후보 다수 · 2020년대 후기 실패 반복 (통시적 참조) |
| **C2** | **아밀로이드** | amyloid beta · Aβ · aducanumab · lecanemab · gantenerumab · alzheimer amyloid · dementia amyloid | 대규모 실패 반복 · aducanumab FDA 논란 · dementia/alzheimer 는 여기 전용 |

**대조군 사용 규칙 (v2 · 사전 커밋)**:
- 대조군은 **주 테마 3분위 정렬에 포함하지 않음** (별개 절로 병행 관측)
- 대조군의 상위 3분위 진입 여부는 사후 정보 정합성 검증에만 사용 (알파 판정 무관)
- SF (§5) 와 별도 · SF 는 "상장 순수주 부재" 특징 · 대조군은 "상장 종목 있음 · 반복 실패" 특징

## 5. SF (v2 · 공상과학 감시 목록 · 완전 재정의 · Selection Fatigue 용어 폐기)

**정의 (v2)**: **공상과학 (Science Fiction) 감시 목록** = 대중 관심은 있으나 **상장 순수주 부재** · 알파 주장 없음 · 임상 단계·규제 승인·대형사 진입 등 전환 신호가 발생하면 정식 테마로 편입 후보.

**초기 등재 SF 항목 (사전 커밋)**:

| # | 항목 | SF 사유 | 정식 편입 전환 신호 |
|---|---|---|---|
| SF1 | **영생·수명연장 극단** | 상장 순수주 부재 (Altos Labs 등 비상장) · 대중 관심 스타트업 위주 | (a) 상장 IPO · (b) 임상 2상 이상 진입 · (c) 대형 파마 인수/파트너십 |
| SF2 | **기억이식·엔그램 조작** | 마우스 preclinical 위주 · 인간 IND 부재 | (a) IND 승인 · (b) 임상 1상 진입 |
| SF3 | **동면 유도 (induced torpor)** | 우주 항해·중환자 이송 컨셉 · 임상 극초기 | (a) 임상 1상 진입 · (b) 다국적 대형사 매입 계약 |
| SF4 | **뇌-컴퓨터 인터페이스 (BCI)** | Neuralink 비상장 · 상장주는 지원 인프라 (반도체 등) 성격 | (a) BCI 순수주 상장 · (b) FDA De Novo 승인 |

**SF 규칙 (v2 · 사전 커밋)**:
- SF 항목은 주 6 테마 사전 밖 · 순위 산정에 참여 안 함
- **전환 신호 3종 (임상 단계 상승 / 등록 급증 / 대형사 진입)** 중 1건 이상 발생하면 정식 테마 승격 후보 · 별도 세션 승인 후 사전에 추가
- 승격 후에도 소급 순위 사용 금지 (승격일 이후 시점만 유효)
- SF 항목의 **알파 주장 자체가 없음** · H6 판정에 영향 없음

## 6. 검증 (v2 · 분기 리밸런싱 · 이벤트 창 방식 폐기 · 사전 커밋)

**포트폴리오 리밸런싱 기반 판정**:
- 분기 t 종료 시점: **상위 3분위 소속 티커 바스켓** 을 다음 1분기 (t+1) · 4분기 (t+1~t+4) 균등 보유
- **하위 3분위 소속 티커 바스켓** 을 동일 창 병행 (상-하 비교)
- 각 분기 리밸런싱 시 이전 편입 티커 청산 + 신규 편입 종가 매수 (D+1 종가)
- 성과 = 로그 수익률 (log return) 합산 · vs **XBI** 로그 초과수익

**bootstrap**:
- **분기 단위 리샘플링** (블록 부트스트랩) · seed 42 · 10,000회
- 상-하 초과수익 차이 95% CI · CI 하한 > 0 → 알파 통과

**알파 임계 (사전 커밋)**:
- 1분기 창 (t+1 만): 상-하 로그 초과수익 차이 CI 하한 > 0
- 4분기 창 (t+1~t+4): 상-하 로그 초과수익 차이 CI 하한 > 0
- 두 창 모두 통과 시 알파 확인 (한 창만 통과 시 부분 지지)

**폐기 조건**:
- 두 창 모두 CI 하한 ≤ 0 → 폐기
- 순위 사후 조정 (분기말 이전 데이터 사용 등 look-ahead) 발견 → 폐기

## 7. 예상 표본 (v2 · 실측 확장)

**실측 범위 (v2)**:
- 6 주 테마 (WP5 실측 2 테마 완료: obesity_glp1 · hair_loss)
- WP10 확장: 나머지 4 테마 (장수·회춘 · 식사대용·대사 · 동면·저체온 · 신경·기억) + 대조군 2 (NASH · 아밀로이드) = 6 세트

**총 실측 = 8 세트 × 48 분기 = 384 세트 × PubMed+CT.gov 2회 호출 = 768 호출**

**산출**:
- `backend/data/h6_theme_probe_v2_{sha}.csv` (분기별 PubMed·CT.gov 카운트)

## 8. 사전 커밋 항목 요약 (v2 · **12** 항)

1. 주 테마 6종 (비만·GLP-1 / 탈모 / 장수·회춘 / 식사대용·대사 / 동면·저체온 / 신경·기억)
2. 대조군 2종 (NASH 초기 · 아밀로이드) · 별개 절 · 순위 산정 미참여
3. SF (공상과학) 감시 목록 · 상장 순수주 부재 · 알파 주장 없음
4. 키워드 서로소 (신경·기억에서 alzheimer·dementia 제거)
5. 소급 규칙 = v1 사전은 2015Q1 부터 · 추가 테마는 추가일 이후
6. 신호량 = PubMed 60% + CT.gov 40% (z-점수)
7. 티커 매핑 = CT.gov 스폰서 point-in-time (수동 CSV 폐기)
8. 상 33% · 중 34% · 하 33% 3분위
9. 검증 = 분기 리밸런싱 (1분기 창 + 4분기 창) · 상-하 로그 수익 차이
10. 블록 부트스트랩 (분기 단위) · seed 42 · 10,000회
11. 알파 임계 = 두 창 CI 하한 > 0 (한 창만 통과 = 부분 지지)
12. SF 전환 신호 3종 발생 시 별도 세션 후 정식 테마 추가

## 9. 알려진 편향·리스크

- **키워드 확장 편향**: 사후 확장 시 카운트 인플레이션 · 사전 커밋 준수
- **PubMed 게재 지연**: 실제 연구 → 게재 6~18개월 지연 · 순위가 실 시점 뒤처짐 · point-in-time 규칙 그대로 유지
- **CT.gov 등록 편향**: 국가별 등록 관행 차이 (미국 편중)
- **스폰서 매핑 실패**: CT.gov leadSponsor 표기 불일치 (Inc/Corp/Ltd 정규화 후에도 잔존) · 매핑 실패 표본 제외 편향 명시

## 10. 실행 순서 (승인 후)

1. Fable 초안 검수 (사전 커밋 12항)
2. WP10 확장 실측 (4 주 테마 + 2 대조군 · 384 세트)
3. CT.gov 스폰서 point-in-time 매핑기 신설 (`biotech_h6_sponsor_map.py` · 별건)
4. 분기 리밸런싱 백테스트 엔진 (`biotech_h6_backtest.py` · 별건)
5. 리포트 + Fable 반박 응답

---

**부속**:
- `backend/data/h6_theme_probe_v2_{sha}.csv` (6 테마 + 2 대조군 실측)
- `backend/scripts/biotech_h6_theme_probe.py` (v2 실측 스크립트 · 확장)
- `docs/plans/biotech/README.md` §2 H6 (v2 반영 필요)
