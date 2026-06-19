# 배포 인프라 가이드 — optimus8.cafe24.com

## 1. 서버 사전 준비

```bash
# Ubuntu 22.04 LTS 기준
sudo apt update && sudo apt upgrade -y
sudo apt install -y nginx python3.12 python3.12-venv git curl

# Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# PM2 (Next.js daemon)
sudo npm install -g pm2

# Certbot (Let's Encrypt)
sudo apt install -y certbot python3-certbot-nginx
```

## 2. 디렉토리 레이아웃

```
/root/toss-tradebot-mvp/      # 코드 (git clone)
/var/log/toss-tradebot/        # 로그
/etc/systemd/system/           # tradebot-api.service, tradebot-cron.service
/etc/nginx/sites-available/    # toss-tradebot
```

## 3. 환경변수 설정

```bash
# 1. 코드 체크아웃
git clone git@github.com:GONNIM/toss-tradebot-mvp.git /root/toss-tradebot-mvp
cd /root/toss-tradebot-mvp

# 2. backend .env (.env.example 복사 후 채우기)
cp backend/.env.example backend/.env
chmod 600 backend/.env
nano backend/.env   # ANTHROPIC_API_KEY, TELEGRAM_*, FINNHUB_*, REDDIT_*

# 3. frontend .env.local
cp frontend/.env.example frontend/.env.local
nano frontend/.env.local
```

## 4. Backend 설치 + systemd

```bash
cd /root/toss-tradebot-mvp/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python scripts/init_db.py
```

**systemd 서비스** (`/etc/systemd/system/tradebot-api.service`):

```ini
[Unit]
Description=Toss Tradebot FastAPI
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/toss-tradebot-mvp/backend
EnvironmentFile=/root/toss-tradebot-mvp/backend/.env
ExecStart=/root/toss-tradebot-mvp/backend/.venv/bin/uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10
StandardOutput=append:/var/log/toss-tradebot/api.log
StandardError=append:/var/log/toss-tradebot/api.error.log

[Install]
WantedBy=multi-user.target
```

**Cron 스케줄러** (`/etc/systemd/system/tradebot-cron.service`):

```ini
[Unit]
Description=Toss Tradebot Cron Scheduler (Crazy + Moonshot)
After=network.target tradebot-api.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/toss-tradebot-mvp/backend
EnvironmentFile=/root/toss-tradebot-mvp/backend/.env
ExecStart=/root/toss-tradebot-mvp/backend/.venv/bin/python -m backend.scheduler.cron
Restart=always
RestartSec=30
StandardOutput=append:/var/log/toss-tradebot/cron.log
StandardError=append:/var/log/toss-tradebot/cron.error.log

[Install]
WantedBy=multi-user.target
```

활성화:
```bash
sudo mkdir -p /var/log/toss-tradebot
sudo systemctl daemon-reload
sudo systemctl enable --now tradebot-api tradebot-cron
sudo systemctl status tradebot-api tradebot-cron
```

## 5. Frontend 빌드 + PM2

```bash
cd /root/toss-tradebot-mvp/frontend
npm ci
npm run build
```

**PM2 설정** (`ecosystem.config.js` — 프로젝트 루트):

```javascript
module.exports = {
  apps: [{
    name: 'tradebot-web',
    cwd: '/root/toss-tradebot-mvp/frontend',
    script: 'node_modules/next/dist/bin/next',
    args: 'start -p 3000',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '512M',
    env: { NODE_ENV: 'production' },
    error_file: '/var/log/toss-tradebot/web.error.log',
    out_file: '/var/log/toss-tradebot/web.log',
  }],
};
```

기동:
```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup   # 부팅 시 자동 시작
```

## 6. Nginx 리버스 프록시

`/etc/nginx/sites-available/toss-tradebot`:

```nginx
server {
    listen 80;
    server_name optimus8.cafe24.com;

    # Let's Encrypt http-01 challenge (Certbot 자동 추가)
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # 전체 HTTPS 리다이렉트
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name optimus8.cafe24.com;

    # Let's Encrypt 인증서 (Certbot 자동 갱신)
    ssl_certificate     /etc/letsencrypt/live/optimus8.cafe24.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/optimus8.cafe24.com/privkey.pem;

    # API → FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 그 외 → Next.js
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    client_max_body_size 10M;
}
```

활성화:
```bash
sudo ln -s /etc/nginx/sites-available/toss-tradebot /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Let's Encrypt 발급
sudo certbot --nginx -d optimus8.cafe24.com
```

## 7. GitHub Actions 자동 배포

`.github/workflows/deploy.yml` 이미 자리잡힘 (validate 활성 + deploy job placeholder).

deploy job 활성화 단계 (`secrets` 등록 필요):
- `OPTIMUS8_SSH_KEY` — Ed25519 private key
- `OPTIMUS8_HOST` — `optimus8.cafe24.com`
- `OPTIMUS8_USER` — `root`

워크플로우 실 배포 로직:
```yaml
deploy:
  runs-on: ubuntu-latest
  needs: validate
  if: github.ref == 'refs/heads/main'
  steps:
    - uses: actions/checkout@v4
    - name: Deploy via SSH
      uses: appleboy/ssh-action@v1.0.0
      with:
        host: ${{ secrets.OPTIMUS8_HOST }}
        username: ${{ secrets.OPTIMUS8_USER }}
        key: ${{ secrets.OPTIMUS8_SSH_KEY }}
        script: |
          set -e
          cd /root/toss-tradebot-mvp
          git pull --ff-only origin main
          cd backend && .venv/bin/pip install -e ".[dev]" && cd ..
          cd frontend && npm ci && npm run build && cd ..
          sudo systemctl restart tradebot-api tradebot-cron
          pm2 reload tradebot-web
```

## 8. 검증

```bash
# 헬스체크
curl https://optimus8.cafe24.com/health
# {"status": "ok", "service": "toss-tradebot-mvp"}

# API
curl https://optimus8.cafe24.com/api/v1/moonshot
curl https://optimus8.cafe24.com/api/v1/crazy

# 프론트
curl -I https://optimus8.cafe24.com/

# 로그
tail -f /var/log/toss-tradebot/api.log
tail -f /var/log/toss-tradebot/cron.log
journalctl -u tradebot-api -f
journalctl -u tradebot-cron -f
pm2 logs tradebot-web
```

## 9. 운영 주의사항

- `.env` 권한 600 유지 (사용자 지시: optimus79! 같은 평문 정보 절대 미커밋)
- Toss API 키는 Phase K 활성 시 추가
- Telegram bot 채널 알림 일일 점검
- DB 백업: `sqlite3 /root/toss-tradebot-mvp/backend/data/tradebot.db ".backup '/var/backups/tradebot-$(date +%Y%m%d).db'"` 일일 cron

## 10. Phase K 활성 체크리스트

Toss API 개방 후 활성화 단계:
1. `backend/.env` 에 `TOSS_API_KEY` / `TOSS_API_SECRET` 추가
2. `backend/services/toss_api.py` 구현 (Phase K)
3. `backend/engine/live_loop.py` 구현 (Phase K)
4. systemd 서비스 추가: `tradebot-engine.service`
5. 1주 dry-run 검증 후 실거래 활성화
