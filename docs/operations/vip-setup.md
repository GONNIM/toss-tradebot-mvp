# VIP 감시 활성화 — 관리자 매뉴얼

> **접근 대상**: 서버 관리자 · SOPS age key 보유자 한정.
> **본 문서를 보는 이유**: `/vip` 공개 페이지에서 SOPS 파일명·env 이름을 제거하고 (TBE Phase 6-1) 이 내부 문서로 이관.

---

## 1. 활성화 절차

`docs/operations/secrets-management.md` §2 완료 상태에서:

```bash
cd <repo-root>
sops edit backend/.env.sops.yaml
```

에디터에서 다음 두 라인 추가:

```yaml
VIP_ENABLED: "true"
VIP_AVG_PRICE: "<평단가 · 원 단위 정수>"
```

저장 후 커밋·push → GHA 자동 배포 (2~3분 내 반영).

---

## 2. 관련 문서

- `docs/operations/secrets-management.md` — SOPS + age 셋업
- `docs/operations/sniper-setup.md` — 스나이퍼 설정 (동일 SOPS env 편집 패턴)
- `docs/operations/deployment.md` — 배포 자동화
