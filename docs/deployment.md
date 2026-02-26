# Deployment Guide

Self-hosted server + Cloudflare + nginx + systemd + uv.

Assumes:
- SSH alias `geomermaids` configured in `~/.ssh/config`
- Ubuntu/Debian on the server (adjust package manager if needed)
- Domain managed by Cloudflare
- Repo: `https://github.com/gsueur/parcel-sentinel.git`

---

## 1. Server prerequisites

```bash
ssh geomermaids

# uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env   # or re-login

# Python 3.12
uv python install 3.12

# nginx
sudo apt install -y nginx ufw
```

---

## 2. Clone and install

```bash
sudo mkdir -p /opt/location-sentinel
sudo chown $USER:$USER /opt/location-sentinel

git clone https://github.com/gsueur/parcel-sentinel.git /opt/location-sentinel
cd /opt/location-sentinel

uv sync --no-dev
mkdir -p data
```

---

## 3. Environment file

```bash
cat > /opt/location-sentinel/.env << 'EOF'
ENV=production
LOG_LEVEL=INFO
DUCKDB_PATH=/opt/location-sentinel/data/location_sentinel.duckdb
MAPBOX_TOKEN=<your-token>
EOF

chmod 600 /opt/location-sentinel/.env
```

Override any other `config.py` defaults here as needed.

---

## 4. Cloudflare Origin Certificate

In the Cloudflare dashboard:
**SSL/TLS > Origin Server > Create Certificate**
- Key type: RSA 2048
- Validity: 15 years
- Hostnames: your domain

Download the certificate and key to the server:

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo tee /etc/ssl/cloudflare/origin.pem   # paste certificate
sudo tee /etc/ssl/cloudflare/origin.key   # paste private key
sudo chmod 600 /etc/ssl/cloudflare/origin.key
```

Then in Cloudflare dashboard set **SSL/TLS mode to Full (strict)**.

---

## 5. nginx config

```bash
sudo tee /etc/nginx/sites-available/location-sentinel << 'EOF'
# Trust Cloudflare IPs and restore real client IP
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;
real_ip_header CF-Connecting-IP;

server {
    listen 443 ssl;
    server_name YOUR_DOMAIN;

    ssl_certificate     /etc/ssl/cloudflare/origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare/origin.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name YOUR_DOMAIN;
    return 301 https://$host$request_uri;
}
EOF

# Replace YOUR_DOMAIN
sudo sed -i 's/YOUR_DOMAIN/your.domain.com/g' /etc/nginx/sites-available/location-sentinel

sudo ln -s /etc/nginx/sites-available/location-sentinel /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6. Firewall

Lock port 80/443 to Cloudflare IPs only. SSH stays open.

```bash
sudo ufw allow 22/tcp

for ip in \
  173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 103.31.4.0/22 \
  141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 188.114.96.0/20 \
  197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 104.16.0.0/13 \
  104.24.0.0/14 172.64.0.0/13 131.0.72.0/22; do
  sudo ufw allow from $ip to any port 443
  sudo ufw allow from $ip to any port 80
done

sudo ufw --force enable
sudo ufw status
```

---

## 7. Systemd service

```bash
sudo tee /etc/systemd/system/location-sentinel.service << 'EOF'
[Unit]
Description=Location Sentinel Analytics API
After=network.target

[Service]
Type=exec
User=debian
WorkingDirectory=/home/debian/REMOTESENSING/location-sentinel
EnvironmentFile=/home/debian/REMOTESENSING/location-sentinel/.env
Environment=HOME=/home/debian
Environment=PATH=/home/debian/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/debian/REMOTESENSING/location-sentinel/.venv/bin/uvicorn src.location_sentinel.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --loop asyncio
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=location-sentinel

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now location-sentinel
sudo systemctl status location-sentinel
```

Replace `YOUR_LINUX_USER`. Confirm the `uv` path with `which uv` on the server -- it may be under `/root/.local/bin/uv` if you ran the install as root.

---

## 8. Verify

```bash
# Service logs
sudo journalctl -u location-sentinel -f

# Local health check (bypass nginx)
curl http://127.0.0.1:8000/v1/health

# Through nginx/Cloudflare
curl https://your.domain.com/v1/health
```

---

## 9. Deploy workflow (from your Mac)

```bash
git push origin master
ssh geomermaids 'cd /opt/location-sentinel && git pull && sudo systemctl restart location-sentinel'
```

Wrap in a local `Makefile` target if you want a single command:

```makefile
deploy:
	git push origin master
	ssh geomermaids 'cd /opt/location-sentinel && git pull && sudo systemctl restart location-sentinel'
```

Then: `make deploy`

---

## Notes

- **Workers**: must be 1 for DuckDB (single writer, exclusive lock). Switch to Postgres to scale beyond 1 worker.
- **Event loop**: use `--loop asyncio`. uvloop segfaults on some Linux/libc combinations -- keep it out.
- **Direct venv invocation**: use `.venv/bin/uvicorn` directly, not `uv run`. The `uv run` wrapper behaves inconsistently in systemd's minimal environment.
- **HOME and PATH**: must be set explicitly in the unit -- systemd does not inherit the user's shell environment.
- **Corrupted WAL**: if the service ever crashes hard (SIGSEGV), DuckDB may leave a corrupted `.wal` file. On next startup it will fail with `Failure while replaying WAL`. Fix: stop the service, delete `data/location_sentinel.duckdb` and `data/location_sentinel.duckdb.wal`, restart. Cached results are lost but recomputed on demand.
- **Cloudflare timeout**: 100s (free/pro plans). App default is 60s -- safely within limit.
- **Cloudflare IP ranges**: update periodically from https://www.cloudflare.com/ips/
- **`.env` and `*.duckdb`**: must be in `.gitignore` -- never commit them.
