# 01. Activist Universe — 감시 대상 리스트

**목표**: Tier 1 (실행력 검증된 유명 activist) 우선 하드코딩 → 사용자가 UI 편집기로 추가·삭제·비활성화.

**CIK 확보 방식**: SEC EDGAR full-text search (`efts.sec.gov/LATEST/search-index?q=<name>&forms=SC+13D%2FA`) → SC 13D filer 로 자주 등장하는 CIK 확정. Trian(0001345471) 확보에 이미 검증한 방식.

**한국 대응 코드**: DART filer 검색 (`opendart.fss.or.kr/api/company.json` 또는 `list.json`) 로 `corp_code` 확보. 개인·법인 구분.

---

## 1. 미국 Universe (Tier 1 · 실행 확실)

| # | 이름 | 대표 인물 | CIK (확정 · 실측 필요) | 대표 사례 |
|---|------|-----------|-----|-----------|
| 1 | Elliott Investment Management | Paul Singer | 0001048445 (실측) | 삼성물산 · AT&T · Twitter |
| 2 | Icahn Enterprises / Carl Icahn | Carl Icahn | 0000921669 (실측) | Netflix · Apple · McDonald's |
| 3 | Pershing Square Capital | Bill Ackman | 0001336528 (실측) | Herbalife · Target · Universal Music |
| 4 | Trian Fund Management | Nelson Peltz | **0001345471 (검증완료)** | Wendy's · P&G · Disney · GE |
| 5 | Third Point LLC | Dan Loeb | 0001040273 (실측) | Sony · Yahoo · Bath & Body Works |
| 6 | ValueAct Holdings | Jeffrey Ubben (전) · Mason Morfit | 0001418814 (실측) | Microsoft · Adobe · Rolls-Royce |
| 7 | Starboard Value LP | Jeff Smith | 0001517137 (실측) | Papa John's · Newell Brands · Salesforce |
| 8 | Engine No. 1 | Chris James | (실측) | ExxonMobil (climate proxy fight) |
| 9 | Jana Partners | Barry Rosenstein | 0001159159 (실측) | Whole Foods · Netflix |
| 10 | Cevian Capital | Christer Gardell | (실측) | ABB · Ericsson |
| 11 | Sachem Head Capital | Scott Ferguson | (실측) | Whitbread |
| 12 | Corvex Management | Keith Meister | (실측) | Yum Brands · Fluidigm |
| 13 | Land & Buildings | Jonathan Litt | (실측) | REIT 전문 |
| 14 | Legion Partners | Chris Kiper | (실측) | 소형주 |
| 15 | Marcato Capital | Mick McGuire | (실측) | Buffalo Wild Wings |
| 16 | Blue Harbour Group | Cliff Robbins | (실측) | Xerox |
| 17 | Politan Capital | Quentin Koffey | (실측) | 헬스케어 |
| 18 | Impactive Capital | Christian Alejandro Asmar | (실측) | ESG 활동 |
| 19 | Blackwells Capital | Jason Aintabi | (실측) | Peloton |
| 20 | Bluebell Capital Partners | Marco Taricco · Giuseppe Bivona | (실측) | Danone · Vodafone · GSK |
| 21 | Ancora Advisors | Fred DiSanto | (실측) | 국내 도입 · Norfolk Southern |
| 22 | Dalton Investments | (실측) | (실측) | 한국 진출 이력 |
| 23 | Silchester International Investors | Stephen Butt | (실측) | 삼성전자 우선주 지분 |
| 24 | Palliser Capital | James Smith | (실측) | 삼성물산 · Rio Tinto |
| 25 | Silver Lake | (실측) | (실측) | Twitter · Airbnb |
| 26 | Blackstone Group (activism 부문) | (실측) | (실측) | 다수 |
| 27 | ScottsMiracle-Gro Follow-on: Marcato | 통합 | — | 중복 |
| 28 | Cerberus Capital | (실측) | (실측) | Elbit · 한국 국내 |
| 29 | Cvian Capital (변경) | 중복 | — | — |
| 30 | Manchester United Watch / Nasdaq 개별 | (실측) | (실측) | 참고 |

**실측 검증 배치**: Phase A 착수 첫 스텝. Trian 방식대로 `efts.sec.gov` 검색 → SC 13D filer CIK 확보 → 리스트에 확정 값 반영.

**향후 확장 후보 (Tier 2, 하드코딩 후 추가)**: Effissimo Capital Management (일본계) · Toro Investment Partners · Politan · Land & Buildings 세컨더리 · Sachem Head 등

---

## 2. 한국 Universe (국내 activist)

| # | 이름 | 대표 인물 | 대표 사례 |
|---|------|-----------|-----------|
| 1 | **얼라인파트너스** | 이창환 | SM엔터 · KT&G · JB금융지주 |
| 2 | **KCGI (강성부펀드)** | 강성부 | 한진칼 · 대한항공 · KISCO홀딩스 |
| 3 | **VIP자산운용** | 최준철·김민국 | 다수 소형주 |
| 4 | **트러스톤자산운용** | 이석희 | 태광산업 · BYC |
| 5 | **한국투자밸류자산운용** | 이채원 | 남양유업 · 우진 |
| 6 | **차파트너스** | 차정호 | 소형·중형 activism |
| 7 | **밸류파트너스자산운용** | (실측) | 소형 개별 사례 |
| 8 | **주주와기업가치연구소 (SKI)** | (실측) | 캠페인성 |
| 9 | **좋은기업지배구조연구소 (CGCG)** | (실측) | 정책 · 표결 |
| 10 | **네오플럭스** | (실측) | PEF · activism 사례 |

## 3. 한국 활동 이력 있는 외국계

| # | 이름 | 사례 |
|---|------|------|
| 11 | Elliott | 삼성물산(2015) · SK하이닉스(2018) |
| 12 | Palliser Capital | 삼성물산 · Rio Tinto |
| 13 | Silchester International | 삼성전자 우선주 |
| 14 | Dalton Investments | 다수 사례 |
| 15 | City of London Investment | Emerging markets |
| 16 | Ancora Advisors | Norfolk Southern (직접 국내 사례 검증 필요) |
| 17 | Cerberus Capital | 국내 사모 · activism 스타일 |
| 18 | Third Point | Sony 사례 (한국 X 사례 없음) |
| 19 | Effissimo Capital | Toshiba · 한국 시장 진출 검토 이력 |
| 20 | Oasis Management | 홍콩 · 아시아 activism (한국 사례 검증 필요) |

**KR corp_code 실측 방식**:
1. DART Open API `list.json?corp_code=` 로는 회사 → 공시 조회.
2. Activist 자체가 `주식등의대량보유상황보고서` 를 낸 이력을 역추적 — `list.json?pblntf_ty=F` (F = 대량보유) 필터로 최근 6개월 조회 → filer 이름 매칭.
3. Phase B 첫 스텝에서 실측.

---

## 4. 제외 대상 (신호 강도 낮음)

- **소액주주 결집체 · 헤이홀더** — 실행력·자본 부족. 정보성으로만 유용.
- **뮤추얼펀드 대량 보유** — passive · 액티비즘 아님 (Vanguard · BlackRock 등).
- **인덱스·ETF 편입** — 기계적 매매 · 신호 무의미.
- **개인 대량주주** — 특수관계인 오검출 위험 · Phase D 이후 별도 다룸.

## 5. UI 편집 흐름 ([[03-phase-a-c-roadmap]] 참조)

- `data/activist_universe.json` — 확정된 리스트 (SOPS 밖 · JSON 오버라이드 방식)
- `PATCH /api/v1/activist/universe` — UI 에서 추가·삭제·비활성 (VIP editor 패턴 재활용)
- **비활성 옵션** — 삭제 대신 flag 로 폴링만 제외 (히스토리 보존)
- **Tier 필드** — 강도 스코어링 (Tier 1 배수 1.2, Tier 2 = 1.0, Tier 3 = 0.9)

## 6. Universe 크기 예상

- 미국 Tier 1 · 30개 + Tier 2 · 15개 = **약 45개 CIK 폴링**
- 한국 국내 activist · 10개 + 외국계 국내 활동 · 5개 = **15개 filer 매칭**
- **SEC EDGAR**: 5분 폴링 × 45 CIK = 초당 0.15 요청 (SEC 정책 초당 10 요청 초과 무관)
- **DART**: 최신 공시 목록 조회 (`list.json`) 로 15명 이하 filer 매칭 · 5분 폴링
