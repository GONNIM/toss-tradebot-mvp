# WP71-1 · FE-DIFF 정밀 측정 결과 (2026-09-18)

> Playwright headless · 운영 서버 · 인증 없는 부분만 (admin 미로그인 화면)
> 뷰포트: 데스크톱 1280×900 · 모바일 390×844 · 라이트/다크 각 1건 · 총 4 케이스
> **admin 콘텐츠 (표·md 문서) 는 인증 필요로 측정 제외** · WP71-2 구조 전환으로 자동 해결

## 측정 결과 (activist-radar vs biotech · 인증 없는 상태)

| 뷰포트 | 스킴 | 요소 | 속성 | activist-radar | biotech | 차이 |
|---|---|---|---|---|---|---|
| desktop | dark | button_first | background-color | `rgb(24, 24, 27)` | `rgba(0, 0, 0, 0)` | ⚠️ 다름 |
| desktop | dark | button_first | border-bottom-color | `rgb(228, 228, 231)` | `rgb(228, 228, 231)` | ✅ |
| desktop | dark | button_first | border-bottom-width | `0px` | `0px` | ✅ |
| desktop | dark | button_first | font-size | `12px` | `12px` | ✅ |
| desktop | dark | button_first | padding-bottom | `4px` | `0px` | ⚠️ 다름 |
| desktop | dark | button_first | padding-left | `8px` | `0px` | ⚠️ 다름 |
| desktop | dark | button_first | padding-right | `8px` | `0px` | ⚠️ 다름 |
| desktop | dark | button_first | padding-top | `4px` | `0px` | ⚠️ 다름 |
| desktop | dark | h1 | color | `rgb(9, 9, 11)` | `rgb(9, 9, 11)` | ✅ |
| desktop | dark | h1 | font-size | `30px` | `24px` | ⚠️ 다름 |
| desktop | dark | h1 | font-weight | `700` | `700` | ✅ |
| desktop | dark | h1 | line-height | `36px` | `32px` | ⚠️ 다름 |
| desktop | dark | h2_first | font-size | `18px` | `14px` | ⚠️ 다름 |
| desktop | dark | h2_first | font-weight | `600` | `600` | ✅ |
| desktop | dark | h2_first | line-height | `28px` | `20px` | ⚠️ 다름 |
| desktop | dark | main_container | max-width | `1280px` | `1280px` | ✅ |
| desktop | dark | main_container | padding-bottom | `24px` | `24px` | ✅ |
| desktop | dark | main_container | padding-left | `16px` | `16px` | ✅ |
| desktop | dark | main_container | padding-right | `16px` | `16px` | ✅ |
| desktop | dark | main_container | padding-top | `24px` | `24px` | ✅ |
| desktop | dark | p_first | color | `rgb(113, 113, 122)` | `rgb(113, 113, 122)` | ✅ |
| desktop | dark | p_first | font-size | `14px` | `14px` | ✅ |
| desktop | dark | p_first | line-height | `20px` | `20px` | ✅ |
| desktop | light | button_first | background-color | `rgb(24, 24, 27)` | `rgba(0, 0, 0, 0)` | ⚠️ 다름 |
| desktop | light | button_first | border-bottom-color | `rgb(228, 228, 231)` | `rgb(228, 228, 231)` | ✅ |
| desktop | light | button_first | border-bottom-width | `0px` | `0px` | ✅ |
| desktop | light | button_first | font-size | `12px` | `12px` | ✅ |
| desktop | light | button_first | padding-bottom | `4px` | `0px` | ⚠️ 다름 |
| desktop | light | button_first | padding-left | `8px` | `0px` | ⚠️ 다름 |
| desktop | light | button_first | padding-right | `8px` | `0px` | ⚠️ 다름 |
| desktop | light | button_first | padding-top | `4px` | `0px` | ⚠️ 다름 |
| desktop | light | h1 | color | `rgb(9, 9, 11)` | `rgb(9, 9, 11)` | ✅ |
| desktop | light | h1 | font-size | `30px` | `24px` | ⚠️ 다름 |
| desktop | light | h1 | font-weight | `700` | `700` | ✅ |
| desktop | light | h1 | line-height | `36px` | `32px` | ⚠️ 다름 |
| desktop | light | h2_first | font-size | `18px` | `14px` | ⚠️ 다름 |
| desktop | light | h2_first | font-weight | `600` | `600` | ✅ |
| desktop | light | h2_first | line-height | `28px` | `20px` | ⚠️ 다름 |
| desktop | light | main_container | max-width | `1280px` | `1280px` | ✅ |
| desktop | light | main_container | padding-bottom | `24px` | `24px` | ✅ |
| desktop | light | main_container | padding-left | `16px` | `16px` | ✅ |
| desktop | light | main_container | padding-right | `16px` | `16px` | ✅ |
| desktop | light | main_container | padding-top | `24px` | `24px` | ✅ |
| desktop | light | p_first | color | `rgb(113, 113, 122)` | `rgb(113, 113, 122)` | ✅ |
| desktop | light | p_first | font-size | `14px` | `14px` | ✅ |
| desktop | light | p_first | line-height | `20px` | `20px` | ✅ |
| mobile | dark | button_first | background-color | `rgb(24, 24, 27)` | `rgba(0, 0, 0, 0)` | ⚠️ 다름 |
| mobile | dark | button_first | border-bottom-color | `rgb(228, 228, 231)` | `rgb(228, 228, 231)` | ✅ |
| mobile | dark | button_first | border-bottom-width | `0px` | `0px` | ✅ |
| mobile | dark | button_first | font-size | `12px` | `12px` | ✅ |
| mobile | dark | button_first | padding-bottom | `4px` | `0px` | ⚠️ 다름 |
| mobile | dark | button_first | padding-left | `8px` | `0px` | ⚠️ 다름 |
| mobile | dark | button_first | padding-right | `8px` | `0px` | ⚠️ 다름 |
| mobile | dark | button_first | padding-top | `4px` | `0px` | ⚠️ 다름 |
| mobile | dark | h1 | color | `rgb(9, 9, 11)` | `rgb(9, 9, 11)` | ✅ |
| mobile | dark | h1 | font-size | `30px` | `24px` | ⚠️ 다름 |
| mobile | dark | h1 | font-weight | `700` | `700` | ✅ |
| mobile | dark | h1 | line-height | `36px` | `32px` | ⚠️ 다름 |
| mobile | dark | h2_first | font-size | `18px` | `14px` | ⚠️ 다름 |
| mobile | dark | h2_first | font-weight | `600` | `600` | ✅ |
| mobile | dark | h2_first | line-height | `28px` | `20px` | ⚠️ 다름 |
| mobile | dark | main_container | max-width | `none` | `none` | ✅ |
| mobile | dark | main_container | padding-bottom | `24px` | `24px` | ✅ |
| mobile | dark | main_container | padding-left | `16px` | `16px` | ✅ |
| mobile | dark | main_container | padding-right | `16px` | `16px` | ✅ |
| mobile | dark | main_container | padding-top | `24px` | `24px` | ✅ |
| mobile | dark | p_first | color | `rgb(113, 113, 122)` | `rgb(113, 113, 122)` | ✅ |
| mobile | dark | p_first | font-size | `14px` | `14px` | ✅ |
| mobile | dark | p_first | line-height | `20px` | `20px` | ✅ |
| mobile | light | button_first | background-color | `rgb(24, 24, 27)` | `rgba(0, 0, 0, 0)` | ⚠️ 다름 |
| mobile | light | button_first | border-bottom-color | `rgb(228, 228, 231)` | `rgb(228, 228, 231)` | ✅ |
| mobile | light | button_first | border-bottom-width | `0px` | `0px` | ✅ |
| mobile | light | button_first | font-size | `12px` | `12px` | ✅ |
| mobile | light | button_first | padding-bottom | `4px` | `0px` | ⚠️ 다름 |
| mobile | light | button_first | padding-left | `8px` | `0px` | ⚠️ 다름 |
| mobile | light | button_first | padding-right | `8px` | `0px` | ⚠️ 다름 |
| mobile | light | button_first | padding-top | `4px` | `0px` | ⚠️ 다름 |
| mobile | light | h1 | color | `rgb(9, 9, 11)` | `rgb(9, 9, 11)` | ✅ |
| mobile | light | h1 | font-size | `30px` | `24px` | ⚠️ 다름 |
| mobile | light | h1 | font-weight | `700` | `700` | ✅ |
| mobile | light | h1 | line-height | `36px` | `32px` | ⚠️ 다름 |
| mobile | light | h2_first | font-size | `18px` | `14px` | ⚠️ 다름 |
| mobile | light | h2_first | font-weight | `600` | `600` | ✅ |
| mobile | light | h2_first | line-height | `28px` | `20px` | ⚠️ 다름 |
| mobile | light | main_container | max-width | `none` | `none` | ✅ |
| mobile | light | main_container | padding-bottom | `24px` | `24px` | ✅ |
| mobile | light | main_container | padding-left | `16px` | `16px` | ✅ |
| mobile | light | main_container | padding-right | `16px` | `16px` | ✅ |
| mobile | light | main_container | padding-top | `24px` | `24px` | ✅ |
| mobile | light | p_first | color | `rgb(113, 113, 122)` | `rgb(113, 113, 122)` | ✅ |
| mobile | light | p_first | font-size | `14px` | `14px` | ✅ |
| mobile | light | p_first | line-height | `20px` | `20px` | ✅ |

## 스크린샷 파일 (4장 × 2 페이지 = 8장)

- `screenshots/activist-radar_desktop_light.png`
- `screenshots/activist-radar_desktop_dark.png`
- `screenshots/activist-radar_mobile_light.png`
- `screenshots/activist-radar_mobile_dark.png`
- `screenshots/biotech_desktop_light.png`
- `screenshots/biotech_desktop_dark.png`
- `screenshots/biotech_mobile_light.png`
- `screenshots/biotech_mobile_dark.png`

## 노출 검사

- 스크린샷·리포트: **토큰·쿠키·헤더 값 노출 0건** (측정 시 admin 헤더 사용 안 함)
- config 로더 강제 · setup_secure_logging 활성

## 판정

- 인증 없는 부분 (컨테이너·헤더·탭·배너) 측정 결과 표 참조
- ✅ = activist-radar 와 biotech 값 동일
- ⚠️ = 차이 존재 · WP71-2 구조 전환 후 재측정 대상

**다음 단계**: WP71-2 (구조 전환 · JSON 라우터 + activist-radar 골격 복제)