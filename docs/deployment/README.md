# Cronos deployment with Nginx

Prepared 2026-10-20 for the current repository. This runbook assumes Ubuntu 24.04 LTS, a single server, host Nginx, Docker Engine with Compose v2, and a DNS name such as `monitor.example.com`. Replace that example domain everywhere. Commands use `/opt/cronos` as the application checkout and a deployment account with sudo and Docker access. No production deployment has been performed by preparing this document.

## 1. Topology and prerequisites

Browser/tablet → HTTPS Nginx :443 → Uvicorn HTTP/WebSocket on **127.0.0.1:8100**. Nginx serves the Vue build directly. Compose runs the API, Celery worker, one scheduler, MySQL, Redis and RabbitMQ. Redis runs tasks/cache; RabbitMQ transports live notifications. Do not replace the ASGI command with a WSGI-only Gunicorn command: the alarm gateway requires WebSockets.

Required before proceeding:

- DNS A record points to this server. Publish AAAA only if IPv6 is configured too.
- Public inbound 80/443 and restricted administrative SSH access. Keep database, Redis, RabbitMQ and port 8100 private; Compose already publishes only 8100 on loopback.
- Outbound DNS/HTTPS and connectivity from the worker to monitored endpoints.
- A tested backup destination outside this server.
- Docker installed using the [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/). Docker-published ports can bypass UFW; do not add public broker/database mappings.
- Node.js matching `.nvmrc` on the build machine, or an equivalent CI build environment. Node is needed to build the frontend, not to serve it.

Install host packages and check Docker:

```bash
sudo apt update
sudo apt install nginx certbot ca-certificates curl git openssl
sudo systemctl enable --now nginx docker
docker compose version
```

Review the existing host before changing anything:

```bash
sudo nginx -T
sudo ss -lntp
df -h
```

Do not overwrite unrelated Nginx sites. If UFW is in use, preserve the actual SSH port before adjusting rules; permit TCP 80/443. This runbook assumes Nginx is the public TLS terminator. A Cloudflare/load-balancer deployment needs its own trusted-proxy and real-client-IP configuration.

## 2. Install the application and secrets

Place the source in `/opt/cronos` using your repository URL or a source archive. Do not copy a developer `.env`, `.runtime`, database, virtualenv, or debug APK into production. Run the following from the source checkout as the deployment account:

```bash
cd /opt/cronos
umask 077
cp .env.example .env
mkdir -p secrets
chmod 700 secrets
chmod 600 .env
```

Edit `.env` securely. Generate distinct random values with `openssl rand -hex 32` for `DJANGO_SECRET_KEY`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD` and `RABBITMQ_DEFAULT_PASS`. Hexadecimal passwords avoid URL interpolation problems in the Compose AMQP URL. Generate a Fernet encryption key without putting a real secret into shell history:

```bash
docker run --rm python:3.12-slim sh -c 'pip install --quiet cryptography && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
```

Put that value in `DEVICE_ENCRYPTION_KEY`. Preserve this key with backups: changing it prevents decryption of stored device credentials. Do not regenerate any existing production key during routine updates.

Required production values:

```dotenv
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=monitor.example.com
TRUST_PROXY=true
CORS_ALLOWED_ORIGINS=https://monitor.example.com,https://localhost
CRONOS_DEMO_MODE=false
MYSQL_DATABASE=cronos
MYSQL_USER=cronos
MYSQL_HOST=mysql
MYSQL_PORT=3306
REDIS_URL=redis://redis:6379/0
RABBITMQ_DEFAULT_USER=cronos
RABBITMQ_DEFAULT_VHOST=cronos
RABBITMQ_EXCHANGE=cronos.notifications
PROBE_DENIED_HOSTS=localhost,metadata.google.internal,metadata,monitor.example.com
PROBE_ALLOWED_CIDRS=
```

Also fill the generated secret fields from `.env.example`. Set `RABBITMQ_URL=amqp://cronos:YOUR_GENERATED_HEX_PASSWORD@rabbitmq:5672/cronos`, matching `RABBITMQ_DEFAULT_PASS`; Compose overrides this URL for API/worker from the initialization variables. Non-URL-safe credentials/vhost names require appropriate URL encoding and Compose changes. Restrict `PROBE_ALLOWED_CIDRS` to the private networks you explicitly intend to monitor; leave it empty if none. Never use `0.0.0.0/0` merely to bypass probe restrictions.

`TRUST_PROXY=true` is appropriate here because API access is limited to loopback and Nginx overwrites the forwarding headers. Keep `https://localhost` in CORS for the Capacitor Android app. Do not use wildcard hosts/origins. The scheduler must run only once.

## 3. Build, migrate and start services

```bash
cd /opt/cronos
docker compose config --quiet
docker compose build
docker compose up -d mysql redis rabbitmq
docker compose run --rm api python manage.py migrate --noinput
docker compose run --rm api python manage.py check
docker compose run --rm api python manage.py createsuperuser
docker compose up -d api worker scheduler
docker compose ps
docker compose logs --tail=100 api worker scheduler
```

Do not run `seed_demo` or enable demo login in production. Initialization passwords apply to new MySQL/RabbitMQ volumes; changing `.env` does not rotate existing database/broker users. Rotate those using their respective administration tools and coordinate application restarts.

Collect Django admin static assets and copy them to a host directory readable by Nginx:

```bash
docker compose exec api python manage.py collectstatic --noinput
sudo install -d -m 755 /var/www/cronos-static
sudo docker compose cp api:/app/staticfiles/. /var/www/cronos-static/
sudo chmod -R a+rX /var/www/cronos-static
```

Build the web frontend using the Node version in `.nvmrc`. The HTTPS URL is compiled into the build; changing `.env` at runtime does not rebuild it:

```bash
cd /opt/cronos/frontend
npm ci
VITE_API_URL=https://monitor.example.com/api/v1 VITE_ALLOW_LOCAL_HTTP=false npm run build
sudo install -d -m 755 /var/www/cronos-web
sudo cp -a dist/. /var/www/cronos-web/
sudo chmod -R a+rX /var/www/cronos-web
cd /opt/cronos
```

Do not run Vite's development server on production. Only copy `dist` to the public document root, never the application checkout or `.env`.

## 4. Bootstrap HTTPS

First create an HTTP-only site so Certbot can validate the domain. This avoids referencing certificate paths before a certificate exists:

```bash
sudo install -d -m 755 /var/www/letsencrypt
sudo tee /etc/nginx/sites-available/cronos >/dev/null <<'NGINX'
server {
    listen 80;
    server_name monitor.example.com;
    location ^~ /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 404; }
}
NGINX
sudo ln -s /etc/nginx/sites-available/cronos /etc/nginx/sites-enabled/cronos
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d monitor.example.com
```

Use the real domain in the heredoc and Certbot command. If the symlink already exists, inspect it rather than recreating it. Remove a conflicting default site only after confirming it is unused. DNS and public port 80 must work for this validation method.

Copy the complete production template, edit its domain/certificate paths, and activate it:

```bash
sudo cp /etc/nginx/sites-available/cronos /etc/nginx/sites-available/cronos.http-backup
sudo cp /opt/cronos/docs/deployment/nginx.conf.example /etc/nginx/sites-available/cronos
sudoedit /etc/nginx/sites-available/cronos
sudo nginx -t
sudo systemctl reload nginx
sudo certbot renew --dry-run
```

Ensure Nginx reloads after certificate renewal:

```bash
sudo install -d /etc/letsencrypt/renewal-hooks/deploy
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx >/dev/null <<'SH'
#!/bin/sh
nginx -t && systemctl reload nginx
SH
sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
```

The template forwards `Upgrade` and `Connection` for the exact WebSocket route and preserves the URI in `proxy_pass`, following [Nginx WebSocket guidance](https://nginx.org/en/docs/http/websocket.html). The 90-second timeout permits gateway pings. It serves Django static assets separately from the Vue frontend.

## 5. Acceptance checks

Run on the server:

```bash
cd /opt/cronos
curl -fsS -H 'Host: monitor.example.com' http://127.0.0.1:8100/api/v1/health/live
curl -fsS https://monitor.example.com/api/v1/health/live
curl -fsS https://monitor.example.com/api/v1/health/ready
curl -I https://monitor.example.com/
curl -I https://monitor.example.com/static/admin/css/base.css
sudo ss -lntp
docker compose exec api python manage.py check --deploy
docker compose logs --tail=100 api worker scheduler
```

Readiness includes database, Redis and recent monitor heartbeat; allow one scheduler cycle after startup. It does not prove RabbitMQ forwarding or audible delivery. Review `check --deploy` warnings in context: Nginx handles HTTPS redirect in this topology; HSTS should only be enabled after HTTPS and all required subdomains are confirmed. Do not suppress warnings blindly.

In a browser, sign in with the new account, create a monitored target, assign users/roles, register notifications in Settings and wait for **connected**. Send a test notification. Inspect browser Network for WebSocket status **101** on `/api/v1/realtime/ws` and a ready message after authentication. Do not put device credentials into URLs, shell history or screenshots.

For the Android phone/tablet:

1. Install a signed production APK built/configured for `https://monitor.example.com/api/v1`. The existing `output/cronos-debug.apk` defaults to workstation loopback and USB forwarding; do not distribute that build as production.
2. Sign in, register the device, allow notification permission, enable monitoring and select **Allow background alarms**. Approve the Android battery exemption and verify connected status.
3. Send a test while open, then with the screen locked. Confirm both notification and actual alarm sound at the tablet's alarm volume; use Stop alarm afterward.
4. With an enabled QA target that has previously reported a heartbeat, stop its agent. Agent offline opens after 90 seconds plus up to 30 seconds for evaluation and 15 seconds for dispatch under healthy scheduling. Confirm the native alarm. Retire the QA target after testing.
5. Repeat after a reconnect and prolonged idle on the actual deployment network. Local test successes do not guarantee every vendor's battery policy. Reopen Cronos after force-stop/reboot. Continuous monitoring needs a live network and uses additional battery.

For an Android build machine with SDK/JDK configured, an HTTPS debug validation build can be made with:

```bash
VITE_API_URL=https://monitor.example.com/api/v1 ./scripts/android-build.sh
```

That helper still produces a **debug** APK. Release keystore creation, signing, secure keystore backup and distribution are separate release steps; do not call its output signed production software. Production devices must not depend on `adb reverse`.

Register monitored servers through the Servers UI and use its generated agent installation command; see the agent guide linked from the project README. Keep per-server enrollment credentials private. Maintenance suppresses notifications, and disabled/retired targets are not monitored.

## 6. Updates, backups and rollback

Before any update, record the currently deployed source revision and preserve the web/static release directories. Back up `.env`, any secrets, signing keys and the database to encrypted, access-controlled storage. Never publish these backups under `/var/www`.

Example database backup from `/opt/cronos` (the database password stays inside the container):

```bash
umask 077
mkdir -p backups
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump --no-tablespaces --single-transaction --quick -u "$MYSQL_USER" "$MYSQL_DATABASE"' > "backups/cronos-$(date -u +%Y%m%dT%H%M%SZ).sql"
```

Check the command exit status and nonempty output, encrypt/copy off-host, and test a restore into a separate environment. The MySQL volume is authoritative application state; Redis and RabbitMQ volumes also require an environment-appropriate backup/recovery policy. Broker live queues are temporary and do not replay missed alarms on reconnect. Back up RabbitMQ configuration/user definitions separately if they are changed after initialization. A VM snapshot alone is not a tested database restore.

For a planned update, schedule a monitoring outage, back up first, build the new image before stopping services, then:

```bash
cd /opt/cronos
docker compose build
docker compose stop scheduler worker api
docker compose run --rm api python manage.py migrate --noinput
docker compose up -d api worker scheduler
```

Rebuild/copy frontend and collect/copy Django static assets using section 3. Repeat section 5. Keep exactly one scheduler. During the outage, telemetry/probes/live notifications may be unavailable.

Rollback requires the previous source/image and matching web/static assets. Database migrations may be incompatible with old code: review migration reversibility before rollback, or restore the pre-update database during a controlled outage. Do not blindly reverse migrations or restore over live writes. Restoring loses writes since the backup. Never run `docker compose down -v` as an update or repair command; it deletes persistent volumes.

## 7. Troubleshooting

| Symptom | Checks |
| --- | --- |
| Nginx 502 | `docker compose ps`; API logs; loopback health request with the configured Host; Nginx error log. |
| WebSocket missing 101 | Exact WS location, upgrade headers, HTTPS/WSS, Host/Origin configuration, API ASGI command. A normal unauthenticated HTTP GET is not a valid gateway test. |
| Accepted notification but no alarm | Device connected at publication time, enabled registration/preferences, server membership, Android notification permission/alarm volume/battery exemption. Acceptance is broker confirmation, not receipt. |
| Agent offline never opens | Previously received heartbeat, target enabled, maintenance/preferences, worker and scheduler running, readiness heartbeat. |
| Readiness fails | MySQL/Redis reachability and scheduler/worker logs; missing or old JobHeartbeat. |
| Admin CSS missing | Re-run collectstatic, copy to `/var/www/cronos-static`, inspect Nginx alias and permissions. |
| Wrong API/loopback in APK | Rebuild/configure with the public HTTPS API; existing app Settings may retain a prior API override. |
| DB/broker authentication after editing .env | Existing-volume passwords are not reset by initialization variables; rotate service users explicitly. |

Useful commands:

```bash
sudo nginx -t
sudo tail -n 100 /var/log/nginx/cronos-error.log
cd /opt/cronos
docker compose ps
docker compose logs --tail=100 api worker scheduler rabbitmq
docker compose exec rabbitmq rabbitmq-diagnostics -q ping
```

Share redacted logs only. This document and template are prepared configuration; the target server must pass Nginx syntax validation, container startup, public HTTPS, WebSocket and real-device acceptance checks before deployment is considered complete.
