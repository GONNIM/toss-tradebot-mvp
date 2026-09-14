# H1a 검증 설계서 초안 (WP2 · 2026-09-08 · 사후 조정 금지)

**연계**: `README.md` §2 H1a 정의 · §2-0 판정식 · §3-5 백테스트 사양 v1

**상태**: 초안 · Fable 검수 대기 · 실행 없음

---

## 1. H1a 정의 (README §2 승계 · 사전 커밋)

**날짜가 사전 공개된 이벤트만 포함**. FDA PDUFA date · **사전 공지된 ADCOM meeting date**. 사전 공개 캘린더 부재 이벤트(accelerated review 등)는 원천 배제.

## 2. 이벤트 정의 (사전 커밋)

**이벤트 = FDA Advisory Committee 회의일 (D-day)**

- 수집 소스: **Federal Register API** `federalregister.gov/api/v1/documents.json`
  - `conditions[term]=Advisory Committee`
  - `conditions[agencies][]=food-and-drug-administration`
- **D-day = 회의일 (meeting_date)** · 공고일 (publication_date) 아님
- **공고일 < 회의일** 조건 (사전 공지 검증 · 사후 공고 배제)

## 3. 창·진입·청산·benchmark·비용 (WP9 v2 · 사후 조정 금지)

- **검정 창**: **D-30 ~ D-1** (사전 30일 알파 · 사후 공지 이벤트 배제 근거 = 공고일 < 회의일)
- **진입 (WP9 v2 정정)**: **max(공고일+1, D-30) 종가 (adj_close)** · 사전 공지 정보가 실제 시장에 반영 가능한 최초 거래일부터 매수 · 미래 참조 배제 · 공고→회의 시차 짧은 이벤트는 자동으로 창 단축
- **청산 (WP9 v2 정정)**: **D-1 종가 (adj_close)** · 회의 당일(D-day) 정보 도달 이전 (뉴스에 팔기 원칙 · H8 검정 3 지지 방향)
- **이벤트 적격 (WP9 v2 · 사전 커밋)**: **공고일+1 > D-5 이벤트 제외** · 사전 30일 알파 검증에 6영업일 미만은 표본 왜곡 · `excluded["short_lead"]` 카운트만
- **D+1 ~ D+30 병기**: H8 검정 3 (뉴스에 팔기 후반부) 용도로만 산출 · H1a 알파 판정에는 사용하지 않음
- **benchmark**: **XBI** (참고 IWM)
- **net = 왕복 1.0%** · 민감도 0.5/2.0/5.0% 병기

## 4. 알파 임계 (README §2 H1a 승계 · 사전 커밋 · 사후 조정 금지)

- **net excess ≥ +2%** · **히트율 ≥ 30%** · **bootstrap 95% CI 하한 > 0**
- **폐기 조건**: bootstrap 95% CI 하한 ≤ 0 OR 히트율 < 20%

## 5. 사전 커밋 항목 요약 (총 **10** 항 · WP9 v2)

1. 이벤트 = FDA AdCom 회의일 · 공고일 아님
2. 공고일 < 회의일 (사전 공지 검증)
3. 소스 = Federal Register API (무인증)
4. 검정 창 D-30~D-1 (사전 30일 알파)
5. **진입 = max(공고일+1, D-30) 종가 adj_close** (WP9 v2)
6. **청산 = D-1 종가 adj_close** (뉴스 전 청산 · WP9 v2)
7. **공고일+1 > D-5 이벤트 제외** (short_lead · WP9 v2)
8. D+1~D+30 = H8 검정 3 용도만 병기
9. benchmark XBI (참고 IWM) · 비용 왕복 1.0% · 민감도 0.5/2.0/5.0%
10. 알파 임계 net ≥ +2% · hit ≥ 30% · CI 하한 > 0 · 사후 조정 금지

## 6. 예상 표본 (WP2 실측 결과 · 2026-09-08)

**Federal Register 실측 (`git_sha=add7af7`)**:

| 지표 | 값 | 비율 |
|---|---|---|
| 전체 공고 수 | **457** | 100% |
| 회의일 파싱 성공 (abstract) | **21** | 4.6% |
| 위원회명 파싱 성공 | 191 | 42% |
| 신청사 파싱 성공 (abstract) | **7** | 1.5% |
| 회사명→티커 매핑 성공 | **0** | 0% (신청사 7건 중) |
| 공고→회의 시차 중앙값 | **41일** | — |
| 공고→회의 시차 min/max | 13 / 333일 | — |

**해석**:
- abstract 만으로 **신청사·약물명 추출 실질 불가** (1.5%). AdCom 공고는 대부분 회의 절차·의제 요약이며 신청사 명시가 드묾
- 회의일 파싱도 abstract 에 "The meeting will be held on YYYY" 형식이 드물어 4.6% 로 저조
- 시차 중앙값 41일 = **창 D-30~D-1 확보 가능** (사전 공지 여유 충분)

**후속 필수 (별건 · 표본 확보 조건)**:
- **full_text_url 다운로드 + DATES/AGENDA 절 파싱** · 공식 HTML 본문에는 `DATES:` 절과 `Agenda:` 절이 표준 포함되며 여기서 회의일·신청사·약물명 추출
- 파싱 대상 문서 457건 각각 1~50KB HTML · Federal Register 서버 부하 관용
- 예상 개선: 회의일 파싱 ≥90% · 신청사 파싱 ≥50% (다수 공고에 명시)

## 7. 알려진 편향·리스크

- **abstract 파싱 하한**: 위 실측대로 abstract 만으로 신청사 추출 1.5% · full_text 파싱이 알파 검증의 전제
- **회의 취소·연기**: Federal Register 공고 후 취소되는 경우 → `type=Notice` 재공고 여부 확인 필요
- **다중 신청사 회의**: 단일 회의에서 복수 신청사 심의 시 이벤트 중복 계상 방지 규칙 필요 (이벤트당 primary sponsor 1개)
- **회사명↔티커 매핑 정밀도**: `biotech_ticker_set_add7af7.csv` (304 티커) 범위 밖 신청사 (Big Pharma 대형주 등) 는 표본 제외 · 편향 방향 명시 필요

## 8. 실행 순서 (승인 후)

1. Fable 초안 검수 (사전 커밋 8항)
2. full_text_url 다운로드기 신설 (`biotech_h1a_fulltext.py` · 별건 · SEC 무관)
3. DATES/AGENDA 절 파싱 규칙 확정 (fixture 테스트 5건)
4. `h1a_events_{sha}.csv` v2 재산출 (회의일·신청사·약물명 추출률 개선)
5. 이벤트 적격 필터 (공고일 < 회의일 · 매핑 성공만 표본 편입)
6. 백테스트 (`biotech_h3_backtest.py` 재사용 여부 판단 · 창 D-30~D-1 특화)
7. 리포트 + Fable 반박 응답

---

**부속**:
- `backend/data/h1a_events_add7af7.csv` (457 rows · v1 abstract 파싱)
- `backend/scripts/biotech_h1a_collect.py` (수집기 v1)
- `docs/plans/biotech/README.md` §2 H1a
- `docs/plans/biotech/SOURCES.md` Federal Register API
