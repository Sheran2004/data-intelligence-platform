# Deployment Guide

This guide walks you through deploying the AI Data Intelligence Platform to various hosting providers.

## Table of Contents
1. [Local Production Run](#local-production-run)
2. [Docker](#docker)
3. [Heroku](#heroku)
4. [Render](#render)
5. [Railway](#railway)
6. [Fly.io](#flyio)
7. [DigitalOcean App Platform](#digitalocean-app-platform)
8. [VPS (Manual)](#vps-manual)
9. [Post-deploy checklist](#post-deploy-checklist)

---

## 1. Local Production Run

Run the production server locally with gunicorn:
```bash
pip install -r requirements.txt
gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:5000 wsgi:app
```

The app will be available at `http://localhost:5000`.

For background processing (schedules + SSE), run the dev server alongside or use a process manager (see VPS section).

---

## 2. Docker

### Build the image
```bash
docker build -t data-intelligence-platform .
```

### Run the container
```bash
docker run -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e PORT=5000 \
  -e DIP_DB_PATH=/app/data/platform.db \
  data-intelligence-platform
```

### With docker-compose
```yaml
# docker-compose.yml
version: "3.9"
services:
  web:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - DIP_DB_PATH=/app/data/platform.db
      - PORT=5000
    restart: unless-stopped
```
```bash
docker-compose up -d
```

The `/app/data` volume persists the SQLite database between container restarts.

---

## 3. Heroku

1. Install the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli).
2. Login and create an app:
   ```bash
   heroku login
   heroku create your-app-name
   ```
3. Deploy:
   ```bash
   git push heroku main
   ```
4. Open the app:
   ```bash
   heroku open
   ```

The `Procfile` and `runtime.txt` are auto-detected.

To persist data on Heroku, add a Postgres-backed dyno or use an external database.

---

## 4. Render

1. Go to [render.com](https://render.com) and create a new **Web Service**.
2. Connect your GitHub repo.
3. Render auto-detects `Procfile` and `runtime.txt`.
4. Configure:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:$PORT wsgi:app`
5. Add a **Persistent Disk** mounted at `/opt/render/project/src/data` (for SQLite persistence).

---

## 5. Railway

1. Go to [railway.app](https://railway.app) and **New Project → Deploy from GitHub**.
2. Select your repo.
3. Railway auto-detects the Dockerfile.
4. Add a volume at `/app/data` to persist the SQLite DB.

---

## 6. Fly.io

1. Install [flyctl](https://fly.io/docs/getting-started/installing-flyctl/).
2. Launch:
   ```bash
   fly launch
   ```
3. Add a persistent volume:
   ```bash
   fly volumes create data_volume --size 1
   ```
4. Mount it in `fly.toml`:
   ```toml
   [[mounts]]
     source = "data_volume"
     destination = "/app/data"
   ```
5. Deploy:
   ```bash
   fly deploy
   ```

---

## 7. DigitalOcean App Platform

1. Create a new app from your GitHub repo.
2. App Platform auto-detects Python and uses `Procfile`.
3. Add a **Databases** component (Postgres or Dev DB) if you want managed persistence.
4. Or use the bundled persistent disk for SQLite.

---

## 8. VPS (Manual)

For full control, deploy to a VPS (DigitalOcean Droplet, AWS EC2, etc.):

### 1. Server setup
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv nginx certbot python3-certbot-nginx
```

### 2. Clone & install
```bash
git clone https://github.com/<you>/data-intelligence-platform.git
cd data-intelligence-platform
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Create systemd service (`/etc/systemd/system/dip.service`)
```ini
[Unit]
Description=Data Intelligence Platform
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/data-intelligence-platform
Environment="PATH=/var/www/data-intelligence-platform/venv/bin"
Environment="DIP_DB_PATH=/var/www/data-intelligence-platform/data/platform.db"
ExecStart=/var/www/data-intelligence-platform/venv/bin/gunicorn \
    -w 2 -k gthread --threads 4 -b 127.0.0.1:5000 \
    --access-logfile - wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable dip
sudo systemctl start dip
```

### 4. Nginx reverse proxy (`/etc/nginx/sites-available/dip`)
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # SSE needs these
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/dip /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 5. HTTPS (free Let's Encrypt)
```bash
sudo certbot --nginx -d your-domain.com
```

---

## 9. Post-deploy checklist

After deploying, verify:

- [ ] **App loads** — visit the URL, dashboard renders
- [ ] **API health** — `curl https://your-app.com/api/stats` returns 200
- [ ] **Demo loads** — click ⚡ Load Demo, 6 runs appear
- [ ] **Real sources work** — run a job prompt, RemoteOK/HN records appear
- [ ] **Charts render** — open a run, donut + bar charts visible
- [ ] **Dark/Light toggle** — top-right moon button works
- [ ] **SSE live updates** — start a run, sidebar updates without refresh
- [ ] **Share link** — click Share, open the URL, see public view
- [ ] **Webhook** — set a Slack URL, run a workflow, check Slack channel
- [ ] **Persistence** — restart the server, runs still in sidebar

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `5000` | Server listen port (set by most hosts) |
| `DIP_DB_PATH` | `data/platform.db` | SQLite database path (use a persistent volume) |
| `DIP_DISABLE_SCHEDULER` | `0` | Set to `1` to disable background scheduler |
| `DIP_CORS_ORIGINS` | (all) | Comma-separated CORS origin whitelist |

---

## Scaling Notes

- **Database:** SQLite is fine for single-instance demos (<100K records). For multi-instance production, swap to Postgres by replacing `data_intelligence/database.py` with a Postgres adapter.
- **Background jobs:** The scheduler + SSE run in-process. For multi-worker gunicorn, use a dedicated worker (e.g. add a second Procfile entry).
- **Caching:** Add Redis in front of `/api/records` for high-traffic deployments.

---

## Troubleshooting

**Port 5000 in use:** Change `PORT` env var or update `app.py`'s `app.run()` call.

**SQLite locked:** Make sure `DIP_DB_PATH` points to a persistent volume, not the container's ephemeral filesystem.

**SSE not streaming:** Nginx needs `proxy_buffering off;` (see VPS section). Heroku/Render handle this automatically.

**Out of memory:** Increase the dyno size or reduce `gunicorn -w` workers.

---

## Cost Comparison

| Host | Free tier | Recommended for |
|------|-----------|-----------------|
| Render | 750h/mo web service + 1GB disk | **Hackathon demo** |
| Railway | $5 credit/mo | Quick deploys |
| Fly.io | 3 shared VMs + 3GB volume | **Production** |
| Heroku | Eco dyno $5/mo | Classic |
| DigitalOcean | $4/mo droplet | Full control |

For a hackathon demo, **Render** is the easiest. For long-term production, **Fly.io** with a volume.