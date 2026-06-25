# 섹터별 주도주 Top 3 — MVP 설계안

| 항목 | 값 |
|---|---|
| 문서 ID | sector-leaders/01-mvp-design |
| 작성일 | 2026-06-23 |
| 상태 | 사용자 승인 (채팅, 2026-06-23) → 구현 대기 |
| 대체 대상 | 기존 README의 Crazy Picks · Moonshot Picks (시장 방향: US→한국) |
| 기존 로드맵 매핑 | implementation-roadmap.md Phase B/C/D/G/H 중 Discovery 부분 재정의 |
| 외부 의존 신규 | pdfplumber, camelot-py, pykrx, OpenDartReader (또는 dart-fss) |

---

## 1. 한 줄 컨셉

산업통상부 월간 수출입동향 시계열을 KRX 업종 주도주(시총×수출비중)에 매핑하고 Pearson 상관 + lead/lag로 수출-주가 유의성을 검증해, **사용자가 검증된 신호만** 보게 한다.

## 2. 배경

### 사용자 가설 (2026-06-23 채팅)
> "주식 족보가 통째로 풀려 있는데 아무도 안 본다. 매달 산업통상부가 '수출입 동향' 자료를 올린다. 주가하고 거의 싱크가 100% 맞는 자료가 수출 자료다. 업종 수출만 봐도 답이 나온다."

### 본 검증 결과 (B-1 단계)
- **데이터 가용성**: 매월 1일 motir.go.kr 보도자료 PDF 1장에 ① 20품목×13개월 시계열, ② 9지역×13개월, ③ 유망 품목 3종, ④ 5대 소비재, ⑤ 원자재 가격, ⑥ 5.1~25일 잠정(발표 6일 전), ⑦ 세부 품목 정의(MTI↔KRX 매핑 핵심 단서), ⑧ 4년치 누적 표가 모두 포함. **사실상 단일 PDF가 정형 데이터셋**.
- **"100% 싱크"는 과장**이나 **반도체·AI 인프라 사이클에서는 부분적 참**. 25.5월 △21.2% → 26.5월 +169.4%의 극단 변화가 SK하이닉스·삼성전자 주가와 동행 가능성 매우 높음.
- 부진 섹터(자동차 △5.9%, 가전 △21.7%, 섬유 △6.6%) 동시 존재 → 모든 섹터에서 강한 시그널은 기대 못함. **시그널 강도를 검증해 라벨링하는 게 본 서비스의 본질**.

### 참고 자료
- `/tmp/motie_research/2026-05-motie-export.pdf` (37p, KDI 사본)
- 사용자 메모리 `project-motir-rebrand` (산업통상자원부 → 산업통상부, 도메인 motie→motir)

## 3. 데이터 소스

| # | 데이터 | 소스 | 빈도 | 책임 모듈 |
|---|---|---|---|---|
| 1 | 20품목 × 13개월 시계열 | motir.go.kr 월간 PDF | 매월 1일 11시 | `motir_export/pdf_parser.py` |
| 2 | 9지역 × 13개월 시계열 | 동일 PDF | 동일 | 동일 |
| 3 | 유망 품목 시계열 (OLED/SSD/MCP) | 동일 PDF | 동일 | 동일 |
| 4 | 5대 소비재 시계열 | 동일 PDF | 동일 | 동일 |
| 5 | 원자재 가격 (두바이유/DDR/NAND/리튬/니켈) | 동일 PDF | 동일 | 동일 |
| 6 | 5.1~25일 잠정 (참고 4) | 동일 PDF (다음 단계) | 동일 | 동일 |
| 7 | KRX 주가·시총 | `pykrx` | 일별 | `krx_price/price_loader.py` |
| 8 | 종목별 수출비중 (해외매출비중) | DART 사업보고서 (분기) | 분기별 | `dart_revenue/revenue_extractor.py` |
| 9 | 품목 ↔ KRX 업종 매핑 | 수동 작성 YAML | 분기 갱신 | `mapping/mti_to_krx.yaml` |

## 4. 분석 룰

### 4.1 주도주 선정

```
sector_leader_score(stock, item)
  = log10(market_cap_krw) × export_revenue_ratio
  
선정 = 품목당 score 상위 3종목 (Top 3)
```

- `market_cap_krw`: 직전 거래일 KRX 시가총액 (원)
- `export_revenue_ratio`: 0~1 사이, DART 사업보고서 매출 구성에서 "해외/수출 매출 비중". 직전 분기 기준.
- `log10`은 시총 절대값이 너무 큰 종목(삼성전자 등)이 모든 섹터를 독점하는 것을 완화.

### 4.2 수출-주가 유의성

```
input
  - export_yoy_24m: 해당 품목 24개월 수출 YoY 증감률 (월간)
  - stock_return_24m: 주도주 월간 수익률 (24개월)

calc
  - Pearson r (전체 24개월)
  - lead/lag k ∈ [-3, +3] 각각 r_k = corr(export_yoy_t-k, stock_return_t)
  - r_max = max |r_k|, k_max = argmax |r_k|

label
  |r_max| ≥ 0.7  → ★★★ 강한 동행
  0.4 ≤ |r_max| < 0.7 → ★★ 중간
  |r_max| < 0.4  → ★ 약함 (참고용)
```

> 24개월 표본은 표본 수가 작아 p-value 해석에 주의. MVP에선 시각화 + R²·r 명시 위주, Granger 등 고급 통계는 차후.

## 5. Phase 분해

| Phase | 작업 | 산출물 | 의존 |
|---|---|---|---|
| **B-2a** | PDF 다운로더 + 좌표 기반 파서 + 누적 DB 스키마 (`is_provisional` 플래그 포함) | 2026-05 PDF → DB 적재 검증 | — |
| **B-2b** | 2025-05 PDF 추가 다운로드로 24개월 시계열 완성 + APScheduler 매월 1일 11:30 자동 수집 | 24개월 DB + 스케줄러 동작 | B-2a |
| **B-2c** | `pykrx` 주가/시총 + DART 수출비중 + `mti_to_krx.yaml` 매핑 | 매핑 + 종목 메타 + 24M 일봉 | B-2a |
| **B-2d** | 주도주 선정 점수 + Pearson + lead/lag 엔진 + 신뢰도 배지 | 분석 엔진 + 단위 테스트 | B-2b, B-2c |
| **B-2e** | FastAPI 라우트 + Next.js `/sector-leaders` UI | 사용자 접근 가능 화면 | B-2d |
| **F-1** | `layout.tsx` NAV·`page.tsx` CARDS에서 Crazy/Moonshot 숨김 + Sector Leaders 추가 | 메뉴 정리 | B-2e |

배포 정책: 메모리 `feedback-deploy-only-when-complete`에 따라 **B-2a~F-1 전 Phase 로컬 완료 후 단일 배포**. Phase별 부분 배포 금지.

## 6. 화면 흐름 (`/sector-leaders`)

```
┌─────────────────────────────────────────────────────────────┐
│ [품목 사이드 리스트]   │  [선택 품목 상세]                  │
│                       │                                     │
│ ★★★ 반도체   +169.4%  │  품목 헤더: 반도체  +169.4%        │
│ ★★★ 컴퓨터   +290.7%  │  ───────────────────────────       │
│ ★★  바이오   +5.2%    │  13개월 수출액·증감률 차트          │
│ ★   디스플레 +9.4%    │  ───────────────────────────       │
│ ─   자동차   △5.9%    │  주도주 Top 3 카드                  │
│ ─   가전     △21.7%   │   ┌─SK하이닉스─┐ ┌─삼성전자─┐ ...   │
│ ...                   │   │ 시총 ₩…    │ │ 시총 ₩…   │     │
│ (★별 정렬 + 색상 강도) │   │ 수출비중 …  │ │ 수출비중 … │     │
│                       │   └────────────┘ └───────────┘     │
│                       │                                     │
│                       │  종목별 상세 (Top 3 각각):          │
│                       │   24개월 주가 차트 + 수출 오버레이  │
│                       │   Pearson r=0.82  ★★★ 강한 동행    │
│                       │   최강 lead/lag: t-1 (수출이 1개월   │
│                       │     선행)                           │
└─────────────────────────────────────────────────────────────┘
```

## 7. 모듈 구조

```
backend/
  discovery/
    data_sources/
      motir_export/          # 신규
        __init__.py
        downloader.py        # KDI/motir 우선순위 다운로드
        pdf_parser.py        # pdfplumber/Camelot 좌표 추출
        item_extractor.py    # 참고 2 표 → 20품목 13M
        region_extractor.py  # 지역별 13M
        commodity_extractor.py  # 원자재 가격
      krx_price/             # 신규
        __init__.py
        price_loader.py      # pykrx 24M 일봉, 시총
      dart_revenue/          # 신규
        __init__.py
        revenue_extractor.py # 사업보고서 매출 구성
      mapping/
        __init__.py
        mti_to_krx.yaml      # 신규: 20품목 ↔ KRX 업종 1:N
        loader.py
    sector_leaders/          # 신규
      __init__.py
      leader_picker.py       # score = log10(시총) × 수출비중
      correlation.py         # Pearson + lead/lag
      labels.py              # ★★★ / ★★ / ★

  services/
    models.py                # 신규 테이블 추가:
                             #   ExportRecord(item, month, value, yoy, is_provisional)
                             #   RegionRecord, CommodityRecord
                             #   SectorLeader(item, ticker, score, rank, r, k_max)

  api/
    routes/
      sector_leaders.py      # 신규
      schemas.py             # 응답 모델 추가

  scheduler/
    motir_monthly.py         # 신규: 매월 1일 11:30 잡

frontend/
  app/
    sector-leaders/          # 신규 라우트
      page.tsx
      [item]/page.tsx        # 또는 query param 방식
    crazy/                   # 유지 (NAV에서만 숨김)
    moonshot/                # 유지 (NAV에서만 숨김)
  components/
    sector-leaders/          # 신규
      ItemList.tsx
      ItemDetailChart.tsx
      LeaderCard.tsx
      CorrelationChart.tsx
      ConfidenceBadge.tsx
```

## 8. DB 스키마 (요약)

```python
class ExportRecord(Base):
    item: str                # 반도체/자동차/…
    region: Optional[str]    # None=전체, '미국'/'중국'/…
    month: date              # 해당 월 1일
    value_musd: float        # 백만 달러
    yoy_pct: float           # 전년동월대비 %
    is_provisional: bool     # 잠정치 여부
    source_pdf: str          # 출처 PDF 파일명
    fetched_at: datetime
    confirmed_at: Optional[datetime]  # 확정치로 갱신된 시각
    
    UNIQUE(item, region, month)

class CommodityRecord(Base):
    name: str                # 두바이유/DDR4_8Gb/NAND_128G/리튬/니켈
    month: date
    value: float
    unit: str                # $/B, $, $/kg, $/Ton
    yoy_pct: Optional[float]
    is_provisional: bool

class SectorLeader(Base):
    item: str
    ticker: str              # KRX 6자리
    name: str
    rank: int                # 1~3
    score: float
    market_cap_krw: int
    export_revenue_ratio: float
    pearson_r: Optional[float]
    lead_lag_month: Optional[int]  # k_max
    confidence: str          # strong/medium/weak
    computed_at: datetime
```

## 9. 잠정 → 확정 BACKFILL

- 매월 1일 발표는 **잠정치** (`is_provisional=true`). 약 9개월 후 ('27.2월) 확정치 발표.
- 확정 발표 보도자료 다운로드 시:
  - 동일 `(item, region, month)` 키로 갱신
  - 기존 잠정 값은 **별도 테이블 `ExportRecordHistory`에 보존**
  - `is_provisional=false`, `confirmed_at=now()` 갱신
- upbit `core/strategy_engine.py` BACKFILL 패턴 차용 (지표 상태 백업/복원 → 본 프로젝트에서는 분석 결과 백업/복원).
- 분석 모듈(B-2d)은 항상 최신값을 사용하되, 신뢰도 배지 옆에 `is_provisional`이면 "잠정" 마크 표시.

## 10. 리스크 & 미결정

| 항목 | 리스크 | MVP 대응 |
|---|---|---|
| PDF 양식 변경 | 좌표 기반 파서 깨짐 | 파싱 실패 시 알림 + 다음 발표 전까지 수동 보정. 추후 OCR+LLM fallback 검토 |
| DART 수출비중 자동화 | 사업보고서 양식 다양·자동 추출 난도↑ | MVP 1차는 수동 입력 + 분기별 갱신. 자동화는 후속 Phase |
| 24개월 표본 크기 | Pearson r의 통계적 신뢰도 한계 | r·R² 명시 + 신뢰도 배지 + "표본 24개월" 캡션. 누적 PDF로 표본↑ 가능 |
| 잠정 vs 확정 간 차이가 큰 품목 | r 변동 가능 | 잠정 분석 시 배지에 "잠정" 마크. 확정 발표 시 자동 재계산 |
| 미수출 종목 매핑 | 같은 KRX 업종 안에서도 수출 0인 종목 존재 (예: 일부 내수 회사) | `export_revenue_ratio=0` 종목은 score=0 처리해서 자동 탈락 |
| 5.1~25일 잠정 데이터 | 양식이 정형은 강하나 본 MVP 1차에선 미사용 | B-2a 파서는 추출만 해두고, MVP 2차에서 "D-5 사전 알림" 메뉴로 활성 |

## 11. 비목표 (Out of Scope)

- 자동매매 (기존 Phase K 별도)
- 종목 추천이 아닌 **검증된 시그널의 표시**가 본 MVP의 본질. "사라" "팔라"는 표기 금지, 사용자가 직접 판단.
- 백테스팅은 차후 (B-3 후속 작업으로 분리)
- 미국 주식 (기존 Crazy/Moonshot는 코드 유지, NAV에서만 숨김. 시장 전환은 별도 의사결정 후 정식 디프리시에이션)

## 12. 변경 이력

| 일자 | 변경 | 비고 |
|---|---|---|
| 2026-06-23 | 최초 작성 (사용자 채팅 승인) | B-1 검증 결과 반영 |
