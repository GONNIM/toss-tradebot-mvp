# Operations 인덱스 (관리자 전용)

TBE Phase 6-1 지시에 따라 공개 페이지에서 제거된 설치·환경 설정·SOPS 편집 절차를 이 인덱스 하위로 이관.

## 관리자 매뉴얼

| 문서 | 내용 |
|---|---|
| [operations/secrets-management.md](operations/secrets-management.md) | SOPS + age 최초 셋업 · key 관리 · CI 주입 |
| [operations/deployment.md](operations/deployment.md) | 서버 배포 자동화 · systemd · GHA workflow |
| [operations/sniper-setup.md](operations/sniper-setup.md) | 스나이퍼 라이브 스위치·인증 토큰 발급·회전 |
| [operations/vip-setup.md](operations/vip-setup.md) | VIP 감시 활성화 |

## 원칙

- 공개 페이지(SSR)에 로컬 경로·env 이름·SOPS 파일명·터미널 명령을 노출하지 않는다 (OSINT 회피).
- 사용자 UI 는 "관리자 문의" 정도의 안내만 제공하고, 실제 절차는 본 인덱스 하위 문서로 유도.
- 본 문서·하위 문서는 리포지토리 접근 권한이 있는 관리자만 열람.
