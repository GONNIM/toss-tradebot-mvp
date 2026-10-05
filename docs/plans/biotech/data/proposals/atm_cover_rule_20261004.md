# 제안 · 424B5 표지 규칙 (ATM 판정) 검증 결과 (P3a ⑦ · 2026-10-04)

- 상태: **제안 (Fable 검수 전 · 코드 미반영)**. 화면 · 파생 파일의 ATM 값은 모두 "미확인"이다 (`backend/scripts/biotech_filings.py` ATM_UNKNOWN).
- 규칙 (PRD v0.5 FR-6a 제안): 424B5 본문 앞 6,000자에 (A) 판매 대리인 계약 문구가 있고 (B) "Up to $" 금액이 있고 (C) 주식 수 공모 문구가 없으면 ATM (시장가 분할 발행) 으로 본다.
- 원문: SEC primaryDocument 20건 · 2026-10-04 로컬 · 공용 헤더 (`biotech_sec_common.build_client`) · 장부 `p3a_424b5_cover` 20건 · 403 · 429 없음.
- 본문 변환: HTML 태그 제거 · HTML 엔티티 해제 · 공백 하나로 합침 · 제어 문자 · 단독 surrogate 제거. 앞 6,000자 = 변환한 글자 기준.

## 1. 표본 선택 (요청 0)

- 출처: P3a ② submissions 로컬 실행 (`filings/submissions_20261004.json` · 후보 80) 의 최근 12개월 424B5. P2 에서 받은 4건은 뺐다.
- 종목당 가장 최근 424B5 1건. ATM 과 인수 공모가 섞이게 종목을 둘로 나눴다. 가장 최근 424B5 앞 5일 안에 다른 424B5 가 있는 종목 (예비 · 확정 연속 · 인수 공모 추정) 에서 티커 순 10개, 없는 종목에서 티커 순 10개다.
- 후보 풀: 앞 5일 안 연속 20종목 · 단독 27종목. 이 구분은 표본을 섞기 위한 것이며 정답이 아니다.
- 정답: 구현자가 원문 표지를 읽고 붙였다. ATM = 표지에 판매 대리인과 판매 계약 (sales agreement) 으로 수시 판매한다고 적힌 문서. 인수 공모 = 표지에 주식 수 또는 금액 공모와 인수인 (underwriters) 보수 · "See Underwriting" 이 적힌 문서.

## 2. 문구 목록 (검수 대상)

| 구분 | 뜻 | 정규식 |
|---|---|---|
| A | 판매 대리인 계약 문구 | `\bsales agreement\b|\bsales agents?\b|equity distribution agreement|open market sale agreement|at[- ]the[- ]market (?:issuance |offering )?sales agreement|controlled equity offering` |
| B | "Up to $" 금액 | `\bup to \$\s?\d[\d,.]*(?:\s*(?:million|billion))?` |
| C | 주식 수 공모 문구 | `\b(?:we are|are) (?:offering|selling)\s+(?:an aggregate of\s+)?\d{1,3}(?:,\d{3})+\s+(?:shares|common shares)\b` |

A 의 문구: sales agreement · sales agent(s) · equity distribution agreement · open market sale agreement · at-the-market (issuance/offering) sales agreement · controlled equity offering.

## 3. 결과

| 구분 | 건수 |
|---|---|
| 적중 (ATM → ATM) | 3 |
| 오검출 (인수 공모 → ATM) | 0 |
| 놓침 (ATM → 아님) | 1 |
| 정상 제외 (인수 공모 → 아님) | 16 |

- 정답 ATM 은 20건 중 4건이다. 표본이 작아 적중률을 일반화할 수 없다.
- 오검출은 0건이다. P2 에서 문구 검출이 틀린 인수 공모 유형 (기본 투자설명서 일반 문구) 은 앞 6,000자 밖이라 걸리지 않았다.
- 놓침 1건은 ATRA (0001193125-26-219518) 다. 이 문서는 기존 ATM 투자설명서를 고치는 "Second Supplement" 이고 전체 4,281자다. 표지에 "Up to $" 가 없고 남은 금액 "$79,269,007 Common Stock" 만 있다. 원인 가설은 하나다. 기존 ATM 의 금액을 바꾸는 보충 문서는 "Up to $" 대신 금액만 적는다. 규칙은 고치지 않았다.
- 금액만 적은 예비 인수 공모 2건 (ABCL "$200,000,000 Common Shares" · AMLX "$350,000,000 Shares of common stock") 은 C 가 없지만 A 가 없어 ATM 으로 잡히지 않았다. A 가 이 유형을 막는 조건이다.

## 4. 20건 상세 (인용은 앞 6,000자에서 검출 위치 앞뒤 60자)

| 종목 | 접수번호 | 제출일 | 표본 묶음 | 정답 | 규칙 | A | B | C | A 인용 | B 인용 | C 인용 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ALT | 0001104659-26-047979 | 2026-04-24 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  |  Pre-Funded Warrants to Purchase Shares of Common Stock ​ ​ We are offering 64,250,000 shares of our common stock, par value $0.0001 per share, accomp |
| ANNX | 0001193125-25-280384 | 2025-11-13 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | Warrants to Purchase up to 3,750,000 Shares of Common Stock We are offering 25,096,153 shares of our common stock, par value $0.001 per share, or, in  |
| APGE | 0001104659-26-034562 | 2026-03-25 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | tus Dated August 12, 2024) 5,000,000 shares of Common Stock We are offering 5,000,000 shares of our common stock. The public offering price for each s |
| ASMB | 0001193125-26-237361 | 2026-05-26 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | d Warrants to Purchase up to 415,000 Shares of Common Stock We are offering 3,358,602 shares of our common stock, par value $0.001 per share, and/or ( |
| AVTX | 0001104659-26-056481 | 2026-05-07 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | rrants to Purchase up to 1,400,000 Shares of Common Stock ​ We are offering 19,730,000 shares of common stock and, in lieu of common stock to certain  |
| BCAX | 0001193125-26-072875 | 2026-02-26 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | Warrants to Purchase up to 2,200,000 Shares of Common Stock We are offering 7,175,000 shares of our common stock, par value $0.0001 per share, and, in |
| BIOA | 0001193125-26-019530 | 2026-01-22 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | ctus dated November 25, 2025) 5,897,435 Shares Common Stock We are offering 5,897,435 shares of our common stock. Our common stock is listed on The Na |
| DNTH | 0001193125-26-102472 | 2026-03-11 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | -funded Warrants to Purchase 402,468 Shares of Common Stock We are offering 7,313,582 shares of our common stock and, in lieu of common stock to certa |
| DYN | 0001193125-26-312576 | 2026-07-22 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | spectus dated March 5, 2024) 18,300,000 Shares Common Stock We are offering 18,300,000 shares of our common stock. Our common stock is listed on The N |
| EDIT | 0001104659-26-066382 | 2026-05-26 | pair_within_5d | underwritten | not_ATM |  |  | O |  |  | ck Warrants to Purchase 55,555,556 Shares of Common Stock ​ We are offering 55,555,556 shares of our common stock and accompanying common stock warran |
| ABCL | 0001193125-26-344944 | 2026-08-11 | single | underwritten | not_ATM |  |  |  |  |  |  |
| ABOS | 0001628280-25-051852 | 2025-11-13 | single | ATM | ATM | O | O |  | 24 $50,000,000 Common Stock We have entered into an amended sales agreement, or Sales Agreement, with BofA Securities, Inc., Stifel, Ni | ue $0.0001 per share, having an aggregate offering price of up to $50,000,000 from time to time through the Sales Agents. Sales of shares |  |
| ALXO | 0001193125-26-031754 | 2026-01-30 | single | underwritten | not_ATM |  |  | O |  |  | nded Warrants to Purchase 18,574,120 Shares of Common Stock We are offering 76,979,112 shares of our common stock, par value $0.001 per share (common  |
| AMLX | 0001193125-26-355696 | 2026-08-18 | single | underwritten | not_ATM |  |  |  |  |  |  |
| ANRO | 0001104659-26-083268 | 2026-07-14 | single | underwritten | not_ATM |  |  | O |  |  | dated February 11, 2025) 3,776,436 Shares of Common Stock ​ We are offering 3,776,436 shares of our common stock, par value $0.0001 per share, or the  |
| ANTX | 0001193125-26-164095 | 2026-04-20 | single | ATM | ATM | O | O |  | SUPPLEMENT $80,000,000 Common Stock We have entered into an open market sale agreement (the “sales agreement”) with Jefferies LLC (“Jefferies”), d | s of our common stock having an aggregate offering price of up to $80,000,000 from time to time through Jefferies acting as sales agent o |  |
| ARTV | 0001193125-26-214706 | 2026-05-08 | single | underwritten | not_ATM |  |  | O |  |  | Warrants to Purchase up to 2,170,138 Shares of Common Stock We are offering 23,871,526 shares of our common stock, par value $0.0001 per share, and in |
| ATRA | 0001193125-26-219518 | 2026-05-12 | single | ATM | not_ATM | O |  |  | Supplement ”) amends and supplements the information in our sales agreement prospectus, dated November 13, 2023 (the “ Sales Agreement  |  |  |
| AVBP | 0001104659-26-058700 | 2026-05-11 | single | ATM | ATM | O | O |  |  3, 2025) $250,000,000 Common Stock We have entered into an Open Market Sale Agreement SM (the sales agreement) with Jefferies LLC (Jefferies), as | s of our common stock having an aggregate offering price of up to $250,000,000 from time to time through or to Jefferies, as our agent. Ou |  |
| CABA | 0001193125-26-202441 | 2026-05-04 | single | underwritten | not_ATM |  |  | O |  |  | tus dated March 31, 2025) 51,725,000 Shares of Common Stock We are selling 51,725,000 shares of our common stock, par value $0.00001 per share, or the |

## 5. 검수 질문

1. 이 규칙을 화면의 "ATM 계약 확인" 판정에 쓸까요? 오검출 0 · 놓침 1 (보충 문서 유형) 입니다.
2. 놓친 유형 (기존 ATM 금액을 바꾸는 보충 문서) 을 잡으려면 B 에 "sales agreement prospectus" 같은 문구를 더해야 합니다. 이 변경은 표본을 본 뒤의 수정이라 새 표본으로 다시 검증해야 합니다. 진행할까요?
3. 정답 ATM 이 4건뿐입니다. ATM 표본을 늘리는 추가 검증 (예: ATM 추정 묶음에서 10건 · SEC 10건) 이 필요할까요?
