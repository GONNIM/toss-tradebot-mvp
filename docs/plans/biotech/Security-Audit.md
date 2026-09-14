# Biotech Catalyst Radar · Security Audit

**목적**: 자격증명·SEC UA·봇 감지 우회 관련 위반·사고 이력 · 재발 방지 조치 기록.

---

## §1. 대상 자격증명

- DART_API_KEY (opendart.fss.or.kr)
- EODHD_API_KEY / TIINGO_API_KEY / ALPHAVANTAGE_API_KEY / SIMFIN_API_KEY (backend/.env)
- SEC (무인증 · UA 규정만)

## §2. 상시 규칙

- 신규 스크립트: `from backend.services import config` 필수 · `from backend.scripts._biotech_bootstrap import require_secure_logging` 필수 · main() 첫 줄 `require_secure_logging()` 호출 (WP8 · 2026-09-08)
- SEC UA: `TossTradebot-BiotechRadar/1.0 (sung2011103@naver.com)` · `From: sung2011103@naver.com` (B59)
- SEC 요청 간격: 0.5s (2 req/s · SEC 10 req/s 이내)
- 403 감지: 즉시 중단 · UA 순환 재시도 금지 (B59 · B105)
- IP 차단 우회 (서버 실행·네트워크 변경) 금지 (B105)
- 봇 감지 페이지 우회 금지 (대안 공식 소스 사용 · B127)

## §3-A · SEC UA 위반 사례

- 2026-09-03 · `Archives/*` 접근 시 UA 순환 4회 후 IP 차단 (B55+) · 규정 위반 · 재발 방지 = 선언 UA 통일 (B59)

## §3-B · 자격증명 로그 노출 사고 (재발 방지 우선순위 P0)

| # | 일시 (UTC) | 스크립트 | 자격증명 | 원인 | 조치 |
|---|---|---|---|---|---|
| 1 | 2026-08-22 | (초기 다수) | DART_API_KEY | httpx INFO 로거가 request URL 전체 로깅 · crtfc_key 노출 | `backend/services/config.py` 자동 `setup_secure_logging()` 도입 · SecretMaskingFilter 등록 · httpx WARNING 승격 |
| 2 | 2026-09-02 | biotech_coverage_test2 (초기) | EODHD_API_KEY · FMP_API_KEY | httpx INFO 로거 URL 파라미터 노출 | 사후 억제 코드 반영 (임시) · 재발급 없음 (사용자 위험 수용) |
| 3 | 2026-09-02 | biotech_h3_targets_census (B49) | DART_API_KEY (마이너 · 확인 불충분) | 신규 스크립트 config 미경유 가능성 · 이후 로그 확인 불가 | 명시적 마스킹 억제 코드 추가 |
| 4 | **2026-09-08** | **biotech_h5_glp1_map (WP3 신규)** | **DART_API_KEY (40자 hex)** | **신규 스크립트가 `config` 미경유 · `load_dotenv` 직접 호출 · httpx INFO 로 crtfc_key 전문 출력** | 사후 억제 (`httpx WARNING`) · **WP8 구조화**: (a) `_biotech_bootstrap.py` + `require_secure_logging()` 강제 (b) `test_biotech_secure_entry.py` 로 신규 파일 config·bootstrap import 강제 검증 (c) 사용자 결정 = **재발급 없음** |

## §4 · WP8 (2026-09-08) 재발 방지 구조

- **공용 bootstrap**: `backend/scripts/_biotech_bootstrap.py` · `require_secure_logging()` 함수 = SecretMaskingFilter 등록 확인 + httpx level ≥ WARNING 확인 · 실패 시 SystemExit(97)
- **테스트 강제**: `backend/tests/test_biotech_secure_entry.py` · biotech_*.py 전 파일에 (a) `from backend.services import config` 존재 (b) `_biotech_bootstrap` import 존재 (c) main() 내부 `require_secure_logging()` 호출 존재 세 조건 검사 · CI 통합 필수
- **이력**: 12건 (신규 WP2~WP7 6건 + 기존 6건) 전건 config import 부재 발견 → 배치 삽입 · 78/78 통과 확인 (2026-09-08 세션 2)
- **인프라 층 사용 허가 (B47)**: `backend.services.config` 는 인프라 유틸 · biotech 응용 격리 원칙에 위배되지 않음

## §5 · 봇 감지 우회 금지 (2026-09-06 · B127 이후)

- FDA AdCom 캘린더 페이지 · KIND 조회공시 검색 → 봇 감지 차단
- 대응 = 우회 금지 · 공식 API 대안 사용 (연방관보 API · DART OpenAPI)
