# 운영 서버 배포 가이드 — `deploy-tossbot`

| 항목 | 값 |
|---|---|
| 서버 | optimus8.cafe24.com |
| Backend | FastAPI · uvicorn · 127.0.0.1:8001 |
| Frontend | Next.js · 127.0.0.1:3000 |
| 시스템 | systemd 2개 service (`tossbot-backend`, `tossbot-frontend`) |
| 트리거 | 로컬 alias `deploy-tossbot` → ssh → /root/deploy-tossbot.sh |

---

## 최초 셋업 (한 번만)

### 1. 서버에 git clone

```bash
ssh root@optimus8.cafe24.com
cd /root
git clone <git-remote-url> toss-tradebot-mvp
cd toss-tradebot-mvp
```

### 2. backend Python 3.12 venv

```bash
cd /root/toss-tradebot-mvp/backend
python3.12 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### 3. frontend 의존성

```bash
cd /root/toss-tradebot-mvp/frontend
npm install --legacy-peer-deps
cp .env.example .env.local   # 또는 직접 작성
# .env.local 에 NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 설정
chmod 600 .env.local
npm run build
```

### 4. systemd unit 등록

```bash
cd /root/toss-tradebot-mvp
sudo cp scripts/server/tossbot-backend.service /etc/systemd/system/
sudo cp scripts/server/tossbot-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tossbot-backend
sudo systemctl enable --now tossbot-frontend
sudo systemctl status tossbot-backend tossbot-frontend --no-pager
```

### 5. deploy 스크립트 배치

```bash
# 로컬에서:
scp scripts/server/deploy-tossbot.sh root@optimus8.cafe24.com:/root/
ssh root@optimus8.cafe24.com "chmod +x /root/deploy-tossbot.sh"
```

### 6. 로컬 alias 등록

`~/.zshrc` 또는 `~/.bashrc`에 추가:

```bash
alias deploy-tossbot='ssh root@optimus8.cafe24.com "/root/deploy-tossbot.sh"'
```

적용:
```bash
source ~/.zshrc   # or ~/.bashrc
type deploy-tossbot   # 확인
```

### 7. nginx reverse proxy (선택)

도메인으로 접근 시 nginx 설정 별도 — 본 가이드 범위 외. 기본은
`http://optimus8.cafe24.com:3000` 직접 접근 또는 SSH 터널.

---

## 일상 배포

로컬 코드 변경 + git push 후:

```bash
deploy-tossbot
```

5 단계 자동 수행 — git pull · backend deps · frontend build · systemctl
restart · 상태 확인. 출력에 `✅ deploy-tossbot 완료` 가 보이면 성공.

---

## 자매 프로젝트 패턴

`upbit-tradebot-mvp` 의 `deploy-tradebot` (orionhunter7.cafe24.com) 패턴
차용. 같은 alias-on-ssh 패턴이라 운영 mental model 일치.

---

## 트러블슈팅

### `tossbot-backend` 가 시작되지 않음
```bash
ssh root@optimus8.cafe24.com
journalctl -u tossbot-backend -n 50 --no-pager
```
주요 원인:
- `backend/venv` 미생성 → 최초 셋업 2번 단계 재실행
- numpy 1.x vs 2.x 호환성 (서버 CPU) → `requirements.txt`의
  `numpy>=1.26.0,<2.0.0` 적용 확인. pykrx 가 2.x 요구하면 별도 venv
  또는 대체 라이브러리 검토

### `tossbot-frontend` 가 시작되지 않음
```bash
journalctl -u tossbot-frontend -n 50 --no-pager
```
주요 원인:
- `npm run build` 미수행 → deploy 스크립트 3/5 단계 재실행
- `.env.local` 의 `NEXT_PUBLIC_API_BASE_URL` 잘못 설정 → backend 포트 일치 확인

### KDI motir PDF 수동 다운로드 필요 (catalog 미등재)
[`backend/discovery/data_sources/motir_export/downloader.py`](../../backend/discovery/data_sources/motir_export/downloader.py)
의 `KDI_NUM_CATALOG` dict에 신규 발표월 num 추가 후 커밋 → push → `deploy-tossbot`.

### 운영 DB (`backend/data/tradebot.db`) 백업
```bash
ssh root@optimus8.cafe24.com "cp /root/toss-tradebot-mvp/backend/data/tradebot.db /root/tradebot.db.$(date +%Y%m%d-%H%M).bak"
```

---

## 참고

- 자매 프로젝트: `upbit-tradebot-mvp` (orionhunter7.cafe24.com, `deploy-tradebot`)
- 배포 정책: [[feedback-deploy-only-when-complete]] — 멀티 Phase 작업은
  전체 Phase 로컬 완료 후 단일 배포
