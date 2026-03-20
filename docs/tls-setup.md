# TLS / HTTPS Setup Guide — ZKML

This guide covers securing ZKML with TLS using a reverse proxy.

---

## 1. Architecture

```
Internet → Nginx (TLS termination, :443) → Docker services
                ├─ /           → web:3000
                ├─ /api/       → registry:8000
                ├─ /flower/    → flower:5555  (IP-restricted)
                └─ /grafana/   → grafana:3001 (IP-restricted)
```

All services communicate internally over Docker networks using plain HTTP. TLS is terminated at the reverse proxy.

---

## 2. Nginx Configuration

### 2.1 Install Nginx

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx

# macOS
brew install nginx
```

### 2.2 Obtain TLS Certificate (Let's Encrypt)

```bash
sudo certbot certonly --nginx -d your-domain.com -d api.your-domain.com
```

### 2.3 Nginx Site Configuration

Create `/etc/nginx/sites-available/zkml`:

```nginx
# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name your-domain.com api.your-domain.com;
    return 301 https://$host$request_uri;
}

# Frontend + API
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # TLS certificates
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # TLS hardening
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    # HSTS (6 months)
    add_header Strict-Transport-Security "max-age=15768000; includeSubDomains; preload" always;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # OCSP stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    # Frontend (Next.js)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Increase timeouts for proof operations
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;

        # Large circuit uploads
        client_max_body_size 300m;
    }

    # Flower (admin only)
    location /flower/ {
        allow 10.0.0.0/8;       # Internal network
        allow 192.168.0.0/16;
        deny all;

        proxy_pass http://127.0.0.1:5555/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Grafana (admin only)
    location /grafana/ {
        allow 10.0.0.0/8;
        allow 192.168.0.0/16;
        deny all;

        proxy_pass http://127.0.0.1:3001/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2.4 Enable the Site

```bash
sudo ln -s /etc/nginx/sites-available/zkml /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 3. Environment Configuration

Update `.env` for production HTTPS:

```bash
# Ensure all URLs use https://
NEXTAUTH_URL=https://your-domain.com
NEXT_PUBLIC_API_URL=https://your-domain.com/api
CORS_ORIGINS=https://your-domain.com

# Webhook URLs must be HTTPS (enforced by the API)
# Callback URLs must be HTTPS
```

---

## 4. Certificate Auto-Renewal

Let's Encrypt certificates expire every 90 days. Certbot sets up auto-renewal by default:

```bash
# Verify auto-renewal is configured
sudo certbot renew --dry-run

# If not, add a cron job:
echo "0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'" | sudo crontab -
```

---

## 5. Alternative: Caddy (Auto-TLS)

Caddy handles TLS automatically with zero configuration:

```
# Caddyfile
your-domain.com {
    handle /api/* {
        reverse_proxy registry:8000
    }
    handle {
        reverse_proxy web:3000
    }
}
```

```bash
# Run Caddy
docker run -d --name caddy \
  -p 80:80 -p 443:443 \
  -v ./Caddyfile:/etc/caddy/Caddyfile \
  -v caddy_data:/data \
  caddy:2-alpine
```

---

## 6. Validation

After setup, verify TLS configuration:

```bash
# Check certificate
openssl s_client -connect your-domain.com:443 -servername your-domain.com < /dev/null 2>&1 | openssl x509 -noout -dates

# Check HSTS header
curl -sI https://your-domain.com | grep -i strict

# Check HTTP → HTTPS redirect
curl -sI http://your-domain.com | grep -i location

# Full scan (SSL Labs)
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=your-domain.com
```

---

## 7. Docker Network Considerations

Ensure the reverse proxy can reach Docker services. Two approaches:

**Option A — Host network mode** (used above): Services bind to `127.0.0.1:<port>`, Nginx on host proxies directly.

**Option B — Docker network**: Add Nginx as a service in `docker-compose.prod.yml`:

```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/zkml.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - registry
      - web
    restart: unless-stopped
```
